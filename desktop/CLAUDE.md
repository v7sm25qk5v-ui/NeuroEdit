# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.


## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

## Repository layout

The application is the native PySide6 desktop editor in **`desktop/`**. The
repository root contains project documentation and CI configuration; no React/Vite
prototype is present in this checkout. All commands and architecture below refer
to the desktop app unless noted.

## Commands (desktop)

All commands assume `cd desktop` first.

```bash
# Setup (one-time). Python 3.12 is preferred for SAM3.
python3.12 -m venv .venv          # see venv-location caveat below
source .venv/bin/activate
python -m pip install -e ".[sam]" # adds torch, transformers, hf-hub

# Run the app
python -m neuroedit_desktop

# Lint
ruff check src
ruff format src

# Fast syntax check without paying torch's import cost (~7s warm, ~90s cold)
python -c "import py_compile; py_compile.compile('src/neuroedit_desktop/<file>.py', doraise=True)"

# SAM3 weights are gated. After install:
hf auth login
```

The updater release collects **765 tests** (`python -m pytest tests/ -q`;
local clean exit on 2026-11-17). v0.5.20-alpha (inserted slides) collects
**804** (local clean exit and Ruff on 2026-11-17). With instant cuts
(`test_playback_cue.py`) the suite collects **831** (clean local run, 2026-11-17). Published v0.5.19-alpha passed all 765 macOS
CI tests; both installer builds passed. The Windows fixture path blocker is fixed;
its informational suite now reports 741 passed, 17 failed and 7 skipped. See
HANDOFF.md and docs/releases/v0.5.19-alpha-verification.json for evidence and
remaining Windows portability/runtime validation.
Keep it and `ruff check src tests scripts` green before every release tag.
Every public release must also update GitHub's Latest release and repository
Releases sidebar. Verify `/releases/latest` resolves to the new tag, alongside
the installer assets and README links. The publication workflow explicitly sets
`prerelease: false` and `make_latest: "true"` for visibility; retain alpha and
unsigned-build labels in the tag and notes when applicable.
`tests/conftest.py` redirects NeuroEdit's application preferences to a temporary
INI file; tests must not read or write the user's native QSettings store.

### venv-location note (current setup is intentional)

`desktop/.venv` is a symlink to `~/Documents/Claude/venv`, which lives **inside
iCloud Drive on purpose** — this is the chosen setup; do not relocate it.
Tradeoff to remember: if the optional `[sam]` stack (torch, ~1.6 GB of dylibs)
is installed here, Apple's iCloud file-provider can inflate `import torch` from
~7 s to 90+ s on cold start. The current venv is ~600 MB and does **not**
include torch, so `SamBackend.probe()` returns "missing" and SAM features
no-op until `pip install -e ".[sam]"` is run. If torch cold-start ever becomes
painful, the fix is to `pip install -e ".[sam]"` once and accept the first-run
sync delay — not to move the venv off iCloud.

## Big-picture architecture

### Process and threading model

- Single `QApplication` process. UI on the main thread.
- SAM (PyTorch + transformers) runs on background `QThread`s via four worker
  `QObject`s in `ui/sam_workers.py`: `SamProbeWorker`, `SamSegmentWorker`,
  `SamPropagationWorker`, and `SamDownloadWorker`. `ui/sam_workflow.py` owns the
  `MainWindow` orchestration methods for probing, setup, segmentation,
  propagation, re-track, and weight cleanup. `ui/main_window.py` re-exports the
  workers for import stability. Each emits `progress(str)` and `finished(...)`.
  Workers wrap calls into `sam_backend.SamBackend`.
- Because torch import + first weight download can take tens of seconds, every
  long-running stage is paired with a 500 ms heartbeat timer
  (`_start_sam_heartbeat` / `_tick_sam_heartbeat`) that appends elapsed
  seconds to the SAM panel status — this is what proves the app is alive
  during the cold start.

### Rendering pipeline (the part that bites macOS newcomers)

