"""Conformation comparison and local binding pocket divergence analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ResidueDisplacement:
    chain: str
    resi: str
    resn: str
    displacement_angstrom: float
    atom_count: int


@dataclass
class ConformationComparisonResult:
    mobile_object: str
    target_object: str
    overall_ca_rmsd: float
    pocket_rmsd: float
    inspected_pocket_residues: int
    top_displacements: List[ResidueDisplacement] = field(default_factory=list)
    heatmap_applied: bool = False
    warning: Optional[str] = None

    def to_markdown(self) -> str:
        lines = [
            f"### 📊 Conformation & Pocket Divergence Analysis",
            f"- **Mobile Model**: `{self.mobile_object}`",
            f"- **Target Model**: `{self.target_object}`",
            f"- **Overall Cα RMSD**: `{self.overall_ca_rmsd:.3f} Å`",
            f"- **Pocket Local RMSD**: `{self.pocket_rmsd:.3f} Å` ({self.inspected_pocket_residues} residues analyzed)",
        ]
        if self.heatmap_applied:
            lines.append("- **3D Heatmap**: Applied B-factor displacement spectrum (`Blue=0.0 Å` $\\to$ `White=1.0 Å` $\\to$ `Red≥2.5 Å`).")

        if self.top_displacements:
            lines.append("\n#### 🔍 Top Displaced Residues (Conformational Shifts)")
            lines.append("| Chain | Resi | Residue | Max Displacement (Å) | Atoms |")
            lines.append("| :--- | :--- | :--- | :---: | :---: |")
            for r in self.top_displacements[:5]:
                lines.append(f"| `{r.chain}` | `{r.resi}` | **{r.resn}** | **{r.displacement_angstrom:.2f} Å** | {r.atom_count} |")

        if self.warning:
            lines.append(f"\n> ⚠️ *Note*: {self.warning}")

        return "\n".join(lines)


def _get_active_cmd() -> Any:
    try:
        from pymol import cmd
        return cmd
    except ImportError:
        return None


def compare_conformations(
    mobile_object: str,
    target_object: str,
    pocket_selection: str = "organic",
    cutoff: float = 5.0,
    apply_heatmap: bool = True,
    cmd_override: Any = None,
) -> ConformationComparisonResult:
    """Compare two protein conformations and compute pocket-level residue divergence.

    1. Superimposes mobile onto target to ensure aligned coordinate frame.
    2. Identifies pocket residues within `cutoff` Å of `pocket_selection`.
    3. Calculates per-residue atomic displacement and local pocket RMSD.
    4. Writes displacement into B-factor column and maps a blue-white-red spectrum.
    """
    cmd = cmd_override or _get_active_cmd()
    if cmd is None:
        return ConformationComparisonResult(
            mobile_object=mobile_object,
            target_object=target_object,
            overall_ca_rmsd=0.0,
            pocket_rmsd=0.0,
            inspected_pocket_residues=0,
            warning="PyMOL cmd is not available in current environment.",
        )

    # Validate objects exist
    for obj in (mobile_object, target_object):
        try:
            if cmd.count_atoms(f"model {obj}") == 0:
                return ConformationComparisonResult(
                    mobile_object=mobile_object,
                    target_object=target_object,
                    overall_ca_rmsd=0.0,
                    pocket_rmsd=0.0,
                    inspected_pocket_residues=0,
                    warning=f"Object '{obj}' not found or contains no atoms.",
                )
        except Exception as exc:
            return ConformationComparisonResult(
                mobile_object=mobile_object,
                target_object=target_object,
                overall_ca_rmsd=0.0,
                pocket_rmsd=0.0,
                inspected_pocket_residues=0,
                warning=f"Error inspecting object '{obj}': {exc}",
            )

    # 1. Superimpose / Align
    overall_ca_rmsd = 0.0
    try:
        # Align on C-alpha
        align_res = cmd.align(
            f"(model {mobile_object}) and name CA",
            f"(model {target_object}) and name CA",
        )
        if isinstance(align_res, (list, tuple)) and len(align_res) > 0:
            overall_ca_rmsd = float(align_res[0])
    except Exception:
        # Fallback to general align
        try:
            align_res = cmd.align(f"model {mobile_object}", f"model {target_object}")
            if isinstance(align_res, (list, tuple)) and len(align_res) > 0:
                overall_ca_rmsd = float(align_res[0])
        except Exception:
            pass

    # 2. Identify pocket residues
    # Find pocket residues either around ligand in target or around pocket_selection
    pocket_sel_name = f"_flow_pock_{abs(hash((mobile_object, target_object))) % 10000}"
    try:
        # Check if pocket_selection exists
        has_ligand = cmd.count_atoms(pocket_selection) > 0
        if has_ligand:
            cmd.select(
                pocket_sel_name,
                f"(model {target_object} and polymer.protein) within {cutoff} of ({pocket_selection})",
            )
        else:
            # If no ligand found, analyze all protein residues
            cmd.select(pocket_sel_name, f"model {target_object} and polymer.protein and name CA")
    except Exception:
        cmd.select(pocket_sel_name, f"model {target_object} and polymer.protein and name CA")

    # 3. Extract paired atoms
    target_atoms: Dict[Tuple[str, str, str], Tuple[float, float, float]] = {}
    mobile_atoms: Dict[Tuple[str, str, str], Tuple[float, float, float]] = {}
    residue_names: Dict[Tuple[str, str], str] = {}

    try:
        # Iterate target pocket atoms
        class Storage:
            data: list = []

        store = Storage()
        store.data = []
        cmd.iterate_state(
            1,
            pocket_sel_name,
            "data.append((chain, resi, name, resn, x, y, z))",
            space={"data": store.data},
        )
        for chain, resi, name, resn, x, y, z in store.data:
            key = (str(chain), str(resi), str(name))
            target_atoms[key] = (float(x), float(y), float(z))
            residue_names[(str(chain), str(resi))] = str(resn)

        # Iterate mobile matching atoms
        store.data = []
        cmd.iterate_state(
            1,
            f"model {mobile_object} and polymer.protein",
            "data.append((chain, resi, name, resn, x, y, z))",
            space={"data": store.data},
        )
        for chain, resi, name, resn, x, y, z in store.data:
            key = (str(chain), str(resi), str(name))
            if key in target_atoms:
                mobile_atoms[key] = (float(x), float(y), float(z))
    except Exception as exc:
        try:
            cmd.delete(pocket_sel_name)
        except Exception:
            pass
        return ConformationComparisonResult(
            mobile_object=mobile_object,
            target_object=target_object,
            overall_ca_rmsd=overall_ca_rmsd,
            pocket_rmsd=0.0,
            inspected_pocket_residues=0,
            warning=f"Coordinate extraction encountered an error: {exc}",
        )
    finally:
        try:
            cmd.delete(pocket_sel_name)
        except Exception:
            pass

    if not mobile_atoms:
        return ConformationComparisonResult(
            mobile_object=mobile_object,
            target_object=target_object,
            overall_ca_rmsd=overall_ca_rmsd,
            pocket_rmsd=0.0,
            inspected_pocket_residues=0,
            warning="No matching residue coordinates found between models in the pocket region.",
        )

    # 4. Calculate displacements
    squared_diff_sum = 0.0
    common_keys = [k for k in target_atoms if k in mobile_atoms]
    res_displacements: Dict[Tuple[str, str], List[float]] = {}

    for k in common_keys:
        tx, ty, tz = target_atoms[k]
        mx, my, mz = mobile_atoms[k]
        dist_sq = (tx - mx) ** 2 + (ty - my) ** 2 + (tz - mz) ** 2
        squared_diff_sum += dist_sq

        res_key = (k[0], k[1])
        res_displacements.setdefault(res_key, []).append(math.sqrt(dist_sq))

    pocket_rmsd = math.sqrt(squared_diff_sum / len(common_keys)) if common_keys else 0.0

    # Build per-residue summary
    displacement_list: List[ResidueDisplacement] = []
    res_max_disp_map: Dict[Tuple[str, str], float] = {}

    for (chain, resi), dists in res_displacements.items():
        max_d = max(dists) if dists else 0.0
        res_max_disp_map[(chain, resi)] = max_d
        displacement_list.append(
            ResidueDisplacement(
                chain=chain,
                resi=resi,
                resn=residue_names.get((chain, resi), "UNK"),
                displacement_angstrom=max_d,
                atom_count=len(dists),
            )
        )

    # Sort descending by displacement
    displacement_list.sort(key=lambda item: item.displacement_angstrom, reverse=True)

    # 5. Apply Heatmap to PyMOL
    heatmap_applied = False
    if apply_heatmap:
        try:
            # Set default B-factor of mobile protein to 0
            cmd.alter(f"model {mobile_object} and polymer.protein", "b = 0.0")

            # Update B-factor for each pocket residue with displacement value
            for (chain, resi), max_d in res_max_disp_map.items():
                chain_filter = f" and chain '{chain}'" if chain else ""
                cmd.alter(
                    f"model {mobile_object} and resi {resi}{chain_filter}",
                    f"b = {round(max_d, 2)}",
                )

            # Apply smooth spectrum on mobile object
            cmd.spectrum(
                "b",
                "blue_white_red",
                selection=f"model {mobile_object} and polymer.protein",
                minimum=0.0,
                maximum=2.5,
            )
            heatmap_applied = True
        except Exception:
            heatmap_applied = False

    return ConformationComparisonResult(
        mobile_object=mobile_object,
        target_object=target_object,
        overall_ca_rmsd=overall_ca_rmsd,
        pocket_rmsd=pocket_rmsd,
        inspected_pocket_residues=len(displacement_list),
        top_displacements=displacement_list,
        heatmap_applied=heatmap_applied,
    )
