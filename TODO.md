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

## Optimization Backlog
_(automation-maintained — new findings appended below, checked off when implemented)_

The primary open code-health/runtime work lives in **P4.5** (modularize the
`main_window.py` dialog/MainWindow split, reduce undo-snapshot serialize cost,
audit cold-start imports). The items here are smaller, fresh findings surfaced
by the optimization automation; they are not duplicated into P4.5.

- [x] **Project, export, SAM, and release-integrity review fixes.** Fixed
  2026-07-11: project switches now confirm unsaved work and reseed undo history;
  Save As stages the new project and migrates app-managed assets; media/content
  changes invalidate PHI attestations; VFR export/SAM use media timestamps;
  SAM output names are collision-resistant and stale results are discarded;
  export refuses missing or source-overwriting media and atomically replaces an
  audio-muxed output. Project-library thumbnails require de-identification
  confirmation. Installer messaging now accurately declares SAM source-build
  support, and tagged release builds wait for lint/test quality gates.

- [x] **Stale project-library thumbnail could survive a failed refresh.** Fixed
  2026-08-09: when a cached `.neuroedit-thumbnail.jpg` is older than
  `project.json`, the thumbnail worker removes it before invoking ffmpeg and only
  emits a refreshed thumbnail after a successful command. This prevents a stale
  derived preview from being reused after media or de-identification state
  changes when thumbnail regeneration fails.

- [x] **Project Library used source duration for trimmed-case previews.** Fixed
  2026-08-13: recent-project metadata now reports the timeline content end
  across clips, audio, and slides instead of summing raw source durations, and
  thumbnail generation seeks inside the first clip's trimmed source range. This
  keeps the library row duration and derived preview aligned with what the
  reviewer will actually see after opening a trimmed project.

- [x] **Export preflight missed non-clip source media.** Fixed 2026-08-19:
  exports now apply the same missing-media and source-overwrite guard to
  narration audio tracks and slide image/still assets that already protected
  timeline clips. This prevents a missing narration/still from silently changing
  the exported case, and prevents saving an MP4 over an app-managed still or
  audio source.

- [x] **Readiness warnings were clip-only for privacy attestations.** Fixed
  2026-08-20: export-readiness warnings now require consent, de-identification,
  and PHI review for any reviewable media surface — clips, slides/stills, or
  audio — matching the guided PHI review and export checklist. Slide/still-only
  exports also get the same no-redaction-box reminder that clip-based exports
  already received.

- [x] **Zero-duration slides extended export duration but rendered black.**
  Fixed 2026-08-21: the exporter now uses one effective slide-duration floor
  for content duration, timeline segment boundaries, and slide lookup, so
  legacy/corrupt zero-duration slides render during the minimum export span
  instead of padding the output with black frames.

- [x] **Inactive audio placeholders blocked visual exports.** Fixed
  2026-08-22: export source-media preflight now treats only audio tracks with a
  positive duration and positive volume as required source media, matching the
  audio mux path. Muted or empty missing narration placeholders no longer block
  otherwise visual exports, while active missing narration still fails early.

- [x] **Stale `project_end_time` cache after undo/redo (correctness).** Fixed
  2026-06-20: `_apply_snapshot()` now clears `_project_end_time_cache` after
  replacing the project, so undo/redo cannot reuse a duration from the prior
  document state. A focused regression test restores a longer snapshot after
  caching a shorter duration.
- [x] **`_open_recent_project` lacked the early `project_end_time` cache
  invalidation its sibling open paths have (consistency / defense-in-depth,
  low priority).** Fixed 2026-06-21: `_open_recent_project` now invalidates the
  cached duration immediately after `ProjectStore.open()` swaps the project,
  matching the dialog-open and new-project paths. A focused ordering regression
  test proves invalidation happens before loaded-project validation.
