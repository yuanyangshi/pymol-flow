"""3D Viewport active selection awareness and inspection utilities for PyMOL."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SelectionSummary:
    """Summary of user's active 3D viewport selection ('sele') in PyMOL."""

    has_selection: bool = False
    atom_count: int = 0
    residue_count: int = 0
    models: list[str] = field(default_factory=list)
    residues: list[str] = field(default_factory=list)  # e.g. ["ASP-52", "LYS-89"]
    chains: list[str] = field(default_factory=list)
    is_ligand: bool = False
    is_protein: bool = False
    label: str = ""

    def to_description(self) -> str:
        """User-friendly short description for UI badge and tool guidance."""
        if not self.has_selection:
            return "No active selection"
        parts = []
        if self.residues:
            if len(self.residues) <= 4:
                parts.append(", ".join(self.residues))
            else:
                parts.append(f"{self.residues[0]}...{self.residues[-1]} ({len(self.residues)} residues)")
        else:
            parts.append(f"{self.atom_count} atoms")

        if self.models:
            parts.append(f"in {', '.join(self.models)}")
        return " ".join(parts)


def get_viewport_selection_summary(cmd_api: Any = None) -> SelectionSummary:
    """Inspect the active PyMOL viewport selection ('sele') and return structured metadata.

    Safe and non-destructive: only reads properties of 'sele'.
    """
    if cmd_api is None:
        from pymol import cmd as cmd_api

    try:
        selections = cmd_api.get_names("selections") or []
        if "sele" not in selections:
            return SelectionSummary(has_selection=False)

        count = cmd_api.count_atoms("sele")
        if count <= 0:
            return SelectionSummary(has_selection=False)

        is_lig = bool(cmd_api.count_atoms("sele and organic") > 0)
        is_prot = bool(cmd_api.count_atoms("sele and polymer.protein") > 0)

        # Iterate over sele to get models, chains, and residues
        from pymol import stored
        stored._sele_data = set()
        cmd_api.iterate(
            "sele",
            "stored._sele_data.add((model, chain, resi, resn))",
        )
        data = getattr(stored, "_sele_data", set())

        models = sorted({item[0] for item in data if item[0]})
        chains = sorted({item[1] for item in data if item[1]})

        # Group residues and format them naturally (e.g., ASP-52, LYS-89)
        def _res_sort_key(item: tuple[str, str, str, str]) -> tuple[str, int, str]:
            chain = item[1]
            try:
                num = int("".join(filter(str.isdigit, item[2])) or "0")
            except Exception:
                num = 0
            return (chain, num, item[3])

        sorted_items = sorted(data, key=_res_sort_key)
        seen_res = set()
        res_labels = []
        for _m, c, ri, rn in sorted_items:
            res_key = (c, ri, rn)
            if res_key not in seen_res:
                seen_res.add(res_key)
                chain_prefix = f"{c}:" if c else ""
                res_labels.append(f"{chain_prefix}{rn}-{ri}")

        summary = SelectionSummary(
            has_selection=True,
            atom_count=count,
            residue_count=len(res_labels),
            models=models,
            residues=res_labels,
            chains=chains,
            is_ligand=is_lig,
            is_protein=is_prot,
        )
        summary.label = summary.to_description()
        return summary
    except Exception:
        return SelectionSummary(has_selection=False)


def clear_viewport_selection(cmd_api: Any = None) -> None:
    """Clear active 3D viewport selection ('sele') in PyMOL."""
    if cmd_api is None:
        from pymol import cmd as cmd_api
    try:
        cmd_api.delete("sele")
        cmd_api.deselect()
    except Exception:
        pass
