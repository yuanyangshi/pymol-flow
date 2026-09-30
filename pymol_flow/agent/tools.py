"""Tool definitions and fast confirmation validation for PyMOL Chat Agent."""

from __future__ import annotations

import ast

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_pymol_python",
            "description": (
                "Execute Python in the live PyMOL session with `from pymol import cmd` available. "
                "Returns stdout or an error."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": (
                            "Python using pymol.cmd directly. cmd.fetch is available for "
                            "requested public structures."
                        ),
                    },
                    "success_reply": {
                        "type": ["string", "null"],
                        "description": (
                            "Short confirmation for a complete simple visual change, used only "
                            "after success. Otherwise null."
                        ),
                    },
                },
                "required": ["code", "success_reply"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_protein_ligand_interactions",
            "description": (
                "Perform quantitative non-covalent protein-ligand interaction profiling (PLIP-style). "
                "Calculates hydrogen bonds, salt bridges, hydrophobic contacts, aromatic/pi interactions, and halogen bonds. "
                "Automatically styles sticks, colors, dashed measurement lines, residue labels, and orients to the pocket in PyMOL, "
                "and returns a structured quantitative Markdown report table."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ligand": {
                        "type": "string",
                        "description": (
                            "PyMOL selection for the ligand. Defaults to 'organic'. "
                            "Can be specific, e.g. 'resn LIG' or 'model 1abc and organic'."
                        ),
                    },
                    "receptor": {
                        "type": "string",
                        "description": "PyMOL selection for the receptor protein. Defaults to 'polymer.protein'.",
                    },
                    "cutoff": {
                        "type": "number",
                        "description": "Pocket definition radius in Angstroms. Defaults to 4.5.",
                    },
                    "visualize": {
                        "type": "boolean",
                        "description": "Whether to render representations, dashed lines, and labels in PyMOL. Defaults to true.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_local_structures",
            "description": (
                "Safely scan and load molecular structure files (.pdb, .cif, .mmcif, .sdf, .mol2, .pse, .pdbqt) "
                "from a local file path or directory into the PyMOL session. "
                "Supports batch loading from directories (e.g. AlphaFold, docking, or screening result folders) "
                "with optional filename pattern filtering."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "The absolute or relative local filesystem path to a structure file "
                            "or directory containing structure files."
                        ),
                    },
                    "pattern": {
                        "type": "string",
                        "description": (
                            "Optional glob pattern to filter files when loading from a directory "
                            "(e.g. '*.pdb', '*model*.cif', '*.sdf'). Defaults to '*' (all supported formats)."
                        ),
                    },
                    "max_files": {
                        "type": "integer",
                        "description": (
                            "Maximum number of structure files to load into PyMOL from a directory. "
                            "Defaults to 20 to maintain high performance."
                        ),
                    },
                    "clean_scene": {
                        "type": "boolean",
                        "description": (
                            "Whether to clear the current scene before loading. Defaults to false."
                        ),
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_conformations",
            "description": (
                "Compare two protein conformations (e.g. WT vs Mutant, Apo vs Holo, or AlphaFold models). "
                "Calculates overall Cα RMSD, local pocket RMSD, identifies top shifted residues, "
                "and generates a blue-white-red residue displacement heatmap spectrum in PyMOL."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mobile_object": {
                        "type": "string",
                        "description": "Name of the mobile PyMOL object to superimpose and measure displacement on.",
                    },
                    "target_object": {
                        "type": "string",
                        "description": "Name of the reference/target PyMOL object.",
                    },
                    "pocket_selection": {
                        "type": "string",
                        "description": "Optional selection defining the pocket of interest (e.g. 'organic' or 'resi 50-75'). Defaults to 'organic'.",
                    },
                    "cutoff": {
                        "type": "number",
                        "description": "Distance cutoff in Angstroms around pocket_selection to define the pocket residues. Defaults to 5.0.",
                    },
                    "apply_heatmap": {
                        "type": "boolean",
                        "description": "Whether to color mobile_object with a B-factor displacement heatmap (Blue=0Å, Red>=2.5Å). Defaults to true.",
                    },
                },
                "required": ["mobile_object", "target_object"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_publication_preset",
            "description": (
                "Apply high-end publication-grade visual and rendering presets to the PyMOL session. "
                "Configures lighting, ambient occlusion, shadows, sampling, and backgrounds."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "style": {
                        "type": "string",
                        "enum": ["nature", "cell_outline", "cryo_pocket", "keynote_dark"],
                        "description": (
                            "The publication aesthetic style: "
                            "'nature' (soft diffuse lighting, white background, high-sampling cartoon), "
                            "'cell_outline' (Cell Press comic/editorial black border outlines), "
                            "'cryo_pocket' (translucent pocket surface enclosing high-contrast sticks), "
                            "'keynote_dark' (sleek OLED dark mode with luminescent secondary structure accents)."
                        ),
                    },
                    "selection": {
                        "type": "string",
                        "description": "PyMOL selection to apply surface or styling on. Defaults to 'all'.",
                    },
                },
                "required": ["style"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "visualize_plddt",
            "description": (
                "Analyze and apply official AlphaFold / ESMFold pLDDT confidence spectrum coloring. "
                "Categorizes B-factors into Very High (>90 dark blue), Confident (70-90 light blue), "
                "Low (50-70 yellow), and Very Low (<50 orange). Optionally trims or hides disordered flexible loops."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selection": {
                        "type": "string",
                        "description": "PyMOL selection containing AlphaFold/ESMFold model atoms. Defaults to 'all'.",
                    },
                    "hide_disordered": {
                        "type": "boolean",
                        "description": "Whether to hide low-confidence disordered loops (pLDDT < 50) to highlight the core fold. Defaults to false.",
                    },
                    "min_plddt": {
                        "type": "number",
                        "description": "Threshold below which loops are considered disordered and hidden. Defaults to 50.0.",
                    },
                },
            },
        },
    },
]


def can_confirm_directly(code: str) -> bool:
    """Conservatively limit the shortcut; other code still runs normally."""
    allowed = {
        "color", "show", "hide", "select", "set", "label", "zoom", "orient",
        "center", "turn", "move", "bg_color", "fetch", "count_atoms",
        "align", "super", "cealign", "pair_fit",
    }
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False

    def checks_nonempty(node: ast.AST) -> bool:
        if not isinstance(node, ast.Assert) or not isinstance(node.test, ast.Compare):
            return False
        check = node.test
        call = check.left
        return (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "cmd"
            and call.func.attr == "count_atoms"
            and len(check.ops) == 1
            and isinstance(check.ops[0], ast.Gt)
            and isinstance(check.comparators[0], ast.Constant)
            and check.comparators[0].value == 0
        )

    if not any(checks_nonempty(node) for node in tree.body):
        return False

    for node in tree.body:
        if not isinstance(node, (ast.ImportFrom, ast.Expr, ast.Assert)):
            return False

    changed = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if not (
                isinstance(fn, ast.Attribute)
                and isinstance(fn.value, ast.Name)
                and fn.value.id == "cmd"
                and fn.attr in allowed
            ):
                return False
            if fn.attr == "fetch" and not any(
                kw.arg == "async_"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value == 0
                for kw in node.keywords
            ):
                return False
            changed = changed or fn.attr != "count_atoms"
    return changed
