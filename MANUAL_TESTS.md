# Release manual tests

Run the app, load a structure that contains a ligand, and try the following in order.

1. **Typed manipulation:** “Show the ligand as sticks and color it yellow.” Confirm the live viewport changes.
2. **Multi-turn reference:** “Now select and show residues within 5 angstroms of it.” Confirm the model uses the ligand from the prior turn and leaves a named selection.
3. **Voice:** Click the microphone once and say “Color chain A cyan.” Stop speaking; confirm recording ends automatically after about one second, the transcript is sent, and the scene changes. Confirm the stop square still ends recording manually.
4. **Error recovery:** Ask “First try `cmd.not_a_real_method()` and then recover by coloring chain A green.” Choose **⋯ → Show Command Log** and confirm the API error is returned to the model and a valid follow-up call succeeds.
5. **No visual inspection:** Ask to frame a selected site. Confirm the command log uses `orient`, with no screenshot capture or repeated cosmetic adjustments. Even an explicit request for visual inspection must not capture/send an image.
6. **Files:** Drag a `.pdb`, `.cif`, `.mmcif`, or `.pse` onto the chat panel. Confirm it loads into the current session and is immediately available in the next prompt.
7. **Public fetch:** Ask “Download human hemoglobin.” Confirm the agent resolves a suitable public PDB accession, calls `cmd.fetch`, and loads it into the live scene.

## Windows release checks

- **Clean Source Checkout**: Verify that the checkout contains no `.env` files, build caches, test outputs, or recorded audio files.
- **Credential Storage**: Save an API key via the GUI dialog, quit PyMOL, and relaunch. Confirm the key persists via Windows Credential Manager without prompting again.
- **Launcher Integrity**: Test `run.bat`, `run.ps1`, and the desktop shortcut created by `create_shortcut.py`. Confirm PyMOL launches cleanly with the chat dock attached.
- **Audio & Voice**: Confirm microphone recording, automatic silence cutoff, Whisper transcription, and manual interrupt functionality using actual speech.
- **Confidentiality & Anonymization Audit**: Before any release or commit, verify that zero real experimental molecule IDs, internal project codes, or local host filesystem paths exist in documentation, prompts, tests, or code.
