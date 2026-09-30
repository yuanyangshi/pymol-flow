"""Voice capture and OpenAI transcription for Windows."""

from __future__ import annotations

import sys
from pathlib import Path

from pymol.Qt import QtCore

from ..api_client import OpenAIHTTPClient
from ..config import APP_DIR, api_key, ensure_app_dirs, transcription_model


VOICE_HELPER_SCRIPT = (
    Path(__file__).resolve().parents[2] / "voice_helper" / "voice_helper.py"
)


class VoiceRecorder(QtCore.QObject):
    """Manage the background Python voice recorder helper."""

    state_changed = QtCore.pyqtSignal(bool)
    finished = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        ensure_app_dirs()
        self.path = APP_DIR / "voice-request.wav"
        self.stop_path = APP_DIR / "voice-request.stop"
        self.error_path = APP_DIR / "voice-request.error"
        self.status_path = APP_DIR / "voice-request.status"
        self.process = QtCore.QProcess(self)
        self.process.finished.connect(self._process_finished)
        self._recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    def toggle(self) -> None:
        if self.is_recording:
            self.stop_path.touch()
        else:
            self.start()

    def start(self) -> None:
        if not VOICE_HELPER_SCRIPT.is_file():
            raise RuntimeError(
                f"The voice helper was not found at {VOICE_HELPER_SCRIPT}."
            )

        for path in (self.path, self.stop_path, self.error_path, self.status_path):
            path.unlink(missing_ok=True)

        self.process.setProgram(sys.executable)
        self.process.setArguments([
            str(VOICE_HELPER_SCRIPT),
            str(self.path),
            str(self.stop_path),
        ])
        self.process.setStandardOutputFile(str(self.status_path))
        self.process.setStandardErrorFile(str(self.error_path))

        self.process.start()
        if not self.process.waitForStarted(3000):
            raise RuntimeError(self.process.errorString() or "Could not start voice recording")
        self._recording = True
        self.state_changed.emit(True)

    def _process_finished(self, exit_code, _exit_status) -> None:
        was_recording = self._recording
        self._recording = False
        if was_recording:
            self.state_changed.emit(False)

        stderr = bytes(self.process.readAllStandardError()).decode("utf-8", "replace").strip()
        if self.error_path.is_file():
            stderr = self.error_path.read_text(errors="replace").strip() or stderr
        status = self.status_path.read_text(errors="replace") if self.status_path.is_file() else ""
        if exit_code == 0 and not stderr and "done" in status.splitlines() and self.path.is_file() and self.path.stat().st_size > 44:
            self.finished.emit(self.path)
            return
        self.finished.emit(None)
        if stderr:
            self.error.emit(stderr)
        elif was_recording:
            self.error.emit("Voice recording ended before audio was captured.")


def transcribe(path: Path) -> str:
    key = api_key()
    if not key:
        raise RuntimeError("An OpenAI API key is required. Open ⋯ → API Key Settings… to add one.")
    return OpenAIHTTPClient(key).transcribe(path, transcription_model())
