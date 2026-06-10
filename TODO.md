# NeuroEdit Roadmap TODO

This roadmap tracks product work after the current alpha baseline. Keep items
small enough to verify, and move completed implementation details into release
notes or docs instead of expanding this file indefinitely.

Ordering rationale: ship a verified alpha first (P0), then close the editing
gaps users hit in every session (P1), then make SAM results feel like real
project assets (P2) since SAM is the differentiating feature, then deepen the
PHI story (P3) which is the trust-critical feature for clinical users. Captions
and export polish (P4) widen the audience. Stryker/DICOM (P5) is the largest
bet and stays parked until sample data and a design pass exist.

## P0 — Unblock and ship the current alpha

- [ ] **Fix the dev environment (blocker).** `desktop/.venv` →
  `~/Documents/Claude/venv` is broken: its interpreter symlinks point at a
  Python 3.13 framework that has been uninstalled
  (`/Library/Frameworks/Python.framework/Versions/3.13` is gone). The app and
  test suite cannot run. Reinstall Python 3.12 (preferred per CLAUDE.md) or
  3.13, then recreate the venv at the same location and
  `pip install -e ".[sam]"`. Do not relocate the venv (intentional iCloud
  placement).
- [ ] Run `ruff check src tests` and `python -m pytest tests/ -q` once the venv
  is restored — the 2026-06-09 review session changed exporter/undo/SAM paths
  and was verified by lint + syntax check only.
- [ ] Commit the working-tree changes (review-session fixes + Project Library +
  annotation workflow) and tag `v0.2.3-alpha` (bump
  `neuroedit_desktop.__version__` if the tag name differs).
- [ ] Verify the generated macOS DMG launches, imports media, plays/scrubs, and
  exports an MP4 plus `.export-report.txt`.
- [ ] Decide when to make the GitHub repository private (recommended —
  commercialization intent; see HANDOFF).
- [ ] Decide when to add Windows Authenticode signing and macOS Developer ID
  signing/notarization.

## P1 — Timeline editing gaps (every-session friction)

- [ ] Add a distinct selected-state outline in each of `_paint_video_blocks`,
  `_paint_audio_blocks`, `_paint_slide_blocks`, and `_paint_markers`
  (`editor_panels.py`); drive from a single `selected_track_item` state.
- [ ] Add marker edit/delete support.
- [ ] Add clip rename support.
- [ ] Add zoom-to-fit for the whole timeline.
- [ ] Add snap-to-playhead for clip, slide, marker, and audio positioning.
- [ ] Acceptance: a user can trim, rename, mark, and navigate a simple case video
  without needing hidden shortcuts.

## P2 — SAM and mask workflow (the differentiator)

- [ ] Add named mask objects so users can distinguish multiple segmentations.
- [ ] Add delete/regenerate controls for masks and propagated masks (orphaned
  mask PNGs in `masks/` should be cleaned up when their annotation is deleted).
- [ ] Add a status row in the SAM panel showing last propagation start, end, frames
  processed, and result (success / canceled / error); persist last-run in the
  project so it survives reopening.
- [ ] When `SamBackend.probe()` returns missing, replace the SAM panel body with a
  one-screen explainer plus 'Install Dependencies' / 'Download Weights' buttons
  that route to the existing onboarding flow.
- [ ] Let the user choose the propagation window (start/duration) instead of the
  hardcoded 5 s from the playhead (`_run_propagation` in `main_window.py`).
- [ ] Use the annotation's color for saved mask overlays — `_save_mask_rgba`
  hardcodes cyan, so the SAM panel color choice currently has no effect on masks.
- [ ] Acceptance: SAM results feel like editable project assets, not one-off
  hidden outputs.

## P3 — Privacy and PHI review (trust-critical)

- [ ] Add a guided PHI review mode that steps through timeline sections needing
  review.
- [ ] Show a modal pre-export checklist that requires explicit acknowledgement of
  PHI review, de-identification, and consent before the export job starts. Write
  the same flags to the export report.
