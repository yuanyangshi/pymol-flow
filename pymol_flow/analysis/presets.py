"""Publication-grade visual presets and AlphaFold/ESMFold pLDDT confidence spectrum tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class PresetResult:
    style: str
    description: str
    commands_executed: int
    success: bool
    details: Optional[str] = None

    def to_markdown(self) -> str:
        status_icon = "✨" if self.success else "⚠️"
        lines = [
            f"{status_icon} **Visual Preset Applied**: `{self.style.upper()}`",
            f"- **Style Profile**: {self.description}",
            f"- **Operations**: {self.commands_executed} rendering parameters configured.",
        ]
        if self.details:
            lines.append(f"- **Details**: {self.details}")
        return "\n".join(lines)


@dataclass
class PLDDTResult:
    selection: str
    total_atoms: int
    mean_plddt: float
    very_high_pct: float  # > 90
    confident_pct: float  # 70-90
    low_pct: float        # 50-70
    very_low_pct: float   # < 50
    disordered_hidden: bool
    success: bool
    warning: Optional[str] = None

    def to_markdown(self) -> str:
        lines = [
            f"### 🧬 AlphaFold / ESMFold pLDDT Confidence Profile",
            f"- **Target Selection**: `{self.selection}`",
            f"- **Mean pLDDT Score**: **{self.mean_plddt:.1f}** / 100.0",
            f"\n#### 📊 Confidence Breakdown",
            f"- 🟦 **Very High** (pLDDT > 90): `{self.very_high_pct:.1f}%` *(Highly accurate backbone & sidechains)*",
            f"- 🩵 **Confident** (70 ≤ pLDDT < 90): `{self.confident_pct:.1f}%` *(Reliable backbone geometry)*",
            f"- 🟨 **Low** (50 ≤ pLDDT < 70): `{self.low_pct:.1f}%` *(Flexible/uncertain loop regions)*",
            f"- 🟧 **Very Low** (pLDDT < 50): `{self.very_low_pct:.1f}%` *(Predicted intrinsically disordered)*",
        ]
        if self.disordered_hidden:
            lines.append(f"\n- ✂️ **Disorder Filter**: Low-confidence disordered loops (pLDDT < 50) have been hidden to highlight the core structured fold.")
        if self.warning:
            lines.append(f"\n> ⚠️ *Note*: {self.warning}")
        return "\n".join(lines)


def _get_active_cmd() -> Any:
    try:
        from pymol import cmd
        return cmd
    except ImportError:
        return None


def apply_publication_preset(
    style: str = "nature",
    selection: str = "all",
    cmd_override: Any = None,
) -> PresetResult:
    """Apply high-end publication-grade rendering presets to PyMOL session.

    Available Styles:
    - 'nature' / 'nsc': Soft diffuse lighting, clean white background, pastel secondary colors, high-sampling cartoon.
    - 'cell_outline' / 'comic': Black-line comic/editorial cell-shading (ray_trace_mode 3) with crisp silhouette.
    - 'cryo_pocket': Translucent surface enclosing high-contrast stick representations of the pocket residues and ligand.
    - 'keynote_dark': Sleek dark presentation background with vibrant neon secondary structure accents.
    """
    cmd = cmd_override or _get_active_cmd()
    if cmd is None:
        return PresetResult(
            style=style,
            description="PyMOL cmd is unavailable in current environment.",
            commands_executed=0,
            success=False,
        )

    style_clean = style.lower().strip()
    count = 0

    try:
        if style_clean in ("nature", "nsc", "publication", "default"):
            # Nature / Science / Cell elegant aesthetic
            cmd.bg_color("white")
            cmd.set("ray_shadows", 1)
            cmd.set("ray_trace_mode", 1)
            cmd.set("ambient", 0.40)
            cmd.set("direct", 0.65)
            cmd.set("light_count", 2)
            cmd.set("cartoon_sampling", 14)
            cmd.set("ribbon_sampling", 14)
            cmd.set("stick_radius", 0.25)
            cmd.set("stick_ball", 1)
            cmd.set("stick_ball_ratio", 1.2)
            cmd.set("depth_cue", 0)
            cmd.set("ray_trace_fog", 0)
            cmd.set("antialias", 2)
            count = 13
            desc = "Nature/Science elegant soft diffuse lighting with crisp white background and high-sampling cartoon."

        elif style_clean in ("cell_outline", "outline", "comic", "illustration"):
            # Black border illustration style (Cell Press / textbook figures)
            cmd.bg_color("white")
            cmd.set("ray_trace_mode", 3)  # Quantized color + black outlines
            cmd.set("ray_trace_gain", 0.1)
            cmd.set("ray_shadows", 0)
            cmd.set("cartoon_fancy_helices", 1)
            cmd.set("cartoon_side_chain_helper", 1)
            cmd.set("ambient", 0.70)
            cmd.set("antialias", 2)
            count = 8
            desc = "Cell Press illustration style with distinctive black ink outlines and flat cartoon shading."

        elif style_clean in ("cryo_pocket", "cryo", "pocket_surface", "transparent_surface"):
            # Cryo-EM translucent pocket surface
            cmd.bg_color("white")
            cmd.set("transparency", 0.42)
            cmd.set("surface_quality", 1)
            cmd.set("surface_solvent", 0)
            cmd.set("stick_radius", 0.28)
            cmd.set("ray_shadows", 1)
            cmd.set("ambient", 0.35)
            cmd.set("two_sided_lighting", 1)
            if cmd.count_atoms("organic") > 0:
                cmd.set("surface_carve_selection", "organic")
                cmd.set("surface_carve_cutoff", 5.0)
                cmd.set("surface_color", "white", selection)
            # Show translucent surface on target or selection
            cmd.show("surface", selection)
            cmd.show("sticks", f"({selection}) and (organic or (polymer.protein within 4.5 of organic))")
            count = 8
            desc = "Cryo-EM translucent molecular pocket surface enveloping high-contrast interaction sticks."

        elif style_clean in ("keynote_dark", "dark", "presentation", "oled"):
            # Dark keynote theme for modern presentations
            cmd.bg_color("0x121316")  # Sleek basalt dark
            cmd.set("ray_shadows", 1)
            cmd.set("ray_trace_mode", 1)
            cmd.set("ambient", 0.45)
            cmd.set("direct", 0.60)
            cmd.set("antialias", 2)
            cmd.set("stick_radius", 0.26)
            cmd.color("0x4F46E5", f"({selection}) and polymer.protein and ss h")  # Indigo helices
            cmd.color("0x06B6D4", f"({selection}) and polymer.protein and ss s")  # Cyan sheets
            cmd.color("0x94A3B8", f"({selection}) and polymer.protein and not (ss h or ss s)")  # Muted loops
            cmd.color("0xF59E0B", f"({selection}) and organic")  # Luminous amber ligand
            count = 11
            desc = "Keynote dark-mode OLED theme with luminescent secondary structure accents."

        else:
            return PresetResult(
                style=style,
                description=f"Unknown preset style '{style}'. Supported: 'nature', 'cell_outline', 'cryo_pocket', 'keynote_dark'.",
                commands_executed=0,
                success=False,
            )

        return PresetResult(
            style=style_clean,
            description=desc,
            commands_executed=count,
            success=True,
        )
    except Exception as exc:
        return PresetResult(
            style=style_clean,
            description=f"Error applying preset: {exc}",
            commands_executed=count,
            success=False,
        )


def visualize_plddt(
    selection: str = "all",
    hide_disordered: bool = False,
    min_plddt: float = 50.0,
    cmd_override: Any = None,
) -> PLDDTResult:
    """Analyze and apply AlphaFold/ESMFold pLDDT confidence coloring to protein structures.

    Colors:
    - pLDDT > 90: Very High (Dark Blue #0053D6)
    - 70 <= pLDDT < 90: Confident (Light Blue #65CBF3)
    - 50 <= pLDDT < 70: Low (Yellow #FFDB13)
    - pLDDT < 50: Very Low / Disordered (Orange #FF7D45)

    Optionally hides or de-emphasizes regions with pLDDT < `min_plddt`.
    """
    cmd = cmd_override or _get_active_cmd()
    if cmd is None:
        return PLDDTResult(
            selection=selection,
            total_atoms=0,
            mean_plddt=0.0,
            very_high_pct=0.0,
            confident_pct=0.0,
            low_pct=0.0,
            very_low_pct=0.0,
            disordered_hidden=False,
            success=False,
            warning="PyMOL cmd is not available.",
        )

    try:
        class BFactorStore:
            b_list: list = []

        store = BFactorStore()
        store.b_list = []

        cmd.iterate(
            f"({selection}) and polymer.protein and name CA",
            "b_list.append(b)",
            space={"b_list": store.b_list},
        )

        if not store.b_list:
            # Fallback to all protein atoms if no C-alpha
            cmd.iterate(
                f"({selection}) and polymer.protein",
                "b_list.append(b)",
                space={"b_list": store.b_list},
            )

        if not store.b_list:
            return PLDDTResult(
                selection=selection,
                total_atoms=0,
                mean_plddt=0.0,
                very_high_pct=0.0,
                confident_pct=0.0,
                low_pct=0.0,
                very_low_pct=0.0,
                disordered_hidden=False,
                success=False,
                warning=f"No protein atoms found in selection '{selection}'.",
            )

        total = len(store.b_list)
        mean_b = sum(store.b_list) / total

        v_high = sum(1 for b in store.b_list if b >= 90.0)
        conf = sum(1 for b in store.b_list if 70.0 <= b < 90.0)
        low = sum(1 for b in store.b_list if 50.0 <= b < 70.0)
        v_low = sum(1 for b in store.b_list if b < 50.0)

        # Apply DeepMind AlphaFold color scheme
        # Set custom RGB colors
        cmd.set_color("af_very_high", [0.0, 0.325, 0.839])   # #0053D6
        cmd.set_color("af_confident", [0.396, 0.796, 0.953])  # #65CBF3
        cmd.set_color("af_low", [1.0, 0.859, 0.075])         # #FFDB13
        cmd.set_color("af_very_low", [1.0, 0.490, 0.271])    # #FF7D45

        # Color based on B-factor ranges (using PyMOL-compliant selection syntax)
        cmd.color("af_very_high", f"({selection}) and polymer.protein and not b < 90.0")
        cmd.color("af_confident", f"({selection}) and polymer.protein and b < 90.0 and not b < 70.0")
        cmd.color("af_low", f"({selection}) and polymer.protein and b < 70.0 and not b < 50.0")
        cmd.color("af_very_low", f"({selection}) and polymer.protein and b < 50.0")

        # Hide or trim disordered loops if requested
        if hide_disordered:
            cmd.hide("cartoon", f"({selection}) and polymer.protein and b < {min_plddt}")
            cmd.show("lines", f"({selection}) and polymer.protein and b < {min_plddt}")

        return PLDDTResult(
            selection=selection,
            total_atoms=total,
            mean_plddt=mean_b,
            very_high_pct=(v_high / total) * 100.0,
            confident_pct=(conf / total) * 100.0,
            low_pct=(low / total) * 100.0,
            very_low_pct=(v_low / total) * 100.0,
            disordered_hidden=hide_disordered,
            success=True,
        )
    except Exception as exc:
        return PLDDTResult(
            selection=selection,
            total_atoms=0,
            mean_plddt=0.0,
            very_high_pct=0.0,
            confident_pct=0.0,
            low_pct=0.0,
            very_low_pct=0.0,
            disordered_hidden=False,
            success=False,
            warning=f"Error analyzing pLDDT: {exc}",
        )


def show_pocket_surface(
    ligand_selection: str = "organic",
    receptor_selection: str = "polymer.protein",
    carve_cutoff: float = 4.5,
    pocket_stick_cutoff: float = 3.8,
    transparency: float = 0.5,
    surface_color: str = "gray90",
    cartoon_transparency: float = 0.60,
    cmd_api: Any = None,
) -> None:
    """Render a smooth, publication-grade binding pocket cavity surface using PyMOL's native surface_carve.

    Avoids the unphysical 'potato blob' phenomenon caused by calculating surfaces on isolated residue selections,
    and applies high-contrast color hierarchy (Yellow ligand carbons, Cyan pocket residues, translucent ribbons)
    with clean sidechain representations (cartoon_side_chain_helper).
    """
    if cmd_api is None:
        from pymol import cmd as cmd_api

    # 1. Resolve ligand selection
    if ligand_selection == "sele":
        try:
            if "sele" not in cmd_api.get_names("selections") or cmd_api.count_atoms("sele") == 0:
                ligand_selection = "organic"
        except Exception:
            ligand_selection = "organic"

    try:
        if cmd_api.count_atoms(ligand_selection) == 0:
            if cmd_api.count_atoms("organic and not solvent") > 0:
                ligand_selection = "organic and not solvent"
            elif cmd_api.count_atoms("not (polymer or solvent)") > 0:
                ligand_selection = "not (polymer or solvent)"
    except Exception:
        pass

    pocket_sel = f"byres (({receptor_selection}) within {pocket_stick_cutoff} of ({ligand_selection}))"

    try:
        # 1. Clean previous isolated or cluttered surfaces
        cmd_api.hide("surface", "all")

        # 2. Sidechain cleaner & cartoon transparency
        cmd_api.set("cartoon_side_chain_helper", 1)
        if cartoon_transparency > 0:
            cmd_api.set("cartoon_transparency", cartoon_transparency)

        # 3. Base representations: cartoon for protein, crisp sticks for pocket and ligand
        cmd_api.show("cartoon", receptor_selection)
        cmd_api.show("sticks", ligand_selection)
        cmd_api.show("sticks", pocket_sel)

        # 4. Color hierarchy: Yellow ligand carbons, Cyan pocket residue carbons
        cmd_api.color("cyan", f"({pocket_sel}) and elem C")
        cmd_api.color("yellow", f"({ligand_selection}) and elem C")
        cmd_api.set("stick_radius", 0.28, ligand_selection)
        cmd_api.set("stick_radius", 0.18, pocket_sel)

        # 5. Apply smooth continuous cavity surface on the full receptor
        cmd_api.set("surface_carve_selection", ligand_selection)
        cmd_api.set("surface_carve_cutoff", carve_cutoff)
        if surface_color:
            cmd_api.set("surface_color", surface_color, receptor_selection)
        cmd_api.set("transparency", transparency)
        cmd_api.set("two_sided_lighting", 1)
        cmd_api.show("surface", receptor_selection)

        # 6. Center and orient camera on pocket
        cmd_api.orient(ligand_selection)
        cmd_api.zoom(ligand_selection, 4.5)
    except Exception:
        pass


