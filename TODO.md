# NeuroEdit Roadmap TODO

This roadmap tracks product work after the current alpha baseline. Keep items
small enough to verify, and move completed implementation details into release
notes or docs instead of expanding this file indefinitely.

## Release Readiness

- [ ] Verify the generated macOS DMG launches, imports media, plays/scrubs, and
  exports an MP4 plus `.export-report.txt`.
- [ ] Decide when to make the GitHub repository private.
- [ ] Decide when to add Windows Authenticode signing and macOS Developer ID
  signing/notarization.

## Project Library

- [ ] Add `duration` (sum of clip durations) and `media_count` (clip + audio +
  slide count) to each row in the recent-projects dialog.
- [ ] Add project thumbnails from the active clip or first still.
- [ ] Walk each project's clip/audio/slide source paths on dialog open and show
  a per-project indicator if any referenced media file is missing.
- [ ] Add a 'Reveal in Finder/Explorer' action that opens the project's parent
  folder via `QDesktopServices.openUrl(QUrl.fromLocalFile(...))`.
- [ ] Acceptance: a returning user can identify the right project without opening
  multiple `project.json` files.

## Timeline Editing

- [ ] Add a distinct selected-state outline in each of `_paint_video_blocks`,
  `_paint_audio_blocks`, `_paint_slide_blocks`, and `_paint_markers`
  (`editor_panels.py`); drive from a single `selected_track_item` state.
- [ ] Add marker edit/delete support.
- [ ] Add clip rename support.
- [ ] Add zoom-to-fit for the whole timeline.
- [ ] Add snap-to-playhead for clip, slide, marker, and audio positioning.
- [ ] Acceptance: a user can trim, rename, mark, and navigate a simple case video
  without needing hidden shortcuts.

## Annotation Workflow

- [ ] Add duplicate annotation support.
- [ ] Add a Delete button to the annotation inspector and bind the Delete/Backspace
  shortcut to remove the currently selected annotation.
- [ ] Allow users to add, remove, and reorder custom label presets. Persist to a
  user-config JSON; load at startup. (Read-only `ANATOMY_PRESETS` already exist in
  `editor_panels.py`.)
- [ ] Acceptance: users can create, adjust, reuse, and clean up annotations
  without hunting across the canvas and Labels panel.

## Privacy And PHI Review

- [ ] Add a guided PHI review mode that steps through timeline sections needing
  review.
- [ ] Show a modal pre-export checklist that requires explicit acknowledgement of
  PHI review, de-identification, and consent before the export job starts. Write
  the same flags to the export report.
- [ ] Add an explicit `audio_reviewed_for_phi` flag to project state, surfaced as
  a checkbox in the audio panel; warn on export-with-audio if unset (do not block).
- [ ] Add 'Reveal Report' and 'Reveal MP4' buttons to the post-export dialog
  (`QDesktopServices.openUrl`).
- [ ] Acceptance: before export, the app makes unresolved visual/audio PHI risks
  visible and hard to miss.

## Captions And Transcript

- [ ] Generate captions from transcript segments.
- [ ] Add caption preview on the video canvas.
- [ ] Add caption style controls that are simple and export-safe.
- [ ] Export captions as SRT and WebVTT.
- [ ] Acceptance: a user can import or write transcript segments, preview them as
  captions, and export caption files.

## SAM And Mask Workflow

- [ ] Add named mask objects so users can distinguish multiple segmentations.
- [ ] Add delete/regenerate controls for masks and propagated masks.
- [ ] Add a status row in the SAM panel showing last propagation start, end, frames
  processed, and result (success / canceled / error); persist last-run in the
  project so it survives reopening.
- [ ] When `SamBackend.probe()` returns missing, replace the SAM panel body with a
  one-screen explainer plus 'Install Dependencies' / 'Download Weights' buttons
  that route to the existing onboarding flow.
- [ ] Acceptance: SAM results feel like editable project assets, not one-off
  hidden outputs.

## Export And Distribution

- [ ] Add export history for recent output files.
- [ ] Add a collapsible 'Advanced' group to `ExportDialog` that exposes CRF, fps,
  target width/height, and audio codec. Defaults stay glued to the selected preset.
- [ ] Convert `ALPHA_QA_CHECKLIST.md` from a generic template to a per-tag file:
  include the tag SHA, fill date, and results columns. Commit one per release.
- [ ] Evaluate Intel Mac build support if testers need it.
- [ ] Acceptance: non-technical testers can install, export, find their files,
  and report issues with minimal guidance.

## Quality And Regression Coverage

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

## Stryker Imaging / Video Integration

These items target compatibility with Stryker's surgical imaging stack
(1688 AIM 4K, SDC4K / SDC3, SPY-PHI, Connected OR Hub, Studio3). There is
no public Stryker SDK; integration is via DICOM, FTP/SMB drop zones, and
shared file formats. Grouped by user-visible value, highest first.

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