- [x] **Playback loop still does two repaints per 33 ms tick.**
  `_tick_timeline_playback` (`ui/main_window.py:3241`) used to recompute
  `project_end_time()` — four full list comprehensions over
  clips+audio+slides+markers (`ui/timeline_utils.py:13`) — and unconditionally
  call both `self.timeline.refresh()` and `self.video_view.update_annotations()`
  on every 30 fps tick. **Progress 2026-06-19:** `MainWindow` now caches
  `project_end_time` and invalidates it on document edits/project load, so
  playback/seek/export no longer recompute the timeline end each tick. Remaining
  **Correctness fix 2026-06-21:** the monotonic 33 ms clock now remains the
  authoritative playhead clock during video playback; sparse frame timestamps
  from variable-frame-rate screen recordings no longer pause and jump the
  timeline. Remaining low-priority mitigation: reduce annotation repaint work
  when its visible state has not changed. Do not throttle playhead refreshes by
  decoded-frame changes; static VFR sections still need smooth playhead motion.
  **Fixed 2026-06-27:** the timeline/playhead still refreshes on every monotonic
  clock tick, but the canvas now requests a repaint only when its time-dependent
  state changes (annotation visibility/tracked-mask frame, slide, caption cue,
  or fade opacity). A deterministic 10 s synthetic sample required 1 canvas
  repaint request across 300 ticks instead of 300; focused tests cover static overlay
  intervals, visibility boundaries, and continuous fades.
- [x] **A clip that never reaches `LoadedMedia` left `_pending_seek_ms` stuck
  (correctness/robustness).** Fixed 2026-06-22: `_media_status_changed()` now
  clears `_pending_seek_ms` and `_pending_play` on terminal `NoMedia` or
  `InvalidMedia` status, releasing the timeline clock instead of permanently
  freezing playback. Focused regressions cover both terminal statuses while the
  existing test keeps deferred seeks pending through recoverable loading states.
- [x] **Overlay slides froze the underlying video preview.** Fixed 2026-06-22:
  playback sync and timeline ticks now treat only full-frame slides as blocking.
  Overlay slides render above a video while its `QMediaPlayer` continues, with
  focused regressions covering playback started within and continuing through
  an overlay.
- [x] **Multi-file Finder drop did N blocking imports + N preview reloads + N
  undo steps (perf/UX).** Fixed 2026-06-23: `dropEvent` now imports the accepted
  paths as one batch, selects the last successful import, then performs one
  preview load and one dirty/history operation for the gesture. Synchronous
  video probing remains unchanged and is a separate measurement-first follow-up.
  **Verified 2026-06-24:** the batch helpers (`_add_video_clip`/`_add_image_clip`,
  `ui/main_window.py:2646`/`:2656`) only mutate the model; the single trailing
  `_mark_dirty()` (`:2690`) is the lone history/dirty op for the gesture. No
  regression — the batching claim holds.
- [x] **Batch media import lacked feedback while probing videos synchronously
  (perf/UX).** `_import_media_files` (`ui/main_window.py:2671`) loops over
  the dropped paths calling `_add_video_clip` (`:2646`), which runs
  `probe_video` (`video_probe.py:6`) — a blocking `cv2.VideoCapture` open +
  metadata read — inline on the main thread with no progress feedback. Dropping
  many videos freezes the UI for the sum of all probe times. This is the
  measurement-first follow-up flagged when §40 batched the history/preview ops.
  **Mitigated 2026-06-24:** smoothness-fixture measurements were 3.3 ms median
  for 1080p and 9.9 ms for 4K, with an 85.8 ms cold outlier, so worker-thread
  lifecycle complexity was not justified. Multi-video imports now show
  determinate per-video metadata progress and yield to Qt between probes, while
  diagnostics records PHI-safe `media_probe` timings for real-world codecs and
  storage. Clip order and the single-history-step semantics from §40 remain
  covered by focused tests.
