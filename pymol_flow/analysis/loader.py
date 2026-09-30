"""Safe local molecular structure and directory loading utility for PyMOL."""

from __future__ import annotations

from dataclasses import dataclass, field
import fnmatch
import os
from pathlib import Path
import re
from typing import Any, Generator, Sequence

from pymol import cmd

ALLOWED_EXTENSIONS: set[str] = {
    ".pdb", ".cif", ".mmcif", ".ent", ".sdf", ".mol2", ".pse", ".pdbqt",
}


def sanitize_object_name(raw_name: str, existing_names: set[str] | None = None) -> str:
    """Convert filename stem to a clean PyMOL object name complying with selection rules."""
    clean = re.sub(r"[^\w]", "_", raw_name)
    clean = re.sub(r"_+", "_", clean).strip("_")
    if not clean:
        clean = "obj"
    if clean[0].isdigit():
        clean = f"mol_{clean}"
    if existing_names is None:
        return clean
    candidate = clean
    counter = 1
    while candidate in existing_names:
        candidate = f"{clean}_{counter}"
        counter += 1
    return candidate


def find_structure_files(
    directory: Path,
    pattern: str = "*",
    max_scan: int = 1000,
    max_files: int = 20,
    recursive: bool = True,
) -> list[Path]:
    """Find valid molecular structure files with OOM safety and scan limits."""
    results: list[Path] = []
    scan_count = 0

    def _matches_pattern(filename: str, pat: str) -> bool:
        if pat in {"*", ""}:
            return True
        return fnmatch.fnmatch(filename.lower(), pat.lower())

    if recursive:
        walker: Generator[tuple[str, list[str], list[str]], None, None] = os.walk(str(directory))
    else:
        def _single_level():
            try:
                entries = list(os.scandir(str(directory)))
                files = [e.name for e in entries if e.is_file()]
                dirs = [e.name for e in entries if e.is_dir()]
                yield str(directory), dirs, files
            except Exception:
                return
        walker = _single_level()

    for root, _, files in walker:
        for f in files:
            scan_count += 1
            if scan_count > max_scan:
                break
            suffix = Path(f).suffix.lower()
            if suffix in ALLOWED_EXTENSIONS and _matches_pattern(f, pattern):
                results.append(Path(root) / f)
                if len(results) >= max_files:
                    break
        if scan_count > max_scan or len(results) >= max_files:
            break

    def natural_sort_key(p: Path) -> list[Any]:
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", p.name)]

    results.sort(key=natural_sort_key)
    return results[:max_files]


@dataclass
class LoadedStructureInfo:
    object_name: str
    file_name: str
    file_path: str
    atom_count: int = 0
    ca_count: int = 0
    ligand_atom_count: int = 0


