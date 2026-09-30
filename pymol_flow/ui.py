"""Minimal Qt dock UI hosted by the standard PyMOL application."""

from __future__ import annotations

import html
import os
from pathlib import Path
import re
import time
from typing import Any

from pymol import cmd
from pymol.Qt import QtCore, QtGui, QtWidgets

from .agent import AgentReply, PyMOLAgent, should_enable_thinking
from .config import api_key, base_url, enable_thinking, model, thinking_mode
from .keychain import credential_store_name, delete_api_key, read_api_key, save_api_key
from .voice import SpeechPlayer, VoiceRecorder, transcribe


class TaskSignals(QtCore.QObject):
    done = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)


class Task(QtCore.QRunnable):
    def __init__(self, function, *args):
        super().__init__()
        self.function, self.args = function, args
        self.signals = TaskSignals()

    def run(self):
        try:
            self.signals.done.emit(self.function(*self.args))
        except Exception as exc:
            messages = [str(exc) or type(exc).__name__]
            cause = exc.__cause__
            while cause is not None and len(messages) < 3:
                detail = str(cause) or type(cause).__name__
                if detail not in messages:
                    messages.append(detail)
                cause = cause.__cause__
            self.signals.failed.emit(" — ".join(messages))


class DropPanel(QtWidgets.QWidget):
    files_dropped = QtCore.pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        allowed_exts = {".pdb", ".cif", ".mmcif", ".ent", ".sdf", ".mol2", ".pse", ".pdbqt"}
        if any(Path(path).is_dir() or Path(path).suffix.lower() in allowed_exts for path in paths):
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.files_dropped.emit([url.toLocalFile() for url in event.mimeData().urls()])
        event.acceptProposedAction()


class APIKeyDialog(QtWidgets.QDialog):
    """API key status and replacement dialog backed by macOS Keychain."""

    def __init__(self, parent=None, has_key=False, source=""):
        super().__init__(parent)
        current_url = base_url().lower()
        current_model = model().lower()
        is_dashscope = "qianwen" in current_url or "dashscope" in current_url or current_model.startswith("qwen")

        if is_dashscope:
            self.setWindowTitle("DashScope / Qwen API Key")
            link_url = "https://bailian.console.aliyun.com/"
            link_text = "Get DashScope API Key (阿里云百炼)"
        else:
            self.setWindowTitle("API Key Settings")
            link_url = "https://platform.openai.com/api-keys"
            link_text = "Create or manage an API key"

        self.setModal(True)
        self.setMinimumWidth(440)
        layout = QtWidgets.QVBoxLayout(self)

        status_row = QtWidgets.QHBoxLayout()
        status_dot = QtWidgets.QLabel("●")
        status_dot.setObjectName("api_key_status_dot")
        status_dot.setStyleSheet(f"color:{'#49D86D' if has_key else '#777777'}")
        status_text = QtWidgets.QLabel(
            f"API key active — {source}" if has_key else "No API key configured"
        )
        status_row.addWidget(status_dot)
        status_row.addWidget(status_text)
        status_row.addStretch(1)
        layout.addLayout(status_row)

        store_name = credential_store_name()
        explanation = QtWidgets.QLabel(
            "For security, an active key is never displayed. Paste a new key below "
            f"only when you want to add or replace it. Keys entered here are saved "
            f"in {store_name} and are not included in PyMOL session files."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        link = QtWidgets.QLabel(
            f'<a style="color:#9B81FD" href="{link_url}">{link_text}</a>'
        )
        link.setOpenExternalLinks(True)
        layout.addWidget(link)

        self.key_input = QtWidgets.QLineEdit()
        self.key_input.setEchoMode(QtWidgets.QLineEdit.Password)
        self.key_input.setPlaceholderText(
            "Paste a replacement key…" if has_key else "Paste your API key…"
        )
        layout.addWidget(self.key_input)

        self.error_label = QtWidgets.QLabel("")
        self.error_label.setStyleSheet("color:#FF6B68")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.Save).clicked.connect(self._save)
        buttons.rejected.connect(self.reject)
        if read_api_key():
            clear_button = buttons.addButton("Remove Key", QtWidgets.QDialogButtonBox.DestructiveRole)
            clear_button.clicked.connect(self._clear)
        layout.addWidget(buttons)

        self.setStyleSheet("""
            QDialog { background-color:#343434; color:#E8E8E8; }
            QLabel { color:#E8E8E8; }
            QLineEdit { min-height:28px; padding:0 8px; background-color:#222222;
                color:#E8E8E8; border:1px solid #494949; border-radius:3px; }
            QPushButton { min-height:24px; padding:1px 10px; background-color:#3E3E3E;
                color:#E8E8E8; border:1px solid #555555; border-radius:3px; }
            QPushButton:hover { background-color:#494949; border-color:#60B0DC; }
        """)

    def _save(self):
        key = self.key_input.text().strip()
        if len(key) < 20:
            self.error_label.setText("That does not look like a complete API key.")
            return
        try:
            save_api_key(key)
        except Exception as exc:
            self.error_label.setText(str(exc))
            return
        os.environ["OPENAI_API_KEY"] = key
        self.accept()

    def _clear(self):
        delete_api_key()
        os.environ.pop("OPENAI_API_KEY", None)
        self.done(2)