A widget-on-top-of-`QVideoWidget` overlay is **broken on macOS Metal** —
QtMultimedia's native surface paints over the overlay. The fix is to keep
everything in one `QGraphicsScene` owned by `VideoGraphicsView`:

- `QGraphicsVideoItem` (z=0) — receives output from `QMediaPlayer`. A second,
  hidden one (`cue_video_item`) belongs to the cue player (see below);
  `swap_video_items()` trades them at a cut.
- `QGraphicsPixmapItem` (z=5) — shown for image clips; hidden for video clips.
- `AnnotationGraphicsItem` (z=10, custom `QGraphicsObject`) — paints
  annotations, SAM points, slides (when not in overlay mode), and the fade
  overlay. Coordinates inside it are **normalized 0..1 multiplied by `_size`**,
  which is set from `nativeSizeChanged` for video and `pixmap.size()` for
  images. Slide title/body rectangles use the same normalized convention.

The monotonic time-tick path (`_tick_timeline_playback`) is authoritative for
`current_time` during all playback. `QMediaPlayer` renders video but its
`positionChanged` events do not drive the playhead while playback is active;
screen recordings can have sparse variable-frame-rate timestamps that would
otherwise make the timeline pause and jump. When `clip.media_type == "image"`,
the player source is cleared and the pixmap item is shown. Don't try to feed
image paths into QMediaPlayer. Full-frame slides pause video, but slides with
`overlay=True` must leave the underlying video playing while the annotation
layer paints the slide above it.

Instant cuts: within `CUE_LEAD_S` (3 s wall clock) of a cut that would need a
seek or a new source, `_maybe_cue_next_clip` loads the next clip into
`_cue_player`, **paused** (a stopped player does not decode on seek), at its
`trim_start`, on `cue_video_item`. At the cut `_take_cue` swaps the players,
their audio outputs and the two surfaces, then plays: about 5 ms instead of
0.5-0.9 s of frozen picture on long-GOP footage. Never move a player's video
output to the other surface instead: Qt's FFmpeg backend seeks again when the
output changes, which brings the stall back (measured 649 ms). Contiguous cuts
within one file need no cue. A cue that doesn't match the clip (edited, not
ready, or playhead > `CUE_MAX_LATE_MS` past it) falls back to the seek path.
Signals from the cue player are ignored unless it is `self.player`.

### State, persistence, and undo/redo

- `models.py` is the single source of truth for all serializable state. Every
  user-editable thing is a dataclass with `to_dict`/`from_dict` round-tripping
  through `ProjectState`. Adding new fields is fine **iff they have defaults**
  — `from_dict` does `Cls(**data)`, so old saves and old undo snapshots will
  break loudly otherwise.
- `project_store.ProjectStore` writes `project.json` plus sibling directories
  `masks/`, `audio/`, `stills/`. Default autosave path is
  `~/Documents/NeuroEdit/Autosave/`. Autosave runs every 2 s when `dirty`.
- Undo/redo is **compact JSON snapshots of the entire `ProjectState`**, not
  per-field patches. Every `_mark_dirty` / `_mark_project_dirty` pushes a byte
  payload (caps: 50 entries and 64 MiB). `_apply_snapshot` decodes it, rebuilds
  via `ProjectState.from_dict`, and reloads the active clip. The `_restoring`
  guard prevents undo-during-undo from duplicating history.
- `QSettings("NeuroEdit", "Desktop")` is used for app-level prefs (tutorial
  seen flag etc.) — separate from the project file.

### Module map (what lives where)

- `models.py` — every dataclass + `to_dict`/`from_dict`. Split clips persist
  source-in/source-out limits so adjacent pieces cannot reuse the same frames.
  `ProjectState.ripple_after` shifts only timeline items downstream of a
  trim/delete delta, preserving unrelated intentional gaps; the separate
  `arrange_clips_without_overlap` helper still resolves overlap/reorder cases.
  Full slides are either inserted (`Slide.insert`: they own a gap in the video
  storyline, so clips after them play later) or cover (drawn over footage,
  which is hidden). `insert_gap`, `slide_insert_point` (snaps to clip edges
  within `INSERT_SNAP_SECONDS`/`INSERT_SNAP_PX`), `insert_slide`,
  `remove_slide_gap`, `move_inserted_slide`, `place_inserted_slide` and
  `resize_inserted_slide` keep that gap in step; `compact_clip_positions` also
  keeps a slide-filled gap before the first clip.
