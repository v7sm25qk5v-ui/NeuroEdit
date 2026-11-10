# NeuroEdit

NeuroEdit is a standalone desktop video editor for preparing operative video for
conference, research, and educational use. Editing and export run locally;
NeuroEdit does not upload video or audio to a cloud editing service.

Current alpha: [v0.5.14-alpha](https://github.com/v7sm25qk5v-ui/NeuroEdit/releases/tag/v0.5.14-alpha)

### What's new in v0.5.14-alpha

- Added narration and music can be heard on the editing timeline, including
  seeking, overlapping tracks, and still intervals. Recordings retain the
  timeline position where Record was pressed. Closing is blocked while recording
  or finalization is pending, so narration can finish before saving and leaving.
- **File → Relink Unavailable Media** repairs a selected video, image, narration,
  or slide-image reference while preserving edits and requiring fresh privacy
  review. Split references are repaired individually.
- Video metadata imports run in the background, preserve selection order, and
  reject cancelled or stale results. Failed audio probes no longer create
  guessed five-second tracks.
- Single-frame SAM cancellation discards cancelled results. Import/export labels
  fit their controls, and screenshot tooling isolates preferences and verifies
  the panel being captured.

The retained security findings are tracked in [SECURITY_FIXES.md](SECURITY_FIXES.md).
The original scan had partial coverage; these fixes do not constitute a completed audit.

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
- **Narration and audio** — record or import tracks, preview them on the timeline,
  and mix them into exports with per-track timing and volume.
- **Captions** — generated from transcript segments, previewed on the canvas,
  burned in at export or exported as an SRT/VTT sidecar.
- **Export** — H.264 MP4 with resolution presets (a recommended preset is
  preselected from your source resolution and intended use), advanced CRF/fps/
  bitrate controls, export history, and a written export report next to each MP4.
- **Media linking and project library** — add individual files or link a video
  folder on an external drive while keeping the source files in place. Finder/
  File Explorer drag-and-drop, a recent-project library with neutral previews, durations,
  missing-media warnings, explicit relinking, and search/sort are also supported.
- **Appearance** — Light, Dark, or System theme, chosen on first launch and
  switchable any time from View → Appearance.

## Install

### macOS

Download `NeuroEdit-v0.5.14-alpha-macOS-unsigned.dmg` from the release page.
Open the DMG, drag `NeuroEdit.app` into Applications, then right-click the app
and choose `Open` for the first launch.

This build is unsigned and not notarized, so macOS may show a developer warning.
If macOS blocks launch, open `System Settings` -> `Privacy & Security`, choose
`Open Anyway`, then right-click `NeuroEdit.app` -> `Open` again.

### Windows

Download `NeuroEdit-v0.5.14-alpha-Windows-Setup.exe` from the release page on a
Windows PC. If SmartScreen warns, choose `More info` -> `Run anyway`, then follow
the installer.

The Windows installer is built by CI from the same source as macOS. Runtime UI
verification on Windows is still pending; testers should capture toolbar
screenshots at 100%, 125%, and 150% display scaling.

The downloadable installers are editor-only and do not include the optional
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
