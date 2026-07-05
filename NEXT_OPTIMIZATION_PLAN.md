# NeuroEdit Next Optimization + Feature Refinement Plan

## Goal

Make the current alpha feel fast, polished, and clinically trustworthy while folding
in the Figma brand system without destabilizing the recently shipped P1–P4 workflow.
This plan deliberately prioritizes finish, performance, and visual consistency over
large new integrations. The Stryker/DICOM work remains parked until sample data is
available.

## Current baseline to protect

- The roadmap has shipped the core editing workflow: timeline selection/snapping,
  the mask workflow, PHI review, captions, export history, and advanced export
  settings.
- Remaining roadmap blockers are owner/release-channel decisions: deciding repository
  privacy and deciding when to add signing and notarization. macOS DMG launch
  verification is already part of the owner's active workflow, so this plan does
  not treat it as a new blocker.
- The desktop UI already has a centralized dark palette/QSS, a header logo slot,
  a wordmark in the About dialog, and resize-safety logic that prevents clipped
  side panels.
- Performance work has already started in the right places: SAM propagation frame
  loading, overlay cache bounds, deferred canvas refreshes during drags, memoized
  timeline painting, and project-library metadata reads.

## Phase 1 — Release confidence and baseline measurement

**Why first:** smoothness work needs a measured baseline, and brand changes are easier
to judge when the app can be launched and tested consistently.

1. **Keep packaged-build smoke testing focused on gaps, not already-covered work.**
   - Treat macOS DMG launch/import/scrub/export checks as already covered by the
     owner's ongoing QA loop; keep noting regressions, but do not make this a new
     planning blocker.
   - Prioritize the Windows installer runtime pass at 100%, 125%, and 150% display
     scaling because Windows UI verification is still the unresolved packaged-build
     gap.
   - Capture baseline screenshots for the header, timeline, right panels, dialogs,
     project library, export completion, SAM setup/missing-backend state, and PHI
     review stepper before applying the new design language.

2. **Add lightweight performance instrumentation for manual QA.**
   - Add a dev-only diagnostics toggle that logs timeline paint time, canvas paint
     time, project-load time, export startup time, and SAM job queue state.
   - Store logs outside project media folders and avoid PHI-bearing paths by default.
   - Acceptance: a tester can reproduce a “feels sluggish” report with timestamps
     and the active view/panel, without attaching patient content.

3. **Create a repeatable “smoothness fixture” project.**
   - One short 1080p clip, one 4K clip, several annotations, slides, captions,
     masks, audio, and a few missing-media cases.
   - Acceptance: QA can compare cold launch, project open, scrubbing, annotation
     dragging, panel switching, and export startup across builds.

## Phase 2 — Figma brand-system integration