- [x] **§42's probe-progress dialog only reached drag-and-drop; the two
  explicit "Import Video" entry points still froze the UI (perf/UX +
  redundancy).** `_import_video` (`ui/main_window.py:2614`) is wired to both
  File → Import Video (`:1405`) and the Media Explorer "Import Videos" button
  (`:1872`), and it duplicates the `_import_media_files` loop inline — looping
  `_add_video_clip` → `probe_video` synchronously with no `QProgressDialog`.
  Only the drop handler (`:2738`) and single-file import (`:2670`) route through
  `_import_media_files` (`:2672`), so selecting many videos from the menu or the
  Media Explorer button still blocks the main thread for the sum of all probe
  times with zero feedback — the exact freeze §42 fixed for drops. `_import_image`
  (`:2630`) duplicates the same loop. Fix: have `_import_video`/`_import_image`
  delegate to `_import_media_files([Path(p) for p in paths])` after their
  file-dialog selection, deleting the duplicated loop/active-clip/dirty tail.
  **Fixed 2026-06-25:** `_import_video` and `_import_image` now delegate selected
  paths to `_import_media_files`, so File → Import Video and the Media Explorer
  multi-import buttons share the same progress dialog, active-clip selection,
  preview load, and single dirty/history operation as drag-and-drop. Focused
  regressions cover both dialog entry points.

## P0 — Unblock and ship the current alpha

- [x] Fix the dev environment — Python 3.13 reinstalled 2026-06-10; venv
  revived in place, full suite runs.
- [x] Run `ruff check src tests` and `python -m pytest tests/ -q` — green and
  kept green through P1–P4.
- [x] Commit the working-tree changes — landed across the v0.3.x commits.
- [ ] Verify the generated macOS DMG launches, imports media, plays/scrubs, and
  exports an MP4 plus `.export-report.txt`.
- [ ] Decide when to make the GitHub repository private (recommended —
  commercialization intent; see HANDOFF). **Owner action.**
- [ ] Decide when to add Windows Authenticode signing and macOS Developer ID
  signing/notarization. **Owner action.**

## P1 — Timeline editing gaps — ✅ SHIPPED 2026-06-10

All five items implemented (selection outlines, marker edit/delete, clip
rename, zoom-to-fit with Shift+Z toggle-back, snapping with Shift-bypass and
magnet toggle); see Completed section. Follow-ups deliberately deferred:
marker dragging, multi-select, keyboard-delete of timeline selection,
snap-indicator guide line.

## P2 — SAM and mask workflow — ✅ SHIPPED 2026-06-10

All six items implemented (named mask list, delete + orphan cleanup, re-track,
persisted status row, missing-backend explainer, propagation window,
per-mask palette colors); see Completed section. Follow-ups since completed:
single-frame segmentation now stamps `sam_last_run`, mask-list rows are disabled
while a SAM job is running, the inline missing-backend explainer is the single
setup entry point instead of competing with an auto-opened setup dialog, and
track-window UI preferences persist across SAM panel instances via `QSettings`.
No open P2 implementation follow-up is currently code-ready.

## P3 — Privacy and PHI review — ✅ SHIPPED 2026-06-10

All five items implemented (guided PHI review mode, pre-export attestation
checklist with flags written to the export report, `audio_reviewed_for_phi`
flag + Audio-panel checkbox + warn-not-block on export-with-audio, Reveal
MP4/Report buttons, configurable storage location with first-run prompt
recommending a non-cloud-synced folder); see Completed section. Follow-ups
since completed: per-stop review progress persists so a paused guided review can
resume after reopening, and storage-root changes offer a copy-only migration of
existing autosave data. No open P3 implementation follow-up is currently
code-ready.

## P4 — Captions, transcript, and export polish — ✅ SHIPPED 2026-06-10

All items implemented except Intel Mac evaluation (captions from transcript,
canvas preview, simple export-safe style controls, SRT + WebVTT export,
export history, collapsible Advanced export group, per-tag QA checklist
template); see Completed section.

