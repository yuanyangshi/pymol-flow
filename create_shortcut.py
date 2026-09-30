"""Create a silent, high-tech desktop shortcut for PyMOL Flow on Windows."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def find_icon(project_dir: Path) -> str:
    for icon_name in ("pymol_flow.ico", "icon.ico"):
        custom_icon = project_dir / "assets" / icon_name
        if custom_icon.is_file():
            return f"{custom_icon.resolve()},0"

    candidates = [
        os.environ.get("PYMOL_EXE", ""),
        os.environ.get("PYMOL_PATH", ""),
        r"C:\Program Files\PyMOL\PyMOL.exe",
        r"C:\Program Files (x86)\PyMOL\PyMOL.exe",
        str(Path.home() / "AppData" / "Local" / "Programs" / "PyMOL" / "PyMOL.exe"),
    ]
    # Dynamically check virtual environments on current drive and user profile
    drive_root = Path(project_dir.anchor)
    for venv_root in (drive_root / ".virtualenvs", Path.home() / ".virtualenvs"):
        if venv_root.is_dir():
            for sub in venv_root.iterdir():
                cand = sub / "Scripts" / "pymol.exe"
                if cand.is_file():
                    candidates.append(str(cand))

    for c in candidates:
        if c and os.path.isfile(c):
            return f"{c},0"
    return ""


def create_desktop_shortcut(name: str = "PyMOL Flow") -> Path:
    project_dir = Path(__file__).resolve().parent
    run_vbs = project_dir / "run.vbs"
    desktop = Path.home() / "Desktop"
    shortcut_path = desktop / f"{name}.lnk"

    icon_location = find_icon(project_dir)

    # Use wscript.exe targeting run.vbs to completely eliminate the black console window
    vbs_code = [
        'Set oWS = WScript.CreateObject("WScript.Shell")',
        f'sLinkFile = "{str(shortcut_path)}"',
        "Set oLink = oWS.CreateShortcut(sLinkFile)",
        'oLink.TargetPath = "wscript.exe"',
        f'oLink.Arguments = chr(34) & "{str(run_vbs)}" & chr(34)',
        f'oLink.WorkingDirectory = "{str(project_dir)}"',
        "oLink.WindowStyle = 1",
        'oLink.Description = "PyMOL Flow - AI-Powered Molecular Assistant"',
    ]
    if icon_location:
        vbs_code.append(f'oLink.IconLocation = "{icon_location}"')
    vbs_code.append("oLink.Save")

    temp_vbs = project_dir / "_create_shortcut.vbs"
    try:
        temp_vbs.write_text("\r\n".join(vbs_code), encoding="utf-8")
        result = subprocess.run(["cscript", "//nologo", str(temp_vbs)], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"cscript error: {result.stderr or result.stdout}")
    finally:
        if temp_vbs.is_file():
            temp_vbs.unlink(missing_ok=True)

    if not shortcut_path.is_file():
        raise RuntimeError("Shortcut file was not created.")

    return shortcut_path


if __name__ == "__main__":
    try:
        path = create_desktop_shortcut()
        print(f"Successfully created shortcut: {path}")
    except Exception as exc:
        print(f"Failed to create shortcut: {exc}", file=sys.stderr)
        sys.exit(1)