- `project_store.py` — JSON load/save with atomic temp-file rename.
- `sam_backend.py` — model loading, frame extraction (OpenCV), and SAM3 with
  SAM1 (`facebook/sam-vit-base`) fallback. Uses `inspect.signature` to filter
  kwargs for cross-version model compatibility.
- `video_probe.py` — fast `probe_video(path) → (duration, w, h)` via ffmpeg.
- `media_convert.py` — `.mpg`/`.mpeg` (MPEG program streams) are converted on import
  to an H.264 MP4 working copy in the project's `media/` folder
  (`<stem>.neuroedit-<12 hex>.mp4`; the original is never modified). Without it
  Qt's player shows the next keyframe after a paused seek (up to ~0.5 s late) and
  OpenCV repeats one frame for the first ~0.5 s, so preview and export disagree.
  The copy is deinterlaced (flagged frames only), square-pixel, metadata-free.
  Close-time cleanup deletes only files with that name pattern (and stale
  `.neuroedit-convert-*` temps); `ProjectStore.open` re-points clips at
  `<folder>/media/<same name>` when a project folder was moved or copied.
- `exporter.py` — timeline → ffmpeg composition (export pipeline).
- Exporter loading is deferred until export, still capture, or export-settings
  creation; keep that on-demand boundary intact. Live captions stay eager because
  `ui/canvas.py` uses them during normal preview, and torch remains lazy.
- `ui/main_window.py` — `MainWindow`; the unused legacy `TimelineWidget` was
  removed after a repository-wide reference check on 2026-07-06. High-level app
  wiring lives here. It re-exports extracted UI classes where compatibility
  requires it.
- `ui/sam_workflow.py` — `SamWorkflowMixin`, containing `MainWindow`'s SAM
  backend probing, setup/download, segmentation, propagation/re-track,
  heartbeat, and weight-cleanup orchestration.
- `ui/main_window_utils.py` — pure helper/constants split out of `MainWindow`:
  mask palette, supported media extensions, time/color formatting, SAM
  propagation-window math, and orphan-mask cleanup. `main_window.py` re-exports
  these names for compatibility.
- `ui/branding.py` — header/About identity helpers: theme-matched SVG mark
  rasterization and bundled Space Grotesk wordmark font loading. `main_window.py`
  imports these helpers so existing compatibility imports keep working.
- `ui/export_worker.py` — background export execution. The exporter import stays
  inside `ExportWorker.run()` so importing the main window does not load ffmpeg
  composition code. `main_window.py` re-exports the class for compatibility.
- `ui/export_workflow.py` — `ExportWorkflowMixin`, containing `MainWindow`'s MP4
  export, caption export, export history, reveal, progress, and report-writing
  controller methods.
- `ui/history.py` — `HistoryMixin`, containing `MainWindow`'s dirty-state,
  autosave, compact undo/redo snapshot, history-size bookkeeping, and snapshot
  restore controller methods.
- `ui/canvas.py` — `VideoGraphicsView` and `AnnotationGraphicsItem`.
- `ui/sam_workers.py` — SAM worker QObjects.
- `ui/sam_panel.py` — SAM controls, tracked-mask list, and propagation settings.
  `main_window.py` re-exports `SamPanel` for compatibility.
- `ui/labels_panel.py` — annotation list, selected-annotation inspector, and
  built-in/custom label presets. `main_window.py` re-exports `LabelsPanel`.
- `ui/dialogs.py` — SAM setup, storage location, PHI review, export checklist,
  export settings, and export history dialogs. `main_window.py` re-exports
  these names for import stability.
