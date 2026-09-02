# NeuroEdit

NeuroEdit is a standalone desktop video editor for preparing operative video for
conference, research, and educational use. It runs entirely on your own machine —
no video, audio, or patient content ever leaves the computer.

Current alpha release: [v0.5.7-alpha](https://github.com/v7sm25qk5v-ui/NeuroEdit/releases/tag/v0.5.7-alpha)

### What's new in v0.5.7-alpha

- Split Clip now uses iMovie-familiar Command-B, enforces each segment's source
  bounds, and ripple-updates downstream clips and the displayed total duration.
- Arrows and other annotations render on captured stills; the Brush creates
  editable freehand highlights in preview, saved projects, and exports.
- The tutorial's Rectangle step now visibly responds to the requested click and
  includes a hands-on freehand Brush exercise.
- Muted and zero-duration narration placeholders no longer trigger audio export
  or privacy-review behavior reserved for active narration.

## Features

- **Timeline editing** — smooth variable-frame-rate playback, bounded Split
  Clip with ripple trim/delete, drag-to-reorder with snapping, fades, chapter
  markers, zoom-to-fit, and iMovie-familiar Command-B, Space, and frame-step
  shortcuts.
- **Annotation tools** — rectangle, ellipse, arrow, text, and freehand brush /
  highlight overlays over video or captured stills, with per-anatomy label
  presets and a duplicate-at-playhead shortcut.
- **SAM segmentation (source builds)** — click-to-segment an anatomical structure
  and track it through the video. Runs locally on Apple Silicon (MPS) or CPU;
  weights are downloaded once from Hugging Face.
- **Privacy / PHI review** — a guided, resumable PHI review stepper, a redaction
  tool that burns opaque boxes over on-screen identifiers, metadata stripping on
  every export, a pre-export attestation checklist, and a configurable
  (non-cloud-synced) storage location.
- **Slides and stills** — title/body slides, image overlays, and "Take Still"
  frame capture that inherits redactions.
- **Captions** — generated from transcript segments, previewed on the canvas,
  burned in at export or exported as an SRT/VTT sidecar.
- **Export** — H.264 MP4 with resolution presets (a recommended preset is
  preselected from your source resolution and intended use), advanced CRF/fps/
  bitrate controls, export history, and a written export report next to each MP4.
- **Media import and project library** — Finder/File Explorer drag-and-drop,
  recent projects with thumbnails, durations, missing-media warnings, and search/sort.
- **Appearance** — Light, Dark, or System theme, chosen on first launch and
  switchable any time from View → Appearance.

## Install The Alpha

### macOS

Download `NeuroEdit-v0.5.7-alpha-macOS-unsigned.dmg` from the release page.
Open the DMG, drag `NeuroEdit.app` into Applications, then right-click the app
and choose `Open` for the first launch.

This alpha is unsigned and not notarized, so macOS may show a developer warning.
If macOS blocks launch, open `System Settings` -> `Privacy & Security`, choose
`Open Anyway`, then right-click `NeuroEdit.app` -> `Open` again.

### Windows

Download `NeuroEdit-v0.5.7-alpha-Windows-Setup.exe` from the release page on a
Windows PC. If SmartScreen warns, choose `More info` -> `Run anyway`, then follow
the installer.

The Windows installer is built by CI from the same source as macOS. Runtime UI
verification on Windows is still pending; testers should capture toolbar
screenshots at 100%, 125%, and 150% display scaling.

The downloadable alpha installers are editor-only and do not include the optional
SAM/PyTorch runtime. Use a source build with the `[sam]` extra for segmentation.

## Clinical Disclaimer

NeuroEdit is not a medical device, is not FDA-cleared, and is not intended for
diagnosis, treatment, or clinical decision-making. Users are responsible for
patient consent, institutional authorization, de-identification, PHI review, and
compliance with all applicable policies and laws before sharing any exported
video.

## Development

The active application lives in `desktop/`. See
[desktop/README.md](desktop/README.md) for the SAM3 setup and architecture, and
[desktop/CLAUDE.md](desktop/CLAUDE.md) for the full module map.

```bash
cd desktop
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"   # add ".[sam]" for SAM segmentation
python -m neuroedit_desktop
```

Run the quality checks (the release gate):

```bash
cd desktop
ruff check src tests scripts
python -m pytest tests/ -q
```

### QA tooling

- `python scripts/make_smoothness_fixture.py --register` — builds a synthetic
  test project (1080p + 4K clips, all annotation types, slides, captions, a
  missing-media case) for comparing performance across builds. No patient data.
- `python scripts/capture_baseline_screenshots.py` — renders the window, panels,
  and dialogs offscreen to `desktop/qa/screenshots/` (gitignored) for visual
  regression comparison.
- Help → **Performance Diagnostics (Developer)** (or `NEUROEDIT_DIAGNOSTICS=1`)
  logs paint/load/export/SAM timings to a per-user log outside any project
  folder — counts and durations only, never media paths or project names.

Design and QA references live in `desktop/docs/`:
[DESIGN_LANGUAGE.md](desktop/docs/DESIGN_LANGUAGE.md),
[ASSET_CHECKLIST.md](desktop/docs/ASSET_CHECKLIST.md), and
[VISUAL_QA_CHECKLIST.md](desktop/docs/VISUAL_QA_CHECKLIST.md).
