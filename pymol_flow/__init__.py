"""PyMOL Flow plugin entry point."""

from __future__ import annotations

_dock = None


def _qt_main_window():
    """Return PyMOL's real QMainWindow, not its legacy PMGApp wrapper."""
    from pymol.Qt import QtWidgets

    application = QtWidgets.QApplication.instance()
    if application is None:
        raise RuntimeError("PyMOL's Qt application is not running")

    active = application.activeWindow()
    if isinstance(active, QtWidgets.QMainWindow):
        return active

    main_windows = [
        widget for widget in application.topLevelWidgets()
        if isinstance(widget, QtWidgets.QMainWindow)
    ]
    # The PyMOL window owns `pymolwidget`; prefer it over auxiliary windows.
    for window in main_windows:
        if hasattr(window, "pymolwidget"):
            return window
    if main_windows:
        return main_windows[0]
    raise RuntimeError("Could not find PyMOL's Qt main window")


def show():
    """Show (or create) the chat dock in the active PyMOL window."""
    global _dock
    from pymol.Qt import QtCore

    from .ui import PyMOLFlowDock

    parent = _qt_main_window()
    if _dock is None:
        _dock = PyMOLFlowDock(parent)
        parent.addDockWidget(QtCore.Qt.RightDockWidgetArea, _dock)
    else:
        parent.addDockWidget(QtCore.Qt.RightDockWidgetArea, _dock)
    _dock.show()
    _dock.raise_()
    try:
        parent.resizeDocks([_dock], [450], QtCore.Qt.Horizontal)
    except Exception:
        pass

    # Hide PyMOL's redundant top External GUI panel to maximize 3D viewport area
    if hasattr(parent, "ext_window"):
        try:
            parent.ext_window.hide()
            if hasattr(_dock, "top_panel_action"):
                _dock.top_panel_action.setChecked(False)
        except Exception:
            pass
    return _dock


def reload_plugin():
    """Reload all pymol_flow submodules and recreate dock."""
    import importlib
    import sys
    global _dock
    if _dock is not None:
        try:
            _dock.close()
            _dock.deleteLater()
        except Exception:
            pass
        _dock = None

    submodules = [
        m for m in list(sys.modules.keys())
        if m.startswith("pymol_flow.") and m != "pymol_flow"
    ]
    for m in submodules:
        del sys.modules[m]

    import pymol_flow
    importlib.reload(pymol_flow)
    return pymol_flow.show()


def __init_plugin__(app=None):
    """Called by PyMOL's plugin manager."""
    try:
        from pymol.plugins import addmenuitemqt

        addmenuitemqt("PyMOL Flow", show)
        addmenuitemqt("Reload PyMOL Flow", reload_plugin)
    except Exception:
        pass