- [ ] Evaluate Intel Mac build support if testers need it.

## Quality and regression coverage (continuous — pair with each phase)

- [x] Regression tests for the 2026-06-09 review bugs (audio-track delete,
  Cut media_type/fades, exporter duration, from_dict tolerance) —
  `tests/test_regressions.py`.
- [x] Headless `MainWindow()` construction + 5-panel switch test —
  `tests/test_main_window_headless.py`.
- [x] Autosave restore and new-project tests.
- [x] Exporter tests: defaults produce no audio stream; export report
  contains the PHI/consent flag block.
- [x] Resize test at 1085×600 / 1280×720 / 1920×1080 asserting no horizontal
  scrollbar on the right panel (found and fixed a real bug: the panel
  minimum width ignored the vertical scrollbar + frame, so every panel
  scrolled sideways by ~20 px whenever the vertical scrollbar was visible).
- [ ] Keep `ruff check src tests scripts` and `python -m pytest tests/ -q` green
  before every release tag.

## P4.5 — Code health and runtime cost (engineering; no new features)

Highest-leverage engineering work while P0 release items stay owner/hardware
blocked and P5 stays parked. All items are measurement-first and
behavior-preserving — the 155-test suite and `ruff` must stay green with no
user-visible change. Full rationale and acceptance criteria in
[NEXT_OPTIMIZATION_PLAN.md](NEXT_OPTIMIZATION_PLAN.md) Phase 6.

**Optimization sweep 2026-06-16:** with Phases 1–5 (brand system, smoothness
caching, workflow refinement) shipped, this section is now the active work
front. Verified the three open items still stand against the current tree:
`ui/main_window.py` was 6,114 lines with 17 classes still co-located; the undo
path still double-serializes per tick (see below); and cold-start import
deferral is unaudited. No new test regressions. Recommended order is unchanged:
modularize first (makes the rest safer to review), then undo cost, then the
import audit.

- [x] Modularize `ui/main_window.py` by responsibility — the
  graphics view + annotation item and the SAM worker QObjects are already
  extracted (see Progress below), and the app dialogs now live in `ui/dialogs.py`;
  the `MainWindow` class has since been split into cohesive workflow mixins.
  Mechanical moves only; no logic changes. Target met: no `ui/` module is over
  ~2,500 lines. **Progress
  2026-06-14:**
  Project Library dialog + thumbnail worker extracted to `ui/project_library.py`
  and re-exported from `main_window`. **Progress 2026-06-16:** canvas graphics
  moved to `ui/canvas.py`, SAM worker QObjects moved to `ui/sam_workers.py`, and
  both are re-exported from `main_window`. **Progress 2026-06-17:** SAM setup,
  storage location, PHI review, export checklist, export, and export history
  dialogs moved to `ui/dialogs.py` and are re-exported from `main_window`.
  **Progress 2026-07-03:** `ExportWorker` moved to `ui/export_worker.py` and is
  re-exported from `main_window`; its on-demand exporter import is unchanged.
  **Progress 2026-07-04:** `SamPanel` moved to `ui/sam_panel.py` and is
  re-exported from `main_window`, preserving the existing public import and SAM
  workflow behavior.
  **Progress 2026-07-05:** `LabelsPanel` and its preset persistence moved to
  `ui/labels_panel.py`; `main_window` re-exports the panel and shares the preset
  definitions without changing label editing behavior.
  **Progress 2026-07-06:** removed the unused legacy `TimelineWidget` after a
  repository-wide reference check confirmed that `RichTimelineWidget` is the
  only live timeline implementation.
  **Progress 2026-07-07:** moved the header/About brand identity helpers to
  `ui/branding.py`; `main_window` imports the shared SVG mark renderer and
  wordmark font helper, preserving existing compatibility imports.
  **Progress 2026-07-08:** moved pure `MainWindow` utility constants/helpers
  to `ui/main_window_utils.py`; `main_window` re-exports the mask palette,
  media extension sets, formatting/color helpers, SAM propagation-window math,
  and orphan-mask cleanup helpers for compatibility.
  **Progress 2026-07-09:** moved the SAM workflow orchestration methods to
  `ui/sam_workflow.py` as a mixin; `MainWindow` keeps the same signal wiring
  and SAM behavior while the segmentation/propagation/download controller logic
  is isolated from the rest of the window class.
  **Progress 2026-07-10:** moved the MP4/caption export controller methods to
  `ui/export_workflow.py` as a mixin; `MainWindow` keeps the same export button,
  menu action, progress dialog, history, reveal, and report behavior. This brings
  `main_window.py` below the ~2,500-line target. **Progress 2026-08-16:**
  moved undo/redo dirty-state and autosave controller methods to
  `ui/history.py` as a mixin, preserving snapshot semantics and autosave reuse
  while leaving project actions in `main_window.py`. Current line counts:
  `main_window.py` ~2,384, `history.py` ~204, `export_workflow.py` ~312,
  `sam_workflow.py` ~565,
  `main_window_utils.py` ~68, `branding.py` ~74, `labels_panel.py` ~525,
  `sam_panel.py` ~412, `dialogs.py` ~804, `canvas.py` ~1,285,
  `sam_workers.py` ~146. **Completed 2026-08-17:** current line-count review
  confirms no `ui/` module is over the ~2,500-line target. Remaining
  modularization is lower priority and should only target cohesive slices that
  simplify future work.
