# NeuroEdit Desktop

This is the macOS-first Python migration path for the current browser app.

The goal is to keep the existing workflow while moving memory-heavy work out of the browser:

- Native shell: PySide6
- Video playback: Qt Multimedia first, with OpenCV/PyAV available for frame extraction
- Project persistence: project-folder JSON plus external mask/audio/video assets
- SAM processing: separate Python backend boundary so SAM3 tracking can run outside the UI thread

## Run

Use Python 3.12 or 3.13. For SAM3 work, Python 3.12 is the safer target because
the upstream SAM stack is Python/PyTorch-first.

```bash
cd desktop
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[sam]"
python -m neuroedit_desktop
```

If `python3.12` is not installed, Python 3.13 can launch the UI shell:

```bash
cd desktop
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[sam]"
python -m neuroedit_desktop
```

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
