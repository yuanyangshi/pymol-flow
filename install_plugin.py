"""Install PyMOL Flow into PyMOL user configuration on Windows/Linux/macOS."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def get_pymolrc_path() -> Path:
    return Path.home() / ".pymolrc.py"


def install_plugin(project_dir: Path | None = None) -> None:
    if project_dir is None:
        project_dir = Path(__file__).resolve().parent

    pymolrc = get_pymolrc_path()
    marker_start = "# >>> PyMOL Flow initialization >>>"
    marker_end = "# <<< PyMOL Flow initialization <<<"
    old_start = "# >>> Chat with PyMOL initialization >>>"
    old_end = "# <<< Chat with PyMOL initialization <<<"

    snippet = (
        f"{marker_start}\n"
        f"import sys\n"
        f"from pathlib import Path\n"
        f"_plugin_dir = {repr(str(project_dir))}\n"
        f"if _plugin_dir not in sys.path:\n"
        f"    sys.path.insert(0, _plugin_dir)\n"
        f"try:\n"
        f"    import pymol_flow\n"
        f"    pymol_flow.__init_plugin__()\n"
        f"except Exception as _e:\n"
        f"    print(f'[PyMOL Flow] Could not load plugin: {{_e}}')\n"
        f"{marker_end}\n"
    )

    current_content = ""
    if pymolrc.is_file():
        current_content = pymolrc.read_text(encoding="utf-8")

    # Clean legacy markers if present
    if old_start in current_content and old_end in current_content:
        before_old = current_content.split(old_start)[0]
        after_old = current_content.split(old_end)[1]
        current_content = before_old.rstrip() + "\n" + after_old.lstrip()

    if marker_start in current_content and marker_end in current_content:
        # Update existing snippet
        before = current_content.split(marker_start)[0]
        after = current_content.split(marker_end)[1]
        new_content = before.rstrip() + "\n\n" + snippet + after.lstrip()
    else:
        new_content = current_content.rstrip() + ("\n\n" if current_content else "") + snippet

    pymolrc.write_text(new_content, encoding="utf-8")
    print(f"Successfully installed PyMOL Flow into {pymolrc}")
    print("PyMOL Flow will now load automatically whenever you launch PyMOL!")


def uninstall_plugin() -> None:
    pymolrc = get_pymolrc_path()
    if not pymolrc.is_file():
        print(f"No {pymolrc} found.")
        return

    content = pymolrc.read_text(encoding="utf-8")
    removed = False

    for s, e in [
        ("# >>> PyMOL Flow initialization >>>", "# <<< PyMOL Flow initialization <<<"),
        ("# >>> Chat with PyMOL initialization >>>", "# <<< Chat with PyMOL initialization <<<"),
    ]:
        if s in content and e in content:
            before = content.split(s)[0]
            after = content.split(e)[1]
            content = (before.rstrip() + "\n" + after.lstrip()).strip() + "\n"
            removed = True

    if removed:
        pymolrc.write_text(content, encoding="utf-8")
        print(f"Successfully uninstalled PyMOL Flow from {pymolrc}")
    else:
        print("PyMOL Flow configuration was not found in ~/.pymolrc.py.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install PyMOL Flow into PyMOL user startup.")
    parser.add_argument(
        "--uninstall", action="store_true", help="Remove PyMOL Flow from ~/.pymolrc.py"
    )
    args = parser.parse_args()

    if args.uninstall:
        uninstall_plugin()
    else:
        install_plugin()
    return 0


if __name__ == "__main__":
    sys.exit(main())