- [x] Modularize `ui/editor_panels.py` (~2,960 lines) — it is also over the
  ~2,500-line `ui/` target. Extract `AudioPanel` (~970 lines, the largest
  class) into its own `ui/audio_panel.py`, re-exported from `editor_panels`;
  that alone brings the file under ~2,000 lines. Mechanical move only.
  **Done 2026-06-15:** `AudioPanel` moved to `ui/audio_panel.py`, shared
  timeline helpers moved to `ui/timeline_utils.py`, `editor_panels.py` now
  re-exports `AudioPanel` and is ~2,245 lines.
- [ ] Reduce undo/redo snapshot cost: every dirty tick still calls full
  `ProjectState.to_dict()` *and then* a second full `json.dumps` (for the BLAKE2
  hash) *before* the dedup decides to discard the snapshot, so mask-heavy or
  long-transcript projects pay two O(project size) serializes per edit even when
  nothing changed. Autosave (`store.save`, every 2 s when dirty) then serializes
  the same `ProjectState` a third time, independently. Evaluate a cheaper
  change-check ahead of the full serialize, a single shared per-dirty-tick
  serialization reused by both the history hash and autosave, compact JSON
  storage, and a cumulative-size cap (in addition to the 50-entry count); measure
  snapshot time + resident memory on the smoothness fixture before/after. Keep
  undo semantics identical. **Progress 2026-06-14:** dedup now uses compact
  BLAKE2 hashes; pre-serialize short-circuit, shared serialization, compact
  storage, cumulative-size cap, and the memory measurement are still open.
  **Progress 2026-06-18:** history pushes now reuse the same `ProjectState.to_dict()`
  result for the next autosave when no later UI-only/direct dirty change invalidates
  it; focused tests cover reuse and invalidation. Pre-serialize short-circuit,
  compact storage, cumulative-size cap, and smoothness-fixture memory measurement
  remain open. **Progress 2026-07-01:** history now tracks each snapshot's compact
  JSON byte size and evicts the oldest undo states above a 64 MiB cumulative cap,
  while always retaining the current state. **Progress 2026-07-02:** the stacks
  now retain those compact JSON bytes instead of duplicate nested dictionaries.
  On 50 smoothness-fixture edits, traced retained memory fell from 0.631 MiB to
  0.400 MiB (36.6%) while median push time stayed flat (0.640 ms to 0.629 ms).
  **Progress 2026-07-11:** a cached no-op history push now compares the current
  project dict against the cached autosave dict and returns before the compact
  JSON/hash pass, preserving redo clearing and autosave reuse. A true
  pre-`to_dict()` short-circuit remains deferred unless the model gains a safe
  document revision signal; do not add broad mutation bookkeeping for this
  micro-optimization.
