# NeuroEdit Desktop

The active NeuroEdit application: a native, cross-platform (macOS + Windows)
desktop video editor built from one source tree. Memory-heavy work runs off the
UI thread so the app stays responsive while editing operative video.

- Native shell: PySide6
- Video playback: Qt Multimedia rendering with a monotonic timeline clock for
  smooth constant- and variable-frame-rate media
- Media linking: individual-file dialogs, an external-drive folder picker,
  Media Explorer double-click, or Finder/File Explorer drag-and-drop. Video
  sources stay in place and projects store references instead of copying them.
- Slides: full-frame slides pause video; transparent overlay slides remain
  composited above continuously playing video
- Project persistence: project-folder JSON plus external mask/audio/video assets
- SAM processing: separate Python backend boundary so SAM3 tracking runs outside
  the UI thread
- Identity: theme-aware SVG aperture-and-scalpel mark in-app, with generated
  `.icns` and `.ico` assets for packaged builds

The full module map and architecture notes (rendering pipeline, undo/redo,
threading, PHI/redaction safeguards) are in [CLAUDE.md](CLAUDE.md).

## Timeline controls

- Drag a video clip left or right to preview a new sequence position;
  neighboring clips close together during this explicit reorder. Opening or
  refreshing a saved project preserves its existing clip positions and gaps.
  Release commits the visible order, Escape cancels,
  and Undo restores the entire move. Hold near either timeline edge to scroll
  while dragging.
- Full-frame slides, including frames made with **Take Still**, occupy timeline
  time and keep their interval between video clips. Explicit reordering only
  removes time in which no video or full-frame slide is visible. Video clips
  remain a magnetic storyline when Snap is off; Snap controls nearby-edge,
  playhead, and marker alignment for other dragged blocks.
- Mouse-wheel and trackpad scrolling pan through time. Hold Shift while
  scrolling to move vertically through stacked label rows.
- Overlapping labels occupy separate rows. Disabled labels say **Hidden**;
  hover a label for its full name and time range.
- Split pieces retain their source name. Splitting older continuation pieces
  also removes the accumulated `(cont.)` suffixes.
- Playback reuses the decoder across same-file cuts and holds the last frame
  while another video loads. Different files can still have a brief loading
  pause; the preview no longer deliberately clears between them.

## Run

Use Python 3.12 or 3.13. For SAM3 work, Python 3.12 is the safer target because
the upstream SAM stack is Python/PyTorch-first.

```bash
cd desktop
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,sam]"
python -m neuroedit_desktop
```

If `python3.12` is not installed, Python 3.13 can launch the UI shell:

```bash
cd desktop
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev,sam]"
python -m neuroedit_desktop
```

The UI shell and editing workflow run without the SAM stack — install
`-e ".[dev]"` instead of `-e ".[sam]"` to skip the ~1.6 GB PyTorch download;
SAM features simply no-op until the `[sam]` extra is installed.

## Quality checks

The [2026-09-05 codebase review](docs/CODEBASE_REVIEW_2026-09-05.md) records
stability and export-timing fixes, their regression coverage, and remaining
runtime verification work.

```bash
cd desktop
ruff check src tests scripts
python -m pytest tests/ -q
```

For manual smoothness QA, build the synthetic no-PHI fixture once:

```bash
python scripts/make_smoothness_fixture.py --register
```

Then open it from Project Library with Help → Performance Diagnostics enabled
to compare scrubbing, annotation dragging, panel switching, and export startup
across builds.

## SAM 3 Direction

The desktop backend uses Hugging Face Transformers' `facebook/sam3` tracker first:

- Single-frame masks use `Sam3TrackerModel`.
- Video propagation uses `Sam3TrackerVideoModel` and a stateful video inference session.
- The older `facebook/sam-vit-base` path remains as a fallback if SAM3 weights are not available.

The SAM3 weights are gated on Hugging Face. Request access to `facebook/sam3`,
then authenticate inside the virtual environment:

```bash
source .venv/bin/activate
hf auth login
```

For Apple Silicon, the app keeps SAM work on a background worker:

- UI process stays responsive and keeps autosaving.
- SAM worker owns PyTorch/MPS or CPU memory.
- Masks are streamed back as files or compressed arrays.
- If SAM fails or runs out of memory, the project remains intact.
