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

## Dependency Security (audit 2026-06-20, automation-maintained)

Audit of `desktop/pyproject.toml`. Deps are declared as `>=` floors with **no
lock file**, so a fresh install resolves to the latest (clean) release. The risk
below is that the floors still *permit* known-vulnerable versions for any
pinned/cached/offline environment — raise the floors to enforce the fixes.

**P0 — security (raise floor to enforce CVE fixes):**
- [ ] **pillow `>=10` → `>=12.2.0`** (major). Floor allows 10.0–10.1.x, exposed to
  CVE-2023-50447 (ImageMath.eval arbitrary code execution, fixed 10.2.0),
  CVE-2023-4863/5129 (libwebp heap overflow, critical, fixed 10.0.1),
  CVE-2024-28219 (buffer overflow, fixed 10.3.0), and CVE-2026-42308 /
  CVE-2026-42310 (DoS, fixed 12.2.0). Latest 12.2.0 is clean. Major bump
  (10→12) — review Pillow 11 & 12 release notes for removed APIs before bumping.
- [ ] **torch `>=2.7` → `>=2.12.1`** (minor). Floor 2.7.0 carries multiple CVEs,
  several rated critical: CVE-2025-2999 / -3000 / -3001 (critical), plus
  CVE-2025-3730, -2953 and the CVE-2025-5555x DoS/overflow series (fixed across
  2.7.1–2.10.0). Latest 2.12.1 is clean. In the optional `[sam]` extra.
- [ ] **pytest `>=8.0` → `>=9.0.3`** (major, dev-only). CVE-2025-71176 — insecure
  `/tmp/pytest-of-*` dir on UNIX (fixed 9.0.3). Low severity (local, dev tool);
  major bump may need test-suite touch-ups. Latest 9.1.1 clean.

**P3 — housekeeping (no known CVEs; floors lag latest):**
- [ ] huggingface-hub `>=0.30` → 1.20.1 — **major (0.x→1.x), breaking API**; review carefully.
- [ ] numpy `>=2.0` → 2.4.6 (minor) · opencv-python `>=4.10` → 4.13 (minor) ·
  PySide6 `>=6.8` → 6.11.1 (minor) · transformers `>=5.6` → 5.12.1 (minor) ·
  torchvision `>=0.22` → 0.27.1 (minor) · imageio-ffmpeg `>=0.5` → 0.6.0 (minor) ·
  safetensors `>=0.5` → 0.8.0 (minor) · ruff `>=0.8` → 0.15.18 (minor, dev) ·
  pyinstaller `>=6.11` → 6.21.0 (minor) · hatchling `>=1.25` → 1.30.1 (minor, build).

_Note: the request asked to write this to `/Users/alangordillo/Documents/Claude/Code/video editing app/TODO.md`, which does not exist in this remote Linux container. Recorded here in the repo TODO.md (the committable artifact) instead._

## Optimization Backlog
_(automation-maintained — new findings appended below, checked off when implemented)_

The primary open code-health/runtime work lives in **P4.5** (modularize the
`main_window.py` dialog/MainWindow split, reduce undo-snapshot serialize cost,
audit cold-start imports). The items here are smaller, fresh findings surfaced
by the optimization automation; they are not duplicated into P4.5.

- [ ] **Playback loop still does two repaints per 33 ms tick.**
  `_tick_timeline_playback` (`ui/main_window.py:3241`) used to recompute
  `project_end_time()` — four full list comprehensions over
  clips+audio+slides+markers (`ui/timeline_utils.py:13`) — and unconditionally
  call both `self.timeline.refresh()` and `self.video_view.update_annotations()`
  on every 30 fps tick. **Progress 2026-06-19:** `MainWindow` now caches
  `project_end_time` and invalidates it on document edits/project load, so
  playback/seek/export no longer recompute the timeline end each tick. Remaining
  low-priority mitigation: skip `timeline.refresh()` / annotation refresh when
  the visible frame has not changed.

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
per-mask palette colors); see Completed section. Follow-ups deliberately
deferred: record `sam_last_run` for single-frame segmentation too; persist the
track-window UI prefs; disable mask-list rows while a SAM job is running;
consider dropping the auto-shown SamSetupDialog now that the explainer covers
ready-but-no-weights (currently both appear).

## P3 — Privacy and PHI review — ✅ SHIPPED 2026-06-10

All five items implemented (guided PHI review mode, pre-export attestation
checklist with flags written to the export report, `audio_reviewed_for_phi`
flag + Audio-panel checkbox + warn-not-block on export-with-audio, Reveal
MP4/Report buttons, configurable storage location with first-run prompt
recommending a non-cloud-synced folder); see Completed section. Follow-ups
deliberately deferred: per-stop review progress persistence (guided review
state is per-session; completion sets `phi_review_confirmed`), migrating
existing autosave contents when the storage root changes.

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
behavior-preserving — the 123-test suite and `ruff` must stay green with no
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

- [ ] Modularize `ui/main_window.py` (~4,050 lines) by responsibility — the
  graphics view + annotation item and the SAM worker QObjects are already
  extracted (see Progress below), and the app dialogs now live in `ui/dialogs.py`;
  the remaining slice is the still-large `MainWindow` class. Mechanical moves
  only; no logic changes. Target: no `ui/` module over ~2,500 lines. **Progress
  2026-06-14:**
  Project Library dialog + thumbnail worker extracted to `ui/project_library.py`
  and re-exported from `main_window`. **Progress 2026-06-16:** canvas graphics
  moved to `ui/canvas.py`, SAM worker QObjects moved to `ui/sam_workers.py`, and
  both are re-exported from `main_window`. **Progress 2026-06-17:** SAM setup,
  storage location, PHI review, export checklist, export, and export history
  dialogs moved to `ui/dialogs.py` and are re-exported from `main_window`.
  Current line counts: `main_window.py` ~4,050, `dialogs.py` ~798, `canvas.py`
  ~1,238, `sam_workers.py` ~146.
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
  remain open.
- [ ] Audit cold-start import cost — confirm heavy/on-demand imports
  (subprocess/ffmpeg, captions, export) are deferred where possible and torch
  stays lazy; quantify with the diagnostics startup timing.
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
  sets `phi_review_confirmed`; single pre-export attestation checklist
  (PHI/de-id/consent required, audio warn-only) pre-filled from project state,
  flags written to the export report; `audio_reviewed_for_phi` flag +
  Audio-panel checkbox + preflight warning; Reveal MP4/Reveal Report on the
  completion dialog; configurable storage root (`storage/projectRoot` in
  QSettings) with first-run prompt recommending non-cloud-synced folders.
  UX grounded in clinical-software research (soft stops over hard stops,
  alert-fatigue avoidance, human-in-the-loop review). 9 tests in
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
  `prompt_points` and replaces frames in place; `sam_last_run` persisted in
  the project and shown as a status row; missing-backend explainer with
  Install/Download buttons; track window spinbox + "To clip end" default;
  8-color mask palette (no red) burned into the saved PNGs. 8 new tests in
  `tests/test_sam_workflow.py`. UX choices grounded in research on
  Premiere/Resolve/FCP/Roto Brush/3D Slicer conventions and complaints.