- [x] Audit cold-start import cost — completed 2026-06-29. The export pipeline
  is now imported only when export, still capture, or export-settings creation
  is requested; `torch` remains lazy. Live-caption helpers remain eager because
  the normal canvas preview uses them. Warm `main_window` import stayed flat at
  a 0.17 s median while removing the exporter from the startup module graph.
- [x] Housekeeping: remove the iCloud conflict copies under `src/`
  (`__init__ 2.py`, `__main__ 2.py`, `video_probe 2.py`, `ui/__init__ 2.py`) —
  already `.gitignore`d but physically present and confusing to tooling.

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
- [x] P1 timeline editing (2026-06-10): FCP-style selection outline
  (`#FFD60A` + brightness lift) on clips/audio/slides/markers; marker
  context-menu + double-click edit and delete (≥12px hit area); clip rename
  via context menu; zoom-to-fit ("Fit" button + Shift+Z, second press restores
  prior zoom/scroll); snapping to playhead/edges/markers/t=0 with 10-screen-px
  threshold, Shift momentary bypass, magnet toggle (default on). Playhead
  scrubbing never snaps. 13 new tests in `tests/test_timeline_editing.py`.
- [x] P3 privacy/PHI review (2026-06-10): guided PHI review stepper (Edit
  menu) over clips/slides/audio with what-to-look-for hints — completing it
  sets `phi_review_confirmed`; per-stop progress persists for paused/resumed
  review sessions; single pre-export attestation checklist
  (PHI/de-id/consent required, audio warn-only) pre-filled from project state,
  flags written to the export report; `audio_reviewed_for_phi` flag +
  Audio-panel checkbox + preflight warning; Reveal MP4/Reveal Report on the
  completion dialog; configurable storage root (`storage/projectRoot` in
  QSettings) with first-run prompt recommending non-cloud-synced folders and a
  copy-only migration flow for existing autosave contents. UX grounded in
  clinical-software research (soft stops over hard stops, alert-fatigue
  avoidance, human-in-the-loop review). Focused tests in
  `tests/test_phi_review.py`.
- [x] P4 captions + export polish (2026-06-10): `captions.py` turns transcript
  segments into accessibility-conventional cues (≤42 chars/line, ≤2 lines,
  proportional split timing, speaker prefixes) with SRT/WebVTT export and a
  shared canvas/exporter painter (white-on-dark box, safe-area margins);
  caption style fields + Audio-panel controls + live preview; burn-in export
  option that forces re-render over cue spans; File → Export Captions and
  Export History (QSettings, Reveal buttons); collapsible Advanced export
  group (CRF/fps/size/AAC bitrate) glued to presets; per-tag QA checklist
  template. 11 tests in `tests/test_captions.py`.
- [x] P2 SAM mask workflow (2026-06-10): 3D-Slicer-style mask list in the SAM
  panel (color swatch, inline rename, visibility checkbox, context menu);
  delete routes through undo-safe `_delete_annotation`, orphan mask PNGs swept
  at app close (undo/redo stacks respected); explicit Re-track replays stored
  `prompt_points` and replaces frames in place; propagation and single-frame
  segmentation both persist `sam_last_run` in the project and show it as a
  status row; missing-backend explainer with Install/Download buttons is the
  setup entry point; track window spinbox + "To clip end" default; 8-color mask
  palette (no red) burned into the saved PNGs. Focused tests in
  `tests/test_sam_workflow.py`. UX choices grounded in research on
  Premiere/Resolve/FCP/Roto Brush/3D Slicer conventions and complaints.