- [ ] Add an explicit `audio_reviewed_for_phi` flag to project state, surfaced as
  a checkbox in the audio panel; warn on export-with-audio if unset (do not block).
- [ ] Add 'Reveal Report' and 'Reveal MP4' buttons to the post-export dialog
  (`QDesktopServices.openUrl`).
- [ ] Add a configurable default storage location. Today
  `default_project_root()` hardcodes `~/Documents/NeuroEdit/Autosave/`, which on
  macOS is iCloud-synced when "Desktop & Documents Folders" is on (and OneDrive
  on Windows) — so PHI in `masks/`/`stills/` of an unsaved scratch project can
  auto-upload to a personal cloud account. Add a one-time "Where NeuroEdit
  stores projects" preference (persist in `QSettings("NeuroEdit", "Desktop")`),
  read it in `default_project_root()`, and surface a first-run prompt that
  recommends a non-cloud-synced folder (e.g. `~/Library/Application
  Support/NeuroEdit/`). Per-project Save As already lets users choose a
  destination; this fixes only the pre-Save-As scratch window.
- [ ] Acceptance: before export, the app makes unresolved visual/audio PHI risks
  visible and hard to miss, and PHI never lands in a cloud-synced folder without
  the user having chosen it.

## P4 — Captions, transcript, and export polish

- [ ] Generate captions from transcript segments.
- [ ] Add caption preview on the video canvas.
- [ ] Add caption style controls that are simple and export-safe.
- [ ] Export captions as SRT and WebVTT.
- [ ] Add export history for recent output files.
- [ ] Add a collapsible 'Advanced' group to `ExportDialog` that exposes CRF, fps,
  target width/height, and audio codec. Defaults stay glued to the selected preset.
- [ ] Convert `ALPHA_QA_CHECKLIST.md` from a generic template to a per-tag file:
  include the tag SHA, fill date, and results columns. Commit one per release.
- [ ] Evaluate Intel Mac build support if testers need it.
- [ ] Acceptance: a user can import or write transcript segments, preview them as
  captions, export caption files, and find previous exports without digging.

## Quality and regression coverage (continuous — pair with each phase)

- [ ] Add regression tests for the bugs fixed in the 2026-06-09 review:
  (1) deleting an audio track must not delete unattached transcript segments;
  (2) timeline Cut must preserve `media_type`/fade fields on the right piece;
  (3) `ProjectExporter._duration()` must equal content end (no black tail);
  (4) `ProjectState.from_dict` must tolerate unknown keys from newer saves.
- [ ] Add a test that calls `MainWindow()` headlessly under
  `QT_QPA_PLATFORM=offscreen`, asserts construction, then switches each of the
  5 right-panel tabs and asserts no exception.
- [ ] Add tests for autosave restore and new-project behavior.
- [ ] Add two exporter tests: (1) `ExportSettings()` defaults produce no audio
  stream; (2) export writes a `*.export-report.txt` with the PHI/consent flag block.
- [ ] Add a regression test that constructs `MainWindow` headlessly at 1085×600,
  1280×720, and 1920×1080 and asserts no horizontal scrollbar on the right panel.
- [ ] Keep `ruff check src tests` and `python -m pytest tests/ -q` green before
  every release tag.

## P5 — Stryker Imaging / Video Integration (parked: needs sample data)

These items target compatibility with Stryker's surgical imaging stack
(1688 AIM 4K, SDC4K / SDC3, SPY-PHI, Connected OR Hub, Studio3). There is
no public Stryker SDK; integration is via DICOM, FTP/SMB drop zones, and
shared file formats. **Before building any of this, acquire sample SDC4K /
Connected OR Hub output files** — banner positions, filename conventions, and
bundle formats below are all assumptions until verified against real captures.

### Ingest from Stryker hardware

- [ ] Read DICOM-encapsulated video (Video Endoscopic Image Storage SOP and
  Secondary Capture Multiframe) so files exported from PACS or written by the
  Connected OR Hub can be imported directly without conversion.