**Why second:** the app already has styling tokens, so convert Figma decisions into
centralized code before touching individual widgets. Use the owner's Figma Make
concept, [Redesign video editing app UI](https://www.figma.com/make/EwIb4hEXiKH6uq5NipTXEr/Redesign-video-editing-app-UI?t=GISE85bHg74npOdT-6),
as the source of truth for the app's refreshed video-editor design language.

1. **Translate the Figma Make design language into implementation rules.**
   - Capture the concept's visual grammar as a short in-repo design brief: dark
     editor canvas, clean high-contrast controls, modern rounded panels, clear
     hierarchy between media/timeline/inspector areas, branded accent usage, and
     restrained clinical trust cues.
   - Map the concept to concrete NeuroEdit surfaces: header, transport controls,
     media/project library, timeline tracks, inspector panels, SAM mask list, PHI
     review, caption controls, export dialogs, and empty/error states.
   - Acceptance: every planned UI change can point back to a Figma frame/section and
     an implementation token or component target.

2. **Extract Figma brand tokens into code.**
   - Define the canonical color palette, typography scale, spacing scale, corner
     radii, elevation/border rules, icon sizes, and state colors.
   - Replace one-off inline styles where practical with named semantic tokens such
     as `surface`, `surfaceRaised`, `accentPrimary`, `accentClinical`, `textMuted`,
     `borderSubtle`, `focusRing`, `danger`, and `warning`.
   - Acceptance: changing a brand color in one token file updates buttons, panels,
     timeline selection, status UI, and dialogs consistently.

3. **Refresh app identity surfaces.**
   - Update the header logo treatment, About dialog wordmark, installer assets,
     app icons, and release screenshots from the approved Figma exports.
   - Add an asset checklist that records source Figma frame name, export size,
     file path, and whether the asset is used on macOS, Windows, or in-app only.
   - Acceptance: no placeholder identity remains in the normal app path.

4. **Run an accessibility/color audit.**
   - Check contrast for text, disabled controls, warnings, PHI confirmations,
     timeline selected state, SAM mask colors, and caption previews.
   - Keep red reserved for destructive/privacy risk states and avoid red SAM masks,
     matching the existing palette direction.
   - Acceptance: every major text/control state meets target contrast in screenshots
     and destructive states are visually distinct from primary actions.

## Phase 3 — Smoothness and interaction polish

**Why third:** after the brand surface is stable, optimize the interactions users feel
on every edit.

1. **Timeline and canvas responsiveness.**
   - Add a paint budget target: timeline and canvas interactions should stay under
     16–33 ms per frame during common drags on the QA fixture.
   - Cache static timeline layers separately from moving playhead/selection layers.
   - Avoid full panel refreshes during scrubs, drags, and playhead movement.
   - Acceptance: annotation drag, timeline scrub, marker drag/edit, and zoom-to-fit
     feel immediate on the fixture project.

2. **Panel switching and layout stability.**
   - Precompute right-panel minimum widths after Figma spacing updates so the app
     keeps the current no-clipping guarantee.
   - Shorten or restructure wide labels and multi-button rows if the target design
     should support a narrower minimum window than the current content-driven floor.
   - Acceptance: no horizontal panel scrollbar at supported window sizes, including
     high-DPI Windows.

3. **Background work and progress clarity.**
   - Keep thumbnail generation, media probing, SAM warmup/download, SAM propagation,
     and export work off the UI thread.
   - Add consistent cancellable progress components for long jobs.
   - Disable or clearly mark controls that cannot safely run while a SAM job or
     export is active.
   - Acceptance: no app freeze during imports, thumbnail loading, SAM setup, SAM
     tracking, or export startup.

4. **Microinteractions that make the editor feel premium.**
   - Add subtle hover/focus/pressed states from Figma tokens for toolbar buttons,
     panel tabs, list rows, timeline blocks, and context menus.
   - Add a visible snap guide line and keyboard-delete of selected timeline items,
     both already deferred from P1.
   - Add marker dragging only after the paint-budget work proves timeline updates
     are cheap enough.
   - Acceptance: interactions communicate state immediately without adding visual
     clutter or clinical-risk ambiguity.

## Phase 4 — Workflow refinement before new platform bets

**Why fourth:** these are small trust and retention improvements that matter more than
large integrations before broader alpha testing.

1. **Project Library polish.**
   - Keep thumbnails, relative timestamps, duration/media counts, missing-media
     warnings, and reveal actions as a first-class entry point.
   - Add search/filter and sort by recent/name/missing-media if testers accumulate
     enough projects to need it.
   - Acceptance: a returning tester can find the right case in under five seconds.

2. **SAM workflow follow-ups.**
   - Stamp `sam_last_run` for single-frame segmentation, persist track-window UI
     preferences, disable mask-list rows while a SAM job is running, and decide
     whether to remove the auto-shown setup dialog now that the inline explainer
     exists.
   - Acceptance: SAM setup/status feels like one coherent flow, not two competing
     prompts.

3. **PHI/storage follow-ups.**
   - Persist guided-review progress per stop, not just final completion.
   - Provide a safe migration flow when the storage root changes.
   - Acceptance: users can pause/resume PHI review and move storage without losing
     confidence in what has been reviewed.

4. **Caption/export refinement.**
   - Evaluate Intel Mac support only if testers need it.
   - Add export preset recommendations based on source resolution and intended use
     after the packaged-build smoke pass.
   - Acceptance: the default export path stays simple, with advanced controls hidden
     unless needed.

## Phase 5 — Brand QA and release packaging

1. **Create a visual regression checklist from Figma.**
   - Header, toolbar row wrapping, primary/secondary/danger buttons, right panels,
     dialogs, timeline states, project library rows, SAM mask list, PHI checklist,
     captions preview, export completion, and empty/error states.

2. **Package assets and documentation.**
   - Update release notes and screenshots after brand integration.
   - Make owner decisions on repository privacy and code signing/notarization before
     widening tester distribution.

3. **Gate every release candidate.**
   - `ruff check src tests scripts`
   - `python -m pytest tests/ -q`
   - owner's ongoing packaged macOS smoke notes reviewed for regressions
   - packaged Windows smoke test
   - visual QA against Figma checklist

## Phase 6 — Code health and runtime cost

**Why now:** Phases 1–5 shipped the brand system, smoothness caching, and the
workflow refinements. The remaining roadmap work is owner/hardware-blocked
(packaged-build smoke, signing, Stryker sample data), so the highest-leverage
engineering work left is structural: keep the codebase cheap to change and
cheap to run. Every item below is measurement-first and behavior-preserving —
the 144-test suite and `ruff` must stay green with no unintended user-visible change.

1. **Modularize `ui/main_window.py` (currently ~4,240 lines, down from ~6,500).**
   - `main_window.py` holds `MainWindow` plus `VideoGraphicsView`,
     `AnnotationGraphicsItem`, four SAM worker `QObject`s
     (`SamProbeWorker`/`SamSegmentWorker`/`SamPropagationWorker`/`SamDownloadWorker`),
     and most other dialogs — a single file that is hard to navigate and risky
     to edit. The Project Library dialog + `ThumbnailWorker` were extracted to
     `ui/project_library.py` (2026-06-14), and the canvas graphics classes plus
     SAM worker QObjects were extracted to `ui/canvas.py` and `ui/sam_workers.py`
     (2026-06-16).
   - Extract by responsibility into sibling modules under `ui/` (e.g.
     `ui/canvas.py` for the graphics view + annotation item and
     `ui/sam_workers.py` for the worker QObjects), re-exporting names from the
     original module so existing imports keep working.
   - Pure mechanical moves only — no logic changes — so the diff is reviewable
     and the suite proves equivalence.
   - Acceptance: no single `ui/` module over ~2,500 lines; tests and `ruff`
     green; the rendering hot path can be read and profiled in isolation.
   - Done 2026-06-15: `AudioPanel` was extracted from `ui/editor_panels.py` to
     `ui/audio_panel.py`, shared timeline helpers moved to
     `ui/timeline_utils.py`, and `editor_panels.py` is now ~2,245 lines.
   - Progress 2026-06-16: `main_window.py` now re-exports `VideoGraphicsView`,
     `AnnotationGraphicsItem`, and the four SAM worker classes from sibling
     modules.
   - Progress 2026-06-17: `main_window.py` now re-exports the SAM setup, storage
     location, PHI review, export checklist, export, and export history dialogs
     from `ui/dialogs.py`. Remaining modularization target: the still-large
     `MainWindow` class.
   - Progress 2026-07-03: `ExportWorker` moved to `ui/export_worker.py` and is
     re-exported from `main_window.py`. This preserves the lazy export-pipeline
     boundary; the still-large `MainWindow` class remains the primary target.
   - Progress 2026-07-04: `SamPanel` moved to `ui/sam_panel.py` and is
     re-exported from `main_window.py`. The move is mechanical; the focused SAM
     workflow suite and import-compatibility probe preserve existing behavior.
   - Progress 2026-07-05: `LabelsPanel` and its preset persistence moved to
     `ui/labels_panel.py`; `main_window.py` re-exports the class and imports the
     shared preset definitions. The headless panel suite and an identity probe
     preserve existing behavior and import compatibility.
   - Progress 2026-06-19: `MainWindow` gained a cached project-end-time helper
     used by seek/playback/export and invalidated on document edits/project
     loads. This addressed the playback loop's per-tick `project_end_time()`
     scan without changing playback semantics; repaint throttling remains open.
   - Progress 2026-06-21: the recent-project open path now clears the cached
     project end time immediately after swapping projects, matching the sibling
     open/new paths and preventing future pre-dirty reads from seeing stale data.
   - Correctness fix 2026-06-21: the monotonic timeline clock now advances the
     playhead during video playback instead of allowing sparse
     `QMediaPlayer.positionChanged` events to drive it. This keeps
     variable-frame-rate screen recordings smooth while avoiding per-tick
     reseeks when the same video clip remains active.
   - Correctness fix 2026-06-22: terminal `NoMedia`/`InvalidMedia` statuses now
     clear deferred seek/play state so a source that cannot load cannot leave
     the timeline clock permanently blocked.
   - Correctness fix 2026-06-22: overlay slides no longer pause or repeatedly
     resync the underlying video player. Full-frame slides retain their existing
     blocking behavior.
   - Completed 2026-06-27: the monotonic clock still refreshes the playhead each
     tick, while canvas repaint requests are limited to changes in annotation or
     tracked-mask visibility, slides, caption cues, and fade opacity. A
     deterministic 10 s synthetic sample dropped from 300 canvas repaint
     requests to 1.

2. **Reduce undo/redo snapshot cost.**
   - Undo/redo stores full `ProjectState.to_dict()` copies (cap 50) and can hold
     many MB across the undo + redo stacks for mask-heavy or long-transcript
     projects. Dedup by full-dict `==` was replaced with a cheap BLAKE2 content
     hash (2026-06-14), but `_push_history` still builds the entire snapshot
     (`to_dict()`) and then runs a *second* full `json.dumps` over it for the
     hash on every dirty tick *before* the hash decides whether to keep it — so a
     net-zero edit pays two O(project size) serializes. Autosave then serializes
     the same `ProjectState` a third time (`store.save`, every 2 s when dirty).
   - Options still to evaluate (pick the simplest that measures well): a cheaper
     change-check ahead of the full serialize; a single shared per-dirty-tick
     serialization reused by both the history hash and autosave; store compact
     JSON strings rather than nested dicts; or cap the stacks by cumulative size
     in addition to the 50-entry count. Keep the existing transient-key stripping.
   - Measure before/after on the smoothness fixture with the diagnostics log
     (snapshot time around an annotation drag; resident memory after 50 edits).
   - Acceptance: no behavior change to undo/redo semantics; lower per-edit
     snapshot time and bounded memory on the fixture; undo-history tests green.
   - Progress 2026-06-18: history pushes now cache the full project dict they
     already build and the next autosave reuses that dict if no later UI-only or
     direct dirty change invalidates it. `ProjectStore.save_data()` keeps the
     existing JSON output format while avoiding a repeated `to_dict()` on that
     autosave. Remaining work: pre-serialize short-circuit, compact history
     storage, cumulative-size cap, and smoothness-fixture timing/memory
     measurement.
   - Progress 2026-07-01: undo history now records the compact JSON byte size
     produced for each snapshot hash and evicts oldest states when the stack
     exceeds 64 MiB, in addition to the existing 50-entry cap. The current state
     is always retained.
   - Progress 2026-07-02: undo/redo stacks now retain the compact JSON payload
     instead of a second nested-dictionary representation. Across 50 edits on
     the generated smoothness fixture, traced retained memory fell from 0.631 MiB
     to 0.400 MiB (36.6%); median push time remained flat at 0.640 ms before and
     0.629 ms after. Autosave reuse remains dictionary-based and unchanged.
     Remaining work: evaluate a pre-serialize short-circuit without weakening
     document-change detection.

3. **Audit cold-start import cost. — ✅ DONE 2026-06-29.**
   - `__main__.py` → `MainWindow` pulls in the full module graph eagerly. Confirm
     heavy or rarely-needed imports (subprocess/ffmpeg helpers, captions, export)
     are deferred where they are only used on demand, keeping the `[sam]`/torch
     stack optional as documented in `CLAUDE.md`.
   - Use the diagnostics project-load/startup timing to quantify any change.
   - Result: the export pipeline is now loaded only for export, still capture,
     or export-settings creation. `torch` remains lazy; live-caption helpers
     remain eager because the normal canvas preview uses them. Five-process
     warm import measurements held a 0.17 s median before and after, while the
     exporter (about 45 ms cumulative in the import trace) left the startup
     module graph. Focused export/caption coverage and the full suite stayed green.

4. **Bound batch media-probe feedback. — ✅ DONE 2026-06-24.**
   - Multi-video metadata probing measured 3.3 ms median for 1080p and 9.9 ms
     for 4K on the smoothness fixture, with an 85.8 ms cold outlier. Imports now
     expose determinate per-video progress and log PHI-safe probe timings instead
     of adding a worker lifecycle for these bounded calls.

5. **Housekeeping: drop the iCloud conflict copies. — ✅ DONE 2026-06-14.**
   - `src/neuroedit_desktop/__init__ 2.py`, `__main__ 2.py`, `video_probe 2.py`,
     and `ui/__init__ 2.py` were iCloud sync artifacts (already `.gitignore`d but
     physically present) that confused tooling (`wc`, search) and contributors.
   - The four stray copies were removed; they were not imported, so no real
     module changed. Only the canonical `*.py` files remain under `src/`; tests
     and `ruff` stayed green.

## Recommended immediate next sprint (updated 2026-07-05)

Phases 1–5 shipped (smoothness fixture + diagnostics, the Figma brand system and
tokens, accessibility audit, smoothness caching, and the workflow refinements).
The Phase 6 code-health work is now the active front, since the remaining roadmap
blockers are owner/hardware-bound (Windows installer smoke at 100/125/150 % DPI,
signing/notarization, Stryker sample data). Take the code-health items in order —
each is measurement-first and behavior-preserving:

1. **Continue modularizing `ui/main_window.py`** (now ~3,390 lines after the
   canvas, SAM worker/panel, labels-panel, dialog, and export-worker
   extractions). Split the still-large `MainWindow` class mechanically before
   touching behavior.
2. **Evaluate an undo pre-serialize change check** — compact history storage and
   the cumulative-size cap are complete. Only add a short-circuit if it can prove
   document equality without duplicating mutation bookkeeping or weakening undo.
3. Keep `ruff check src tests scripts` and `python -m pytest tests/ -q` (144 tests)
   green before every release tag; feed any new regressions back into the roadmap.

The unused legacy `TimelineWidget` remains in `main_window.py`; verify that no
external import depends on it before removing it in a separate cleanup.

This keeps the project on a safe optimization loop: measure first, keep the codebase
cheap to change and cheap to run, and only then restart larger feature bets
(Windows packaging hardening, then the parked Stryker/DICOM work).
