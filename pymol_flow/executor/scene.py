"""Scene inspection and viewport capture for PyMOL."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from pymol import cmd

from ..config import CAPTURE_DIR, ensure_app_dirs, max_scene_objects


def get_scene_summary(cmd_api: Any = None) -> dict[str, Any]:
    """Inspect the live PyMOL scene and return a structural inventory of loaded objects and selections."""
    if cmd_api is None:
        cmd_api = cmd
    limit = max_scene_objects()
    objects = cmd_api.get_names("objects")
    selections = cmd_api.get_names("selections")
    object_details = []
    for name in objects[:limit]:
        try:
            safe_sel = f"({name})"
            chains = cmd_api.get_chains(safe_sel)
            atoms = cmd_api.count_atoms(safe_sel)
            ca_atoms = cmd_api.count_atoms(f"{safe_sel} and name CA")
            nucleic_atoms = cmd_api.count_atoms(f"{safe_sel} and polymer.nucleic")
            ligand_atoms = cmd_api.count_atoms(f"{safe_sel} and organic")

            details: dict[str, Any] = {
                "name": name,
                "chains": chains,
                "atoms": atoms,
            }
            if ca_atoms > 0:
                details["protein_ca_atoms"] = ca_atoms
            if nucleic_atoms > 0:
                details["nucleic_atoms"] = nucleic_atoms
            if ligand_atoms > 0:
                details["ligand_atoms"] = ligand_atoms
            object_details.append(details)
        except Exception as exc:
            object_details.append({"name": name, "error": str(exc)})
    active_selection = None
    if "sele" in selections:
        try:
            if cmd_api.count_atoms("sele") > 0:
                from ..analysis.selection import get_viewport_selection_summary
                summary = get_viewport_selection_summary(cmd_api)
                if summary.has_selection:
                    active_selection = summary.label
        except Exception:
            pass

    res: dict[str, Any] = {
        "objects": object_details,
        "selections": selections[:limit],
        "enabled": cmd_api.get_names("all", enabled_only=1)[:limit],
    }
    if active_selection:
        res["active_viewport_selection"] = active_selection
    return res


def capture_viewport(cmd_api: Any = None) -> tuple[Path, str]:
    """Capture the active PyMOL 3D viewport to a PNG file and return its path and base64 URI."""
    if cmd_api is None:
        cmd_api = cmd
    ensure_app_dirs()
    path = CAPTURE_DIR / "viewport.png"
    cmd_api.png(str(path), width=1200, height=900, dpi=150, ray=0, quiet=1)
    if not path.is_file():
        raise RuntimeError("PyMOL did not create the viewport capture")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return path, f"data:image/png;base64,{encoded}"