- `ui/editor_panels.py` — `TimelineCanvas` + `RichTimelineWidget` (the actual
  scrollable timeline with trim handles, fade controls, cut), plus
  `SlideEditorPanel`, `SlidePreview`, `TipsPanel`, `AudioPanel`. Cut splits a
  clip into two pieces sharing the same source path.
- `ui/tutorial.py` — `TutorialOverlay` coach-marks. Steps resolve target
  widgets at display time and can prepare the next hands-on action with
  `on_enter`; an action-selection step must not preselect the same control it
  asks the user to click.
- `ui/styles.py` — color tokens + global QSS.

### Tool routing in `VideoGraphicsView`

A single `mousePressEvent` dispatches by **panel context first, then
`project.active_tool`**:

1. Slides panel open + click in slide title/body rect → drag slide text.
2. `sam` tool → emit point.
3. `rect` / `ellipse` / `arrow` / `redact` → drag-to-create with live preview.
4. `text` → click-to-place.
5. `select` → hit-test annotations: handle drag → resize, body drag → move.

A completed move/resize (select-drag or slide-text drag) emits
`VideoGraphicsView.edit_committed`, which `MainWindow._commit_canvas_edit` turns
into exactly one undo snapshot. During the drag only `annotation_mutated` fires
(marks dirty + light refresh, no history) so the gesture is a single undo step.

Selection state lives on `project.selected_annotation_id` (round-tripped via
undo). `LabelsPanel` and `VideoGraphicsView` both read/write it and re-sync
each other through signals.

### PHI redaction & de-identification

The `redact` annotation type is the PHI tool. It reuses rect geometry but is
treated specially everywhere:

- **Defaults (`_build_drag_annotation`)**: opaque black, `frame_time=0` +
  `ann_duration=0` so it covers the **whole timeline** by default (over-redact
  is the safe default; shorten the window in the Labels panel if needed).
- **Always burned last and on top.** Both the live canvas
  (`AnnotationGraphicsItem._paint_redactions`) and the exporter
  (`ProjectExporter._paint_redactions`) draw redactions opaque in a final pass,
  after every other annotation and the fade — never via the normal shape path
  (which `continue`s on `redact`). Don't move redaction painting earlier.
- **Forces re-encode.** Because a redaction is a visible annotation,
  `_segment_needs_render` returns True for any segment it overlaps, so the fast
  stream-copy path can't emit original PHI frames. `tests/test_redaction_export.py`
  locks both properties (pixels blacked out + segments re-rendered).
- **Take Still** reuses `_render_frame`, so captured stills inherit redactions.

Other PHI safeguards:
- **Metadata is stripped** from every ffmpeg output (`-map_metadata -1
  -map_chapters -1`) so source creation time / device / GPS never reach the MP4.
- **Source audio** can be dropped on export via
  `ExportSettings.mute_source_audio` (Export dialog → Privacy checkbox); narration
  added on the Audio panel is kept.
- `project_preflight_warnings` nudges toward the Redact tool when reviewable
  media exists, PHI review isn't confirmed, and no redactions are present.

### Files to ignore

- iCloud sync conflict copies (`__init__ 2.py`, `__main__ 2.py`,
  `video_probe 2.py`, etc.) are `.gitignore`d. The stray copies under `src/`
  were physically removed on 2026-06-14; if iCloud regenerates any, don't
  import or edit them.


## Optimization Automation Memory

- **Last implementation:** 2026-11-16 (v0.5.17-alpha) — export per-frame decode
  (`exporter._frame_for_clip`) reads CFR frames forward instead of re-seeking,
  and `AudioPreview.sync` caches narration-file existence for one second instead
  of `stat`-ing every track per playback tick.
- **Last reviewed:** 2026-11-17 (HEAD `947503b`) — incremental run over
  `e1b0839..947503b`, the NE-012–NE-031 ticket wave shipped in v0.5.17-alpha
  (`2343eb6`): 74 files, +10.6k/-3.0k. Deep-dived the perf-relevant changes
  (`exporter.py` overlay transform + cross-volume publish + ffmpeg resolution,
  new `ui/edit_gesture.py`, `HistoryMixin._flush_pending_edits`, `_frame_for_clip`
  decode path). No new findings: the wave was already multi-agent reviewed for
  correctness and self-benchmarked (NE-026 export decode / static composition).
  The three 2026-11-13 items stay open (the diff touched `editor_panels.py` /
  `models.py` but did not address them). The `AudioPreview.sync` per-tick `stat`
  item was already fixed 2026-11-16.