@dataclass
class StructureLoadResult:
    success: bool
    path: str
    is_directory: bool
    loaded_structures: list[LoadedStructureInfo] = field(default_factory=list)
    total_found: int = 0
    total_loaded: int = 0
    diagnostic_message: str = ""

    @property
    def loaded_objects(self) -> list[str]:
        return [item.object_name for item in self.loaded_structures]

    def to_markdown(self) -> str:
        if not self.success:
            return f"❌ **结构加载失败**: {self.diagnostic_message}"
        if not self.loaded_structures:
            return (
                f"⚠️ **未在指定路径检索到分子结构**: `{self.path}`\n\n"
                f"支持的分子格式包括: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            )

        lines = [
            "### 📂 本地分子结构加载报告",
            f"- **来源路径**: `{self.path}`",
            f"- **加载数量**: 成功载入 **{self.total_loaded}** 个结构（检索到 {self.total_found} 个文件）",
            "- **载入对象详情**:",
        ]
        for s in self.loaded_structures:
            details = [f"原子数: {s.atom_count}"]
            if s.ca_count > 0:
                details.append(f"Cα: {s.ca_count}")
            if s.ligand_atom_count > 0:
                details.append(f"配体原子: {s.ligand_atom_count}")
            lines.append(f"  - **`{s.object_name}`** (`{s.file_name}`): {', '.join(details)}")

        lines.append("\n- **场景状态**: 已将载入的结构自动居中聚焦在 PyMOL 视口。")
        lines.append("\n> 💡 **后续分析建议**:")
        if len(self.loaded_structures) > 1:
            first_obj = self.loaded_structures[0].object_name
            second_obj = self.loaded_structures[1].object_name
            lines.append(f"> - 构象比对：告诉我“将 `{second_obj}` 对齐到 `{first_obj}` 并计算 RMSD”")
            lines.append(f"> - 构象差异高亮：告诉我“对比各模型构象并用不同颜色高亮差异区域”")
        if any(s.ligand_atom_count > 0 for s in self.loaded_structures):
            lines.append("> - 结合模式分析：告诉我“分析配体相互作用与氢键网络”")

        return "\n".join(lines)


def load_structures_from_path(
    path: str | Path,
    pattern: str = "*",
    max_files: int = 20,
    clean_scene: bool = False,
    auto_orient: bool = True,
    cmd_api: Any = None,
) -> StructureLoadResult:
    """Safely validate, scan, and load molecular structure files from a path or directory into PyMOL."""
    if cmd_api is None:
        cmd_api = cmd

    raw_path_str = str(path).strip().strip("'\"")
    target_path = Path(raw_path_str).expanduser().resolve()

    if not target_path.exists():
        return StructureLoadResult(
            success=False,
            path=str(target_path),
            is_directory=False,
            diagnostic_message=f"指定的路径不存在: `{target_path}`，请检查路径拼写是否正确或是否有读取权限。",
        )

    if clean_scene:
        try:
            cmd_api.reinitialize()
        except Exception:
            cmd_api.delete("all")

    try:
        existing_names = set(cmd_api.get_names("objects") or [])
    except Exception:
        existing_names = set()

    files_to_load: list[Path] = []
    is_dir = target_path.is_dir()

    if is_dir:
        files_to_load = find_structure_files(
            target_path,
            pattern=pattern,
            max_files=max(1, min(max_files, 100)),
        )
    else:
        suffix = target_path.suffix.lower()
        if suffix not in ALLOWED_EXTENSIONS:
            return StructureLoadResult(
                success=False,
                path=str(target_path),
                is_directory=False,
                diagnostic_message=(
                    f"不支持的文件格式 `{suffix}`。支持的分子结构格式包括: "
                    f"{', '.join(sorted(ALLOWED_EXTENSIONS))}"
                ),
            )
        files_to_load = [target_path]

    if not files_to_load:
        return StructureLoadResult(
            success=True,
            path=str(target_path),
            is_directory=is_dir,
            total_found=0,
            total_loaded=0,
            diagnostic_message=f"在 `{target_path}` 中未检索到符合条件的分子结构文件（pattern='{pattern}'）。",
        )

    loaded_info: list[LoadedStructureInfo] = []
    errors: list[str] = []

    for fpath in files_to_load:
        obj_name = sanitize_object_name(fpath.stem, existing_names)
        try:
            if fpath.suffix.lower() == ".pse":
                cmd_api.load(str(fpath))
            else:
                cmd_api.load(str(fpath), obj_name)
            existing_names.add(obj_name)

            safe_sel = f"({obj_name})"
            atoms = cmd_api.count_atoms(safe_sel)
            ca_atoms = cmd_api.count_atoms(f"{safe_sel} and name CA")
            ligand_atoms = cmd_api.count_atoms(f"{safe_sel} and organic")

            loaded_info.append(
                LoadedStructureInfo(
                    object_name=obj_name,
                    file_name=fpath.name,
                    file_path=str(fpath),
                    atom_count=atoms,
                    ca_count=ca_atoms,
                    ligand_atom_count=ligand_atoms,
                )
            )
        except Exception as exc:
            errors.append(f"Failed to load {fpath.name}: {exc}")

    if loaded_info and auto_orient:
        try:
            cmd_api.orient("all")
        except Exception:
            pass

    diag_msg = "; ".join(errors) if errors else ""
    return StructureLoadResult(
        success=len(loaded_info) > 0,
        path=str(target_path),
        is_directory=is_dir,
        loaded_structures=loaded_info,
        total_found=len(files_to_load),
        total_loaded=len(loaded_info),
        diagnostic_message=diag_msg,
    )
