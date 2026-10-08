# PyMOL Flow

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6.svg)](https://microsoft.com/windows)
[![Python: 3.9+](https://img.shields.io/badge/Python-3.9%2B-brightgreen.svg)](https://python.org)
[![PyMOL: 2.x | 3.x](https://img.shields.io/badge/PyMOL-2.x%20%7C%203.x-orange.svg)](https://pymol.org)
[![Tests: 131 Passed](https://img.shields.io/badge/Tests-131%20Passed-success.svg)](tests/)

**PyMOL Flow** is a Windows-native AI copilot embedded directly into PyMOL for structural biology and computer-aided drug design (CADD). It translates natural language, multimodal image inputs, and speech into validated PyMOL workflows, providing automated pocket interaction profiling, conformational displacement heatmaps, AlphaFold pLDDT confidence analysis, and publication-grade molecular rendering.

---

## Core Capabilities

| Module | Function | Description |
| :--- | :--- | :--- |
| **Intelligent Alignment** | `align_structures` | Autonomously aligns monomers, dimers, trimers, and oligomers; resolves C2/C3 rotational symmetry permutations, interfaces ligand/pocket awareness, and handles uneven chain lengths or flexible tails. |
| **Multimodal Vision** | `image_utils` / `ask(..., images)` | Ingests structural biology figures, docking snapshots, clipboard screenshots (Ctrl+V), and live PyMOL viewport captures for visual reasoning. |
| **Viewport Reactivity** | `get_viewport_selection_summary` | Real-time 3D selection awareness (`sele`); dynamically surfaces residue/ligand action pills in the UI upon viewport click events. |
| **Conformation Analysis** | `compare_conformations` | Calculates Cα and pocket-level RMSD, isolates active-site residues, and renders a 3D continuous displacement vector heatmap (blue-white-red spectrum on B-factors). |
| **Model Confidence** | `visualize_plddt` | Maps official AlphaFold & ESMFold 4-tier confidence intervals (pLDDT >90, 70–90, 50–70, <50) with automated disorder loop filtering. |
| **Pocket Profiling** | `analyze_interactions` | Detects non-covalent contacts (hydrogen bonds, salt bridges, hydrophobic contacts) and outputs structured residue contact tables. |
| **Publication Presets** | `apply_publication_preset` | Configures journal-grade ray tracing, lighting, and shading (`nature`, `cell_outline`, `cryo_pocket`, `keynote_dark`). |
| **Batch Ingestion** | `load_local_structures` | Loads trajectories and folders (`.pdb`, `.cif`, `.mmcif`, `.sdf`, `.mol2`, `.pse`) with natural sorting and object name sanitization. |

### Technical Architecture

- **Multimodal Visual Grounding**: Direct clipboard image pasting (`Ctrl+V`), drag-and-drop image import, and native viewport snapshot extraction (`cmd.png`) automatically encode and downscale visual context into OpenAI-compatible `image_url` data structures.
- **Bidirectional 3D Viewport Reactivity**: Background Qt event polling tracks mouse clicks in PyMOL's 3D canvas, immediately transforming quick action pills for inspected residues or ligands.
- **Prompt Caching & Conversation Compaction**: Invariant system prefix structures, historical scene dump stripping, automated tool output compaction, and image payload token placeholders maximize prompt cache hits and avoid payload bloating.
- **Sandboxed Execution Engine**: Python AST validation restricts unsafe system calls (`os`, `sys`, `subprocess`, unauthorized socket/network access) prior to execution.
- **Fail-Safe Circuit Breaker**: Bounded tool execution turns (`MAX_TOOL_ROUNDS = 4`) prevent runaway retries. Visual operations are automatically protected by exception recovery.
- **Enterprise Credential Storage**: Native Windows Credential Manager integration (`io.pymolflow.credentials`) ensures API keys are never written to plain-text sessions or Git history.
- **Windows-Native Audio Capture**: Pure-Python QtMultimedia recorder with voice activity detection (VAD), silence cutoff, and streaming transcription.

---

## Directory Structure

```text
pymol_flow/
├── __init__.py           # Plugin registration and Qt dock widget mounting
├── agent/                # Multi-turn conversational loop, token caching, circuit breaker
│   ├── core.py           # Agent loop, multimodal streaming, and tool dispatch
│   ├── prompts.py        # System prompt and PyMOL selection algebra rules
│   ├── router.py         # Query classifier (fast geometric commands vs. deep reasoning)
│   └── tools.py          # Tool definitions and JSON schemas
├── executor/             # Sandboxed Python execution engine
│   ├── core.py           # AST validation, stdout interception, and error diagnostics
│   ├── result.py         # Execution data models
│   ├── safety.py         # AST syntax validator
│   └── scene.py          # Viewport introspection and object census
├── analysis/             # Structural biology and CADD calculation modules
│   ├── align.py          # Intelligent multimer alignment, symmetry detection & chain mapping
│   ├── conformation.py   # Pocket RMSD and 3D B-factor displacement heatmap
│   ├── interactions.py   # Pocket non-covalent contact profiler
│   ├── loader.py         # Batch file loader with natural sorting
│   └── presets.py        # Journal rendering presets and AlphaFold pLDDT profiler
├── voice/                # Audio recording and speech processing
│   ├── audio.py          # Background recording process manager
│   └── speech.py         # Voice queue and TTS output
├── api_client.py         # Unified DashScope / OpenAI streaming HTTP client
├── config.py             # Configuration and environment variable loader
├── image_utils.py        # Image encoding, downscaling, and PyMOL viewport capture
├── keychain.py           # Windows Credential Manager ctypes interface
└── ui.py                 # PyMOL Qt dock widget, history renderer, attachment preview bar
```
```

---

## Installation

### Prerequisites
- Windows 10 or 11 (64-bit).
- PyMOL 2.x or 3.x (Open-source Conda build or Schrödinger PyMOL).
- Python environment requirements:
  ```cmd
  pip install openai Pillow
  ```

### Quick Launch
- **Command Prompt**: `run.bat`
- **PowerShell**: `.\run.ps1`
- **Desktop Shortcut**: Run `create_shortcut.bat` (or `python create_shortcut.py`) to generate a silent desktop shortcut.

### Permanent Plugin Installation
To auto-load PyMOL Flow whenever PyMOL starts:
```cmd
python install_plugin.py
```
To uninstall:
```cmd
python install_plugin.py --uninstall
```

---

## Configuration

### 1. In-App Setup
Click the **⋯** menu in the dock widget and select **API Key Settings**. The key is stored securely in the Windows Credential Manager under `io.pymolflow.credentials`.

### 2. Environment Variables (.env)
Create a `.env` file in the workspace or `%USERPROFILE%\.pymol-flow\.env`:
```ini
# Alibaba Cloud DashScope (Default)
DASHSCOPE_API_KEY=sk-...
DASHSCOPE_MODEL=qwen3.8-flash

# OpenAI Alternative
# OPENAI_API_KEY=sk-...
# OPENAI_MODEL=gpt-4o
```

---

## Usage Examples

### 1. Visual Representations & Pocket Views
```text
"Show the protein as cartoon, color chains distinctly, and display organic ligands as sticks."
"Highlight binding site residues within 4.0 angstroms of the ligand with yellow sticks."
```

### 2. Conformational Comparison & Displacement Heatmap
```text
"Compare conformations of model_1 and model_2, calculate pocket RMSD, and color by displacement heatmap."
"Show top displaced residues between model_1 and model_2 around the active site."
```

### 3. AlphaFold / ESMFold pLDDT Profiling
```text
"Analyze pLDDT confidence scores for model_1 and apply the AlphaFold 4-color spectrum."
"Trim disordered flexible loops with pLDDT below 50 for model_1."
```

### 4. Non-Covalent Interaction Analysis
```text
"Analyze interactions between ligand_a and the surrounding receptor pocket."
"Identify hydrogen bonds and salt bridges in the binding site."
```

### 5. Publication-Grade Rendering
```text
"Apply publication preset 'nature' with clean lighting and white background."
"Switch to 'cell_outline' cell-shading preset with distinct silhouettes."
"Apply 'keynote_dark' style for presentation slides."
```

### 6. Batch Structure Import
```text
"Batch load all docking poses from C:\path\to\docking_output."
```
*(Folders and files can also be dragged directly into the chat window).*

### 7. Multimodal Visual Input & Figure Analysis
- **Clipboard Paste (`Ctrl+V`)**: Take a screenshot of a paper figure or pocket snapshot and press `Ctrl+V` in the chat window to attach it immediately.
- **Drag & Drop**: Drag image files (`.png`, `.jpg`, `.webp`) straight into the dock panel.
- **Image Button (`🖼`)**: Click to choose image files, paste from clipboard, or capture the current PyMOL 3D viewport in one click (`📸 Capture PyMOL Viewport`).
```text
"Inspect the pocket residues indicated in this figure and display them as sticks in the active structure."
"Compare the ligand binding pose in this image with our docked conformation."
```

---

## Verification

Execute the test suite:
```cmd
python -m unittest discover -s tests -v
```
All 131 automated tests validate AST security sandboxing, multimodal image handling, multi-turn agent logic, coordinate calculations, publication presets, and credential management.

---

## Security & Data Privacy

- **Non-Destructive AST Sandbox**: Dangerous system calls (`os`, `sys`, `subprocess`, `open`), PyMOL process exits (`cmd.quit`, `cmd.exit`), session resets (`cmd.reinitialize`), and bulk scene wipeouts (`cmd.delete('all')`, `cmd.remove('all')`) are strictly blocked by both static AST inspection and runtime proxy barriers.
- **Least-Privilege System Boundaries**: Model operations are restricted strictly to user-specified target objects, leaving existing workspace models untouched.
- **Data Anonymization**: Experimental identifiers, internal project codes, and proprietary filesystem paths are strictly quarantined from public code and documentation.
- **Hardware-Isolated Credentials**: API keys are securely anchored in Windows Credential Manager (`advapi32.dll`), isolated from environment variables and config files.
- **Git Quarantine**: Local configurations (`.env`), rule sets, and session caches are permanently excluded via `.gitignore`.

---

## License

Released under the [MIT License](LICENSE).