- **Prior incremental review (2026-11-15, `e1b0839`, unchanged):** second
  consecutive empty-diff run; no new findings; four open items carried forward.
- **Prior incremental review (2026-11-14, `e1b0839`):** incremental run with an
  empty code diff — no new commits and no manual code edits since the 2026-11-13
  review. No new findings; the four open items re-confirmed and carried forward.
- **Prior incremental review (2026-11-13, `e1b0839`):** incremental run over
  `3e00fc0..HEAD` (single commit: v0.5.15-alpha ripple overlay fix NE-010/NE-011).
  Deep-dived the new `models.py` redaction-ripple helpers (`_ripple_redaction`,
  `move_redactions_with_clips`, `timeline_positions` / `restore_timeline_positions`,
  `_shift_mask_frames`) and the `editor_panels.py` trim-drag rewind path. Three
  findings filed (see TODO "2026-11-13 incremental run"): double rewind per trim
  mouse-move (`_rewind_trim_drag` called both in `mouseMoveEvent` and inside the
  apply methods); reorder re-places only redactions, not other annotations/markers
  (possible gap — confirm intent); and a minor one-shot sort in
  `move_redactions_with_clips` when no redactions exist.
- **Prior full-sweep (2026-11-12, `3e00fc0`):** deep-dived `fdce351..HEAD`
  (v0.5.6→v0.5.14: timeline reorder/drag, labels-in-timeline, narration recording
  rewrite, background media-import probing, brush annotation, video-transition
  last-frame hold, keep-in-place external media). Filed the per-tick narration
  `stat` finding in `AudioPreview.sync` (fixed 2026-11-16: one-second cache,
  immediate checks on seek and source change). Phase 6 modularization
  remains complete; keep future splits ownership-driven rather than
  line-count-driven, and keep a true pre-`to_dict()` undo shortcut deferred
  unless the model gains a trustworthy document revision signal.
- **Mode:** incremental going forward. Next review should deep-dive files changed
  after `947503b` plus one hop. (Full-sweep baselines: `22085f9` 2026-06-17 and
  `3e00fc0` 2026-11-12.)
- **Out-of-scope paths:** `desktop/dist/` and any build output; `*.lock`;
  `.venv/` (symlinked into iCloud, see venv note); vendored deps; iCloud
  conflict copies (`* 2.py`, `.gitignore`d).
