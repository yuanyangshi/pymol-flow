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
        from .align import align_structures
        aln_res = align_structures(
            mobile_object=mobile_object,
            target_object=target_object,
            ligand_selection=pocket_selection,
            focus_pocket=True,
            cmd_override=cmd,
        )
        if aln_res.success:
            overall_ca_rmsd = float(aln_res.overall_ca_rmsd)
    except Exception:
        pass

    # If intelligent align gave 0 or failed, fallback to direct align / super
    if overall_ca_rmsd <= 0.0:
        try:
            align_res = cmd.align(
                f"({mobile_object}) and name CA",
                f"({target_object}) and name CA",
            )
            if isinstance(align_res, (list, tuple)) and len(align_res) > 0:
                overall_ca_rmsd = float(align_res[0])
        except Exception:
            pass

    if overall_ca_rmsd <= 0.0:
        try:
            super_res = cmd.super(
                f"({mobile_object}) and name CA",
                f"({target_object}) and name CA",
            )
            if isinstance(super_res, (list, tuple)) and len(super_res) > 0:
                overall_ca_rmsd = float(super_res[0])
        except Exception:
            try:
                super_res = cmd.super(f"({mobile_object})", f"({target_object})")
                if isinstance(super_res, (list, tuple)) and len(super_res) > 0:
                    overall_ca_rmsd = float(super_res[0])
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
                f"byres ((model {target_object} and polymer.protein) within {cutoff} of ({pocket_selection}))",
            )
        else:
            # If no ligand found, analyze all protein residues
            cmd.select(pocket_sel_name, f"model {target_object} and polymer.protein and name CA")
    except Exception:
        cmd.select(pocket_sel_name, f"model {target_object} and polymer.protein and name CA")

    # 3. Extract atoms
    target_atoms: Dict[Tuple[str, str, str], Tuple[float, float, float]] = {}
    target_ca: Dict[Tuple[str, str], Tuple[str, Tuple[float, float, float]]] = {}
    mobile_atoms: Dict[Tuple[str, str, str], Tuple[float, float, float]] = {}
    mobile_ca: Dict[Tuple[str, str], Tuple[str, Tuple[float, float, float]]] = {}
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
            coords = (float(x), float(y), float(z))
            target_atoms[key] = coords
            residue_names[(str(chain), str(resi))] = str(resn)
            if str(name).upper() == "CA":
                target_ca[(str(chain), str(resi))] = (str(resn), coords)

        # Iterate mobile atoms
        store.data = []
        cmd.iterate_state(
            1,
            f"model {mobile_object} and polymer.protein",
            "data.append((chain, resi, name, resn, x, y, z))",
            space={"data": store.data},
        )
        for chain, resi, name, resn, x, y, z in store.data:
            key = (str(chain), str(resi), str(name))
            coords = (float(x), float(y), float(z))
            mobile_atoms[key] = coords
            if str(name).upper() == "CA":
                mobile_ca[(str(chain), str(resi))] = (str(resn), coords)
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

    # 4. Calculate displacements (Dual-Mode: Exact Match vs Spatial Homology Match)
    squared_diff_sum = 0.0
    common_keys = [k for k in target_atoms if k in mobile_atoms]
    res_displacements: Dict[Tuple[str, str], List[float]] = {}
    displacement_list: List[ResidueDisplacement] = []
    res_max_disp_map: Dict[Tuple[str, str], float] = {}
    mobile_disp_map: Dict[Tuple[str, str], float] = {}

    if len(common_keys) >= 3:
        # Mode 1: Exact (chain, resi, name) match (same protein / mutant / apo vs holo)
        for k in common_keys:
            tx, ty, tz = target_atoms[k]
            mx, my, mz = mobile_atoms[k]
            dist_sq = (tx - mx) ** 2 + (ty - my) ** 2 + (tz - mz) ** 2
            squared_diff_sum += dist_sq

            res_key = (k[0], k[1])
            res_displacements.setdefault(res_key, []).append(math.sqrt(dist_sq))

        pocket_rmsd = math.sqrt(squared_diff_sum / len(common_keys)) if common_keys else 0.0

        for (chain, resi), dists in res_displacements.items():
            max_d = max(dists) if dists else 0.0
            res_max_disp_map[(chain, resi)] = max_d
            mobile_disp_map[(chain, resi)] = max_d
            displacement_list.append(
                ResidueDisplacement(
                    chain=chain,
                    resi=resi,
                    resn=residue_names.get((chain, resi), "UNK"),
                    displacement_angstrom=max_d,
                    atom_count=len(dists),
                )
            )
    else:
        # Mode 2: Spatial Homology Match (cross-kinase / differing residue numbering)
        matched_pairs_count = 0
        for (t_chain, t_resi), (t_resn, t_coords) in target_ca.items():
            best_m_key = None
            min_dist = float("inf")
            for (m_chain, m_resi), (m_resn, m_coords) in mobile_ca.items():
                dist = math.sqrt(
                    (t_coords[0] - m_coords[0]) ** 2
                    + (t_coords[1] - m_coords[1]) ** 2
                    + (t_coords[2] - m_coords[2]) ** 2
                )
                if dist < min_dist:
                    min_dist = dist
                    best_m_key = (m_chain, m_resi)

            # 3.8 Å threshold for aligned homologous C-alpha pairing
            if best_m_key is not None and min_dist <= 3.8:
                m_chain, m_resi = best_m_key
                m_resn, _ = mobile_ca[best_m_key]
                squared_diff_sum += min_dist ** 2
                matched_pairs_count += 1

                res_max_disp_map[(t_chain, t_resi)] = min_dist
                mobile_disp_map[(m_chain, m_resi)] = min_dist
                pair_label = f"{t_resn}{t_resi} ↔ {m_resn}{m_resi}"

                displacement_list.append(
                    ResidueDisplacement(
                        chain=t_chain,
                        resi=t_resi,
                        resn=pair_label,
                        displacement_angstrom=min_dist,
                        atom_count=1,
                    )
                )

        pocket_rmsd = math.sqrt(squared_diff_sum / matched_pairs_count) if matched_pairs_count else 0.0

    if not displacement_list:
        return ConformationComparisonResult(
            mobile_object=mobile_object,
            target_object=target_object,
            overall_ca_rmsd=overall_ca_rmsd,
            pocket_rmsd=0.0,
            inspected_pocket_residues=0,
            warning="No matching residue coordinates found between models in the pocket region.",
        )

    # Sort descending by displacement
    displacement_list.sort(key=lambda item: item.displacement_angstrom, reverse=True)

    # 5. Apply Heatmap to PyMOL
    heatmap_applied = False
    if apply_heatmap:
        try:
            # Set default B-factor of mobile protein to 0
            cmd.alter(f"model {mobile_object} and polymer.protein", "b = 0.0")

            # Update B-factor on mobile object
            for (chain, resi), max_d in mobile_disp_map.items():
                chain_filter = f" and chain '{chain}'" if chain else ""
                cmd.alter(
                    f"model {mobile_object} and resi {resi}{chain_filter}",
                    f"b = {round(max_d, 2)}",
                )

            # Also color target object if different numbering
            if mobile_disp_map != res_max_disp_map:
                cmd.alter(f"model {target_object} and polymer.protein", "b = 0.0")
                for (chain, resi), max_d in res_max_disp_map.items():
                    chain_filter = f" and chain '{chain}'" if chain else ""
                    cmd.alter(
                        f"model {target_object} and resi {resi}{chain_filter}",
                        f"b = {round(max_d, 2)}",
                    )
                cmd.spectrum(
                    "b",
                    "blue_white_red",
                    selection=f"model {target_object} and polymer.protein",
                    minimum=0.0,
                    maximum=2.5,
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