class PyMOLFlowDock(QtWidgets.QDockWidget):
    debug_message = QtCore.pyqtSignal(str)
    token_received = QtCore.pyqtSignal(str)
    thought_received = QtCore.pyqtSignal(str)
    tool_executed = QtCore.pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__("PyMOL Flow", parent)
        self.setObjectName("PyMOLFlowDock")
        self.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)
        self.setMinimumWidth(360)
        self.setMinimumHeight(400)
        self.thread_pool = QtCore.QThreadPool.globalInstance()
        self.agent = None
        self.busy = False
        self._streaming = False
        self._messages: list[dict[str, Any]] = []
        self._active_turn: dict[str, Any] | None = None
        self._thinking_timer = QtCore.QTimer(self)
        self._thinking_timer.setInterval(250)
        self._thinking_timer.timeout.connect(self._on_thinking_tick)
        self._auto_scroll = True
        self._rendering_history = False
        self._last_stream_render = 0.0
        self._stream_timer = QtCore.QTimer(self)
        self._stream_timer.setSingleShot(True)
        self._stream_timer.setInterval(40)
        self._stream_timer.timeout.connect(self._flush_stream_render)

        self.speech = SpeechPlayer(self)
        self.speech.error.connect(self.show_error)
        self.settings = QtCore.QSettings("PyMOLFlow", "PyMOLFlow")

        font = QtGui.QFont("Microsoft YaHei", 10)
        font.setStyleHint(QtGui.QFont.SansSerif)

        root = DropPanel(self)
        root.setObjectName("pymol_flow_panel")
        root.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        root.setAutoFillBackground(True)
        self.panel_root = root
        root.files_dropped.connect(self.load_files)
        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        self.history = QtWidgets.QTextBrowser()
        self.history.setObjectName("chat_history")
        self.history.setOpenLinks(False)
        self.history.anchorClicked.connect(self._on_anchor_clicked)
        self.history.setPlaceholderText("Ask PyMOL to change or inspect the current scene.")
        self.history.setFont(font)
        self.history.document().setDefaultFont(font)
        self.history.installEventFilter(self)
        if hasattr(self.history, "viewport") and self.history.viewport():
            self.history.viewport().installEventFilter(self)

        v_bar = self.history.verticalScrollBar()
        v_bar.sliderPressed.connect(self._on_slider_pressed)
        v_bar.sliderReleased.connect(self._on_slider_released)
        v_bar.valueChanged.connect(self._on_scroll_value_changed)
        layout.addWidget(self.history, 1)

        self.pill_bar = QtWidgets.QWidget()
        self.pill_bar.setObjectName("pill_bar")
        self.pill_layout = QtWidgets.QHBoxLayout(self.pill_bar)
        self.pill_layout.setContentsMargins(0, 0, 0, 2)
        self.pill_layout.setSpacing(6)
        self.pill_bar.setVisible(False)
        layout.addWidget(self.pill_bar)

        self.debug_view = QtWidgets.QPlainTextEdit()
        self.debug_view.setObjectName("chat_debug")
        self.debug_view.setReadOnly(True)
        self.debug_view.setMaximumBlockCount(500)
        self.debug_view.setVisible(False)
        self.debug_view.setMaximumHeight(130)
        layout.addWidget(self.debug_view)
        self.debug_message.connect(self.debug_view.appendPlainText)
        self.token_received.connect(self._on_token_received)
        self.thought_received.connect(self._on_thought_received)
        self.tool_executed.connect(self._on_tool_executed)

        input_row = QtWidgets.QHBoxLayout()
        self.mic_button = QtWidgets.QPushButton("●")
        self.mic_button.setObjectName("chat_mic_button")
        self.mic_button.setToolTip("Start voice input")
        self.mic_button.setFixedSize(34, 32)
        self.input = QtWidgets.QLineEdit()
        self.input.setObjectName("chat_input")
        self.input.setPlaceholderText("Ask PyMOL…")
        self.input.setFont(font)
        self.input.setMinimumHeight(32)
        self.input.returnPressed.connect(self.send)
        self.input.installEventFilter(self)

        self.key_status = QtWidgets.QLabel("●")
        self.key_status.setObjectName("chat_key_status")
        self.key_status.setAlignment(QtCore.Qt.AlignCenter)
        self.key_status.setFixedWidth(14)

        self.menu_button = QtWidgets.QToolButton()
        self.menu_button.setObjectName("chat_menu_button")
        self.menu_button.setText("⋯")
        self.menu_button.setToolTip("Options")
        self.menu_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.menu_button.setFixedSize(32, 32)
        self.options_menu = QtWidgets.QMenu(self.menu_button)
        self.key_action = self.options_menu.addAction("API Key Settings…")
        self.key_action.triggered.connect(self.show_key_dialog)
        self.options_menu.addSeparator()

        self.thinking_menu = QtWidgets.QMenu("Deep Thinking (深度思考)", self.options_menu)
        self.thinking_action = self.thinking_menu.menuAction()
        self.thinking_action.setCheckable(True)
        self.thinking_action.setToolTip("Thinking modes: Auto (智能触发), Always On, Always Off")

        self.thinking_group = QtWidgets.QActionGroup(self)
        self.thinking_group.setExclusive(True)

        self.action_thinking_auto = self.thinking_menu.addAction("Auto (智能触发 — 推荐)")
        self.action_thinking_auto.setCheckable(True)
        self.action_thinking_auto.setData("auto")
        self.action_thinking_auto.setToolTip("Intelligently triggers thinking on complex reasoning, fast for operations")
        self.thinking_group.addAction(self.action_thinking_auto)

        self.action_thinking_on = self.thinking_menu.addAction("Always On (始终开启)")
        self.action_thinking_on.setCheckable(True)
        self.action_thinking_on.setData("on")
        self.action_thinking_on.setToolTip("Always enable deep thinking before answering")
        self.thinking_group.addAction(self.action_thinking_on)

        self.action_thinking_off = self.thinking_menu.addAction("Always Off (极速模式)")
        self.action_thinking_off.setCheckable(True)
        self.action_thinking_off.setData("off")
        self.action_thinking_off.setToolTip("Always disable thinking for instant answers")
        self.thinking_group.addAction(self.action_thinking_off)

        saved_mode = self.settings.value("thinking_mode", thinking_mode(), type=str)
        if saved_mode == "on":
            self.action_thinking_on.setChecked(True)
        elif saved_mode == "off":
            self.action_thinking_off.setChecked(True)
        else:
            self.action_thinking_auto.setChecked(True)

        self.thinking_group.triggered.connect(self._thinking_mode_triggered)
        self.options_menu.addMenu(self.thinking_menu)
        self.options_menu.addSeparator()
        self.speech_action = self.options_menu.addAction("Spoken Replies")
        self.speech_action.setCheckable(True)
        self.speech_action.setToolTip("Spoken replies using voice synthesis")
        self.options_menu.setToolTipsVisible(True)
        self.speech_action.setChecked(self.settings.value("spoken_replies", True, type=bool))
        self.speech_action.setEnabled(self.speech.available)
        self.speech_action.toggled.connect(self._speech_toggled)
        self.options_menu.addSeparator()
        self.debug_action = self.options_menu.addAction("Show Command Log")
        self.debug_action.setCheckable(True)
        self.debug_action.toggled.connect(self.debug_view.setVisible)
        self.options_menu.addSeparator()
        self.top_panel_action = self.options_menu.addAction("Top Panel (顶部控制台)")
        self.top_panel_action.setCheckable(True)
        self.top_panel_action.setToolTip("Toggle PyMOL native upper console and quick buttons")
        main_win = self.parent() if isinstance(self.parent(), QtWidgets.QMainWindow) else None
        is_visible = bool(main_win and hasattr(main_win, "ext_window") and main_win.ext_window.isVisible())
        self.top_panel_action.setChecked(is_visible)
        self.top_panel_action.toggled.connect(self._toggle_top_panel)
        self.options_menu.addSeparator()
        self.reload_action = self.options_menu.addAction("Reload Plugin (热重载)")
        self.reload_action.setToolTip("Reload Python code and restart chat dock without closing PyMOL")
        self.reload_action.triggered.connect(self._reload_plugin)
        self.options_menu.addSeparator()
        self.cancel_action = self.options_menu.addAction("Stop Generation (停止生成)")
        self.cancel_action.setToolTip("Cancel active agent execution (Esc)")
        self.cancel_action.setEnabled(False)
        self.cancel_action.triggered.connect(self.cancel)
        self.menu_button.setMenu(self.options_menu)

        self.stop_button = QtWidgets.QPushButton("⏹ Stop")
        self.stop_button.setObjectName("chat_stop_button")
        self.stop_button.setToolTip("Cancel running operation (Esc)")
        self.stop_button.setVisible(False)
        self.stop_button.clicked.connect(self.cancel)

        input_row.addWidget(self.mic_button)
        input_row.addWidget(self.input, 1)
        input_row.addWidget(self.stop_button)
        input_row.addWidget(self.key_status)
        input_row.addWidget(self.menu_button)
        layout.addLayout(input_row)
        self.setWidget(root)

        self.voice = VoiceRecorder(self)
        self.voice.state_changed.connect(self._recording_changed)
        self.voice.finished.connect(self._recording_finished)
        self.voice.error.connect(self.show_error)
        self.mic_button.clicked.connect(self.toggle_recording)
        self._update_key_status()
        self._apply_style()
        # PyMOL finishes applying its application palette during startup.
        # Reassert the dock's local theme after that pass as well.
        QtCore.QTimer.singleShot(0, self._apply_style)
        QtCore.QTimer.singleShot(750, self._apply_style)
        QtCore.QTimer.singleShot(300, self._refresh_action_pills)
        QtCore.QTimer.singleShot(1000, self._offer_key_setup)

        self._last_state_signature = None
        self._viewport_poll_timer = QtCore.QTimer(self)
        self._viewport_poll_timer.setInterval(700)
        self._viewport_poll_timer.timeout.connect(self._poll_viewport_changes)
        self._viewport_poll_timer.start()

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(450, 780)

    def _apply_style(self):
        window = QtGui.QColor("#1E1F23")
        base = QtGui.QColor("#16171A")
        field = QtGui.QColor("#242730")
        text = QtGui.QColor("#E2E8F0")
        muted = QtGui.QColor("#94A3B8")

        panel_palette = self.panel_root.palette()
        panel_palette.setColor(QtGui.QPalette.Window, window)
        panel_palette.setColor(QtGui.QPalette.WindowText, text)
        self.panel_root.setPalette(panel_palette)

        for widget, background in (
            (self.history, base),
            (self.debug_view, base),
            (self.input, field),
        ):
            palette = widget.palette()
            palette.setColor(QtGui.QPalette.Base, background)
            palette.setColor(QtGui.QPalette.Text, text)
            palette.setColor(QtGui.QPalette.Window, background)
            if hasattr(QtGui.QPalette, "PlaceholderText"):
                palette.setColor(QtGui.QPalette.PlaceholderText, muted)
            widget.setPalette(palette)
            widget.setAutoFillBackground(True)

        self.setStyleSheet("""
            QDockWidget {
                color: #E2E8F0;
                background-color: #1E1F23;
                border: 1px solid #2B2E38;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
            }
            QDockWidget::title {
                background-color: #1E1F23;
                color: #CBD5E1;
                font-weight: 600;
                font-size: 12px;
                padding: 6px 10px;
                border-bottom: 1px solid #2B2E38;
            }
            QWidget#pymol_flow_panel {
                background-color: #1E1F23;
                color: #E2E8F0;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
            }
            QTextBrowser#chat_history, QPlainTextEdit#chat_debug {
                background-color: #16171A;
                color: #E2E8F0;
                border: 1px solid #2B2E38;
                border-radius: 8px;
                padding: 6px;
                selection-background-color: #5B45B2;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
            }
            QWidget#pill_bar {
                background: transparent;
            }
            QPushButton#action_pill {
                background-color: #21242D;
                color: #A5B4FC;
                border: 1px solid #374151;
                border-radius: 11px;
                padding: 3px 8px;
                font-size: 11px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
            }
            QPushButton#action_pill:hover {
                background-color: #3730A3;
                color: #FFFFFF;
                border-color: #6366F1;
            }
            QPushButton#action_pill:pressed {
                background-color: #4338CA;
            }
            QLabel#selection_badge {
                color: #38BDF8;
                font-size: 11px;
                font-weight: 600;
                padding: 2px 4px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
            }
            QPushButton#action_pill_sele {
                background-color: #0F2A4A;
                color: #38BDF8;
                border: 1px solid #0284C7;
                border-radius: 11px;
                padding: 3px 8px;
                font-size: 11px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
            }
            QPushButton#action_pill_sele:hover {
                background-color: #0284C7;
                color: #FFFFFF;
                border-color: #38BDF8;
            }
            QPushButton#clear_selection_btn {
                background-color: #27272A;
                color: #94A3B8;
                border: 1px solid #3F3F46;
                border-radius: 9px;
                padding: 1px 6px;
                font-size: 10px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
            }
            QPushButton#clear_selection_btn:hover {
                background-color: #DC2626;
                color: #FFFFFF;
                border-color: #EF4444;
            }
            QScrollBar:vertical {
                border: none;
                background-color: #16171A;
                width: 7px;
                margin: 0px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background-color: #334155;
                min-height: 20px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #475569;
            }
            QScrollBar::handle:vertical:pressed {
                background-color: #64748B;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                background: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
            QScrollBar:horizontal {
                border: none;
                background-color: #16171A;
                height: 7px;
                margin: 0px;
                border-radius: 3px;
            }
            QScrollBar::handle:horizontal {
                background-color: #334155;
                min-width: 20px;
                border-radius: 3px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #475569;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
                background: none;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: none;
            }
            QLineEdit#chat_input {
                min-height: 32px;
                padding: 0px 10px;
                background-color: #242730;
                color: #F1F5F9;
                border: 1px solid #333842;
                border-radius: 6px;
                selection-background-color: #5B45B2;
                font-size: 13px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
            }
            QLineEdit#chat_input:focus {
                border: 1px solid #7C5CFC;
                background-color: #262A35;
            }
            QLineEdit#chat_input:disabled {
                color: #64748B;
                background-color: #1A1C22;
                border-color: #262932;
            }
            QPushButton#chat_mic_button {
                background-color: #242730;
                color: #94A3B8;
                border: 1px solid #333842;
                border-radius: 6px;
                font-size: 15px;
                padding: 0px;
            }
            QPushButton#chat_mic_button:hover {
                background-color: #2E333F;
                color: #38BDF8;
                border-color: #475569;
            }
            QPushButton#chat_mic_button[recording="true"] {
                color: white;
                background-color: #DC2626;
                border-color: #EF4444;
            }
            QPushButton#chat_stop_button {
                background-color: #DC2626;
                color: #FFFFFF;
                border: 1px solid #EF4444;
                border-radius: 6px;
                font-size: 11px;
                font-weight: 600;
                padding: 4px 10px;
                min-height: 24px;
            }
            QPushButton#chat_stop_button:hover {
                background-color: #B91C1C;
                border: 1px solid #F87171;
            }
            QPushButton#chat_stop_button:pressed {
                background-color: #991B1B;
            }
            QLabel#chat_key_status {
                color: #4ADE80;
                font-size: 14px;
            }
            QLabel#chat_key_status[active="false"] {
                color: #64748B;
            }
            QToolButton#chat_menu_button {
                background-color: transparent;
                color: #94A3B8;
                border: 1px solid transparent;
                border-radius: 6px;
                font-size: 18px;
                padding: 0px;
            }
            QToolButton#chat_menu_button:hover {
                background-color: #242730;
                border: 1px solid #333842;
                color: #F1F5F9;
            }
            QToolButton#chat_menu_button::menu-indicator {
                image: none;
                width: 0px;
            }
            QMenu {
                background-color: #1E1F23;
                color: #E2E8F0;
                border: 1px solid #333842;
                border-radius: 6px;
                padding: 4px;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
            }
            QMenu::item {
                padding: 6px 24px 6px 10px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #2E333F;
                color: #FFFFFF;
            }
            QScrollBar:vertical {
                background-color: #16171A;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background-color: #333842;
                min-height: 24px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #475569;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

    def _thinking_mode_triggered(self, action: QtWidgets.QAction):
        mode = action.data() or "auto"
        self.settings.setValue("thinking_mode", mode)
        if self.agent is not None:
            self.agent.enable_thinking = mode

    def _ensure_agent(self):
        if self.agent is None:
            # Agent work runs off the GUI thread; emitting Qt signals safely
            # queues debug and streaming updates back onto the GUI thread.
            current_mode = self.settings.value("thinking_mode", thinking_mode(), type=str)
            self.agent = PyMOLAgent(
                debug=self.debug_message.emit,
                on_token=self.token_received.emit,
                on_thought=self.thought_received.emit,
                on_tool_call=self.tool_executed.emit,
                enable_thinking=current_mode,
            )
        return self.agent

    def _offer_key_setup(self):
        if not api_key():
            self.show_key_dialog()

    def _update_key_status(self):
        active = bool(api_key())
        self.key_status.setProperty("active", active)
        current_url = base_url().lower()
        provider = "DashScope / Qwen" if "qianwen" in current_url or "dashscope" in current_url else "AI"
        self.key_status.setToolTip(
            f"{provider} API key active" if active else f"No {provider} API key configured"
        )
        self.key_status.style().unpolish(self.key_status)
        self.key_status.style().polish(self.key_status)

    def show_key_dialog(self):
        active_key = api_key()
        stored_key = read_api_key()
        store_name = credential_store_name()
        source = store_name if stored_key and stored_key == active_key else "environment configuration"
        dialog = APIKeyDialog(self, has_key=bool(active_key), source=source)
        result = dialog.exec_()
        if result == QtWidgets.QDialog.Accepted:
            self.agent = None
            self._update_key_status()
            self._append_message("PyMOL", f"API key saved securely in {store_name}.")
            return True
        if result == 2:
            self.agent = None
            self._update_key_status()
            message = f"{store_name} key removed."
            if api_key():
                message += " A key from the environment configuration remains active."
            self._append_message("PyMOL", message)
        return False

    def _reload_plugin(self):
        try:
            from . import reload_plugin
            reload_plugin()
        except Exception:
            try:
                import pymol_flow
                pymol_flow.reload_plugin()
            except Exception:
                pass

    def _toggle_top_panel(self, checked: bool):
        main_win = self.parent() if isinstance(self.parent(), QtWidgets.QMainWindow) else None
        if main_win and hasattr(main_win, "ext_window"):
            main_win.ext_window.setVisible(checked)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape and self.busy:
            self.cancel()
            event.accept()
            return
        super().keyPressEvent(event)

    def cancel(self):
        """Immediately cancel active agent execution and restore user input."""
        if not self.busy:
            return
        self._cancelled_task = True
        if self.agent is not None:
            self.agent.cancel()
        self._streaming = False
        self._thinking_timer.stop()

        if self._active_turn is not None:
            thought = self._active_turn.get("thought", "")
            streamed = self._active_turn.get("text", "")
            elapsed = max(0.1, time.time() - self._active_turn.get("start_time", time.time()))
            cancelled_text = (streamed + ("\n\n" if streamed else "")) + "*[⏹ 操作已由用户手动取消]*"
            self._messages.append({
                "id": self._active_turn["id"],
                "who": "PyMOL",
                "text": cancelled_text,
                "thought": thought,
                "thought_duration": self._active_turn.get("thought_duration", 0.0),
                "exec_duration": 0.0,
                "total_duration": elapsed,
                "tool_calls": self._active_turn.get("tool_calls", []),
                "thought_expanded": False,
                "tools_expanded": {},
            })
            self._active_turn = None
            self._render_history(scroll_to_bottom=True)

        self._set_busy(False)

    def _ensure_api_key(self):
        return bool(api_key()) or self.show_key_dialog()

    def _on_thought_received(self, chunk: str):
        if not chunk:
            return
        if self._active_turn is None:
            self._active_turn = {
                "id": len(self._messages),
                "who": "PyMOL",
                "text": "",
                "thought": "",
                "thought_duration": 0.0,
                "exec_duration": 0.0,
                "total_duration": 0.0,
                "tool_calls": [],
                "state": "thinking",
                "start_time": time.time(),
                "thought_expanded": False,
                "tools_expanded": {},
            }
            self._thinking_timer.start()
        else:
            self._active_turn["state"] = "thinking"
        self._active_turn["thought"] += chunk
        if not self._thinking_timer.isActive():
            self._thinking_timer.start()

    def _on_tool_executed(self, tool_info: dict):
        if self._active_turn is not None:
            self._active_turn["state"] = "executing"
            if self._active_turn.get("thought") and not self._active_turn.get("thought_duration"):
                self._active_turn["thought_duration"] = max(0.1, time.time() - self._active_turn["start_time"])
            self._active_turn.setdefault("tool_calls", []).append(tool_info)
            self._render_history(scroll_to_bottom=self._auto_scroll)

    def _on_thinking_tick(self):
        if self._active_turn is not None and self._active_turn.get("state") in {
            "thinking", "processing", "executing"
        }:
            self._render_history(scroll_to_bottom=False)

    def _on_anchor_clicked(self, url: QtCore.QUrl):
        url_str = url.toString()
        if url_str.startswith("toggle://thought_"):
            try:
                msg_id = int(url_str.replace("toggle://thought_", ""))
                for m in self._messages:
                    if m.get("id") == msg_id:
                        m["thought_expanded"] = not m.get("thought_expanded", False)
                        break
                if self._active_turn and self._active_turn.get("id") == msg_id:
                    self._active_turn["thought_expanded"] = not self._active_turn.get("thought_expanded", False)
                self._auto_scroll = False
                self._render_history(scroll_to_bottom=False)
            except Exception:
                pass
            return
        if url_str.startswith("toggle://tool_"):
            try:
                parts = url_str.replace("toggle://tool_", "").split("_")
                msg_id, t_idx = int(parts[0]), int(parts[1])
                for m in self._messages:
                    if m.get("id") == msg_id:
                        tools_exp = m.setdefault("tools_expanded", {})
                        tools_exp[t_idx] = not tools_exp.get(t_idx, False)
                        break
                if self._active_turn and self._active_turn.get("id") == msg_id:
                    tools_exp = self._active_turn.setdefault("tools_expanded", {})
                    tools_exp[t_idx] = not tools_exp.get(t_idx, False)
                self._auto_scroll = False
                self._render_history(scroll_to_bottom=False)
            except Exception:
                pass
            return
        QtGui.QDesktopServices.openUrl(url)

    def _on_token_received(self, token: str):
        if not token:
            return
        self._streaming = True
        if self._active_turn is None:
            self._active_turn = {
                "id": len(self._messages),
                "who": "PyMOL",
                "text": "",
                "thought": "",
                "thought_duration": 0.0,
                "exec_duration": 0.0,
                "total_duration": 0.0,
                "tool_calls": [],
                "state": "answering",
                "start_time": time.time(),
                "thought_expanded": False,
                "tools_expanded": {},
            }
        elif self._active_turn.get("state") in {"thinking", "processing", "executing"}:
            self._active_turn["state"] = "answering"
            if not self._active_turn.get("thought_duration") and self._active_turn.get("thought"):
                self._active_turn["thought_duration"] = max(0.1, time.time() - self._active_turn["start_time"])
            self._thinking_timer.stop()

        self._active_turn["text"] += token
        now = time.time()
        if now - self._last_stream_render >= 0.04:
            self._last_stream_render = now
            self._stream_timer.stop()
            self._render_history(scroll_to_bottom=False)
        elif not self._stream_timer.isActive():
            self._stream_timer.start(40)

    def send(self):
        text = self.input.text().strip()
        if not text or self.busy:
            return
        if not self._ensure_api_key():
            return
        self.speech.stop()
        self.input.clear()
        self._streaming = False
        self._cancelled_task = False
        self._auto_scroll = True
        self._append_message("You", text)
        self._set_busy(True)
        try:
            agent = self._ensure_agent()
        except Exception as exc:
            self.show_error(str(exc))
            self._set_busy(False)
            return

        mode = self.settings.value("thinking_mode", thinking_mode(), type=str)
        will_think = should_enable_thinking(text, mode)
        initial_state = "thinking" if will_think else "processing"

        self._active_turn = {
            "id": len(self._messages),
            "who": "PyMOL",
            "text": "",
            "thought": "",
            "thought_duration": 0.0,
            "exec_duration": 0.0,
            "total_duration": 0.0,
            "tool_calls": [],
            "state": initial_state,
            "start_time": time.time(),
            "thought_expanded": False,
            "tools_expanded": {},
        }
        self._thinking_timer.start()
        self._render_history(scroll_to_bottom=True)

        task = Task(agent.ask, text)
        task.signals.done.connect(self._answer_received)
        task.signals.failed.connect(self._task_failed)
        self.thread_pool.start(task)

    def _answer_received(self, answer):
        if getattr(self, "_cancelled_task", False):
            self._cancelled_task = False
            return
        self._streaming = False
        self._stream_timer.stop()
        self._thinking_timer.stop()
        reply_str = str(answer)

        if self._active_turn is not None:
            streamed = self._active_turn.get("text", "")
            final_content = reply_str if reply_str and reply_str != "ignored in stream mode" else streamed
            if not final_content:
                final_content = streamed

            thought = getattr(answer, "thought", "") or self._active_turn.get("thought", "")
            t_dur = getattr(answer, "thought_duration", 0.0) or self._active_turn.get("thought_duration", 0.0)
            e_dur = getattr(answer, "exec_duration", 0.0)
            tot_dur = getattr(answer, "total_duration", 0.0)
            tool_calls = getattr(answer, "tool_calls", []) or self._active_turn.get("tool_calls", [])

            self._messages.append({
                "id": self._active_turn["id"],
                "who": "PyMOL",
                "text": final_content,
                "thought": thought,
                "thought_duration": t_dur,
                "exec_duration": e_dur,
                "total_duration": tot_dur,
                "tool_calls": tool_calls,
                "thought_expanded": False,
                "tools_expanded": {},
            })
            self._active_turn = None
        else:
            self._append_message("PyMOL", reply_str)

        self._render_history(scroll_to_bottom=self._auto_scroll)
        self._set_busy(False)
        if self.speech_action.isChecked() and self.isVisible() and not self.voice.is_recording:
            self.speech.speak(str(answer))

    def _speech_toggled(self, enabled):
        self.settings.setValue("spoken_replies", enabled)
        if not enabled:
            self.speech.stop()

    def _on_slider_pressed(self):
        self._auto_scroll = False

    def _on_slider_released(self):
        v_bar = self.history.verticalScrollBar()
        if v_bar.value() >= max(0, v_bar.maximum() - 35):
            self._auto_scroll = True
        else:
            self._auto_scroll = False
        self._render_history(scroll_to_bottom=False)

    def _on_scroll_value_changed(self, value: int):
        if getattr(self, "_rendering_history", False):
            return
        v_bar = self.history.verticalScrollBar()
        if value >= max(0, v_bar.maximum() - 35):
            self._auto_scroll = True
        else:
            self._auto_scroll = False

    def _flush_stream_render(self):
        if self._active_turn is not None:
            self._last_stream_render = time.time()
            self._render_history(scroll_to_bottom=False)

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if event.key() == QtCore.Qt.Key_Escape and self.busy:
            self.cancel()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Escape and self.busy:
            self.cancel()
            return True
        if hasattr(self, "history") and (
            obj == self.history or (hasattr(self.history, "viewport") and obj == self.history.viewport())
        ):
            if event.type() == QtCore.QEvent.Wheel:
                if event.angleDelta().y() > 0:
                    self._auto_scroll = False
            elif event.type() == QtCore.QEvent.KeyPress:
                if event.key() in (QtCore.Qt.Key_PageUp, QtCore.Qt.Key_Up):
                    self._auto_scroll = False
        return super().eventFilter(obj, event)

    def cancel(self):
        """Cancel running agent execution immediately and unlock input."""
        if not self.busy and not getattr(self, "_active_turn", None):
            return
        self._cancelled_task = True
        self._stream_timer.stop()
        self._thinking_timer.stop()
        self._streaming = False
        self.speech.stop()
        if hasattr(self, "agent") and self.agent is not None:
            self.agent.cancel()
        if self._active_turn is not None:
            self._messages.append({
                "id": self._active_turn["id"],
                "who": "PyMOL",
                "text": "*[⏹ 操作已由用户手动取消]*",
                "thought": self._active_turn.get("thought", ""),
                "thought_duration": self._active_turn.get("thought_duration", 0.0),
                "exec_duration": self._active_turn.get("exec_duration", 0.0),
                "total_duration": max(0.1, time.time() - self._active_turn.get("start_time", time.time())),
                "tool_calls": self._active_turn.get("tool_calls", []),
                "thought_expanded": False,
                "tools_expanded": {},
            })
            self._active_turn = None
        else:
            self._append_message("PyMOL", "*[⏹ 操作已由用户手动取消]*")
        self._render_history(scroll_to_bottom=self._auto_scroll)
        self._set_busy(False)

    def hideEvent(self, event):
        self.speech.stop()
        super().hideEvent(event)

    def _task_failed(self, message):
        if getattr(self, "_cancelled_task", False):
            self._cancelled_task = False
            return
        self._streaming = False
        self._stream_timer.stop()
        self._thinking_timer.stop()
        self._active_turn = None
        self.show_error(message)
        self._set_busy(False)

    def _format_inline(self, s: str) -> str:
        s = html.escape(s)
        s = re.sub(r"\*\*([^*]+)\*\*", r'<b style="color: #F8FAFC; font-weight: 600;">\1</b>', s)
        s = re.sub(
            r"`([^`]+)`",
            r'<code style="background-color: #242832; color: #93C5FD; padding: 1px 4px; border: 1px solid #333844; border-radius: 3px; font-family: Consolas, monospace; font-size: 11.5px; font-weight: 600;">\1</code>',
            s,
        )
        s = re.sub(r"(?<!\w)\*([^*]+)\*(?!\w)", r'<i style="color: #CBD5E1;">\1</i>', s)
        return s

    def _format_content(self, text: str) -> str:
        code_blocks = []

        def save_code_block(match):
            lang = match.group(1) or ""
            code = match.group(2)
            code_blocks.append((lang, code))
            return f"\n\n__CODE_BLOCK_{len(code_blocks)-1}__\n\n"

        # 1. Protect fenced code blocks
        text_clean = re.sub(r"```(\w+)?\n?(.*?)```", save_code_block, text, flags=re.DOTALL)

        lines = text_clean.split("\n")
        processed_lines: list[str] = []
        i = 0
        n = len(lines)

        def is_table_sep(s: str) -> bool:
            s = s.strip()
            if not s or "|" not in s:
                return False
            parts = [p.strip() for p in s.strip("|").split("|")]
            return len(parts) >= 1 and all(bool(re.match(r"^:?[-]{2,}:?$", p)) for p in parts)

        def parse_row(line_str: str) -> list[str]:
            trimmed = line_str.strip()
            if trimmed.startswith("|"):
                trimmed = trimmed[1:]
            if trimmed.endswith("|"):
                trimmed = trimmed[:-1]
            return [c.strip() for c in trimmed.split("|")]

        while i < n:
            line = lines[i]
            stripped = line.strip()

            if stripped.startswith("__CODE_BLOCK_") and stripped.endswith("__"):
                processed_lines.append(stripped)
                i += 1
                continue

            # Markdown Table detection
            if "|" in stripped and i + 1 < n and is_table_sep(lines[i + 1]):
                table_lines = [stripped]
                delimiters = [p.strip() for p in lines[i + 1].strip().strip("|").split("|")]
                i += 2  # skip header and delimiter row
                while i < n and "|" in lines[i].strip() and not lines[i].strip().startswith("```"):
                    table_lines.append(lines[i].strip())
                    i += 1

                # Parse header
                header_cells = parse_row(table_lines[0])
                num_cols = len(header_cells)

                # Determine alignments
                col_aligns = []
                for idx_c in range(num_cols):
                    d = delimiters[idx_c] if idx_c < len(delimiters) else ""
                    if d.startswith(":") and d.endswith(":"):
                        col_aligns.append("center")
                    elif d.endswith(":"):
                        col_aligns.append("right")
                    else:
                        col_aligns.append("left")

                th_cells = []
                for c_idx, c_val in enumerate(header_cells):
                    align = col_aligns[c_idx]
                    th_cells.append(
                        f'<th style="color: #93C5FD; font-size: 11px; font-weight: bold; text-align: {align}; padding: 7px 10px;">{self._format_inline(c_val)}</th>'
                    )
                th_html = "".join(th_cells)

                # Parse body rows
                rows_html = []
                for r_idx, r_line in enumerate(table_lines[1:]):
                    bg = "#181A21" if r_idx % 2 == 0 else "#1F232D"
                    r_cells = parse_row(r_line)
                    td_cells = []
                    for c_idx in range(num_cols):
                        align = col_aligns[c_idx]
                        val = r_cells[c_idx] if c_idx < len(r_cells) else ""
                        val_fmt = self._format_inline(val)
                        td_cells.append(
                            f'<td style="color: #CBD5E1; font-size: 11px; line-height: 145%; text-align: {align}; padding: 6px 10px;">{val_fmt}</td>'
                        )
                    rows_html.append(f'<tr bgcolor="{bg}">{"".join(td_cells)}</tr>')

                table_html = (
                    f'<table width="100%" cellpadding="0" cellspacing="1" bgcolor="#2E3442" style="margin: 8px 0; border-radius: 6px;">'
                    f'<tr bgcolor="#222836">{th_html}</tr>'
                    f'{"".join(rows_html)}'
                    f'</table>'
                )
                processed_lines.append(table_html)
                continue

            # Headings: #, ##, ###, ####
            m_h1 = re.match(r"^#\s+(.+)$", stripped)
            m_h2 = re.match(r"^##\s+(.+)$", stripped)
            m_h3 = re.match(r"^###\s+(.+)$", stripped)
            m_h4 = re.match(r"^####\s+(.+)$", stripped)
            if m_h1:
                h_text = self._format_inline(m_h1.group(1))
                processed_lines.append(
                    f'<div style="font-size: 14px; font-weight: bold; color: #F8FAFC; margin-top: 14px; margin-bottom: 6px; padding-bottom: 4px; border-bottom: 1px solid #334155;">{h_text}</div>'
                )
                i += 1
                continue
            elif m_h2:
                h_text = self._format_inline(m_h2.group(1))
                processed_lines.append(
                    f'<div style="font-size: 13px; font-weight: bold; color: #60A5FA; margin-top: 12px; margin-bottom: 5px; padding-bottom: 3px; border-bottom: 1px dashed #2E3440;">{h_text}</div>'
                )
                i += 1
                continue
            elif m_h3:
                h_text = self._format_inline(m_h3.group(1))
                processed_lines.append(
                    f'<div style="font-size: 12px; font-weight: bold; color: #38BDF8; margin-top: 9px; margin-bottom: 4px;">{h_text}</div>'
                )
                i += 1
                continue
            elif m_h4:
                h_text = self._format_inline(m_h4.group(1))
                processed_lines.append(
                    f'<div style="font-size: 11.5px; font-weight: bold; color: #A78BFA; margin-top: 7px; margin-bottom: 3px;">{h_text}</div>'
                )
                i += 1
                continue

            # Horizontal rule
            if re.match(r"^(\-{3,}|\*{3,}|_{3,})$", stripped):
                processed_lines.append('<div style="border-top: 1px solid #2B2E38; margin: 10px 0;"></div>')
                i += 1
                continue

            # Blockquotes
            m_quote = re.match(r"^>\s*(.+)$", stripped)
            if m_quote:
                q_text = self._format_inline(m_quote.group(1))
                processed_lines.append(
                    f'<table width="100%" cellpadding="6" cellspacing="0" style="margin: 4px 0;">'
                    f'<tr><td style="border-left: 3px solid #7C5CFC; background-color: #1A1926; color: #CBD5E1; font-size: 11.5px; line-height: 140%;">'
                    f'{q_text}'
                    f'</td></tr></table>'
                )
                i += 1
                continue

            # Unordered lists: - item, * item, + item
            m_ul = re.match(r"^(\s*)[-*+]\s+(.+)$", line)
            if m_ul:
                indent = 16 if len(m_ul.group(1)) >= 2 else 6
                item_text = self._format_inline(m_ul.group(2))
                processed_lines.append(
                    f'<div style="margin: 3px 0 3px {indent}px; line-height: 150%; color: #CBD5E1;"><span style="color: #60A5FA; font-weight: bold;">•</span> &nbsp;{item_text}</div>'
                )
                i += 1
                continue

            # Numbered lists: 1. item, 2. item
            m_ol = re.match(r"^(\s*)(\d+)\.\s+(.+)$", line)
            if m_ol:
                indent = 16 if len(m_ol.group(1)) >= 2 else 6
                num = m_ol.group(2)
                item_text = self._format_inline(m_ol.group(3))
                processed_lines.append(
                    f'<div style="margin: 3px 0 3px {indent}px; line-height: 150%; color: #CBD5E1;"><span style="color: #A78BFA; font-weight: bold; font-size: 11px;">{num}.</span> &nbsp;{item_text}</div>'
                )
                i += 1
                continue

            # Regular paragraph lines
            if stripped:
                line_fmt = self._format_inline(stripped)
                processed_lines.append(f'<div style="margin: 3px 0; line-height: 155%; color: #E2E8F0;">{line_fmt}</div>')
            else:
                # Empty line -> subtle vertical paragraph gap
                processed_lines.append('<div style="height: 6px;"></div>')

            i += 1

        result_html = "\n".join(processed_lines)

        # Re-insert code blocks
        for idx, (lang, code) in enumerate(code_blocks):
            escaped_code = html.escape(code.strip()).replace("\n", "<br>").replace(" ", "&nbsp;")
            lang_label = f'<span style="color: #64748B; font-size: 10px; font-weight: 600; text-transform: uppercase;">{lang}</span>' if lang else ""
            header_row = f'<tr><td style="padding: 4px 8px; background-color: #121418; border-bottom: 1px solid #232730;">{lang_label}</td></tr>' if lang_label else ""
            block_html = (
                f'<table width="100%" cellpadding="6" cellspacing="0" style="margin: 6px 0;" bgcolor="#14161B">'
                f'{header_row}'
                f'<tr><td style="border: 1px solid #282C35; border-radius: 4px; font-family: Consolas, monospace; font-size: 11.5px; color: #93C5FD; font-weight: 600; line-height: 140%;">'
                f'{escaped_code}'
                f'</td></tr></table>'
            )
            result_html = result_html.replace(f"__CODE_BLOCK_{idx}__", block_html)

        return result_html

    def _render_message_card(self, msg: dict[str, Any]) -> str:
        who = msg.get("who", "PyMOL")
        text = msg.get("text", "")
        content = self._format_content(text)

        if who == "You":
            return (
                '<table width="100%" cellpadding="9" cellspacing="0" style="margin-bottom: 8px;" bgcolor="#28233C">'
                '<tr><td style="border: 1px solid #433966; border-radius: 8px;">'
                '<div style="color: #A78BFA; font-size: 11px; font-weight: bold; margin-bottom: 4px;">'
                '👤 You</div>'
                f'<div style="color: #F8FAFC; font-size: 13px; line-height: 150%;">{content}</div>'
                '</td></tr></table>'
            )
        elif who == "PyMOL":
            t_dur = msg.get("thought_duration", 0.0)
            e_dur = msg.get("exec_duration", 0.0)
            tot_dur = msg.get("total_duration", 0.0)
            meta_chips = []
            if t_dur > 0:
                meta_chips.append(f"思考 {t_dur:.1f}s")
            if e_dur > 0:
                meta_chips.append(f"运行 {e_dur:.1f}s")
            elif tot_dur > 0 and not t_dur:
                meta_chips.append(f"耗时 {tot_dur:.1f}s")
            meta_str = " · ".join(meta_chips)
            meta_html = (
                f' &nbsp;<span style="color: #64748B; font-size: 10px; font-weight: normal;">({meta_str})</span>'
                if meta_str else ""
            )

            badge_html = (
                '<div style="margin-bottom: 5px;">'
                f'<span style="color: #4ADE80; font-size: 11px; font-weight: bold;">✦ PyMOL AI</span>{meta_html}'
                '</div>'
            )

            # Collapsible Thought pill
            thought = msg.get("thought", "").strip()
            thought_html = ""
            if thought:
                is_expanded = msg.get("thought_expanded", False)
                arrow = "▼" if is_expanded else "▶"
                dur_label = f" {t_dur:.1f}s" if t_dur > 0 else ""
                thought_toggle = f"toggle://thought_{msg['id']}"
                thought_html = (
                    f'<div style="margin: 3px 0 6px 0;">'
                    f'<a href="{thought_toggle}" style="text-decoration: none; color: #94A3B8; font-size: 11px; font-weight: 500;">'
                    f'<span style="color: #A78BFA;">💭</span> Thought for{dur_label} &nbsp;<span style="color: #7C5CFC; font-size: 10px;">{arrow}</span>'
                    f'</a>'
                )
                if is_expanded:
                    escaped_thought = html.escape(thought).replace("\n", "<br>")
                    thought_html += (
                        f'<table width="100%" cellpadding="6" cellspacing="0" style="margin-top: 4px; margin-bottom: 4px;" bgcolor="#16171B">'
                        f'<tr><td style="border: 1px solid #282C35; border-left: 2px solid #7C5CFC; border-radius: 4px; color: #94A3B8; font-size: 11px; line-height: 140%;">'
                        f'{escaped_thought}'
                        f'</td></tr></table>'
                    )
                thought_html += '</div>'

            # Collapsible Tool Execution pills
            tool_calls = msg.get("tool_calls", [])
            tools_html = ""
            if tool_calls:
                tools_exp = msg.get("tools_expanded", {})
                for t_idx, tc in enumerate(tool_calls):
                    is_tc_expanded = tools_exp.get(t_idx, False)
                    t_arrow = "▼" if is_tc_expanded else "▶"
                    t_dur_val = tc.get("duration", 0.0)
                    dur_str = f"{t_dur_val:.1f}s" if t_dur_val > 0 else ""
                    is_failed = tc.get("ok") is False or bool(tc.get("error"))

                    if is_failed:
                        icon = "⚠"
                        icon_color = "#F87171"
                        status_str = f"failed · {dur_str}" if dur_str else "failed"
                    else:
                        icon = "⚡"
                        icon_color = "#38BDF8"
                        status_str = dur_str

                    dur_text = f" ({status_str})" if status_str else ""
                    tool_toggle = f"toggle://tool_{msg['id']}_{t_idx}"
                    code_text = tc.get("code", "")
                    tools_html += (
                        f'<div style="margin: 3px 0 6px 0;">'
                        f'<a href="{tool_toggle}" style="text-decoration: none; color: #94A3B8; font-size: 11px; font-weight: 500;">'
                        f'<span style="color: {icon_color};">{icon}</span> Ran PyMOL script{dur_text} &nbsp;<span style="color: {icon_color}; font-size: 10px;">{t_arrow}</span>'
                        f'</a>'
                    )
                    if is_tc_expanded:
                        escaped_code = html.escape(code_text.strip()).replace("\n", "<br>").replace(" ", "&nbsp;")
                        out_html = ""
                        tc_out = str(tc.get("output", "") or "").strip()
                        tc_err = str(tc.get("error", "") or "").strip()
                        if tc_out:
                            escaped_out = html.escape(tc_out).replace("\n", "<br>").replace(" ", "&nbsp;")
                            out_html += (
                                f'<div style="margin-top: 5px; padding-top: 4px; border-top: 1px dashed #334155; color: #CBD5E1; font-family: Consolas, monospace; font-size: 11px;">'
                                f'<span style="color: #64748B;"># Output:</span><br>{escaped_out}</div>'
                            )
                        if tc_err:
                            escaped_err = html.escape(tc_err).replace("\n", "<br>").replace(" ", "&nbsp;")
                            out_html += (
                                f'<div style="margin-top: 5px; padding-top: 4px; border-top: 1px dashed #5C282F; color: #F87171; font-family: Consolas, monospace; font-size: 11px;">'
                                f'<span style="color: #EF4444;"># Error:</span><br>{escaped_err}</div>'
                            )
                        border_color = "#EF4444" if is_failed else "#38BDF8"
                        tools_html += (
                            f'<table width="100%" cellpadding="6" cellspacing="0" style="margin-top: 4px; margin-bottom: 4px;" bgcolor="#16171B">'
                            f'<tr><td style="border: 1px solid #282C35; border-left: 2px solid {border_color}; border-radius: 4px; color: #93C5FD; font-family: Consolas, monospace; font-size: 11px;">'
                            f'{escaped_code}'
                            f'{out_html}'
                            f'</td></tr></table>'
                        )
                    tools_html += '</div>'

            return (
                '<table width="100%" cellpadding="10" cellspacing="0" style="margin-bottom: 8px;" bgcolor="#202328">'
                '<tr><td style="border: 1px solid #303540; border-radius: 8px;">'
                f'{badge_html}'
                f'{thought_html}'
                f'{tools_html}'
                f'<div style="color: #E2E8F0; font-size: 13px; line-height: 150%;">{content}</div>'
                '</td></tr></table>'
            )
        elif who == "Error":
            return (
                '<table width="100%" cellpadding="9" cellspacing="0" style="margin-bottom: 8px;" bgcolor="#361E22">'
                '<tr><td style="border: 1px solid #5C282F; border-radius: 8px;">'
                '<div style="color: #F87171; font-size: 11px; font-weight: bold; margin-bottom: 4px;">'
                '⚠ Error</div>'
                f'<div style="color: #FDA4AF; font-size: 13px; line-height: 150%;">{content}</div>'
                '</td></tr></table>'
            )
        else:
            return (
                '<table width="100%" cellpadding="9" cellspacing="0" style="margin-bottom: 8px;" bgcolor="#1E232F">'
                '<tr><td style="border: 1px solid #2D3748; border-radius: 8px;">'
                f'<div style="color: #60A5FA; font-size: 11px; font-weight: bold; margin-bottom: 4px;">'
                f'ℹ {html.escape(who)}</div>'
                f'<div style="color: #CBD5E1; font-size: 13px; line-height: 150%;">{content}</div>'
                '</td></tr></table>'
            )

    def _render_active_turn_card(self, turn: dict[str, Any]) -> str:
        state = turn.get("state", "thinking")
        start_time = turn.get("start_time", time.time())
        thought_raw = turn.get("thought", "").strip()

        if state == "thinking":
            elapsed = max(0.1, time.time() - start_time)
            preview_html = ""
            if thought_raw:
                snippet = thought_raw[-240:]
                escaped_snip = html.escape(snippet).replace("\n", " ")
                preview_html = (
                    f'<div style="color: #818CF8; font-size: 11px; font-style: italic; line-height: 135%; margin-top: 4px; max-height: 70px; overflow: hidden;">'
                    f'…{escaped_snip}'
                    f'</div>'
                )
            return (
                '<table width="100%" cellpadding="10" cellspacing="0" style="margin-bottom: 8px;" bgcolor="#202328">'
                '<tr><td style="border: 1px solid #303540; border-radius: 8px;">'
                '<div style="color: #4ADE80; font-size: 11px; font-weight: bold; margin-bottom: 5px;">✦ PyMOL AI</div>'
                f'<div style="color: #A78BFA; font-size: 11px; font-weight: 500;">💭 正在深度思考中… <span style="color: #C4B5FD;">({elapsed:.1f}s)</span></div>'
                f'{preview_html}'
                '</td></tr></table>'
            )
        elif state == "processing":
            elapsed = max(0.1, time.time() - start_time)
            return (
                '<table width="100%" cellpadding="10" cellspacing="0" style="margin-bottom: 8px;" bgcolor="#202328">'
                '<tr><td style="border: 1px solid #303540; border-radius: 8px;">'
                '<div style="color: #4ADE80; font-size: 11px; font-weight: bold; margin-bottom: 5px;">✦ PyMOL AI</div>'
                f'<div style="color: #38BDF8; font-size: 11px; font-weight: 500;">⚡ 正在生成与执行指令… <span style="color: #7DD3FC;">({elapsed:.1f}s)</span></div>'
                '</td></tr></table>'
            )
        else:
            elapsed = max(0.1, time.time() - start_time)
            t_dur = turn.get("thought_duration", 0.0)
            dur_label = f" {t_dur:.1f}s" if t_dur > 0 else ""
            thought_html = ""
            if thought_raw:
                thought_toggle = f"toggle://thought_{turn['id']}"
                is_exp = turn.get("thought_expanded", False)
                arrow = "▼" if is_exp else "▶"
                thought_html = (
                    f'<div style="margin: 3px 0 6px 0;">'
                    f'<a href="{thought_toggle}" style="text-decoration: none; color: #94A3B8; font-size: 11px; font-weight: 500;">'
                    f'<span style="color: #A78BFA;">💭</span> Thought for{dur_label} &nbsp;<span style="color: #7C5CFC; font-size: 10px;">{arrow}</span>'
                    f'</a>'
                )
                if is_exp:
                    escaped_thought = html.escape(thought_raw).replace("\n", "<br>")
                    thought_html += (
                        f'<table width="100%" cellpadding="6" cellspacing="0" style="margin-top: 4px; margin-bottom: 4px;" bgcolor="#16171B">'
                        f'<tr><td style="border: 1px solid #282C35; border-left: 2px solid #7C5CFC; border-radius: 4px; color: #94A3B8; font-size: 11px; line-height: 140%;">'
                        f'{escaped_thought}'
                        f'</td></tr></table>'
                    )
                thought_html += '</div>'

            tools_html = ""
            tool_calls = turn.get("tool_calls", [])
            if tool_calls:
                tools_exp = turn.get("tools_expanded", {})
                for t_idx, tc in enumerate(tool_calls):
                    is_tc_expanded = tools_exp.get(t_idx, False)
                    t_arrow = "▼" if is_tc_expanded else "▶"
                    t_dur_val = tc.get("duration", 0.0)
                    dur_str = f"{t_dur_val:.1f}s" if t_dur_val > 0 else ""
                    is_failed = tc.get("ok") is False or bool(tc.get("error"))

                    if is_failed:
                        icon = "⚠"
                        icon_color = "#F87171"
                        status_str = f"failed · {dur_str}" if dur_str else "failed"
                    else:
                        icon = "⚡"
                        icon_color = "#38BDF8"
                        status_str = dur_str

                    dur_text = f" ({status_str})" if status_str else ""
                    tool_toggle = f"toggle://tool_{turn['id']}_{t_idx}"
                    code_text = tc.get("code", "")
                    tools_html += (
                        f'<div style="margin: 3px 0 6px 0;">'
                        f'<a href="{tool_toggle}" style="text-decoration: none; color: #94A3B8; font-size: 11px; font-weight: 500;">'
                        f'<span style="color: {icon_color};">{icon}</span> Ran PyMOL script{dur_text} &nbsp;<span style="color: {icon_color}; font-size: 10px;">{t_arrow}</span>'
                        f'</a>'
                    )
                    if is_tc_expanded:
                        escaped_code = html.escape(code_text.strip()).replace("\n", "<br>").replace(" ", "&nbsp;")
                        out_html = ""
                        tc_out = str(tc.get("output", "") or "").strip()
                        tc_err = str(tc.get("error", "") or "").strip()
                        if tc_out:
                            escaped_out = html.escape(tc_out).replace("\n", "<br>").replace(" ", "&nbsp;")
                            out_html += (
                                f'<div style="margin-top: 5px; padding-top: 4px; border-top: 1px dashed #334155; color: #CBD5E1; font-family: Consolas, monospace; font-size: 11px;">'
                                f'<span style="color: #64748B;"># Output:</span><br>{escaped_out}</div>'
                            )
                        if tc_err:
                            escaped_err = html.escape(tc_err).replace("\n", "<br>").replace(" ", "&nbsp;")
                            out_html += (
                                f'<div style="margin-top: 5px; padding-top: 4px; border-top: 1px dashed #5C282F; color: #F87171; font-family: Consolas, monospace; font-size: 11px;">'
                                f'<span style="color: #EF4444;"># Error:</span><br>{escaped_err}</div>'
                            )
                        border_color = "#EF4444" if is_failed else "#38BDF8"
                        tools_html += (
                            f'<table width="100%" cellpadding="6" cellspacing="0" style="margin-top: 4px; margin-bottom: 4px;" bgcolor="#16171B">'
                            f'<tr><td style="border: 1px solid #282C35; border-left: 2px solid {border_color}; border-radius: 4px; color: #93C5FD; font-family: Consolas, monospace; font-size: 11px;">'
                            f'{escaped_code}'
                            f'{out_html}'
                            f'</td></tr></table>'
                        )
                    tools_html += '</div>'

            content = self._format_content(turn.get("text", ""))
            status_html = ""
            if state == "executing":
                status_html = f'<div style="color: #38BDF8; font-size: 11px; font-weight: 500; margin-top: 4px;">⚡ 正在执行操作并分析结果… <span style="color: #7DD3FC;">({elapsed:.1f}s)</span></div>'
            elif not content and state != "answering":
                status_html = f'<div style="color: #94A3B8; font-size: 11px; font-weight: 500; margin-top: 4px;">⚡ 正在生成回复… <span style="color: #CBD5E1;">({elapsed:.1f}s)</span></div>'

            return (
                '<table width="100%" cellpadding="10" cellspacing="0" style="margin-bottom: 8px;" bgcolor="#202328">'
                '<tr><td style="border: 1px solid #303540; border-radius: 8px;">'
                '<div style="color: #4ADE80; font-size: 11px; font-weight: bold; margin-bottom: 5px;">✦ PyMOL AI</div>'
                f'{thought_html}'
                f'{tools_html}'
                f'{status_html}'
                f'<div style="color: #E2E8F0; font-size: 13px; line-height: 150%;">{content}</div>'
                '</td></tr></table>'
            )

    def _render_history(self, scroll_to_bottom: bool = False):
        v_bar = self.history.verticalScrollBar()
        if v_bar.isSliderDown():
            return

        old_val = v_bar.value()

        self._rendering_history = True
        try:
            cards = [self._render_message_card(m) for m in self._messages]
            if self._active_turn is not None:
                cards.append(self._render_active_turn_card(self._active_turn))

            self.history.setHtml("".join(cards))

            should_scroll = scroll_to_bottom or self._auto_scroll
            if should_scroll:
                self.history.moveCursor(QtGui.QTextCursor.End)
                self.history.ensureCursorVisible()
                v_bar.setValue(v_bar.maximum())
            else:
                v_bar.setValue(min(old_val, v_bar.maximum()))
        finally:
            self._rendering_history = False

    def _append_message(self, who: str, text: str):
        thought = getattr(text, "thought", "")
        t_dur = getattr(text, "thought_duration", 0.0)
        e_dur = getattr(text, "exec_duration", 0.0)
        tot_dur = getattr(text, "total_duration", 0.0)
        tool_calls = getattr(text, "tool_calls", [])

        self._messages.append({
            "id": len(self._messages),
            "who": who,
            "text": str(text),
            "thought": thought,
            "thought_duration": t_dur,
            "exec_duration": e_dur,
            "total_duration": tot_dur,
            "tool_calls": tool_calls,
            "thought_expanded": False,
            "tools_expanded": {},
        })
        self._render_history(scroll_to_bottom=True)

    def _set_busy(self, busy: bool):
        self.busy = busy
        self.input.setEnabled(not busy)
        self.mic_button.setEnabled(not busy)
        self.stop_button.setVisible(busy)
        if hasattr(self, "cancel_action"):
            self.cancel_action.setEnabled(busy)
        self.input.setPlaceholderText("Working… (Click Stop or press Esc to cancel)" if busy else "Ask PyMOL…")
        if not busy:
            self.input.setFocus()
            self._refresh_action_pills()

    def _on_pill_clicked(self, prompt: str):
        if self.busy:
            return
        self.input.setText(prompt)
        self.send()

    def _poll_viewport_changes(self):
        """Poll 3D viewport state changes (objects and 'sele' selection) to dynamically update pills."""
        if not hasattr(self, "pill_bar") or self.busy:
            return
        try:
            from pymol import cmd
            objs = tuple(cmd.get_names("objects", 1) or [])
            sels = cmd.get_names("selections") or []
            sele_count = cmd.count_atoms("sele") if "sele" in sels else 0
            sig = (objs, sele_count)
            if sig != getattr(self, "_last_state_signature", None):
                self._last_state_signature = sig
                self._refresh_action_pills()
        except Exception:
            pass

    def _refresh_action_pills(self):
        """Refresh quick action pills based on active 3D selection and scene inventory."""
        if not hasattr(self, "pill_layout") or not hasattr(self, "pill_bar"):
            return
        while self.pill_layout.count():
            item = self.pill_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        # 1. First check if user clicked/selected atoms in the 3D viewport ('sele')
        from .analysis.selection import clear_viewport_selection, get_viewport_selection_summary
        sele_summary = get_viewport_selection_summary()

        pills = []
        if sele_summary.has_selection:
            # Active 3D viewport selection detected!
            badge = QtWidgets.QLabel(f"📍 {sele_summary.label}")
            badge.setObjectName("selection_badge")
            badge.setToolTip("Active 3D viewport selection ('sele')")
            self.pill_layout.addWidget(badge)

            clear_btn = QtWidgets.QPushButton("✕")
            clear_btn.setObjectName("clear_selection_btn")
            clear_btn.setToolTip("Clear 3D selection")
            clear_btn.setCursor(QtCore.Qt.PointingHandCursor)
            clear_btn.clicked.connect(lambda: [clear_viewport_selection(), self._refresh_action_pills()])
            self.pill_layout.addWidget(clear_btn)

            if sele_summary.is_ligand:
                pills = [
                    ("🔗 配体互作 (PLIP)", "分析配体 'sele' 与受体蛋白在 4.5Å 内的非共价相互作用"),
                    ("🔬 口袋表面", "为配体 'sele' 结合口袋显示 50% 半透明表面"),
                    ("🎯 居中对齐", "居中聚焦选中的配体 'sele' 并将周边残基显示为棒状"),
                ]
            elif sele_summary.is_protein:
                short_desc = sele_summary.label.split(" in ")[0] if " in " in sele_summary.label else sele_summary.label
                pills = [
                    ("🔍 残基分析", f"深入分析选中的残基 '{short_desc}' 周边微环境与接触残基"),
                    ("🎨 棒状高亮", "将选中的残基 'sele' 显示为棒状并标注残基名与序号"),
                    ("⚡ 突变预测", f"评估选中的残基 '{short_desc}' 定点突变时的侧链位阻变化"),
                ]
            else:
                pills = [
                    ("🔍 聚焦选中", "聚焦选中的 'sele' 并显示棒状"),
                    ("🎨 高亮着色", "将选中的 'sele' 着色为亮黄色"),
                ]
        else:
            objects = []
            try:
                from pymol import cmd
                objects = cmd.get_names("objects", 1) or []
            except Exception:
                pass

            if len(objects) == 1:
                obj = objects[0]
                pills = [
                    ("📊 AF2 pLDDT", f"Analyze pLDDT confidence and color {obj} by pLDDT spectrum"),
                    ("✨ Nature View", f"Apply publication preset 'nature' to {obj}"),
                    ("🎯 Trim Loops (<50)", f"Trim disordered loops with pLDDT below 50 for {obj}"),
                    ("🔬 Pocket Surface", f"Show binding pocket surface and contact residues for {obj}"),
                ]
            elif len(objects) >= 2:
                obj1, obj2 = objects[0], objects[1]
                pills = [
                    ("🔄 RMSD Heatmap", f"Compare conformations of {obj1} and {obj2} with displacement heatmap"),
                    ("📊 Pocket Shift", f"Compare binding pocket residues of {obj1} and {obj2}"),
                    ("✨ Cell Outline", "Apply publication preset 'cell_outline'"),
                    ("🎨 Keynote Dark", "Apply publication preset 'keynote_dark'"),
                ]

        if not pills and not sele_summary.has_selection:
            self.pill_bar.setVisible(False)
            return

        pill_btn_style = "action_pill_sele" if sele_summary.has_selection else "action_pill"
        for label, prompt in pills:
            btn = QtWidgets.QPushButton(label)
            btn.setObjectName(pill_btn_style)
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, p=prompt: self._on_pill_clicked(p))
            self.pill_layout.addWidget(btn)
        self.pill_layout.addStretch(1)
        self.pill_bar.setVisible(True)

    def show_error(self, message: str):
        if "command limit" in message.lower():
            friendly_msg = (
                "已达到单次操作的最大指令步数上限（已执行多轮结构调整）。<br>"
                "当前 3D 视图已呈现已执行的操作结果，您可以直接在 PyMOL 中查看，或针对当前观察继续提问。"
            )
            self._append_message("Error", friendly_msg)
            return
        self._append_message("Error", message)

    def load_files(self, paths):
        from .analysis import load_structures_from_path
        loaded_names = []
        for raw_path in paths:
            path = Path(raw_path).expanduser().resolve()
            if not path.exists():
                continue
            res = load_structures_from_path(path, auto_orient=False)
            if res.success and res.loaded_structures:
                loaded_names.extend(res.loaded_objects)
        if loaded_names:
            try:
                cmd.orient("all")
            except Exception:
                pass
            msg = f"已成功载入 {len(loaded_names)} 个分子结构：\n" + ", ".join(f"`{name}`" for name in loaded_names)
            self._append_message("PyMOL", msg)
            self._refresh_action_pills()

    def toggle_recording(self):
        if not self._ensure_api_key():
            return
        try:
            self.speech.stop()
            self.voice.toggle()
        except Exception as exc:
            self.show_error(str(exc))

    def _recording_finished(self, path):
        if path is None:
            return
        self._set_busy(True)
        self._start_transcription(path)

    def _start_transcription(self, path):
        task = Task(transcribe, path)
        task.signals.done.connect(self._transcribed)
        task.signals.failed.connect(self._task_failed)
        self.thread_pool.start(task)

    def _recording_changed(self, recording: bool):
        self.mic_button.setProperty("recording", recording)
        self.mic_button.setText("■" if recording else "●")
        self.mic_button.setToolTip("Listening — click to stop" if recording else "Start voice input")
        self.input.setEnabled(not recording and not self.busy)
        self.input.setPlaceholderText("Listening…" if recording else ("Working…" if self.busy else "Ask PyMOL…"))
        self.mic_button.style().unpolish(self.mic_button)
        self.mic_button.style().polish(self.mic_button)

    def _transcribed(self, text):
        self._set_busy(False)
        self.input.setText(str(text))
        self.send()


# Backward compatibility alias
PyMOLChatDock = PyMOLFlowDock