- **Known false positives / intentionally not optimized:**
  - `AnnotationGraphicsItem.paint` (`ui/canvas.py:86+`) allocates
    `QColor`/`QPen`/`QBrush`/`QFont` from string literals per paint — idiomatic
    Qt; the overlay only repaints on annotation change or playback tick, so
    caching pens is a micro-optimization with marginal payoff. Skip.
  - `_clip_at_time` / `_slide_at_time` linear scans per playback tick are O(n)
    but n is small (a few dozen clips); not worth an index until projects grow.
  - Historical per-session test counts in HANDOFF (§ entries) are left as
    written by prior sweeps — do not "correct" 117/118 there.
  - `ui/dialogs.py` (`873b74d`) is a verbatim mechanical move of dialog code
    that was already reviewed in the `22085f9` full sweep — no new findings.
    Skip re-reviewing it unless its logic (not just its location) changes.
  - Identity rendering (`_render_svg_pixmap` / `_restyle_identity`, §37) re-rasterizes
    the mark SVG on theme toggle and on every About-dialog open. Both are rare,
    user-driven events (not a paint/playback path), so caching the pixmap by
    (theme, size, dpr) is a marginal win — skip, same rationale as the per-paint
    Qt allocations below.
  - §36 overlay-slide change adds no per-tick cost: `_tick_timeline_playback`
    computes `active_slide`/`next_slide` once and reuses them; net `_slide_at_time`
    calls per tick are unchanged (still ~2). Don't re-flag it as new scan cost.
  - §35 invalid-media recovery handles terminal `NoMedia`/`InvalidMedia` status in
    `_media_status_changed`. Qt6 sets that status on load failure (alongside
    `errorOccurred`), so the status handler covers the unloadable-clip case; a
    separate `errorOccurred` slot would be redundant — not a gap.
  - Autosave snapshot reuse (`6700b67`) was audited for the stale-snapshot risk:
    all five `self.dirty = True` sites live in `main_window.py` and each either
    refreshes `_autosave_snapshot` (the history push) or nulls it; no other
    module sets `dirty` directly (panels route through `_mark_dirty`). The
    shallow-copy snapshot shares nested dicts with the cached autosave dict, but
    neither is mutated in place, so the aliasing is safe. No correctness issue,
    no new finding — don't re-audit unless a new `dirty` write path is added.
  - `TimelineCanvas.paintEvent` (`ui/editor_panels.py:354`) already caches the
    whole static layer in a QPixmap keyed by `_static_fingerprint`, which
    deliberately omits `current_time`; per-tick playback only repaints the
    playhead + snap indicator over the cached pixmap. `_annotation_lanes`,
    `_slide_lanes`, and `_slide_lane_count` are memoized on geometry signatures.
    This is the §44/§45 repaint-reduction work — do not re-flag timeline paint
    as per-tick scan cost.
  - `VideoGraphicsView._video_frame_changed` (`ui/canvas.py`) copies each decoded
    frame into `_last_video_frame`, but `QVideoFrame` is implicitly shared
    (ref-counted); rasterization to a QPixmap happens only in
    `begin_video_transition` (a source cut), never per frame. Not a per-frame
    cost — skip.
  - `project_end_time()` is called O(annotations) per *static* timeline render,
    but that render only runs on edits (cache miss), and `_tick_timeline_playback`
    uses the cached `MainWindow._project_end_time()`. Playback is unaffected; not
    worth threading a cache through `TimelineCanvas`.
  - Export per-frame decode (`exporter._frame_for_clip`) already avoids the
    NE-026 benchmark's seek-per-frame cost for constant-frame-rate sources: it
    trusts OpenCV's CFR index and reads frames forward (`read_forward` /
    `cap.grab()` for a 0–2 frame skip) rather than re-seeking each frame, falling
    back to timestamp seek only for true VFR files or large jumps. The
    `benchmark_export_decode.py` 5× seek-vs-sequential gap is the worst-case VFR
    cost, not the common path — do not re-flag export decode as a caching/seek
    optimization. (NE-026 also measured static composition and chose no new cache.)