- [ ] Auto-populate project metadata (patient ID, study date, procedure, surgeon)
  from the DICOM header on import — gated by an explicit "import PHI" confirmation.
- [ ] Recognize Stryker SDC filename / folder conventions on import and pre-fill
  the project name and tags.
- [ ] Detect 4K vs 1080p source resolution on import and default the export preset
  accordingly.

### Multi-stream / fluorescence workflows

- [ ] Synchronized multi-stream timeline: when an AIM / SPY-PHI case has parallel
  white-light + ICG fluorescence recordings, show them as stacked tracks with a
  locked playhead and let the user pick which stream is primary per timeline segment.
- [ ] Fluorescence-aware annotation preset: a "Fluorescence finding" label group
  with high-contrast colors that read against the green ICG overlay or the
  grayscale NIR background.
- [ ] Picture-in-picture / side-by-side export composer for white-light +
  fluorescence views in a single output MP4 (common in case-review decks).
- [ ] Import AIM mode-change markers if the SDC writes a sidecar log listing
  imaging-mode timestamps; surface them as timeline chapters automatically.

### PHI handling for Stryker output

- [ ] One-click "Redact Stryker patient banner" preset that covers the fixed
  top-left/right banner region the Connected OR Hub burns into recorded video.
  Verify position against several SDC4K sample files before shipping defaults.
- [ ] Patient-ID consistency check: when multiple media files are added to a
  project, compare DICOM Patient ID tags and warn if they differ.

### DICOM export (compatible with Stryker's PACS path)

- [ ] Export the edited MP4 as a DICOM Video Endoscopic Image Storage SOP
  instance, preserving the original Study / Series / Patient identifiers, so
  the redacted edit can be pushed back into the same PACS study.
- [ ] Emit a DICOM Structured Report (SR) sidecar containing the annotation list
  (label, timestamp range, observer, free text) so PACS viewers can render
  observations alongside the video.
- [ ] Optionally emit annotations as a DICOM Greyscale Softcopy Presentation State
  (GSPS) object so PACS can overlay them on the original pixels without baking
  them into the encoded stream.

### Hospital workflow integration

- [ ] Modality Worklist (MWL) client: query a configured DICOM MWL endpoint to
  pull the day's scheduled cases and pre-create projects with surgeon, procedure,
  and scheduled time pre-filled.
- [ ] Configurable "publish to" destination — FTP, SMB share, or DICOM Store SCU
  — mirroring the targets the Connected OR Hub already writes to.
- [ ] HL7 FHIR `Media` resource export (for sites with FHIR EMRs) so the finished
  edit can be referenced from the patient's chart.

### Studio3 / MyPatient Hub interop

- [ ] Read Studio3 case bundles (the archive format MyPatient Hub downloads) and
  import them as NeuroEdit projects. Depends on documenting the bundle structure
  from sample files — lower priority until sample data is available.

### Acceptance

A surgical-case clip captured on a Stryker 1688 / SDC4K can be imported into
NeuroEdit, redacted (banner + annotations), and exported back to PACS as a DICOM
Video instance plus a Structured Report — without leaving the app or touching
command-line tools.

## Completed (kept for context; details in HANDOFF.md)

- [x] Project Library: duration + media count per row, thumbnails, missing-media
  indicator, relative timestamps, Reveal in Finder/Explorer, status colors.
- [x] Annotation workflow: duplicate at playhead (Cmd+D), Delete button in the
  inspector + Delete/Backspace on canvas, custom label presets persisted to
  `~/.neuroedit/custom_label_presets.json`, set start/end to playhead.
- [x] 2026-06-09 review: transcript-deletion bug, Cut losing media_type/fades,
  export duration ratchet, ffmpeg pipe deadlocks, Windows thumbnail/date bugs,
  SAM3 frame-loading speedup + 4K downscale, mask-cache memory cap, undo-history
  noise from draw settings, forward-compatible project loading, HF token
  masking, env-aware weight-cache path.
