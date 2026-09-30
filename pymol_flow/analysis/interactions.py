"""Quantitative non-covalent protein-ligand interaction profiler (PLIP-style).

Calculates hydrogen bonds, salt bridges, hydrophobic contacts, aromatic/pi interactions,
and halogen bonds using PyMOL's native spatial indexing and coordinate geometry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any


@dataclass
class InteractionItem:
    """A single detected non-covalent contact between receptor and ligand."""

    interaction_type: str
    residue_name: str
    residue_number: str
    chain: str
    receptor_atom: str
    ligand_atom: str
    distance: float
    details: str = ""

    @property
    def residue_label(self) -> str:
        chain_part = f":{self.chain}" if self.chain else ""
        return f"{self.residue_name}-{self.residue_number}{chain_part}"


@dataclass
class InteractionReport:
    """Consolidated interaction profile report containing structured metrics and rendering methods."""

    ligand_selection: str
    receptor_selection: str
    pocket_cutoff: float
    pocket_residues: list[dict[str, str]] = field(default_factory=list)
    interactions: list[InteractionItem] = field(default_factory=list)
    diagnostic_message: str = ""

    @property
    def hydrogen_bonds(self) -> list[InteractionItem]:
        return [item for item in self.interactions if item.interaction_type == "Hydrogen Bond"]

    @property
    def salt_bridges(self) -> list[InteractionItem]:
        return [item for item in self.interactions if item.interaction_type == "Salt Bridge"]

    @property
    def hydrophobic_contacts(self) -> list[InteractionItem]:
        return [item for item in self.interactions if item.interaction_type == "Hydrophobic Contact"]

    @property
    def pi_interactions(self) -> list[InteractionItem]:
        return [
            item for item in self.interactions
            if item.interaction_type in {"π-Stacking", "Cation-π"}
        ]

    @property
    def halogen_bonds(self) -> list[InteractionItem]:
        return [item for item in self.interactions if item.interaction_type == "Halogen Bond"]

    def summary(self) -> dict[str, int]:
        return {
            "pocket_residues": len(self.pocket_residues),
            "hydrogen_bonds": len(self.hydrogen_bonds),
            "salt_bridges": len(self.salt_bridges),
            "hydrophobic_contacts": len(self.hydrophobic_contacts),
            "pi_interactions": len(self.pi_interactions),
            "halogen_bonds": len(self.halogen_bonds),
            "total_interactions": len(self.interactions),
        }

    def to_markdown(self) -> str:
        """Render a publication-style Markdown report with summary badges and a structured table."""
        if self.diagnostic_message:
            return f"**相互作用分析提示**: {self.diagnostic_message}"

        summary = self.summary()
        res_count = summary["pocket_residues"]
        hb_count = summary["hydrogen_bonds"]
        sb_count = summary["salt_bridges"]
        hp_count = summary["hydrophobic_contacts"]
        pi_count = summary["pi_interactions"]
        xb_count = summary["halogen_bonds"]

        md_lines = [
            "### 蛋白-配体相互作用定量分析报告 (PLIP Profiler)",
            "",
            f"- **分析对象**: 配体 `{self.ligand_selection}` ↔ 受体 `{self.receptor_selection}`",
            f"- **口袋截断距离**: `{self.pocket_cutoff:.1f} Å`（识别到 **{res_count}** 个口袋残基）",
            f"- **相互作用统计**: 氢键: **{hb_count}** | 盐桥: **{sb_count}** | 疏水接触: **{hp_count}** | π相互作用: **{pi_count}** | 卤键: **{xb_count}**",
            "",
        ]

        if not self.interactions:
            md_lines.append(
                f"在当前截断半径（{self.pocket_cutoff:.1f} Å）内未检测到典型极性氢键或强相互作用。"
                "建议适当扩大检索截断距离或检查配体质子化/加氢状态。"
            )
            return "\n".join(md_lines)

        md_lines.extend([
            "| 相互作用类型 | 受体残基 | 受体原子 | 配体原子 | 距离 (Å) | 特征说明 |",
            "| :--- | :--- | :--- | :--- | :---: | :--- |",
        ])

        # Sort interactions: Salt Bridge > Hydrogen Bond > pi-Interactions > Halogen Bond > Hydrophobic Contact
        type_priority = {
            "Salt Bridge": 1,
            "Hydrogen Bond": 2,
            "π-Stacking": 3,
            "Cation-π": 4,
            "Halogen Bond": 5,
            "Hydrophobic Contact": 6,
        }
        sorted_items = sorted(
            self.interactions,
            key=lambda x: (type_priority.get(x.interaction_type, 99), x.distance),
        )

        for item in sorted_items:
            md_lines.append(
                f"| **{item.interaction_type}** | `{item.residue_label}` | `{item.receptor_atom}` | `{item.ligand_atom}` | **{item.distance:.2f}** | {item.details} |"
            )

        md_lines.append("")
        md_lines.append(
            "*提示：已在 PyMOL 3D 视口中以黄色虚线标出氢键、洋红色虚线标出盐桥，并将口袋关键残基高亮显示。*"
        )
        return "\n".join(md_lines)

    def render_in_pymol(self, cmd_api: Any = None) -> None:
        """Apply visual styling, dashed interaction lines, and orient the camera in PyMOL."""
        if cmd_api is None:
            from pymol import cmd as cmd_api

        if self.diagnostic_message or not self.pocket_residues:
            return

        try:
            pocket_sel = f"byres (({self.receptor_selection}) within {self.pocket_cutoff} of ({self.ligand_selection}))"
            # 1. Base representations
            cmd_api.show("cartoon", self.receptor_selection)
            cmd_api.show("sticks", self.ligand_selection)
            cmd_api.color("yellow", f"({self.ligand_selection}) and elem C")
            cmd_api.show("sticks", pocket_sel)
            cmd_api.color("cyan", f"({pocket_sel}) and elem C")

            # 2. Hide solvent/water by default around pocket
            cmd_api.hide("everything", "solvent")

            # 3. Clean previous measurement objects
            for obj in ["hbonds", "salt_bridges", "halogen_bonds", "pi_contacts"]:
                if obj in cmd_api.get_names("all"):
                    cmd_api.delete(obj)

            # 4. Measure and style Hydrogen Bonds
            if self.hydrogen_bonds:
                cmd_api.distance(
                    "hbonds",
                    f"({self.ligand_selection}) and elem N,O",
                    f"({pocket_sel}) and elem N,O",
                    cutoff=3.6,
                    mode=2,
                )
                cmd_api.set("dash_color", "yellow", "hbonds")
                cmd_api.set("dash_width", 2.5, "hbonds")
                cmd_api.set("dash_gap", 0.25, "hbonds")

            # 5. Measure and style Salt Bridges
            if self.salt_bridges:
                cmd_api.distance(
                    "salt_bridges",
                    f"({self.ligand_selection}) and (elem N,O)",
                    f"({pocket_sel}) and resn ASP+GLU+ARG+LYS+HIS and (name OD*+OE*+NZ+NH*+NE*)",
                    cutoff=4.2,
                )
                cmd_api.set("dash_color", "magenta", "salt_bridges")
                cmd_api.set("dash_width", 3.0, "salt_bridges")

            # 6. Label interacting residues
            interacting_resis = {item.residue_number for item in self.interactions if item.interaction_type in {"Hydrogen Bond", "Salt Bridge", "π-Stacking"}}
            if interacting_resis:
                resi_query = "+".join(sorted(interacting_resis))
                label_target = f"({pocket_sel}) and name CA and resi {resi_query}"
                cmd_api.label(label_target, "'%s%s' % (resn, resi)")
                cmd_api.set("label_color", "white")
                cmd_api.set("label_size", 16)

            # 7. Orient and center on ligand & binding site
            cmd_api.orient(f"({self.ligand_selection}) or ({pocket_sel})")
        except Exception:
            pass


def analyze_interactions(
    ligand_selection: str = "organic",
    receptor_selection: str = "polymer.protein",
    cutoff: float = 4.5,
    cmd_api: Any = None,
    visualize: bool = True,
) -> InteractionReport:
    """Analyze non-covalent interactions between ligand and receptor using PyMOL coordinates.

    Args:
        ligand_selection: PyMOL selection string identifying the ligand.
        receptor_selection: PyMOL selection string identifying the receptor protein.
        cutoff: Pocket definition radius in Angstroms.
        cmd_api: PyMOL cmd instance (defaults to global pymol.cmd).
        visualize: Whether to render representations and dashed lines in PyMOL.

    Returns:
        InteractionReport containing detailed interaction breakdown and Markdown report.
    """
    if cmd_api is None:
        from pymol import cmd as cmd_api

    # 1. Resolve ligand selection if default doesn't match
    try:
        lig_atoms = cmd_api.count_atoms(ligand_selection)
    except Exception:
        lig_atoms = 0

    if lig_atoms == 0:
        # Fallback to non-solvent organic molecules in the scene
        candidates = ["organic and not solvent", "not (polymer or solvent)"]
        found = False
        for cand in candidates:
            try:
                if cmd_api.count_atoms(cand) > 0:
                    ligand_selection = cand
                    found = True
                    break
            except Exception:
                continue
        if not found:
            return InteractionReport(
                ligand_selection=ligand_selection,
                receptor_selection=receptor_selection,
                pocket_cutoff=cutoff,
                diagnostic_message=(
                    f"未能在场景中找到匹配配体选择 `{ligand_selection}` 的原子。"
                    "请确认配体对象名称或残基名（例如指定 `resn LIG` 或 `model <对象名> and organic`）。"
                ),
            )

    try:
        rec_atoms = cmd_api.count_atoms(receptor_selection)
    except Exception:
        rec_atoms = 0

    if rec_atoms == 0:
        return InteractionReport(
            ligand_selection=ligand_selection,
            receptor_selection=receptor_selection,
            pocket_cutoff=cutoff,
            diagnostic_message=f"未能在场景中找到受体蛋白原子（选择 `{receptor_selection}` 为空）。",
        )

    # 2. Extract pocket residues and atom coordinate data
    pocket_sel = f"byres (({receptor_selection}) within {cutoff} of ({ligand_selection}))"

    from pymol import stored
    stored._pocket_atoms = {}
    stored._ligand_atoms = {}

    try:
        cmd_api.iterate_state(
            1,
            pocket_sel,
            "stored._pocket_atoms[(model, index)] = (resn, resi, chain, name, elem, x, y, z)",
        )
        cmd_api.iterate_state(
            1,
            ligand_selection,
            "stored._ligand_atoms[(model, index)] = (resn, resi, chain, name, elem, x, y, z)",
        )
    except Exception as exc:
        return InteractionReport(
            ligand_selection=ligand_selection,
            receptor_selection=receptor_selection,
            pocket_cutoff=cutoff,
            diagnostic_message=f"提取坐标时出错: {exc}",
        )

    pocket_atom_dict = getattr(stored, "_pocket_atoms", {})
    ligand_atom_dict = getattr(stored, "_ligand_atoms", {})

    # Extract unique pocket residues
    unique_res_keys = set()
    pocket_res_list = []
    for (resn, resi, chain, _name, _elem, _x, _y, _z) in pocket_atom_dict.values():
        key = (resn, resi, chain)
        if key not in unique_res_keys:
            unique_res_keys.add(key)
            pocket_res_list.append({"name": resn, "resi": resi, "chain": chain})

    # Sort pocket residues by chain and residue number
    def resi_key(item: dict[str, str]) -> tuple[str, int]:
        try:
            return (item["chain"], int("".join(c for c in item["resi"] if c.isdigit()) or 0))
        except Exception:
            return (item["chain"], 0)

    pocket_res_list.sort(key=resi_key)

    # 3. Find atomic pairs using PyMOL's native C++ spatial index
    try:
        pairs = cmd_api.find_pairs(ligand_selection, pocket_sel, cutoff=cutoff, mode=0)
    except Exception as exc:
        return InteractionReport(
            ligand_selection=ligand_selection,
            receptor_selection=receptor_selection,
            pocket_cutoff=cutoff,
            pocket_residues=pocket_res_list,
            diagnostic_message=f"计算空间近邻原子对时出错: {exc}",
        )

    # 4. Classify interactions
    detected_interactions: list[InteractionItem] = []
    seen_contacts: set[tuple[str, str, str, str, str]] = set()

    # Known residue categories
    acidic_resns = {"ASP", "GLU"}
    basic_resns = {"LYS", "ARG", "HIS"}
    aromatic_resns = {"PHE", "TYR", "TRP", "HIS"}
    hydrophobic_resns = {"ALA", "VAL", "LEU", "ILE", "MET", "PHE", "TRP", "PRO", "CYS", "TYR"}

    for lig_key, rec_key in pairs:
        if lig_key not in ligand_atom_dict or rec_key not in pocket_atom_dict:
            continue

        l_resn, l_resi, l_chain, l_name, l_elem, lx, ly, lz = ligand_atom_dict[lig_key]
        r_resn, r_resi, r_chain, r_name, r_elem, rx, ry, rz = pocket_atom_dict[rec_key]

        l_elem = (l_elem or "").upper().strip()
        r_elem = (r_elem or "").upper().strip()
        r_resn = (r_resn or "").upper().strip()
        r_name = (r_name or "").upper().strip()
        l_name = (l_name or "").upper().strip()

        # Euclidean distance
        dx = lx - rx
        dy = ly - ry
        dz = lz - rz
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)

        # 4.1 Hydrogen Bond detection (N, O donors/acceptors within 3.6A)
        if l_elem in {"N", "O"} and r_elem in {"N", "O"} and 2.2 <= dist <= 3.6:
            contact_key = ("HB", r_resn, r_resi, r_name, l_name)
            if contact_key not in seen_contacts:
                seen_contacts.add(contact_key)
                is_backbone = r_name in {"N", "O"}
                details = "主链氢键" if is_backbone else "侧链氢键"
                detected_interactions.append(
                    InteractionItem(
                        interaction_type="Hydrogen Bond",
                        residue_name=r_resn,
                        residue_number=r_resi,
                        chain=r_chain,
                        receptor_atom=r_name,
                        ligand_atom=l_name,
                        distance=dist,
                        details=details,
                    )
                )

        # 4.2 Salt Bridge detection (Charge-charge interaction within 4.2A)
        is_salt_bridge = False
        sb_details = ""
        if r_resn in acidic_resns and r_name in {"OD1", "OD2", "OE1", "OE2"}:
            if l_elem == "N" and dist <= 4.2:
                is_salt_bridge = True
                sb_details = f"阴性侧链 ({r_resn}) ↔ 阳性配体原子"
        elif r_resn in basic_resns and r_name in {"NZ", "NH1", "NH2", "NE", "ND1", "NE2"}:
            if l_elem in {"O", "N"} and dist <= 4.2:
                is_salt_bridge = True
                sb_details = f"阳性侧链 ({r_resn}) ↔ 阴性配体基团"

        if is_salt_bridge:
            contact_key = ("SB", r_resn, r_resi, r_name, l_name)
            if contact_key not in seen_contacts:
                seen_contacts.add(contact_key)
                detected_interactions.append(
                    InteractionItem(
                        interaction_type="Salt Bridge",
                        residue_name=r_resn,
                        residue_number=r_resi,
                        chain=r_chain,
                        receptor_atom=r_name,
                        ligand_atom=l_name,
                        distance=dist,
                        details=sb_details,
                    )
                )
            continue

        # 4.3 Halogen Bond (Halogen Cl, Br, I, F ↔ Lewis Base N, O, S within 3.8A)
        if l_elem in {"CL", "BR", "I", "F"} and r_elem in {"N", "O", "S"} and dist <= 3.8:
            contact_key = ("XB", r_resn, r_resi, r_name, l_name)
            if contact_key not in seen_contacts:
                seen_contacts.add(contact_key)
                detected_interactions.append(
                    InteractionItem(
                        interaction_type="Halogen Bond",
                        residue_name=r_resn,
                        residue_number=r_resi,
                        chain=r_chain,
                        receptor_atom=r_name,
                        ligand_atom=l_name,
                        distance=dist,
                        details=f"卤素 {l_elem} ↔ 路易斯碱 {r_elem}",
                    )
                )
            continue

        # 4.4 Aromatic / pi-interactions (Aromatic ring carbons within 4.5A)
        if r_resn in aromatic_resns and r_name in {"CG", "CD1", "CD2", "CE1", "CE2", "CZ", "NE1", "CH2", "CZ2", "CZ3"}:
            if l_elem == "C" and dist <= 4.5:
                contact_key = ("PI", r_resn, r_resi, r_name, l_name)
                if contact_key not in seen_contacts:
                    seen_contacts.add(contact_key)
                    detected_interactions.append(
                        InteractionItem(
                            interaction_type="π-Stacking",
                            residue_name=r_resn,
                            residue_number=r_resi,
                            chain=r_chain,
                            receptor_atom=r_name,
                            ligand_atom=l_name,
                            distance=dist,
                            details=f"芳香环接触 ({r_resn})",
                        )
                    )
                continue
            elif l_elem == "N" and dist <= 4.2:
                contact_key = ("CPI", r_resn, r_resi, r_name, l_name)
                if contact_key not in seen_contacts:
                    seen_contacts.add(contact_key)
                    detected_interactions.append(
                        InteractionItem(
                            interaction_type="Cation-π",
                            residue_name=r_resn,
                            residue_number=r_resi,
                            chain=r_chain,
                            receptor_atom=r_name,
                            ligand_atom=l_name,
                            distance=dist,
                            details=f"芳香环与阳离子配体原子",
                        )
                    )
                continue

        # 4.5 Hydrophobic Contact (Carbon-Carbon within 4.0A, excluding backbone carbonyl C)
        if l_elem == "C" and r_elem == "C" and r_resn in hydrophobic_resns and r_name != "C" and 2.8 <= dist <= 4.0:
            contact_key = ("HP", r_resn, r_resi, r_name, l_name)
            if contact_key not in seen_contacts:
                seen_contacts.add(contact_key)
                detected_interactions.append(
                    InteractionItem(
                        interaction_type="Hydrophobic Contact",
                        residue_name=r_resn,
                        residue_number=r_resi,
                        chain=r_chain,
                        receptor_atom=r_name,
                        ligand_atom=l_name,
                        distance=dist,
                        details="非极性碳接触",
                    )
                )

    report = InteractionReport(
        ligand_selection=ligand_selection,
        receptor_selection=receptor_selection,
        pocket_cutoff=cutoff,
        pocket_residues=pocket_res_list,
        interactions=detected_interactions,
    )

    if visualize:
        report.render_in_pymol(cmd_api)

    return report