- **Architecture notes (high-signal):**
  - Narration recording (v0.5.14, `ui/audio_panel.py`) now waits for
    `QMediaRecorder` `StoppedState` before probing the *recorded file's* real
    duration (`_probe_audio_duration`, wav-header or ffmpeg), instead of using
    monotonic elapsed; it handles recorder errors, project-change-mid-recording,
    and zero/non-finite durations. `recording_pending` blocks app close.
    Zero-duration audio tracks are now valid placeholders (duration input min is
    0.0), consistent with the "ignore inactive audio" export/preflight rules.
  - Narration *preview* during playback lives in `ui/audio_preview.py`
    (`AudioPreview`): per-track `QMediaPlayer`+`QAudioOutput`, synced from
    `_tick_timeline_playback`. Players are created/torn down as tracks enter/leave
    the active window; `QAudioOutput` volume is clamped 0..1 (export can amplify
    to 2). File existence checks use a one-second cache during continuous playback
    and refresh immediately on seek or source change.
  - Audio import duration probing runs in a single Python executor worker; a GUI
    timer commits the result only for the original, unchanged document. Cancel
    discards results; an already running probe finishes before its Python thread
    exits. Window teardown stops polling, so late results cannot mutate a closed
    project. The insertion time is captured before probing.
  - Media import probing runs off-thread: `MediaImportWorker`
    (`ui/media_import_worker.py`) on a `QThread`, probing each path and
    re-stat-ing before/after to discard metadata if the file changed mid-probe.
    Thread lifecycle (started→run, finished→quit/deleteLater) is wired in
    `main_window._import_media_files`.
  - Redaction ripple (v0.5.15, NE-010/NE-011, `models.py`): on a ripple edit
    `ProjectState.ripple_after` routes `type == "redact"` annotations through
    `_ripple_redaction` (covered footage stays covered; a redaction grows over
    footage revealed at the edit point; a finite window never collapses to 0,
    which means "to end of timeline"). Clip reorder routes them through
    `move_redactions_with_clips`, which re-places each redaction to the smallest
    single window still holding all its covered footage (so a redaction spanning
    now-non-adjacent clips widens rather than exposing either piece). Trim drags
    snapshot the whole timeline at press via `timeline_positions()` and re-apply
    one ripple from that state per mouse move (`restore_timeline_positions` +
    `_rewind_trim_drag`), so the result is independent of the drag path; a trim
    drag dropped on the trash deletes the clip as it was at press. Non-redact
    annotations/markers are NOT re-placed on reorder — only on ripple trims via
    `ripple_after` — see the open TODO item questioning whether that is intended.
  - New `brush` freehand annotation type: stored as normalized `points` in
    `geometry`, painted as a round-cap/round-join polyline in both the live canvas
    (`ui/canvas.py:_paint_brush`) and the exporter (`exporter.py:_paint_brush`);
    hit-test is per-segment distance. Keep canvas/export paint in parity.
  - Undo/redo = full `ProjectState.to_dict()` JSON snapshots (cap 50 entries and
    64 MiB of compact serialized bytes), deduped
    by BLAKE2 hash. `_push_history()` builds `to_dict()` once and caches the full
    dict in `_autosave_snapshot`;
    autosave (2 s when dirty) reuses it via `ProjectStore.save_data(dict)` when
    still valid, so the third independent serialize is gone on the common
    push-then-autosave path. As of 2026-07-11, a cached no-op push also skips
    the compact JSON/hash pass when the current dict matches `_autosave_snapshot`.
    Compact byte storage, the 64 MiB cap, and fixture measurement are complete;
    only a true pre-`to_dict()` short-circuit remains open, and only if it can
    be proven without broad mutation bookkeeping.
  - Modularization is past the Phase 6 line-count target: `main_window.py`
    ~2,384 lines (down from ~6,500); canvas → `ui/canvas.py`, SAM workers →
    `ui/sam_workers.py`, SAM workflow → `ui/sam_workflow.py`, export workflow →
    `ui/export_workflow.py`, dialogs → `ui/dialogs.py`, export worker →
    `ui/export_worker.py`, branding → `ui/branding.py`, utility helpers →
    `ui/main_window_utils.py`, audio → `ui/audio_panel.py`, project library →
    `ui/project_library.py`, all re-exported from their origin module where
    compatibility requires it. `ui/history.py` owns dirty-state, autosave, and
    undo/redo snapshot controller methods. Future splits should be
    ownership-driven rather than line-count-driven.
  - Slider/text undo-coalescing (v0.5.17, `ui/edit_gesture.py`): `EditGesture`
    mirrors the canvas's `annotation_mutated`/`edit_committed` for panel widgets —
    live mutations emit `changed` (history-less dirty mark), and the gesture ends
    (idle timer, focus-out, or source switch) emits `committed` (one undo
    snapshot). `CommitTextEdit` adds the missing `editingFinished` to `QTextEdit`.
    `HistoryMixin._flush_pending_edits` runs before any document-replacing action
    (undo/redo/save/project-switch/close): it calls `interpretText()` on every
    spinbox in the audio/slides/labels panels (NE-016: `setKeyboardTracking(False)`
    means typed digits reach the model only on Enter/focus-out, which a menu
    shortcut triggers neither) and commits each panel's open gesture.
  - Playback-loop optimization is partially complete: `MainWindow._project_end_time()`
    caches `project_end_time()` for seek/playback/export and invalidates on
    document edits/project load/undo/redo restores. Playback uses the monotonic
    timeline clock rather than sparse media-position events so VFR recordings
    keep smooth playhead motion. Still open: measure and reduce redundant
    annotation repaint work; decoded-frame changes must not gate playhead refresh.
  - Project replacement now confirms unsaved edits, blocks only result-producing
    export/SAM jobs, clears media caches, and reseeds undo/redo history for the
    loaded document. Do not reintroduce a trailing dirty-mark on project open.
  - Deferred-seek state machine (§30b): a seek issued right after `setSource()`
    is silently dropped because the media isn't loaded, so a trimmed clip would
    play from 0 instead of `trim_start`. On a **fresh** source
    `_sync_player_to_timeline` stashes `_pending_seek_ms`/`_pending_play` and
    `pause()`s; `_media_status_changed` applies the seek (and plays if still in
    playback) once status is `LoadedMedia`/`BufferedMedia`. While
    `_pending_seek_ms` is outstanding both `_position_changed` and
    `_tick_timeline_playback` bail. Terminal `NoMedia`/`InvalidMedia` statuses
    clear the pending seek/play state so an unloadable source releases the
    timeline clock.
  - Finder drag-and-drop (§32) and file-dialog imports (§43):
    `MainWindow.setAcceptDrops(True)` +
    `dragEnterEvent`/`dropEvent`; `_dropped_media_paths` filters local files by
    `VIDEO_EXTENSIONS | IMAGE_EXTENSIONS`; each accepted path routes through the
    same `_import_media_files` helper as File -> Import Video, File -> Import
    Image, and single-file Media Explorer imports. A batch import loads one
    preview, selects the last successful clip, and creates one dirty/history
    operation; multi-video batches also share the §42 metadata progress dialog.
  - Published baseline suite is **723 tests** (Claude-verified and tagged v0.5.18-alpha
    macOS CI-verified on 2026-11-17: 723 passed in 102.41 s, clean exit; see HANDOFF).
    The gate is
    `ruff check src tests scripts` + `python -m pytest tests/ -q`, both green at
    the last release marker. The NE-012–NE-031 wave added the export,
    undo-coalescing, caption-PHI, tutorial-safety, lifecycle, and
    version-consistency suites. Informational Windows CI remains blocked by the
    `QSettings.fileName()` forward-slash vs backslash fixture assertion (NE-027
    follow-up); it does not gate releases.
  - torch/SAM stack is lazy by design (venv has no torch → SAM no-ops); the
    cold-start import audit is complete and keeps the exporter out of the normal
    startup module graph.
  - Identity assets (§37/§38): header + About lockups use theme-matched SVG marks
    (`neuroedit-mark-{light,dark}.svg`) rasterized at DPR via `_render_svg_pixmap`;
    `_restyle_identity` re-renders them on theme change. The wordmark font is the
    bundled Space Grotesk TTFs under `resources/fonts/`, loaded once (guarded by
    `_wordmark_fonts_loaded`) via `QFontDatabase.addApplicationFontFromData`;
    `_wordmark_font()` falls back to the app font if the family fails to register.
    Regenerate packaged icons with `scripts/generate_icons.py` from
    `resources/neuroedit-appicon.svg`.

## In-app updater (2026-11-17, v0.5.19-alpha)

`update_release.py` validates the fixed GitHub release/asset schema and versions;
`update_service.py` handles Qt HTTPS and streaming digest verification;
`update_install.py` stages and hands off platform installation;
`ui/update_dialog.py` is presentation only; `ui/update_workflow.py` coordinates
explicit user actions with the normal save/close flow. No startup network check.
Read `docs/IN_APP_UPDATES.md` before modifying updater, build-tag metadata, or
installer restart behavior. Keep helper launch after all save/close rejection
branches and before native worker shutdown can force process exit.
