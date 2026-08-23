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

This repo contains two apps:

- **Root** (`./`): legacy React/Vite/TypeScript browser prototype. Largely
  superseded — most current work happens in `desktop/`.
- **`desktop/`**: the active native macOS application (PySide6). All commands
  and architecture below refer to the desktop app unless noted.

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

The suite under `tests/` collects **162 tests** (`python -m pytest tests/ -q`).
Keep it and `ruff check src tests scripts` green before every release tag.

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

- `QGraphicsVideoItem` (z=0) — receives output from `QMediaPlayer`.
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

- `models.py` — every dataclass + `to_dict`/`from_dict`. Includes
  `ProjectState.arrange_clips_without_overlap`, an opt-in helper that re-packs
  the video track sequentially. **It is not auto-called from trim/cut paths**
  — those intentionally leave gaps.
- `project_store.py` — JSON load/save with atomic temp-file rename.
- `sam_backend.py` — model loading, frame extraction (OpenCV), and SAM3 with
  SAM1 (`facebook/sam-vit-base`) fallback. Uses `inspect.signature` to filter
  kwargs for cross-version model compatibility.
- `video_probe.py` — fast `probe_video(path) → (duration, w, h)` via ffmpeg.
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
- `ui/tutorial.py` — `TutorialOverlay` coach-marks. Steps are
  `(title, body, target_resolver)` triples; resolver returns a widget at
  display time so dynamically-built widgets work.
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

- **Last implementation:** 2026-08-23 — export duration now uses the same
  positive-duration, positive-volume active-audio criteria as source-media
  preflight and audio muxing, so inactive narration placeholders do not extend
  otherwise visual exports.
- **Last reviewed:** 2026-08-23 — fallback review followed the export/audio
  source handling changed on 2026-08-22. Phase 6 modularization remains complete;
  keep future splits ownership-driven rather than line-count-driven, and keep a
  true pre-`to_dict()` undo shortcut deferred unless the model gains a
  trustworthy document revision signal.
- **Mode:** incremental. Next optimization review should deep-dive files changed
  after the §44 commit plus one hop. (Full-sweep baseline was `22085f9`,
  2026-06-17.)
- **Out-of-scope paths:** root React/Vite prototype (legacy, superseded by
  `desktop/`); `desktop/dist/` and any build output; `node_modules/`; `*.lock`;
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
- **Architecture notes (high-signal):**
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
  - Suite is **155 tests**; gate is `ruff check src tests scripts` +
    `python -m pytest tests/ -q`, both green at this marker.
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
