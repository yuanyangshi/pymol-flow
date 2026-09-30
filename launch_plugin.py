"""Development launcher loaded by PyMOL with `pymol -r launch_plugin.py`."""

import sys

# Also protect the signed bundle when this file is loaded with PyMOL's run
# command, bypassing the native launcher's environment configuration.
sys.dont_write_bytecode = True

from pathlib import Path

# PyMOL's `run ..., main` supplies __script__, not the script's __file__.
# Add the adjacent package explicitly when launched outside this directory.
_launcher_path = globals().get("__script__") or __file__
_package_root = str(Path(_launcher_path).resolve().parent)
if _package_root not in sys.path:
    sys.path.insert(0, _package_root)

from pymol.Qt import QtCore, QtWidgets

# If launched interactively without -x, immediately hide the external GUI dock
# to prevent it from flashing or jumping on screen during startup.
_app = QtWidgets.QApplication.instance()
if _app is not None:
    for _w in _app.topLevelWidgets():
        if isinstance(_w, QtWidgets.QMainWindow) and hasattr(_w, "ext_window"):
            try:
                _w.ext_window.hide()
            except Exception:
                pass
            break

import pymol_flow as plugin_mod


def _show_and_ensure_splash():
    plugin_mod.show()
    try:
        from pymol import cmd
        if not cmd.get_names("all"):
            cmd.splash(1)
    except Exception:
        pass


plugin_mod.__init_plugin__()
if _app is not None:
    QtCore.QTimer.singleShot(0, _show_and_ensure_splash)


