# NeuroEdit — Session Handoff

## 2026-11-18 — NeuroEdit 1.1 release preparation

- Prepared `v1.1.0` for the export overhaul below. Updated the package version,
  README, and checked-in notes for the existing GitHub installer workflow.
  Skipped local test reruns at the user's request.

## 2026-11-18 — Export rebuilt with one sheet and background progress

- **Ask:** "build and implement" the export review below. Owner decisions taken as recommended:
  the report moves into the project folder, and the frame rate matches the video automatically.
- **Built** by two Sonnet subagents in parallel on separate files, then reviewed and integrated by the coordinator.
- **Shared module** (`desktop/src/neuroedit_desktop/export_plan.py`, new):
  - quality presets;
  - the VideoToolbox bitrate, which also drives the size estimate;
  - the encode-time estimate, using a learned pixel rate;
  - `automatic_fps`, which never opens iCloud-evicted files;
  - non-colliding readable names.

  The exporter's `_hardware_bitrate` uses it.
- **Engine** (`exporter.py`):
  - `-progress pipe:1` streaming progress ("Exporting… 3:12 of 12:41"), monotonic;
  - cancel kills ffmpeg (measured 6–21 ms, was 3.5–5 s);
  - probes are cancel-aware, and the encoder probe is cached per session;
  - checks before encoding: iCloud hydration, writable destination, free space;
  - join + audio mix in one pass into a hidden partial in the destination, then an atomic rename,
    with `+faststart` only on the final file;
  - `ExportError(message, details)` with plain messages naming the clip;
  - `sweep_stale_export_temp()`, wired at startup in `__main__.py` on a daemon thread.
  - The audio-mix input `-ss` was tried and rejected: MPEG-TS sources with a non-zero start time mixed differently.
- **Flow** (`ui/dialogs.py`, `ui/export_workflow.py`, `ui/export_worker.py`, `ui/main_window.py`,
  `ui/tutorial.py`, `models.py`):
  - **One export sheet** (`ExportDialog`; `ExportChecklistDialog` removed):
    - quality radios with "About 1.1 GB · about 2 min on this Mac";
    - remove-original-audio, on by default;
    - captions;
    - More options: frame rate "Automatic (matches your video: N fps)" and audio quality;
    - name + remembered folder (`export/lastFolder`), with "Replaces the existing file" if the name exists;
    - an inline privacy gate, collapsed to "✓ … confirmed" when still valid;
    - non-blocking "N suggestions".
  - The preflight modal, the separate checklist, the save panel, CRF/width/height and the File type combo are gone.
  - ⌘E / File ▸ Export Movie… opens the sheet.
  - **Background export:** the Export button becomes "Exporting 42% · 1 min left"; clicking it offers Cancel Export.
  - **Success:** a status-bar toast with Show in Finder, plus a Dock bounce.
  - **Failure:** one box with Details and Try Again.
  - **Report:** written to `<project folder>/Export Reports/`.
  - **Model:** new field `ProjectState.export_preferences`, round-trips, old projects load.
- **Coordinator fixes:**
  - four `test_regressions.py` stubs updated to the new engine entry points;
  - `scripts/capture_baseline_screenshots.py` now captures the sheet unconfirmed and confirmed,
    instead of the removed checklist;
  - `desktop/CLAUDE.md` updated.
- **Verified:**
  - Full suite: **943 passed** (was 879; 64 new tests across `test_export_plan.py`,
    `test_export_engine_pipeline.py` and `test_export_sheet.py`, plus updates). `ruff check src tests scripts` is clean.
  - **GUI responsiveness during a background export**, measured headless: the 10 ms main-thread
    timer had a p95 of 10.7 ms for an untouched clip and 11.2 ms when every frame went through
    the Python label renderer. The worst single stall was 96 ms.
  - Offscreen screenshots of both sheet states look right.
- **Not verified:**
  - not tried in the running app (no second instance);
  - not tried with real surgical footage, or with multi-GB or iCloud-only media in the app;
  - the Dock bounce and toast placement on a real Mac;
  - Windows, where libx264 makes the size estimate approximate.
- **Gotcha:** macOS evicted the venv again (35,840 dataless files, about 1 GB). The first
  full-suite run hung on a cold import, and the capture test timed out until the files downloaded.
  If tests hang, `sample <pid> 1` and `lsof -p <pid>` show the file being downloaded.
- **Next:** try an export in the installed app with real footage.

## 2026-11-18 — Export pathway review (no code changed)

- **Ask:** review export and make it combine the best of iMovie, Final Cut Pro and
  DaVinci Resolve: efficient, smooth, simple, "just works".
- **Full write-up:** `desktop/docs/export-review-2026-11-18.md`. It covers the measurements,
  17 ranked findings with file:line references, the reference-app patterns to borrow,
  the proposed single export sheet, and the build order.
- **Headline:**
  - The engine is correct.
  - The friction is the flow. Making one file takes five serial modal windows, and the whole app is
    blocked (`ApplicationModal`) while exporting.
  - Progress sits at 0% through untouched segments.
  - Cancel takes 3.5–5 s.
  - Export runs no free-space or iCloud check before it starts, so it can fail late with raw ffmpeg errors.
  - There is no ⌘E and no menu item for exporting video.
  - Output is always 30 fps.
- **Measured** on an M3 Pro:
  - Export runs at about 6× realtime at 1080p, limited by the VideoToolbox encoder (about 200 fps).
  - Running 2–3 encodes in parallel gives no speed-up.
  - On noisy footage, libx264 veryfast is 2.4× *slower* than VideoToolbox and its files are 10× larger.
    Keep VideoToolbox; don't act on the claim that "libx264 is faster", which held only for a clean test pattern.
- **Next:**
  1. Engine work in `exporter.py`: progress with ETA through `-progress pipe:1`, kill-on-cancel,
     checks before encoding for free space, iCloud and write access, a sweep of stale temp
     folders, plain-language errors, and fewer full-file passes.
  2. Flow work in `dialogs.py`, `export_workflow.py` and `main_window.py`: one sheet with the privacy gate
     inline, ⌘E, a remembered location, background export with a toolbar progress pill, and a notification.
  3. Owner decisions: where the export report goes (proposed: the project folder, not
     beside the MP4), and automatic frame-rate matching.

## 2026-11-18 — NeuroEdit 1.0 published

- Published [v1.0.0](https://github.com/v7sm25qk5v-ui/NeuroEdit/releases/tag/v1.0.0)
  from `5f4ca4809b2d2ca8b5e6af6b747fd99cff12a4f2`, annotated tag
  `f5bfb8a99938d8596d18f8a30f75d16c2e7148ab`. GitHub Latest matched the
  checked-in notes. The macOS DMG, macOS ZIP, and Windows installer all
  returned HTTP 200 and have SHA-256 digests. The v0.5.26-alpha.1 updater
  accepted the published macOS ZIP and Windows EXE metadata as an upgrade.
- [Tagged CI](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/44408017785)
  passed 879 macOS tests and built and published both installers.
  [Main CI](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/44408017646)
  passed. The informational Windows suite recorded 853 passes, 19 failures,
  and 7 skips. Seventeen failures matched v0.5.26-alpha.1. Both additional
  failures were variants of `test_copies_bytes_mode_and_times_with_progress`
  asserting POSIX mode `0600` after copying on Windows. The copied bytes
  assertion passed in both variants. Native installed-app testing remains open.

## 2026-11-18 — NeuroEdit 1.0 release preparation

- Prepared NeuroEdit 1.0 with the Save As improvement in `27e80a8`. The
  `v1.0.0` tag and `1.0.0` package version match the version format used by
  the installed updater and Windows packaging. Updated README and added the
  checked-in notes used by the tagged GitHub installer workflow.

## 2026-11-18 — Save As froze the app; rebuilt with one dialog and a progress bar (committed)

- **Report:** saving a project made the app stop responding, and choosing a
  new location "did not let" the user. They asked for a streamlined save to any
  location, with no crash and with a progress bar.
- **Findings:**
  - Save As copied every managed file (imported `media/`, ~2.8 GB here) with
    `shutil.copy2` on the UI thread.
  - Worse, `_migrate_history_payloads` called `_migrate_managed_assets` once per
    undo/redo snapshot. Each call re-copied every video, because a copy is never
    `samefile` with its source. With a deep undo stack that is 100+ GB of
    synchronous copying.
  - `~/Documents` is iCloud Desktop & Documents and the disk is 98% full (12 GB
    free), so macOS had evicted some media to iCloud (`dataless`). Reading those
    downloads them first. `copy2` also copies `st_flags`, which a normal process
    can't set, so a save could fail with "Operation not permitted".
  - The user's interrupted save left `~/Documents/NeuroEdit/bad video example/`
    with project.json and media copies; one copy was 0 bytes at 15:56. That
    folder was not modified.
  - Save As was two prompts: a name text box, then a folder-only picker. That is
    likely the "doesn't let me pick a location" part; not confirmed with the user.
- **Fix:**
  - New `desktop/src/neuroedit_desktop/project_copy.py`: plan (dedupe by
    destination, skip up-to-date copies), free-space check (same-volume clones
    not counted), and a copy that clones on APFS or else copies in 8 MB chunks.
    It copies mode and times only, supports cancel, and on cancel or error
    removes only files it created.
  - `ui/main_window.py`:
    - `_ask_save_destination`: a single `getSaveFileName` dialog that remembers
      the last folder.
    - `_save_project_as`: plan → space check → `_run_save_copy` (worker thread,
      app-modal `QProgressDialog` with bytes, file x of y and an "iCloud" label,
      local `QEventLoop`) → write project.json → rewrite history against the set
      of copies.
    - Replace and non-empty-folder prompts.
    - `_save_in_place` split out.
    - `_save_in_progress` guards against a second save and against closing.
    - `_migrate_managed_assets` gains an optional `copy_file`.
  - Existing tests switched from `QInputDialog` + `getExistingDirectory` to
    `getSaveFileName`.
  - New `desktop/tests/test_project_copy.py`: copier, skip, cancel and error
    cleanup, space check, single dialog, one copy despite 13 undo steps, cancel,
    error reporting and the close guard.
- **Environment gotcha:** 552 repo files and ~36k venv files (1 GB) were also
  evicted to iCloud. Pytest sat in `read()` during collection for 5+ minutes; a
  pytest started at 3:03 PM by another session was stuck the same way and was
  left alone. They were fetched back by reading them in parallel; see the
  CLAUDE.md venv note.
- **Verification:**
  - Ruff clean, and the full suite **879 passed**, 2 existing warnings, 107.7 s,
    on top of `bc6701f` (v0.5.26-alpha.1, released by another session while this
    was in progress).
  - `test_project_copy.py` has 11 tests. The progress dialog runs for real
    offscreen in the window tests.
- **Not verified:**
  - Not tried in the running app, and not with real multi-GB media or a real
    iCloud-only file (a second app instance would race the autosave).
  - The native macOS save panel's look, and APFS cloning across volumes, are
    untested.
- **Next:** try Save As by hand on the "bad video example" case.
  Re-saving into that folder skips the four complete copies and recopies the
  incomplete one. Consider warning when the chosen location is in iCloud.

## 2026-11-18 — v0.5.26-alpha.1 published

- Published [v0.5.26-alpha.1](https://github.com/v7sm25qk5v-ui/NeuroEdit/releases/tag/v0.5.26-alpha.1)
  from `6ed57e3077ae5614c542befdc243538179142161`, annotated tag
  `5ac7c210f8483f4fcbae9c04345b3a7a49bdbb29`. GitHub Latest matched the
  checked-in notes and the public Latest URL resolved to the release. The
  macOS DMG, macOS ZIP, and Windows installer each returned HTTP 200 and
  have GitHub SHA-256 digests. The repository sidebar was not verified because
  browser access timed out.
- [Tagged CI](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/44391141664)
  passed 868 macOS tests, built both installers, and published the release.
  [Main CI](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/44391141390)
  passed. The informational Windows suite had 844 passes, 17 failures, and
  7 skips. Sixteen failures matched v0.5.25-alpha. The additional failure was
  a relative-date boundary assertion in `test_small_lifecycle_items.py`.
  Neither that test nor its implementation changed in this release. No tests
  were run locally at the user's request.

## 2026-11-18 — v0.5.26-alpha release preparation

- Prepared v0.5.26-alpha from the interface refresh in `35ff4b0` (NE-037 through
  NE-040). Updated the package version, README, and GitHub release notes.
  Skipped local test reruns at the user's request. The tag triggers the existing
  GitHub quality and installer workflow.
- The [v0.5.26-alpha workflow](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/44390296521)
  stopped before packaging. macOS had 867 passes and one stale assertion for
  the light theme's canvas color in `test_appearance_action_persists_and_reapplies_theme`.
  The test now checks both configured canvas tokens. Cut `v0.5.26-alpha.1`
  for that correction and retained the original Git tag for traceability.

## 2026-11-18 — Style refresh: palette, steppers, radii, wheel guard

User asked for a style update, logged as NE-037 to NE-040 in `CODING_TICKETS.md`.
The style changes were committed on `main` as `35ff4b0`.

- **NE-037 palette.** `desktop/src/neuroedit_desktop/ui/styles.py` `LIGHT_THEME`
  is now pale watercolor-blue surfaces (`#e6ecf2`/`#f5f8fb`/`#fbfcfe`),
  blue-gray borders and charcoal text/primary (`#25292e`, `#33383e`).
  `DARK_THEME` is charcoal (`#161819`…`#2a2e33`) with a washed-blue primary
  `#8fb4d8` and dark `on_primary` label text. Status hues keep their meaning;
  timeline lanes are blue/sage/lilac/ochre. All pairs were checked against
  every rule in `tests/test_design_tokens.py` before editing. The SAM point
  toggle (`ui/sam_panel.py`) and export audio warning (`ui/dialogs.py`) no
  longer hard-code old dark-palette hex values. The first-run appearance text
  in `__main__.py` and `docs/DESIGN_LANGUAGE.md` were updated. Out of scope:
  the identity mark SVGs, annotation preset colours, SAM mask palette and the
  green/red SAM include/exclude point buttons.
- **NE-038 steppers.** Spin boxes get a stepper column with themed chevron
  SVGs and hover/pressed/at-limit states; combo boxes get a matching chevron.
  QSS needs file URLs for arrow images, so `_chevron_icon()` writes tiny SVGs
  to `<tempdir>/neuroedit-ui-icons/` (named by colour, written once).
- **NE-039 radii.** `RADIUS_SM/MD/LG` are 10/12/16 (were 7/8/12) and moved
  above `_build_stylesheet`, which now uses them for buttons, inputs, popups
  and list rows. Circular swatches and the 6px scrollbar pills are unchanged.
- **NE-040 wheel guard.** New `ui/wheel_guard.py`, installed app-wide in
  `__main__.main()`. Spin boxes, combo boxes and sliders (not scrollbars) take
  the wheel only when focused; otherwise the event goes to the parent so the
  panel scrolls. Their `WheelFocus` policy becomes `StrongFocus` on polish so
  the wheel can't focus them. Test: `tests/test_wheel_guard.py`.
- **Verification:** `tests/test_wheel_guard.py` + `tests/test_design_tokens.py`
  pass (20). `ruff check src tests scripts` passes. Offscreen renders of the
  controls in both themes look right. The first full-suite run stopped at
  `test_capture_baseline.py` (its capture subprocess hit the 180 s timeout
  during a very slow iCloud-venv run: 56 tests in 9.6 min); a rerun was still
  in progress at commit time, so the full suite is **not yet confirmed green**.
  Not checked in the running app: the list-row overlap seen in the offscreen
  render (likely pre-existing QSS padding), native Windows look.
- **Next:** confirm the full suite, check the real app in both themes, then
  update the design-system artifact to the new palette and radii.

## 2026-11-18 — Clip speed and refreshed controls released

- Published [v0.5.25-alpha](https://github.com/v7sm25qk5v-ui/NeuroEdit/releases/tag/v0.5.25-alpha)
  from `adef38d24d266f99fccf86d6ad1c9e69b90c7eae`, annotated tag
  `f023494932fa237ea06d347e5be9600a6d0c942d`. GitHub Latest and the
  checked-in notes agree. The updater accepted the macOS ZIP and Windows EXE
  as upgrades from v0.5.24-alpha.1. All three installer URLs returned HTTP 200
  and have GitHub SHA-256 digests.
- Local Ruff passed and the full rerun on the tagged source had **865 passes**
  in 60.11 s. The first local run collected Project Library during an edit.
  The resulting two stale-import failures passed once the finished code loaded.
  [Tagged CI](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/44373935370)
  passed **865 macOS tests** in 93.99 s. Both installers built and the release
  published. [Main CI](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/44373935369)
  passed. Informational Windows had 842 passes, 16 failures and 7 skips.
  The 16 failing test names exactly match v0.5.24-alpha.1.
- The daily optimization notes remain local. Native Windows interaction and
  installed-app playback with the user's footage remain open.

## 2026-11-18 — Clip speed effects and refreshed controls

- Added NE-035 and NE-036 in `CODING_TICKETS.md`. A video clip's right-click
  **Clip Speed** submenu offers 0.25× through 4× and a 1× reset. The speed is
  an undoable project edit. Preview speed combines with clip speed, while
  export renders the edited rate regardless of the transport setting.
- Source trims and split bounds stay in source seconds. Preview, scrub,
  filmstrip, library, SAM, and exporter map through the clip rate. Timeline
  positions and timed redactions follow the retimed footage, and decoded
  source frames receive their redactions even when a slow clip repeats them.
  Source audio uses pitch-preserving tempo filters. Linked captions follow
  narration, whose own recording speed and duration remain intact.
- Projects with a speed effect write schema 2. Projects at normal clip speeds
  retain schema 1. Use the new release to open retimed projects.
- Shared Qt scrollbars use rounded rails and thumbs with no arrow buttons.
  Playback, tools, and shared buttons use consistent states in both themes.
  The header and timeline keep their scrollbars visible at compact sizes.
  Both themes were visually checked with a synthetic editor window.
- Prepared as `v0.5.25-alpha`. Real synthetic export tests cover 0.25× and 4×,
  video timing, redaction coverage, source-audio pitch and duration. Native
  Windows UI and playback with the user's footage remain untested.

## 2026-11-18 — Label fitting and live scrub previews released

- Published [v0.5.24-alpha.1](https://github.com/v7sm25qk5v-ui/NeuroEdit/releases/tag/v0.5.24-alpha.1)
  at `e5e1ebfe8b844affef4814ee6fad704e4085271a`, with annotated tag
  `2102409fa2e324fa091e3aa722e5443294c1bb27`. GitHub Latest and the
  checked-in notes agree. The updater accepts the macOS ZIP and Windows
  EXE as upgrades from v0.5.23-alpha.1. All three public installer URLs
  returned HTTP 200 and have GitHub SHA-256 digests.
- The first tag remains unpublished and unchanged. The replacement converts
  point size to positive pixel size even on Windows font backends that leave
  pixel size unresolved. It verifies complete text while allowing fonts to
  wrap differently. The cross-source scrub test uses native path comparison.
- Local Ruff and all **850 tests** passed on the released source (58.41 s).
  [Tagged CI](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/44348625738)
  passed **850 macOS tests** (83.70 s), built both installers and published
  all assets. [Main CI](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/44348626059)
  passed. Informational Windows had 827 passes, 16 failures, and 7 skips.
  The failing test names exactly match v0.5.23-alpha.1, and all four new
  label and scrub failures from the first v0.5.24 tag are resolved.
- The separate daily automation notes remain local. Native runtime checks
  on Windows and playback with the user's footage remain open.

## 2026-11-18 — Fit labels and show frames while dragging the playhead

- Added NE-033 and NE-034 in `CODING_TICKETS.md`. GPT-6.2 Sol at extra-high
  reasoning reviewed the approaches and working changes. Separate agents
  implemented label fitting and the scrub viewer.
- Preview and export share annotation label layout and painting. The backing
  box follows its text and shifts inside the frame. Oversized text wraps or
  shrinks. Selection and drags use the fitted box. A synthetic image reproduced
  the original “Resection cavity” case near a frame edge.
- The editor shows background-decoded video frames during a timeline drag.
  It keeps the newest requested position, checks clip identity and redaction
  timing before displaying the frame, and uses the native player for the exact
  release seek. Filmstrip decoding pauses during the drag.
- Visible filmstrips schedule a first still for each source before filling the
  rest of its strip. Nearby thumbnails reuse decoded frames. In a synthetic
  1080p long-GOP clip, six adjacent stills took a median of 0.33 seconds versus
  1.65 seconds before the change. The startup test covers multiple visible
  batches and confirms that offscreen clips do not delay those results.
- Full macOS offscreen suite passed 849 tests with two existing Qt warnings.
  After the final deferred-seek callback and sparse-frame handoff fixes, 129
  affected tests passed, including the real landscape-to-portrait drag and
  exact native seek. Ruff and `git diff --check` passed. Native Windows and
  installed-app playback with the user's footage remain untested.
- The initial `v0.5.24-alpha` tag passed all 850 required macOS tests.
  Windows CI exposed font resolution differences, including an oversized
  label that failed to fit, and a path separator assertion. Publication was
  canceled before either installer was posted. The `v0.5.24-alpha.1` retry
  preserves that tag and includes the corrected font sizing and path check.

## 2026-11-18 — Daily optimization automation ran (incremental, no code changes)

- Scanned `947503b..7a2fb21` (v0.5.18–v0.5.22 waves + the uncommitted working
  tree): 46 committed files +5.7k/-182, plus the working-tree filmstrip-thumbnail
  and scrub-throttle change. Deep-dived the perf-relevant new code — timeline
  filmstrip (`ui/timeline_thumbnails.py`, `_paint_filmstrip` / `_layout_filmstrip`),
  the instant-cuts cue player (`_maybe_cue_next_clip` / `_next_cut_clip` /
  `_take_cue`), and the inserted-slide model helpers. The updater modules and
  `media_convert.py` are user-driven import/network paths, not paint/playback hot
  paths — no findings there.
- TODO.md "Optimization Backlog": added a 2026-11-18 run note with two
  low-priority findings — the filmstrip key tuples are rebuilt on every
  playhead-only repaint (per-tick allocation the static-cache design otherwise
  avoids), and the playback tick now does ~6 linear clip/slide scans per frame
  via the cue path (watch item; CLAUDE.md already accepts the O(n) scan for small
  n). The three 2026-11-13 items remain open.
- CLAUDE.md memory: "Last reviewed" → `7a2fb21` / 2026-11-18; recorded the
  `TimelineThumbnails` off-thread LRU decode and redacted-source filmstrip
  protection as architecture notes, and the updater/`media_convert` modules as
  out-of-scope-for-playback false positives.

## 2026-11-18 — Timeline filmstrips published in v0.5.23-alpha.1

- Published [v0.5.23-alpha.1](https://github.com/v7sm25qk5v-ui/NeuroEdit/releases/tag/v0.5.23-alpha.1)
  from commit `27f71fb00ebac867f11db757c6091e166a3a33dd`. GitHub Latest and the
  checked-in release notes agree. The app's updater accepted the macOS ZIP and
  Windows EXE as upgrades from v0.5.22-alpha.1. All three public installer
  URLs returned HTTP 200 and GitHub provides SHA-256 digests for the assets.
- The first tag remains intact and unpublished. The released tag replaces the
  thumbnail QRunnable with a single Python executor, removes modal event
  reentrancy from video-import progress, and tests real cue swaps after the
  decoder reports readiness.
- Ruff passed. Local macOS pytest passed **841 tests** (51.57 s).
  [Tagged CI](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/44296005750)
  passed **841 macOS tests** (109.45 s), built all three installers and published
  them. [Main CI](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/44296006124)
  passed. Informational Windows had 818 passes, 16 failures and 7 skips.
  All 16 failures had also appeared in v0.5.22-alpha.1.
- The daily automation documentation remains local. Native installed-app
  playback and Windows runtime smoke checks remain open.

## 2026-11-17 — Editor responsiveness and timeline filmstrips

- The Video row shows stills sampled from each clip's trimmed source range.
  Visible tiles decode on one background worker, with a small memory cache
  and no thumbnail files written to disk. Labels and trim handles remain above
  and beside the filmstrip. Cover slides hide their underlying tiles. A source
  with a timeline redaction uses plain clip bars across its split clips.
- Timeline drags coalesce pointer events into preview seeks about every 33 ms,
  then seek to the release position. Explicit seeks and frame stepping use
  the exact target. Playhead-only updates repaint the old and new playhead
  strips without updating timeline geometry and editing controls.
- Project loading checks readability once per distinct source and rechecks
  after file signature changes. Editor refresh reuses unchanged widget styles.
  The optional SAM backend starts when its panel first opens. Close cleanup
  resolves each distinct mask or media path once across undo and saved state.
- On this Mac with synthetic projects, median restore of 120 splits from one
  file improved from 220 ms to 152 ms (120 probes to one). Median close with
  36 undo revisions improved from 56 ms to 7 ms. A warm refresh with 120 clips
  improved from 1.35 ms to 1.01 ms. Empty startup was roughly unchanged. An
  offscreen burst of 150 pointer moves across a dense project took 37 ms vs
  2.35 s before coalescing. That measures UI work without video decoding.
- A real FFmpeg fixture verified thumbnail source times and the offscreen
  timeline rendered all 20 visible stills from two synthetic clips. Long-GOP
  source seek latency still depends on decoding. Hiding or closing the timeline
  cancels its thumbnail work between frames, so exit can wait for the current
  file open or frame seek on slow media. Native Windows and playback with the
  user's footage remain untested in this pass.
- Ruff and diff checks passed. The full macOS suite passed 841 tests in 54.27 s
  with two existing Qt warnings. After adjusting clip title and over-guidance
  label spacing, the 114 relevant timeline, slide, and thumbnail tests passed
  again and the spacing was checked in an offscreen render.
- The `v0.5.23-alpha` tag remained unpublished after two hosted attempts.
  The first stalled during import cancellation. The second missed the
  long-GOP cue test's timing window and reported a PySide event-filter
  error involving a thumbnail QRunnable.
- The `v0.5.23-alpha.1` retry uses one Python executor for the thumbnail
  worker, feeds the import progress bar directly to avoid nested Qt events,
  and waits for a real decoded standby frame before exercising the cut test.
  The previous tag is preserved.

## 2026-11-17 — Instant cuts release published

Published [v0.5.22-alpha.1](https://github.com/v7sm25qk5v-ui/NeuroEdit/releases/tag/v0.5.22-alpha.1)
from `5028ec8`. The [tagged workflow](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/44233760533)
passed macOS lint and all 832 tests (104.38 s), built both platform installers
and published the checked-in notes. The informational Windows suite had 808
passes, 17 failures and 7 skips. The failed test names match the original tag.
All 19 playback tests passed on both platforms.

The first local suite attempt failed the compressed-audio probe because imageio
could not find a runnable FFmpeg and was interrupted during screenshot capture.
The complete rerun with native FFmpeg passed all 832 tests in 94.32 s.
GitHub Latest returned the new tag and notes, the updater parsed both platform
assets as an upgrade from v0.5.21-alpha, and the DMG, ZIP and EXE links all
returned HTTP 200. Installed-app playback with the user's footage remains open.

## 2026-11-17 — Instant cuts release retry

The original push succeeded. The tagged macOS timeout traceback points to
`progress.canceled.disconnect()` during MPG import completion. The dialog now
hides and is deleted by Qt after completion. Playback review also found that
only the original standby surface notified the cue player. Frames now follow
the current standby surface across swaps, covered by a regression test. The
retry uses `v0.5.22-alpha.1` to preserve the original tag.

## 2026-11-17 — v0.5.22-alpha release (instant cuts)

- User asked to commit the instant-cuts fix, tag and release. Fix committed as
  `f7b0b84`; the release commit bumps `desktop/pyproject.toml` to 0.5.22, updates
  README download names and what's new, and adds
  `desktop/docs/releases/v0.5.22-alpha.md`.
- **Workflow change** (`.github/workflows/build.yml`, release job): it now
  sparse-checks-out `desktop/docs/releases`, fails if `<tag>.md` is missing or
  empty, and publishes that file via `body_path` with the name
  `NeuroEdit <tag>`. Previously it posted a generic body and the notes were
  pasted afterwards. Reason: `/usr/local/bin/gh` here is Intel-only ("bad CPU
  type"), so notes can't be edited from this Mac. **Every future tag needs its
  notes file committed before tagging.**
- Local verification before tagging: Ruff clean, **831 passed**, 2 existing
  warnings, 54.9 s.
- Pushed `main` and annotated tag `v0.5.22-alpha` (tag object `407234b`, commit
  `398be23`) atomically. `git push` via the configured `gh` credential helper
  fails (Intel-only binary, no Rosetta); it worked with
  `-c credential.https://github.com.helper= -c credential.https://github.com.helper=osxkeychain`.
- **Release build FAILED, nothing published:**
  [run 44227026968](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/44227026968).
  The macOS Pytest step hung and hit the job's 15-minute limit (cancelled). Ruff
  passed; installers and publication were skipped. Main quality run
  44227026734 was cancelled the same way. Windows informational failed in 2 min
  as usual. A normal macOS run takes ~90 s, so a test hung; most likely
  something in the new cue-player code on the CI runner. Locally it passes.
  Logs need a GitHub sign-in; not yet read. The tag points at the failing commit
  and has no release.

## 2026-11-17 — Instant cuts between split clips (committed `f7b0b84`)

- **Report:** the preview froze at cuts between clips that had been split from
  one longer recording. A screen recording showed frozen stretches of
  0.37-0.76 s starting just after the cuts at 3.874 s and 8.772 s. The autosaved
  project explains why. Those clips come from the same file but jump far apart
  in the source (151.7 s → 235.4 s). The imported file
  (`media_convert.py`: libx264 veryfast, default keyint) has one keyframe
  every ~8.3 s. Seeking the playing `QMediaPlayer` therefore decodes up to
  8 s of 1080p video before it shows a frame.
- **Measured** in a standalone Qt script on that file (not NeuroEdit):
  - Plain seek: 913-939 ms to the first frame.
  - A standby player that was only seeked (still stopped) decodes nothing
    until play: 830 ms.
  - Paused, then seeked, then moving its output to the main surface: 649 ms,
    because moving the output makes Qt's FFmpeg backend seek again.
  - Paused, seeked, playing on its **own** surface: **2 ms**.
- **Fix** (`ui/main_window.py`, `ui/canvas.py`):
  - A second `QMediaPlayer` (`_cue_player`) has its own muted `QAudioOutput`
    and its own hidden `QGraphicsVideoItem` (`cue_video_item`).
  - Within 3 s of a cut that needs a seek or a new source,
    `_maybe_cue_next_clip` loads the next clip paused at its `trim_start`.
    `_cue_frame_arrived` marks the cue ready when the target frame lands.
  - At the cut, `_take_cue` swaps players, audio outputs and surfaces, then
    plays. Volume and mute carry over, and the idle output is muted.
  - The cue is skipped for contiguous cuts within one file, image clips, cuts
    under a full slide, and clips with media problems. A cue that doesn't fit
    falls back to the old seek path.
  - Player signals are routed through lambdas that ignore the idle player.
  - Switching projects releases the cue player's file.
- **Tests:** `desktop/tests/test_playback_cue.py`, 18 tests:
  - When to cue, including lead time scaled by playback speed.
  - Cue seek and readiness filtering, the swap itself, and four fallback
    cases.
  - Surface swap.
  - A real-decoder test that plays a single-keyframe file as two clips 37 s
    apart. With the cue, the picture changes 5-9 ms after the cut. With the
    cue disabled it stalls 0.56 s and the test fails (checked by A/B).
- **Suite:** Ruff clean. Full suite **831 passed**.
  - Gotcha: `test_undo_history` builds bare windows without `__init__`, so
    `_cue` has a class-level `None` default.
  - `test_capture_baseline` can time out under heavy load, as before.
- **Not verified:** not yet tried in the running app with the user's project.
  A second app instance was not started, because it would race the autosave.
- **Open / possible follow-ups:**
  - Starting playback less than ~1 s before a far cut leaves no time to cue,
    so that one cut still stalls as before.
  - Scrubbing and seeks by clicking are still slow on these 8 s-GOP imports.
    Adding a keyframe interval (e.g. `-g 30`) in `media_convert.py` would help
    future imports, at some file-size cost.
  - The cue player keeps a second decoder open while playing.

## 2026-11-17 — v0.5.21-alpha published and installed on the user's Mac

- Published [NeuroEdit v0.5.21-alpha](https://github.com/v7sm25qk5v-ui/NeuroEdit/releases/tag/v0.5.21-alpha)
  at source `cd86959e90657d819731a6e24978b78ff9ba7c0c`, annotated tag
  `d90c333297585178e7f69be32dbab31752f925f1`. Main and tag pushed atomically;
  existing release tags were not moved. Latest API and all three public installer
  URLs verified; release notes describe the translocated-copy updater fix.
- Tagged [workflow 44173325908](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/44173325908)
  succeeded: required macOS Ruff, **813 tests passed**, two existing warnings,
  93.68 s, both installer builds and publication. Main
  [quality 44173325902](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/44173325902)
  succeeded. Informational Windows: **790 passed, 16 failed, 7 skipped**;
  its failed test names exactly match v0.5.20-alpha, and all nine new cases pass.
- The user saved and quit normally before replacement. The old app initially
  remained running and rejected a normal Quit request; the user completed quit
  after a follow-up. No process was force-killed. Desktop-control inspection
  failed; the separate System Events fallback was denied assistive access.
- One-time bootstrap for the older updater used the production `UpdateService`,
  `prepare_install` and `launch_prepared_install`, not a browser/manual drag.
  Downloaded the published ZIP, verified SHA-256, staged on the installation
  volume and passed deep/strict codesign verification before invoking the normal
  replacement/rollback/relaunch helper. No quarantine attributes were changed.
- Verified installed **0.5.21** and a live process executing directly from
  `/Applications/NeuroEdit.app/Contents/MacOS/NeuroEdit`, with writable parent
  and no App Translocation. Installed signature verification also passed.
  No project contents or native preferences were edited by the bootstrap.
- Evidence: `desktop/docs/releases/v0.5.21-alpha-verification.json`. This verifies
  real download/replacement/restart; the full future update through GUI buttons
  and edited-project reopening remains a separate smoke check. Native Windows
  installation and existing informational failures also remain open.
- Documentation-only publication follow-up does not move the tested release tag.

## 2026-11-17 — macOS translocated updater fix, v0.5.21-alpha prepared

- User reported that Check for Updates offered only the release page. Confirmed
  the running v0.5.19 process was inside a read-only `AppTranslocation` mount,
  while `/Applications/NeuroEdit.app` was writable. The old updater inspected
  only the running bundle, so it incorrectly fell back to manual installation.
- `update_install.py` now checks the two standard Applications folders when the
  running macOS bundle is read-only. Exactly one writable, valid, non-symlinked
  `NeuroEdit.app` must have byte-identical Info.plist and executable SHA-256.
  Different or ambiguous copies are refused. No private macOS APIs, quarantine
  changes, source-checkout updates, or arbitrary filesystem searches added.
- Nine regression cases cover system/user installs, staging on the installed
  volume without changing either original, mismatches, missing/ambiguous copies,
  read-only locations, symlinks and unchanged writable-running-app behavior.
- Verification: Ruff `src tests scripts` passed; full suite **813 passed**, two
  existing Qt warnings, 48.14 s, clean exit. Patched target detection against the
  actual translocated v0.5.19 process selected `/Applications/NeuroEdit.app`.
- Prepared numeric 0.5.21, README/download references, updater docs and release
  notes. Publication and installed-app smoke results will be recorded separately.
- Desktop-control inspection failed with an expired continuation after a long
  tool stall. No app close, replacement, native preferences or project changes
  were performed. The running old build needs the fixed version installed once;
  it cannot download changed updater code before installation.

## 2026-11-17 — v0.5.20-alpha published and verified

- Pushed Claude's three prepared commits on main and the existing annotated
  `v0.5.20-alpha` tag atomically. Release source
  `f0cb76899eb46258eb9988cfd6cdbf89199e4977`; tag object
  `58ed6e38c4ef4d6fdf2b188c9056804eec37aff0`. No existing tag moved.
- Published [NeuroEdit v0.5.20-alpha](https://github.com/v7sm25qk5v-ui/NeuroEdit/releases/tag/v0.5.20-alpha)
  with the prepared release notes and macOS DMG/ZIP plus Windows installer.
  GitHub Latest API reports this tag; alpha/unsigned labels retained, with
  GitHub non-prerelease/Latest status for updater discovery.
- Tagged [workflow 44156708157](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/44156708157)
  succeeded: required macOS Ruff and **804 tests passed**, 2 warnings, 108.93 s;
  both installer builds and publication passed. Main
  [quality 44156707379](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/44156707379)
  also succeeded. Relied on Claude's completed local tests; no local rerun.
- Informational Windows job: **781 passed, 16 failed, 7 skipped, 2 warnings**
  in 126.07 s; Ruff passed. Platform assumptions, paths, cleanup and macOS
  update-helper failures remain; not all classified as test-only. The existing
  informational policy is unchanged, and Windows runtime is not fully validated.
- All three public installer URLs returned HEAD HTTP 200. GitHub-reported
  SHA-256 digests, sizes and publication evidence are recorded in
  `desktop/docs/releases/v0.5.20-alpha-verification.json`. Installer bytes were
  not independently downloaded or installed during this publication.
- v0.5.19-alpha users can now use **Help → Check for Updates…** against a real
  newer release. Actual installed update/restart, native Windows execution and
  inserted slides with real footage remain smoke checks.
- This documentation-only follow-up records publication without moving the
  tested tag. Earlier preparation/not-pushed entries below are historical.

## 2026-11-17 — v0.5.20-alpha release prepared (inserted slides)

- Version 0.5.20 in `desktop/pyproject.toml`; README "What's new", install
  names and updater text; notes in `desktop/docs/releases/v0.5.20-alpha.md`.
- First release that v0.5.19-alpha users can take through **Help → Check for
  Updates…**, so it is the first real use of the in-app update path.
- Local: Ruff (`src tests scripts`) clean; full suite **804 passed**, clean exit (52 s).
- Publication status is recorded in the next entry once CI has run.

## 2026-11-17 — Inserted slides: a slide can push the video later (`46b3a15`, not pushed)

**Why.** A full slide always went in at the playhead *over* the video. A title
slide at 0:00 therefore hid the first seconds of the first clip; the preview
skipped them and the export never showed them. The user wants both slides that
overlap footage and slides that sit *before/between* clips, and asked that a
slide aimed roughly between two clips land between them rather than splitting
a clip a second from its end.

**What changed.**
- `models.py`: `Slide.insert` (default False, so old projects load unchanged as
  cover slides). Helpers `slide_span`, `slide_is_inserted`. `ProjectState`
  gains `insert_gap` + `split_clip_for_gap` (moved from `MainWindow`, which now
  delegates; Take Still is unchanged and marks its slide `insert=True`),
  `slide_insert_point`, `insert_slide`, `remove_slide_gap`, `move_inserted_slide`,
  `place_inserted_slide`, `resize_inserted_slide`. Snapping: nearest clip edge
  within `INSERT_SNAP_SECONDS` (2 s) or `INSERT_SNAP_PX` (16 px at the current
  zoom), never inside another inserted slide, past the end → end. Further inside
  a clip the clip is split there (deliberate mid-clip insert via the playhead).
- `compact_clip_positions` now also keeps a slide-filled gap *before the first
  clip*. Before, any clip drag collapsed that gap and slid the first clip under
  a title slide (also a latent Take Still-at-0:00 bug). Gaps with no slide still
  close as before.
- Timeline (`editor_panels.TimelineCanvas`): inserted slides show the title on
  the left and a centred `|<-[]->|` icon; their time is a dashed placeholder in
  the Video row; cover slides hatch the footage they hide; hover tooltips say
  which. Dragging an inserted slide moves it between clips only (never splits),
  re-applied from the press state each move so the clips part live; Escape
  cancels; trash/delete closes its time. Cover/overlay slides drag as before.
- Slides panel: the "Overlay (transparent)" checkbox became **Placement**:
  Insert (push video later) / Cover video / Overlay. **New Slide now inserts by
  default** at the snapped playhead point. Switching placement opens/closes the
  slide's time; duration edits and delete move the video; Place at Current Time
  re-inserts at the playhead (reading it in the current layout).

**Gotchas.** An inserted slide's time is closed and reopened when it moves; a
move that lands in the same slot restores the press state exactly, because
close+reopen would shift items that start inside the slide's own time.
Inserting/resizing goes through `insert_gap`, so a redaction starting exactly
at the insertion point moves with its footage instead of growing over the
slide. Schema version not bumped: an older build drops `insert` and treats the
slide as cover, with the clips still after it (no footage hidden).

**Verification.** New `desktop/tests/test_slide_insert.py`, 39 tests:
- Snapping table and the zoomed-out snap.
- Never inside another inserted slide.
- Insert, split, move and back, same-slot no-op, resize, and place at the playhead.
- Redactions and mask frames.
- The leading gap surviving a clip drag.
- Timeline: drag (including rightward), Escape, delete, paint, and cache key.
- Panel: New Slide, placement switching, duration, and delete.
- Export: the title slide then the whole clip, frame-compared.
- In-app undo: one step per edit.

The full suite gave **802 passed** with a clean exit (215 s). An earlier run while the reviewer was active timed out only in `test_capture_baseline`, the known 180 s subprocess limit under load. Ruff is clean. An offscreen render of the timeline was checked by eye; nothing was tried in the running app.

**Independent review** (Sonnet, about 7,000 randomized model sequences). Fixed:
- A rightward drag landed one slot too far, because the pointer is now read against the timeline as drawn.
- Take Still inside an inserted slide overlapped it; it now uses `outside_inserted_slides`.
- A redaction moved off the insertion point left its mask frames behind (pre-existing).
- Room within `MIN_SPLIT` (0.05 s) of a clip edge left a clip sliver under the slide; `insert_gap` now snaps to the edge and returns the point.
- A file with both `overlay` and `insert` set closed a gap that never existed.
- A stored duration the spinner can't show (for example 0.3 s) was rewritten by unrelated edits.

**User decision (2026-11-17): "Stop at the slide".** At a clip edge,
`insert_gap` now leaves a finite redaction that ends exactly at the insertion
point where it is, so the redaction box no longer covers the inserted slide.
The trade-off, accepted by the user: that redaction's inclusive end frame, the
next clip's first frame (about 1/30 s), is no longer covered. Inside a clip
(Take Still or a deliberate mid-clip insert) it still grows, because there the
end frame is the same footage resumed after the room
(`test_insert_still_preserves_redaction_on_resumed_source`). Tests:
`test_redaction_ending_at_a_clip_edge_stops_at_an_inserted_slide` and
`..._at_a_split_point_still_covers_the_resumed_footage`. Full suite after this
change: **804 passed**, clean exit (51 s).

**Open, deliberately unchanged:**
- **Labels spanning the insertion point** are capped there.
- **Audio, markers and captions starting inside an inserted slide** don't travel with it when it moves.
- **Narrow slides.** At low zoom a narrow inserted slide shows only the icon; the title is in the tooltip.

**Next:** try it in the app with real footage (Insert a title before a clip, drag it between clips, Take Still near a slide). Committed locally on main; not pushed or released.

## 2026-11-17 — v0.5.19-alpha updater published and verified

- Pushed main and annotated tag `v0.5.19-alpha`, source
  `193178257b30e4ed32597e43c6821428e8817eb5`, tag object
  `75cb8c750b9684a4111297391c393791011a0dd1`. No existing tag moved.
- Published [NeuroEdit v0.5.19-alpha](https://github.com/v7sm25qk5v-ui/NeuroEdit/releases/tag/v0.5.19-alpha).
  GitHub Latest API, live repository Releases sidebar, README links and all
  three installer assets agree. Alpha/unsigned labels retained; GitHub category
  is non-prerelease with explicit Latest for discoverability.
- Tagged [workflow 44142405107](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/44142405107)
  succeeded overall: required macOS quality **765 passed, 2 existing warnings,
  88.59 s**, clean exit; Ruff, macOS build, Windows build and publication passed.
  Main [quality 44142403488](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/44142403488)
  succeeded overall with 765 macOS tests in 79.03 s. No redundant local rerun for
  release metadata; prior local 765-test and updater verification remain above.
- Informational Windows pytest now executes past the fixed fixture: **741 passed,
  17 failed, 7 skipped, 2 warnings** (tagged 105.99 s; main 130.40 s). Failures
  include POSIX/macOS-only tests, paths, cleanup and relative-time assertions.
  Ruff and installer build passed; Windows is not fully runtime validated.
  NE-027 follow-up remains; no claim these failures are all test-only defects.
- Public HEAD HTTP 200 for DMG (131062130 bytes), ZIP (117648652 bytes), and
  Windows EXE (100368059 bytes). GitHub SHA-256 and complete evidence are in
  `desktop/docs/releases/v0.5.19-alpha-verification.json`. These release assets
  were not independently downloaded or installed during publication.
- Install this first updater-enabled alpha manually once, then choose **Help →
  Check for Updates…**. It correctly reports up to date until a newer genuine
  release is published. Actual installed-app replacement/restart and Windows
  installer execution remain native smoke checks. No dummy release created.
- Documentation-only follow-up records publication without moving the tested tag.
  Earlier local/preparation entries below are historical and superseded here.

## 2026-11-17 — v0.5.19-alpha updater release preparation

- The user requested a new alpha to test the in-app updater. Prepared numeric
  version 0.5.19, immutable tag/artifact label v0.5.19-alpha, README/download
  links, updater documentation and release notes. Includes all feature-branch
  changes on top of `46530cbd87d33e8ca8b685d364376c21d93a1964`.
- Prior validation: 765 tests with clean exit, 42 updater cases, independent
  senior review, real Qt GitHub/CDN download verification, and real macOS app
  build/ZIP staging/code-signature checks. No installed app was changed.
  Local tests are not repeated for metadata-only publication; hosted gates remain.
- First installation is manual. After installing, Help → Check for Updates…
  reports up to date until another genuine newer release exists. No second
  dummy release is created merely to show the download path.
- Source is to be fast-forwarded onto main; the tested tag remains immutable.
  Final CI/platform build/assets and Latest/sidebar verification will be recorded
  when publication completes. Native update/restart smoke remains for the user.

## 2026-11-17 — In-app GitHub updater implemented (local feature branch)

- After finishing the v0.5.18-alpha release below, the user requested an in-app
  Check for Updates / install-and-restart experience. Work is on
  `codex/in-app-updates`, based on `46530cbd87d33e8ca8b685d364376c21d93a1964`.
  These feature changes are local/uncommitted; the published v0.5.18-alpha does
  not contain this updater. No new release/version bump was performed for it.
- Three Terra engineers independently implemented release/network handling,
  platform installation, and dialog UI; Sol reviewed the combined code. Root
  integrated menu actions, save/close gates, one-time project reopening, tests,
  and documentation. Ownership stayed separate; no user projects were modified.
- Entry point: **Help → Check for Updates…**. Requests the fixed public NeuroEdit
  GitHub Latest release only on user action. Displays version/full alpha tag and
  plain release notes, streams a cancellable download to private temporary
  storage, and requires matching size and GitHub SHA-256 before installation.
  No project/media data is sent to GitHub. Retry ignores stale reply callbacks.
- macOS: privately stages the ZIP on the installation volume; validates contained
  paths/symlinks, bundle identity, executable and version; detached helper waits
  for the old process to exit before rename/rollback/relaunch. Windows: verified
  EXE, system PowerShell helper waits for process exit and runs Inno silently
  with the existing install directory and an explicit restart switch. Neither
  path force-kills the editor or bypasses OS protections. Read-only installs
  and source checkouts get manual-install guidance.
- Install first honors recording/jobs/save guards and flushes typed edits. A
  failed/cancelled save or helper launch leaves the app running. Dirty content
  is saved before handoff; an existing clean file is not rewritten (preserves
  unknown newer-schema fields). Clean nonempty state missing its file is saved.
  One-time `updates/reopenProject` restores the current saved project on restart;
  empty unsaved projects do not produce a broken reopen flag.
- Packaging embeds the full artifact tag in generated resources/build_info.json;
  numeric package/bundle version remains sourced from pyproject. Build scripts
  set NEUROEDIT_RELEASE_TAG; the Windows installer recognizes
  /NEUROEDIT_RESTART=1. The test fixture compares Path objects so the prior
  Windows slash-normalization setup error is corrected here; subsequent native
  Windows tests have not been run.
- Verification: **765 tests passed, 2 existing Qt deprecation warnings in 117.04 s**,
  clean exit, with unraisable/unhandled-thread warnings treated as errors.
  **42 updater tests** passed; senior review found no remaining blocking defect.
  Ruff, shell syntax, dependency checks and diff checks passed. One live Qt HTTPS
  check of GitHub returned up-to-date for the current 0.5.18 release. An actual
  updater download of the public 117620203-byte macOS ZIP followed GitHub/CDN
  redirects, passed size/SHA-256 verification, and was deleted without installation.
- Built a real temporary macOS app using pinned PyInstaller 6.20.0. Confirmed all
  five updater modules and full-tag metadata are bundled. Created the normal
  ditto ZIP and staged it through prepare_install: real framework symlinks
  extracted, staged codesign --verify --deep --strict passed, existing bundle
  unchanged, staging cleaned. No installed app was replaced or launched.
- Builds/tests used /private/tmp/neuroedit-updater-20261117 and the task-local
  Python runtime. Its package metadata was aligned to the temporary 0.5.18
  snapshot; the intentional iCloud workspace .venv was untouched. NeuroEdit-owned
  preferences and existing autosave hashes match the private pre-feature snapshot.
- Remaining native smoke: actual macOS installed-app replacement/relaunch and
  Windows PowerShell/Inno install/restart. macOS rollback covers failed swap or
  rejected OS launch, not application health after Launch Services accepts it.
  The first updater-enabled release must be installed manually once; subsequent
  releases can use the in-app flow. Details: desktop/docs/IN_APP_UPDATES.md.

## 2026-11-17 — v0.5.18-alpha published and verified

- Committed all 13 current files (MPG import and daily notes), source
  `a68b18970ddd5dea27abdfaf5363d4c6b3d0197a`; pushed main and annotated tag
  `v0.5.18-alpha` atomically. Tag object:
  `390c38eb87259a061c903e646d4096959bf03682`. No old tag moved.
- Published [NeuroEdit v0.5.18-alpha](https://github.com/v7sm25qk5v-ui/NeuroEdit/releases/tag/v0.5.18-alpha)
  with honest alpha/unsigned labels and non-prerelease GitHub category plus
  explicit Latest for discoverability. API and live repository sidebar verified.
- No local tests rerun, per the user's instruction. Tagged workflow
  [44107755944](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/44107755944)
  passed overall: macOS quality **723 passed, 2 warnings in 102.41 s**, clean
  exit; Ruff, both platform builds, and publication succeeded. Main workflow
  [44107756025](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/44107756025)
  passed overall, with 723 macOS tests in 105.39 s.
- Existing nonblocking Windows pytest failure: session fixture compares Qt's
  forward-slash path to Windows backslashes (716 setup errors, 7 skips). Ruff
  and the separate Windows installer build passed; NE-027 follow-up retained.
- All public downloads returned HEAD HTTP 200: macOS DMG (130597017 bytes),
  macOS ZIP (117620203 bytes), Windows Setup.exe (100317872 bytes). GitHub-reported
  SHA-256 hashes and CI results are in
  `desktop/docs/releases/v0.5.18-alpha-verification.json`. Installer bytes were
  not independently downloaded, installed, or exercised with real equipment.
- Final notes, CI documentation, and handoff are in a documentation-only follow-up
  commit. The tested source/tag are unchanged. Known MPG/storage/UI limitations
  and real-equipment/Windows validation gaps remain documented below.

## 2026-11-17 — v0.5.18-alpha release preparation

- The user authorized pushing all current edits and cutting the next release,
  explicitly requesting no additional local testing because Claude completed it.
  Local and remote main were `947503b391c2ca38ba95d74ba818e5d281207cb4`.
  Preserved the MPG working-copy feature, its tests, and daily optimization notes.
- Prepared numeric version 0.5.18, new annotated tag/artifact label v0.5.18-alpha,
  README notes/download links, and `desktop/docs/releases/v0.5.18-alpha.md`.
  Platform/runtime versions derive from pyproject through the existing packaging.
- Claude's existing handoff reports 723 passing tests twice, clean exits, 27 MPG
  regression tests, Ruff and diff checks clean. These are supplied prior results;
  no local test suite was rerun for publication. Required hosted CI gates remain.
- Publication must include macOS DMG/ZIP and Windows installer and make this tag
  Latest in both API and repository sidebar. Final CI, assets, and publication
  evidence will be recorded after the release pipeline completes.

## 2026-11-17 — MPG import: convert to an MP4 working copy (uncommitted)

**Request:** the user's footage is mostly `.mpg`, which the app rejected. They chose
"convert on import" over opening MPG directly (asked and answered in chat).

**Why conversion, measured on MPEG-1/MPEG-2 test files:** `.mpg` was only missing from
`VIDEO_EXTENSIONS`; ffmpeg decoding and export already worked. But MPEG program streams
have no seek index and timestamps starting ~0.5 s in, so (1) Qt's player showed the next
keyframe after a paused seek, up to ~0.5 s late, and (2) OpenCV repeated the frame from
~0.5 s for the first ~0.5 s of each clip in the frame-by-frame export, and the NE-026
sequential read never engaged. A redaction placed by scrubbing could therefore start up to
half a second after the face it was meant to cover. On an H.264 MP4 copy both behave like
any MP4 (0 of 570 OpenCV seeks wrong; Qt identical to an ordinary MP4).

**What changed (base `947503b`, v0.5.17-alpha; nothing committed):**
- New `desktop/src/neuroedit_desktop/media_convert.py`: `convert_to_working_copy` runs
  ffmpeg (`libx264 -preset veryfast -crf 17`, AAC 192k, `yadif=deint=interlaced`, square
  pixels, `-map_metadata -1`, `+faststart`) into a hidden `.neuroedit-convert-*` temp in
  `<project>/media/`, then renames atomically to `<stem>.neuroedit-<12 hex>.mp4` (hash of
  path, size, mtime, so an edited original converts again and an unchanged one is reused).
  Cancel kills ffmpeg at once; stale temps (>10 min) are removed. Refuses a linked media dir.
- `ui/media_import_worker.py`: converts before probing, off the GUI thread; progress per
  file and a status label; results carry the media path, whether the copy is new, and a
  failure reason.
- `ui/main_window.py`: import uses the copy and keeps the original file name as the clip
  name; copies made by a cancelled/discarded/failed import are deleted; failures show the
  reason; Save As copies `media/` working copies; relinking to an MPG is refused with an
  explanation; close-time cleanup deletes only app-named copies (and stale temps) that no
  document, undo step or saved file uses — matched by file name so a moved folder keeps them.
- `project_store.py`: `ProjectStore.open` re-points clips to `<folder>/media/<same name>`
  when the folder was moved or copied (`rebase_working_copies`).
- `ui/main_window_utils.py` (`.mpg`/`.mpeg` in `VIDEO_EXTENSIONS`, `referenced_clip_paths`,
  `only=` filter on `delete_orphan_masks`), `ui/editor_panels.py` (media explorer filters),
  video file-dialog filter, `desktop/CLAUDE.md` module map.
- Tests: new `desktop/tests/test_mpg_import.py` (27).

**Verification:** 27/27 new tests pass; 9 fail on the code before the feature and 4 more
fail on its first version (the review fixes). Full `tests/`: **723 passed** twice (48 s
each), clean exits; Ruff and `git diff --check` clean; user autosave and preference hashes
unchanged by the runs. Conversion speed on synthetic 1080p MPEG-2: ~4 s per minute
(real footage compresses less; expect slower).

**Independent Sonnet review** found, and this change fixes: cleanup deleted any file in
`media/` (including the user's own footage) and emptied a moved project folder's copies;
cancel/close took ~5 s and a forced quit left ffmpeg writing a partial copy; the same file
twice in one discarded batch leaked a copy; failure reasons were hidden; several untested
behaviours (metadata, atomic final name, edited original, interlacing, linked folder).

**Known and left as is:** the UI still says "Keep in Place" although MPGs are copied (an
8-second status message says so after conversion); a truncated MPG converts "successfully"
to a shorter copy (undetectable from the container); only the first audio stream is kept;
Save As copies large working copies on the GUI thread without staging; the old autosave
root keeps its copy after Save As while its project.json still references it; the cancel
test does not reproduce the reviewer's 13 s SIGTERM stall on this synthetic footage.
Masks of a moved project folder still point at the old folder (pre-existing).

**Not verified:** with real MPG recordings from the user's equipment; in the running app;
on Windows.

## 2026-11-17 — Daily optimization automation ran (incremental, no code changes)

- Scanned `e1b0839..947503b` (the NE-012–NE-031 ticket wave shipped in
  v0.5.17-alpha, `2343eb6`: 74 files, +10.6k/-3.0k). Deep-dived the perf-relevant
  changes (`exporter.py` overlay transform / cross-volume publish / ffmpeg
  resolution, new `ui/edit_gesture.py`, `HistoryMixin._flush_pending_edits`,
  `_frame_for_clip` decode path). **No new optimization findings** — the wave was
  already multi-agent reviewed for correctness and self-benchmarked (NE-026
  export decode / static composition), and export CFR decode already reads frames
  forward rather than re-seeking.
- TODO.md "Optimization Backlog": checked off the NE-010→NE-031 umbrella item
  (all ticket code shipped; only hardware/real-media/Windows/installer **validation**
  remains, tracked in CODING_TICKETS.md) and added a dated run note. The three
  2026-11-13 items (trim-drag double rewind, reorder re-places only redactions,
  `move_redactions_with_clips` no-redaction early return) remain open.
- CLAUDE.md memory: "Last reviewed" → `947503b` / 2026-11-17; corrected the stale
  341 → 696 test count; recorded the edit-gesture/flush-pending-edits architecture
  and the export CFR decode-forward false-positive note.

## 2026-11-16 — v0.5.17-alpha published, downloads and Latest verified

- Committed all current Codex and Claude updates: **71 files**, commit
  `2343eb6f647dfbf0c9681c03a070e4c1d3625664`. Pushed main and immutable
  annotated tag `v0.5.17-alpha` atomically. Tag object:
  `f16aff7537875467bb1649060fbaebd5e79ec147`. No old tag moved.
- Published [NeuroEdit v0.5.17-alpha](https://github.com/v7sm25qk5v-ui/NeuroEdit/releases/tag/v0.5.17-alpha).
  GitHub's release category is non-prerelease with explicit Latest so it appears
  in the sidebar; its alpha/unsigned labels and limits remain visible.
  Verified the live browser sidebar, Latest API, README links, and three downloads.
- The user explicitly requested no additional local testing; none was run.
  Required hosted gates were preserved. Tagged workflow
  [43974338054](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/43974338054)
  passed overall: macOS quality **696 passed, 2 warnings in 86.10 s**, clean
  exit; Ruff, macOS/Windows builds, and publication succeeded. Main workflow
  [43974336747](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/43974336747)
  also passed overall: 696 tests in 95.72 s on macOS.
- The new informational Windows test job failed at session-fixture setup:
  Qt normalizes `QSettings.fileName()` with forward slashes while the assertion
  expects the Windows backslash path. Result: 689 setup errors, 7 skips; Ruff
  passed. The pre-existing nonblocking policy is unchanged, and the separate
  Windows installer built successfully. Tracked as an NE-027 follow-up; these
  results do not validate Windows app behavior.
- Uploaded assets all returned public HEAD HTTP 200: macOS DMG (130588090 bytes),
  macOS ZIP (117608848 bytes), Windows Setup.exe (100313963 bytes). CI links and
  GitHub-reported SHA-256 digests are in
  `desktop/docs/releases/v0.5.17-alpha-verification.json`. Installer bytes were
  not independently downloaded, installed, or hardware-tested in this session.
- Final release notes/current CI documentation are published in a documentation-only
  follow-up commit; the tested tag/source remain unchanged. Real audio/SAM,
  native Windows UI/scaling, installed-app smoke, real-media export validation,
  and the other known review follow-ups remain as documented.

## 2026-11-16 — v0.5.17-alpha release preparation

- The user authorized committing/pushing all current updates and publishing a new
  tag, explicitly requesting no local test rerun because testing was already done.
  Preserved the full prior Codex pass and Claude follow-up; local/remote main were
  both `3e24301e10225c82d8d22c85cb5df1830993e5ec`. No old tag is moved.
- Claude's handoff reports 696 tests passed three consecutive times (41.6 s,
  41.1 s, 41.0 s), Ruff and diff checks clean, plus deterministic audio-panel
  teardown and five new regression tests. These are supplied prior results;
  local tests were not rerun for publication. Required hosted workflow quality
  gates are preserved.
- Prepared numeric version 0.5.17, tag/artifact label v0.5.17-alpha, current README
  notes/download links, and `desktop/docs/releases/v0.5.17-alpha.md`. Bundle/runtime
  metadata now derives from pyproject through the included packaging changes.
- Publication must include macOS DMG/ZIP and Windows Setup.exe, and the repository's
  Latest/sidebar must resolve to this new tag. Final CI/build/asset verification
  will be recorded when the pipeline completes.

## 2026-11-16 — Claude follow-up after the Codex continuation (uncommitted)

**Context.** Claude's "fix all tickets" pass was interrupted three times by usage limits; Codex
finished and verified the integration (two entries below). This entry records what Claude did
after returning. Still nothing committed, pushed, version-bumped, or released.

**Three findings from Claude's own independent review that were still present, now fixed:**
- Typed spinbox values. `setKeyboardTracking(False)` (NE-016) means digits typed into a
  duration/start field reach the model only on Enter or focus-out, and Save, Export, Undo, and
  Quit shortcuts cause neither, so a redaction could be exported shorter than its field
  showed. `HistoryMixin._flush_pending_edits` (`desktop/src/neuroedit_desktop/ui/history.py`)
  now calls `interpretText()` on every spinbox in the audio, slide, and labels panels before
  committing gestures.
- Review re-confirmed mid-edit. A label-inspector gesture reset PHI review only when it
  began; re-confirming review while the field kept focus and then changing the value left the
  review confirmed. `MainWindow._mark_annotation_inspector_edit`
  (`ui/main_window.py`) now resets it again, as the audio and slide panels already did.
- Crash notice thread. `_show_error_box` (`__main__.py`) could run `QMessageBox` on a worker
  thread when a slot raised there; it now re-posts itself to the GUI thread.
- Tests: 4 added to `desktop/tests/test_undo_coalescing.py`, 1 to
  `desktop/tests/test_small_lifecycle_items.py`; all 5 fail on the code before these fixes.

**Intermittent crash found and fixed (test code, not app code).** On this Mac the full suite
crashed 3 times in 4 runs with `Fatal Python error: Bus error` / `Segmentation fault` in
`tests/test_audio_import.py::test_real_audio_import`, main thread in garbage collection.
Cause: those tests left each `AudioPanel` (which owns `QMediaCaptureSession` and
`QMediaRecorder`) to be destroyed by the garbage collector at an arbitrary later moment.
`_dispose(panel)` in that file now deletes the panel on the GUI thread
(`deleteLater` + `sendPostedEvents(DeferredDelete)`). Reproduction (`pytest tests/ -k
test_audio_import`): 2 crashes in 4 runs before, 0 in 10 after. This is probably the
unattributed native crash noted in the entry below. The app itself keeps one audio panel for
the life of its window, so no app change was needed.

**Verification (this machine, iCloud-hosted `.venv`, no ffmpeg PATH workaround):**
- `pytest tests/`: **696 passed** three times in a row (41.6 s, 41.1 s, 41.0 s), exit code 0
  each time. The exit-139 crash after the summary that earlier runs showed did not occur.
- `ruff check src tests scripts` clean; `git diff --check` clean.
- `desktop/docs/review-2026-11-12/repros`: 4 passed. Every review repro now passes, so that
  folder has served its purpose and can be removed.
- User files unchanged across all runs: autosave `project.json` (`0d10f810…`) and both
  NeuroEdit preference plists; `~/Library/Logs/NeuroEdit` was not created by any test.

**Not done / open:**
- Claude's second review (NE-015, NE-026, NE-028, NE-029) was cut off by the usage limit
  before reporting and was not restarted. Codex's Sol review covered those paths; Claude had
  separately checked NE-026 frame selection (0 of 7,904 frames differ at 1080p, constant and
  variable frame rate).
- Review findings left as they are: a discrete edit made while a text field still has focus
  shares one undo step with the typed text unless a flush point intervenes (Codex's
  "cross-panel undo boundaries" work may already cover this; not rechecked); `crash.log` is
  never rotated; a failed Save As can leave copied assets in the destination folder.
- Same real-world gaps as below: no run in the actual app, no real SAM, no Windows, no hosted
  CI on these changes, no rebuilt installers.

**Next step:** the user decides whether to commit. The tree holds every ticket's change
(NE-012 to NE-031) on top of `3e24301`.

## 2026-11-16 — Resumed ticket pass: final local verification

- NE-012–NE-031 implementations are integrated and software verified locally.
  Final coordinator runs treated unraisable/unhandled-thread warnings as errors:
  **691 passed in 40.56 s**, then **691 passed in 39.69 s**, both clean exits,
  no skips. Two existing Qt `QMouseEvent.pos()` deprecation warnings remain.
  The engineer's strict full run also passed 691 tests in 40.02 s.
- Independent Sol review approved the changed paths and ran **20 fresh processes,
  100 lifecycle tests, all clean exits**. Coverage includes modal import cancel,
  late cancel, close during import, SAM results before worker exit, and close
  before deferred startup. Ruff, compilation, dependency checks, Bash syntax,
  actionlint, and diff checks passed.
- An intermediate repeat had a native Qt crash. Investigation fixed a separately
  reproducible SAM lifetime race: keep worker/thread references until
  `QThread.finished`, join native cleanup before releasing them, and retain
  parented startup timers that can be stopped on close. Import cancellation now
  uses GUI-owned state rather than a lambda retaining a dying worker wrapper.
  New deterministic tests cover the race and deferred startup. Subsequent runs
  above are clean; the original native crash's exact attribution remains unproven.
- Audio metadata import now uses one Python executor worker with GUI timer polling.
  The combined audio suite passed 32 tests; cancel/stale/close/late-result/retry
  and playback are covered. Insertion stays at the initiating playhead position.
  Cancellation discards results but cannot interrupt an already executing probe;
  that Python worker may delay process exit until its bounded probe finishes.
- Canonical ticket statuses and test mapping are updated. Durable evidence:
  `desktop/docs/engineering-2026-11-16/VERIFICATION.md` and `verification.json`.
  NeuroEdit-owned native preferences and the existing autosave hash match the
  private initial snapshot. The intentional iCloud `.venv` remains unchanged.
- Remaining follow-ups are physical audio/microphone behavior, actual SAM/GPU
  inference, real recordings, Windows native UI, hosted CI, and rebuilt/frozen
  installer smoke tests. No source commit, push, version bump, or release was
  made during this continuation; the public release remains v0.5.16-alpha.

## 2026-11-16 — Codex resumed the interrupted ticket pass (local integration)

- Resumed from Claude's uncommitted fixes on `3e24301`, preserving the original
  staged deletion, all modified source/tests, and untracked work. Incoming patch
  and untracked source/test copies were saved privately under
  `/private/tmp/neuroedit-resume-20261116/` before further changes.
- Sol orchestration/senior review coordinated Terra engineers in disjoint export,
  editor, lifecycle, and packaging areas. Existing implementations were audited
  against NE-012–NE-031 rather than restarted. No commit, push, version bump,
  installer build, or release is part of this resumed work.
- Independent review caught and fixed: closing could bypass a blocked unreadable
  autosave; startup restore missed the newer-schema warning; notes-only scratch
  projects were treated as empty; a hands-on tutorial survived project replacement;
  idle slider/text edits merged with discrete edits; caption review omitted speaker
  labels and interpreted markup. Regression tests reproduce each corrected path.
- Also fixed destination-wide cleanup deleting another export's active partial,
  keyboard-to-held-slider timer boundaries, misleading SAM cache/deletion state,
  MPS cache release, pristine tutorial-sample identification, and cross-panel undo
  boundaries before input mutates the document.
- NE-026 synthetic decode benchmark: 180 long-GOP 1080p frames, 6.258 s seek-per-frame
  versus 1.200 s sequential, all pre-encode RGB hashes identical. Static composition
  measurements did not justify a new cache; existing image decode caches remain.
  Evidence and repeatable scripts: `desktop/docs/engineering-2026-11-16/` and
  `desktop/scripts/benchmark_{export_decode,static_export}.py`. No real operative
  recording benchmark or general VFR guarantee is claimed.
- NE-027: shared reusable quality workflow, informational Windows tests, verified
  immutable action refs, pinned Inno Setup/pytest/Ruff, job timeouts, numeric
  platform versions sourced from pyproject, and separate artifact labels. Latest
  release publication/verification is retained. Official checksum-verified
  actionlint passed; hosted workflows, PowerShell/Inno, frozen apps, and installers
  have not been run in this session.
- Test teardown now deletes MainWindows and drains deferred deletion before fixture
  settings restore; session cleanup depends on settings isolation. Native checks
  exclude OS-global fallback timestamps (e.g. NSLinguisticDataAssetsRequestTime),
  which Qt can update independently; NeuroEdit-owned settings and the original
  autosave hash remain unchanged.
- Documentation now describes the actual native-only checkout and current workflow.
  Historical handoff entries before v0.5.12 were moved unchanged to
  `desktop/docs/history/HANDOFF-before-v0.5.12.md`. Only the confirmed dangling
  `desktop/.venv 2` symlink was removed; the intentional iCloud `.venv` is unchanged.
- Final integration results and ticket statuses are recorded in the entry above.

## 2026-11-16 — "Fix all tickets" pass: batch 1 done, batch 2 in progress (uncommitted)

**Request:** the user asked for every open ticket (NE-013 to NE-031) to be fixed. Work is
on top of `3e24301` plus the uncommitted NE-012 and NE-014 changes below. Nothing is
committed, pushed, version-bumped, or released. THIS ENTRY IS A PROGRESS RECORD; statuses in
`CODING_TICKETS.md` have not been updated for these tickets yet.

**How it is being run:** Sonnet subagents implement tickets on disjoint files (rules in the
session scratchpad `AGENT_RULES.md`), the coordinator reads every diff, a Haiku agent or a
direct run executes the full suite, and Sonnet reviewers attack each batch.

**Batch 1 — implemented, reviewed, review findings fixed:**
- NE-013 `exporter._publish_file`: cross-volume export copies in cancellable chunks to
  `.neuroedit-export-*.partial` in the destination folder, then atomic rename; stale partials
  are removed on the next cross-volume publish. Tested with a simulated `EXDEV`; the reviewer
  also passed a real second volume (disk image).
- NE-023 `exporter.resolve_ffmpeg` / `require_ffmpeg`: bundled ffmpeg first, then every
  `PATH` candidate, each validated with `-version`; only a working path is cached. Used by the
  exporter and the audio-duration probe. Tests no longer call `shutil.which("ffmpeg")`.
- NE-017 `ProjectStore.preserve_unreadable` + `MainWindow._preserve_unreadable_autosave`: an
  unreadable autosave is renamed to `project.unreadable-<timestamp>.json` before anything can
  write; if it cannot be moved, autosave is blocked for the session (`_autosave_blocked_path`);
  orphan-mask cleanup is skipped while any preserved file exists.
- NE-018 `MainWindow._new_project`, `_is_unsaved_scratch_case`, `_resolve_autosave_root_case`,
  `_has_case_content`: a non-empty case that lives only in the autosave folder is never
  replaced without one explicit question, including after opening another project first.
- NE-021 `MainWindow.closeEvent`: asks before closing during an export or SAM job.
- NE-022 `ui/canvas.py` `_scene_to_norm(clamp=True)`: shapes and redactions released outside
  the frame end at the edge.
- NE-031 new `neuroedit_desktop/stills.py` `read_upright_image`: the ONE still decoder, used
  by the preview (`set_image`), import/replace (`main_window`), and the exporter
  (`_frame_for_clip`). OpenCV and Qt disagree on PNG/WebP orientation tags, so they must not
  each decode stills.
- NE-024 `sam_backend.py` (`is_weights_cached`, `delete_weights`, `unload_models`,
  `managed_cache_dirs`, warm-up, partial-mask cleanup) and `ui/sam_workflow.py`
  (`_delete_sam_weights`). Stubbed tests only: torch is not installed here.
- NE-025 `ui/tutorial.py`: on a project with work the tutorial is a read-only tour
  (`project_has_user_content`, `TutorialOverlay.read_only`); `_load_tutorial_video` no longer
  adds the sample clip to such a project. Menu-bar commands are NOT blocked during the tour.
- NE-027 partly: `tests/test_version_consistency.py`, capture-test timeout 30 -> 180 s,
  informational Windows jobs in both workflows (`continue-on-error`, nothing `needs` them).
  NOT done: pinning actions to SHAs (needs verified SHAs), deduplicating the two quality jobs.
- Test infrastructure: the `window` fixture raises on an un-stubbed `QMessageBox`
  (`_forbid_modal_dialogs`); `tests/conftest.py` has a session-end window cleanup (candidate
  fix for the exit-139 crash; not yet confirmed by a full run).

**Batch 1 verification:** full `tests/` run WITHOUT any ffmpeg PATH workaround: 557 passed,
1 failed. The failure was `test_capture_baseline` timing out at 180 s on the first run after
an overnight idle; rerun alone it passes in 3 s (the venv is in iCloud Drive and stalls on
first access). User files unchanged (`project.json` `0d10f810…`, both plists).

**Batch 2 — status:** NE-015 (caption text PHI gate) implemented and read, not yet
independently reviewed: `ui/dialogs.py` (`TRANSCRIPT_REVIEW_KEY`, caption item in the export
checklist, transcript stop in guided review), `ui/export_workflow.py` (`_export_captions`
confirmation). NE-016 / NE-019 / NE-020 and NE-029 are with agents now.

**Batch 3 — not started:** NE-028 (timeline polish), NE-026 (export render-loop cost, measure
first), NE-030 (small lifecycle and documentation items).

**Known open points:** NE-024 P3s from review (`.bin` false positive in `is_weights_cached`,
"deleted" shown when nothing existed, MPS memory); NE-022 a drag that ends with zero height at
an edge is still rejected by the minimum-size rule with no message; NE-025 tour-only after a
restart when only the sample clip exists.

## 2026-11-15 — NE-014 fixed and reviewed (uncommitted, on top of NE-012)

**Base:** `3e24301` plus the uncommitted NE-012 change described in the next entry. Nothing
committed, no version bump, no release.

**What changed:**
- `desktop/src/neuroedit_desktop/ui/editor_panels.py`: new `view_changed` signal on
  `TimelineCanvas` and `RichTimelineWidget`. `_set_zoom` and a clip press that changes
  `active_clip_id` emit it instead of `project_changed`. Mouse press records
  `_drag_document_state()` (clip id order plus every value from
  `ProjectState.timeline_positions()`); `_report_drag_edit()` emits `project_changed` on
  release only if that changed by more than 1e-9, and also runs at the next press so an edit
  whose release was lost is still reported. `set_project` with a new project clears the
  recorded state. A drop on the trash still reports through `_delete_selected_item`.
- `desktop/src/neuroedit_desktop/ui/history.py`: new `_mark_timeline_view_dirty` (marks
  dirty, drops the cached autosave snapshot, updates the title, re-syncs the player, and
  refreshes the timeline and media panel; no history push, no attestation reset).
- `desktop/src/neuroedit_desktop/ui/main_window.py`: connects `timeline.view_changed` to it.
- Tests: 15 appended to `desktop/tests/test_main_window_headless.py` (new `reviewed`
  fixture: two clips, completed review, one redo step) and 6 to
  `desktop/tests/test_timeline_editing.py`. The NE-014 repro was removed from
  `desktop/docs/review-2026-11-12/repros/test_window.py` (now 6 fail, 1 passes by design).

**Verification:**
- 13 of the first 16 new tests fail on the pre-fix code.
- Final `tests/` run on the finished change: 422 passed, 1 failed in 249 s, the failure being
  the known `test_capture_baseline` 30 s timeout (NE-027). `ruff check src tests scripts`
  clean; `git diff --check` clean. Exit 139 after the summary, as on every local run.
- Haiku run on the first version: 417 passed, 1 failed (same timeout).
- Independent Sonnet review: no P1 or P2. 9,000 randomized drags (redactions, masks,
  captions, markers, slides, audio, trash drops, Escape) compared against the full project
  dict: no edit missed. Old-versus-new table for 20 interactions showed no wrong row. Two P3
  weaknesses fixed (float noise, lost release); two untested behaviours now covered. Five
  deliberate faults in a scratch copy each fail at least one test.
- User files unchanged across every run (`project.json` `0d10f810…`, both plists).
- NOT verified: in the running app by hand; real focus loss on macOS; context menus through
  a real `QMenu`; Windows.

**Known and left as is:**
- A zoom tick still re-syncs the player and refreshes the timeline twice (cheap, but the
  ticket mentioned it).
- Zoom and selection still mark the project unsaved. With the real playback sync, clicking a
  clip that is not under the playhead sets it active and the sync sets it back, so each such
  click marks the project unsaved (same as before the fix).
- `_edit_marker` and `_rename_clip` report an edit even when the text was not changed
  (pre-existing; candidate for NE-028).
- If a release is lost and the timeline is never pressed again, that edit is still
  unreported until the next press (a `focusOutEvent` handler would close it).

**Next steps:** user to decide on committing NE-012 and NE-014 (separately or together);
update the test count in `desktop/CLAUDE.md` (381 -> 423) when committed; then NE-013
(cross-volume export), NE-031 (rotated stills), and the NE-016 / NE-019 pair, which share
the "what counts as a document edit" question this change started to answer.

## 2026-11-15 — NE-012 fixed and reviewed (uncommitted)

**Base:** `3e24301` (v0.5.16-alpha published). Nothing committed, no version bump, no release.

**What changed:**
- `desktop/src/neuroedit_desktop/exporter.py`: `_render_frame` passes the decoded frame size
  (`source_size`) to `_paint_qt`. When a clip is under the playhead, `_paint_qt` wraps
  `_paint_annotations` in `save()` / `translate(source_rect.topLeft())` /
  `scale(fitted / source)` / `restore()` and passes the source's pixel size as `w, h`, so
  labels, shapes, brush strokes, text, and SAM masks are painted in the source's own pixel
  space exactly as `ui/canvas.py` does. `_paint_annotations` keeps its four-argument
  signature. Slides, fades, captions, and redactions are untouched.
- `desktop/tests/test_export_overlay_placement.py`: 21 new tests (square, portrait, wide, and
  4:3 sources; masks; arrow, text, ellipse, brush; stroke and text scaling; same-size
  equivalence; slide and empty-timeline behaviour; stale clip metadata; no effect on
  redactions).
- `desktop/docs/review-2026-11-12/repros/test_pure.py` removed (its last repro moved to
  `tests/`); `REVIEW.md` repro expectations updated to 7 failed, 1 passed.
- `CODING_TICKETS.md`: NE-012 marked Review approved with notes; new NE-031 (EXIF-rotated
  stills differ between preview and export); a `font_size == 0` item added to NE-029.

**Verification:**
- New tests: 14 of the first 17 fail on `3e24301`, all 21 pass on the fix.
- Full `tests/` run on the fix: 397 passed, 1 failed in 180 s, the failure being the known
  `test_capture_baseline` 30 s timeout (NE-027). The four follow-up tests were added after
  that run and were run on their own (21 passed); `ruff check src tests scripts` clean.
  The process exited 139 after the summary, as on every local run this week.
- Pixel comparison against a copy of `3e24301`: identical frames for every overlay type when
  source and export sizes match; also identical for full-frame slides, the empty timeline,
  and frames with fade, caption, and redaction (reviewer's regression run).
- Independent Sonnet review found no defect in the fix. It compared the exporter with the
  real preview painter (`AnnotationGraphicsItem.paint`) over 380 cases: zero difference
  through the same transform, about 3 px at most against a native render scaled down.
- A Haiku run of the first version caught a regression I introduced:
  `tests/test_regressions.py::test_full_frame_still_export_paints_visible_annotations`
  stubs `_paint_annotations` with four arguments, and the first version had widened that
  signature. The transform moved into `_paint_qt` to keep it.
- User files unchanged across every run (`project.json` `0d10f810…`, both preference
  plists).
- NOT verified: in the running app by hand; a real export through ffmpeg end to end; real
  rotated or anamorphic video; Windows.

**Behaviour change to know about:** when the export size differs from the source size,
stroke weight and label text now scale with the picture (matching the preview). Existing
projects exported at a different size from their source will look different from v0.5.16:
lighter for a larger source, heavier for a smaller one. Same-size exports are unchanged.

**Gotchas:**
- Overlays are not clipped to the picture; half a stroke at the picture edge or a label at
  the edge can extend into the letterbox bars. The original repro asserted otherwise and was
  replaced.
- The old session scratchpad holding the arm64 ffmpeg symlink
  (`…-claude-spares-spare-6B000e/…/scratchpad/ffbin`) still exists but may be cleared by a
  reboot; recreate it by symlinking the `imageio_ffmpeg` binary from the venv.
- `desktop/CLAUDE.md` still says the suite collects 381 tests; with this change it is 402.
  Update it when this is committed or released.

**Next steps:** user to decide on committing; try a non-16:9 source in the app; then NE-014
and NE-013; NE-031 is a new P2 with a privacy angle (redactions on rotated photos).

## 2026-11-15 — Corrected the repository's Latest release display

- The user reported the repository's Releases sidebar still showing v0.5.12.
  The new v0.5.16-alpha release existed, but its GitHub prerelease category
  excluded it from Latest. The release checklist had missed this display check.
- Updated the existing release's metadata with `prerelease: false` and explicit
  `make_latest: "true"`. Verified `/releases/latest` now returns v0.5.16-alpha
  and the live repository browser shows "NeuroEdit v0.5.16-alpha Latest".
  The alpha tag, source commit, installer assets, and unsigned-build notices
  remain unchanged. This is a publication/discoverability setting, not a claim
  that the app is production ready.
- Updated the publication workflow to set Latest explicitly and fail its final
  check if GitHub's latest tag differs from the published tag. Added a permanent
  latest-download link to README and the same requirement to desktop/CLAUDE.md.
  The older September handoff's claim that an alpha suffix inherently prevents
  Latest is superseded by this live verified result; no new stable tag was needed.
- The user explicitly requested remembering this requirement for future releases.
- Validation: workflow YAML/settings checks and Bash syntax passed; the exact
  new verification script passed against the live GitHub API. No application
  code or installer changed, so the already verified 381-test release is retained.

## 2026-11-15 — v0.5.16-alpha published and verified

- Published [NeuroEdit v0.5.16-alpha](https://github.com/v7sm25qk5v-ui/NeuroEdit/releases/tag/v0.5.16-alpha)
  as an alpha prerelease, including all current implemented updates and pending
  documentation. Source commit: `f88e7b6fe45e8dfdfb72eabf666e56810b274f94`;
  annotated tag object: `f9800b74cac057aa33296f655bce3bd39b1d1e5a`.
- [Tagged workflow 43756053191](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/43756053191)
  passed all four jobs: quality, macOS, Windows, and publication. Tagged tests:
  **381 passed in 385.29 s**, no skips, clean exit; Ruff passed. Main quality
  workflow 43756053408 also succeeded: **381 passed in 370.02 s**.
- Verified all three uploaded assets: unsigned macOS DMG (130862716 bytes),
  macOS ZIP (117555833 bytes), and Windows Setup.exe (100246368 bytes).
  All public download URLs returned HTTP 200. GitHub-reported SHA-256 digests,
  CI links, and validation scope are preserved in
  `desktop/docs/releases/v0.5.16-alpha-verification.json`. Installer bytes were
  not independently downloaded, installed, or exercised on hardware.
- After push, local main unexpectedly fell back to an older packed reference
  while the index and every working file still matched the published source.
  Found two unheld stale lock files from the push time; preserved both under
  `/private/tmp/neuroedit-release-20261115/` and restored main with a checked
  `git update-ref`. No working files or staged contents were discarded.
- The follow-up release notes/evidence/handoff commit changes documentation only;
  the tested source and published tag remain immutable. Open backlog work is
  unchanged; this release does not claim to implement NE-012–NE-030.

## 2026-11-15 — v0.5.16-alpha release preparation

- The user requested a new tag/release containing all current updates. Local
  and remote main were at `e1b083930e24a83de2534d0baf336ac8e7d262bb`, the
  existing `v0.5.15-alpha` tag. Preserved the pending November 13–15 documentation
  updates in `HANDOFF.md`, `TODO.md`, and `desktop/CLAUDE.md` for inclusion.
- Live GitHub verification resolved the previous handoff's pending question:
  v0.5.15-alpha was published with all three installers. Its tagged workflow
  [43357686920](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/43357686920)
  passed Ruff and **381 tests in 454.79 s**, no skips and a clean exit; main
  quality run 43357680634 also succeeded. No old tag was moved.
- Prepared numeric version `0.5.16` and release/download labels
  `v0.5.16-alpha`. Updated README links/notes, current test-count documentation,
  and the stale NE-010/011 statuses. This refresh carries the implemented
  timeline/redaction fixes forward; it does not implement NE-012–NE-030 or the
  open optimization findings. Release notes are in
  `desktop/docs/releases/v0.5.16-alpha.md`.
- The prior temporary CLI/runtime had been cleared. Recreated a task-local
  environment at `/private/tmp/neuroedit-release-20261115` with the existing
  release constraints and verified the official ARM64 GitHub CLI archive's
  SHA-256 against its GitHub release metadata. The installed Intel CLI and
  intentional iCloud-hosted `.venv` were not replaced or modified.
- Fresh release-candidate checks: **381 passed in 199.33 s**, no skips and clean
  process exit; full Ruff, source compileall, version/default consistency,
  macOS build-script shell syntax, and `git diff --check` passed. Used the
  bundled ARM64 FFmpeg on PATH, Qt offscreen/FFmpeg backend, `PYTHONPATH=src`,
  and the task-local Python runtime. The capture-baseline test passed here;
  this does not close the broader NE-027 hardening ticket.
- The complete native preference snapshot matched before/after validation.
  No project migration, new QA capture, or application runtime code change was
  performed. Previously tracked QA artifacts were left unchanged; the private
  storage-location screenshot remains ignored. Publication/build results for
  the new tag are recorded separately once they complete.

## 2026-11-12 — Release v0.5.15-alpha (NE-010/NE-011 fixes + review docs)

**Release:** version bumped 0.5.14 -> 0.5.15 in `desktop/pyproject.toml`, `desktop/src/neuroedit_desktop/__init__.py`,
`desktop/NeuroEdit.spec`, `desktop/installer/NeuroEdit.iss`, `desktop/scripts/build_alpha_windows.ps1`.
Committed everything below plus `desktop/docs/review-2026-11-12/` and `desktop/qa/`, pushed `main`,
tagged `v0.5.15-alpha` (tag push triggers `.github/workflows/build.yml`: quality job, then mac .dmg + Windows installer, GitHub Release).
**Release-time local check:** full `pytest` here gave 368 passed / 13 failed; the failures are ffmpeg
subprocess exits (code 255) in `test_export_timing.py` / `test_main_window_headless.py` with the system
`/usr/local/bin/ffmpeg` (CI uses the bundled imageio ffmpeg). Not reproduced with CI's setup; CI is the gate.
Ruff not installed in the local venv, so not run at release time. **Next step:** confirm the
Actions run for `v0.5.15-alpha` is green and the Release has both installers.

### Fix details (previously uncommitted)

**What changed (base `3e00fc0`, nothing committed):**
- `desktop/src/neuroedit_desktop/models.py`: `ripple_after` sends redactions through
  `_ripple_redaction` (covered footage stays covered; grows over footage revealed at the edit
  point; a finite window never becomes 0 = unlimited). New
  `ProjectState.move_redactions_with_clips` (clip reorder) and `timeline_positions` /
  `restore_timeline_positions` (trim-drag snapshot).
- `desktop/src/neuroedit_desktop/ui/editor_panels.py`: both trim handles snapshot at press and
  apply one ripple from that state per mouse move (`_rewind_trim_drag`), rewinding before
  snapping; a trim drag dropped on the trash deletes the clip as it was at press;
  `_commit_clip_move` calls `move_redactions_with_clips`.
- `desktop/tests/test_ripple_overlays.py`: 40 new tests. 19 of the first 33 failed before the
  fix; the 7 follow-up tests fail 4 ways when the follow-up fixes are removed.
- `desktop/pyproject.toml`: `[tool.pytest.ini_options] testpaths = ["tests"]`.
- `desktop/docs/review-2026-11-12/repros/conftest.py`: settings isolation for the repro folder;
  the three NE-010/011 repros were removed from `test_pure.py` (now 8 fail, 1 pass by design).

**Verification:**
- Final run of `pytest` (tests/ only) on the finished change: 380 passed, 1 failed in 164 s.
  The failure is the known `tests/test_capture_baseline.py` 30 s timeout (NE-027).
  `ruff check src tests scripts` clean; `git diff --check` clean.
- The process exited 139 after printing the summary. Same thing was seen once on unmodified
  `3e00fc0` earlier today, so it predates this change; not investigated (add to NE-027).
- Independent Sonnet review with randomized property tests: 28,000 single edits, 10,000 chains
  of 1-3 edits, 14,000 real mouse drags; no case of a redaction losing footage it covered.
  Its mutation checks showed the new tests fail when each rule is removed. Scripts are in the
  session scratchpad only (not kept in the repo).
- An earlier Haiku run on the first version of the change: 372 passed in tests/, plus one
  `test_audio_preview` failure ("No ffmpeg exe could be found" from `imageio_ffmpeg`) that
  passes alone and in the final run. Treat as a flake of the iCloud-hosted venv under load.
- NOT verified: in the running app by hand; rendered export frames; Windows.

**Gotcha — test isolation slip (fixed):** the review repros under `desktop/docs/` were collected
by a bare `pytest` from `desktop/` without `tests/conftest.py`, so MainWindow repro tests ran
against the native preferences once and
`~/Library/Preferences/com.neuroedit.Desktop.plist` was rewritten (hash `a76780b4…` ->
`7bd8ebe8…`). Same size (482 bytes), same keys, values as expected; the fixtures restore what
they set. Autosave `project.json` unchanged (`0d10f810…`). Fixed by the two items above; the
final run left all three hashes unchanged. Rule going forward: any test that builds MainWindow
must sit under a conftest that applies `isolated_app_settings`.

**Known trade-offs:** a redaction spanning two clips that are reordered apart widens to one
window; a redaction only on removed footage stays in place; unlimited redactions move earlier
on removal (deviation from the ticket's "never move"); an item added mid-drag is not rewound.

**Next steps:** user to decide on committing; try a trim/reorder with a redaction in the app;
then NE-012, NE-014, NE-013 in that order.

## 2026-11-12 — Full app review, 21 new tickets (NE-010 to NE-030)

- The user asked for a high-level review of the app and its current state,
  orchestrated with Haiku and Sonnet subagents, with tickets for what it found.
  Baseline `3e00fc0` (v0.5.14-alpha). **Review and ticketing only: no
  application source, test, dependency, preference, commit, push, tag, or
  release changed.** Nothing from this entry is committed.
- Coordinator: Claude Fable. Subagents: four Sonnet code reviewers (core
  window/undo/persistence; timeline/canvas; export/PHI/captions;
  audio/import/SAM/library), one Haiku docs/CI auditor, one Haiku test runner,
  one Sonnet verification engineer. The coordinator read the cited source for
  every ticket and reran the failing tests itself.
- Durable report: [desktop/docs/review-2026-11-12/REVIEW.md](desktop/docs/review-2026-11-12/REVIEW.md).
  Tickets: [CODING_TICKETS.md](CODING_TICKETS.md), new section "2026-11-12
  review batch", NE-010 to NE-030, all **Ready** and unassigned.
- Five P1 tickets:
  - NE-010 — redactions stop covering their footage after timeline edits.
    Dragging the head handle of the first clip left moves a whole-timeline
    redaction off t=0 (`models.py:353-358` via `ui/editor_panels.py:1232`).
  - NE-011 — head-trim ripple result depends on the drag path
    (`ui/editor_panels.py:1210-1232`).
  - NE-012 — the exporter paints labels, arrows, and masks over the whole
    output frame instead of the fitted source rectangle (`exporter.py:717-726`,
    `:834`); wrong whenever the source is not the output aspect.
  - NE-013 — final `os.replace` from the temp directory fails when the output
    is on another volume (`exporter.py:125`, `:1165`). Source confirmed only.
  - NE-014 — zooming or clicking the timeline resets a completed PHI review
    and adds an undo step (`ui/main_window.py:832`, `ui/editor_panels.py:1572`).
- Twelve P2 tickets (NE-015 to NE-026) cover caption PHI gating, per-keystroke
  undo snapshots, two scratch-autosave data-loss paths, a spurious dirty mark
  on media load, Take Still caption drift, silent cancel on close, discarded
  edge drags, ffmpeg selection, SAM weight lifecycle, the tutorial editing real
  projects, and export render cost. Four P3 tickets (NE-027 to NE-030) group CI,
  timeline polish, export robustness, and small items including docs drift.
- **Verification.** Ten findings were turned into pytest tests that assert the
  desired behaviour; all fail on `3e00fc0`
  (`desktop/docs/review-2026-11-12/repros/`, **11 failed, 1 passed in 3.32 s**;
  the pass is the settings-isolation guard). They are kept outside `tests/` so
  the release gate stays green; move each into `tests/` when its ticket is
  fixed. Run from `desktop/`:
  `QT_QPA_PLATFORM=offscreen PYTHONPATH=src:tests python -m pytest -p conftest docs/review-2026-11-12/repros -q`.
  NE-013, NE-015, NE-021, NE-024, NE-025 are source confirmed, not executed.
  NE-026 is unmeasured.
- **Suite status on this Mac.** `ruff check src tests scripts` passed (system
  ruff 0.15.16; the project venv has no ruff). Full suite with the project venv
  (Python 3.13.5, PySide6 6.11.1): 341 collected, **328 passed, 13 failed in
  370 s**, process exit 139 after the summary (seen once, not rerun).
  Twelve failures are environmental and also a product finding (NE-023):
  `/usr/local/bin/ffmpeg` is an x86_64 binary, this Mac is arm64 without
  Rosetta, and `exporter.py:165-176` prefers `PATH` ffmpeg over the bundled
  one. With the bundled arm64 ffmpeg first on `PATH` those twelve pass. The
  thirteenth, `tests/test_capture_baseline.py`, exceeds its 30 s child-process
  limit here (three of three runs); see NE-027. Net 340 of 341 locally.
- **Gotchas.** The isolated runtime the earlier entries used
  (`/private/tmp/neuroedit-security-20261106`, `/private/tmp/neuroedit-security-bin`)
  no longer exists. To run export tests locally, put the bundled binary first:
  `python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"`,
  symlink it as `ffmpeg` in a scratch directory, and prepend that to `PATH`.
  First import from the iCloud venv can take over two minutes.
- **Side effects.** SHA-256 of the user's autosave `project.json` and both
  NeuroEdit preference plists were identical before and after every test run.
  The app was not launched.
- **Not covered.** Packaged installers, Windows, physical audio, real SAM
  inference (no torch in the venv), clinical footage, accessibility. Not a
  security audit.
- **Working tree.** New and uncommitted from this session: the
  `CODING_TICKETS.md` batch, this entry, one pointer line in `TODO.md`, and
  `desktop/docs/review-2026-11-12/`. The earlier uncommitted automation edits
  to `HANDOFF.md`, `TODO.md`, and `desktop/CLAUDE.md`, and untracked
  `desktop/qa/`, were left as found.
- **Next steps.** Fix NE-010 and NE-011 together (same function), then NE-012,
  NE-014, NE-013. Settle "what counts as a document edit" once for NE-014,
  NE-016, and NE-019. Owner decisions still open from `TODO.md` P0: DMG launch
  verification, repository visibility, signing.

## 2026-11-10 — v0.5.14-alpha published

- Published [NeuroEdit v0.5.14-alpha](https://github.com/v7sm25qk5v-ui/NeuroEdit/releases/tag/v0.5.14-alpha)
  as a public, non-draft GitHub prerelease. The new immutable annotated tag
  resolves to `c28bf019b1da3f05f85b62d30abef0eee1813bed`; the tag object is
  `fdb467bd69ecce12c564bca5eb7947cec12e81ac`. No existing tag was moved.
- [Installer workflow 42927955107](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/42927955107)
  completed quality, macOS, Windows, and publication jobs successfully.
  Tagged quality passed Ruff and **341 tests in 339.65 s**, no skips and clean
  exit. Final [main quality run 42927955543](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/42927955543)
  also passed Ruff and **341 tests in 412.20 s**, no skips and clean exit.
- All three release assets are uploaded and nonempty:
  - `NeuroEdit-v0.5.14-alpha-macOS-unsigned.dmg` — 129,468,455 bytes.
  - `NeuroEdit-v0.5.14-alpha-macOS-unsigned.zip` — 117,552,547 bytes.
  - `NeuroEdit-v0.5.14-alpha-Windows-Setup.exe` — 100,243,525 bytes.
  GitHub-reported SHA-256 hashes and publication metadata are recorded in
  `desktop/docs/engineering-2026-11-10/release-verification.json`.
  Public HTTP HEAD requests returned 200 for all three installer URLs; the
  installers were not downloaded or installed during verification.
- Release notes and installer links describe the nine verified tickets,
  including original-position narration and the explicit Stop/wait/retry close
  policy. Numeric app/package/bundle defaults are `0.5.14`; artifacts and the
  prerelease use `v0.5.14-alpha`.
- This final publication record is documentation-only; application code stays
  at the tested tag. Native preferences and project files were not changed by
  publication. Existing `desktop/qa/` and the storage-location screenshot remain
  local. Physical microphone/audio latency, native Windows UI/scaling, installed
  app runtime, and actual SAM inference remain unverified. Installers remain
  unsigned/editor-only; no completed security-audit claim is made.

## 2026-11-10 — Release-candidate CI and test lifecycle cleanup

- Final local rerun after cleanup: **341 passed in 139.36 s**, no skips and
  clean exit. Ruff/diff checks passed, and native preferences still exactly
  matched the private pre-validation snapshot. This final candidate is ready
  for the new immutable release tag and its gated installer pipeline.
- Pushed `bf45a3945e793069b0120d83395927a6e2467429` to `origin/main`.
  [Quality run 42926473034](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/42926473034)
  passed Ruff and **341 tests in 358.97 s**, no skips and clean exit.
- The configured Git credential helper referenced an Intel-only CLI. The push
  succeeded using the existing arm64 CLI as a command-scoped helper override;
  global Git configuration was not changed.
- Before tagging, Sol reproduced a deferred startup callback escaping the new
  recording real-window test after monkeypatch teardown. This was a test-only
  lifecycle defect, not attributed to the successful CI run or production app.
  Terra scoped out unrelated SAM startup and added finally close/delete/event
  cleanup while patches remain active. Test assertions are preserved.
- Focused recording/lifecycle checks passed 22 tests. Sol's independent pytest
  post-fixture sentinel passed two tests with clean exit, no late probe, and no
  retained window. No application source or version changed in this cleanup.
  The final full local rerun and tag-build results are recorded separately.
- No release tag was moved or published during this checkpoint. Existing
  untracked QA files and the approved native autosave setting remain untouched.

## 2026-11-10 — v0.5.14-alpha validated release candidate

- The user authorized fixing NE-008/009, updating GitHub, pushing, and cutting
  a new tag/release. Continued the Terra engineer/Sol senior-review arrangement.
  All nine coding tickets are now software verified; release publication is
  recorded separately after CI succeeds.
- Regressions first reproduced three failures: recording at the wrong timeline
  position and premature close/save while active or already finalizing. Record
  now retains its original playhead position. Close is refused until recording
  finishes, with Stop/wait/retry guidance. Recorder failures preserve existing
  files, skip invalid attachment, and do not trap the window in a pending state.
  Error-signal ordering, synchronous completion, repeated/reentrant close,
  failed save/probe, and saved-project recovery are covered.
- Sol inspected the actual changes and independently passed 31 focused tests.
  Final full local suite: **341 passed in 148.64 s**, no skips and clean exit,
  using the existing isolated runtime, bundled arm64 FFmpeg, Qt offscreen, and
  `PYTHONPATH=src`. Full Ruff, source compileall, and diff checks passed.
  Native preferences exactly matched the private pre-validation snapshot,
  including the user-approved autosave folder; no project files were migrated.
- Prepared numeric version `0.5.14` and tag/download labels `v0.5.14-alpha` in
  package metadata, app version, bundle defaults, Windows defaults, and README.
  Release notes are in
  `desktop/docs/engineering-2026-11-10/RELEASE_NOTES.md`. Dependency constraints
  and the reviewed CI quality/build ordering remain unchanged.
- Live GitHub checks confirmed remote main at `81a405f`, write permission, and
  no existing `v0.5.14-alpha` tag. The previous published alpha is
  `v0.5.13-alpha.2`. The release will include the earlier seven reviewed fixes
  as well as these two recording fixes.
- Existing untracked `desktop/qa/` is excluded. New documentation paths were
  generalized, and the local storage-location screenshot is retained locally
  but gitignored because it displays local filesystem paths. Nineteen captures
  were inspected locally; eighteen engineering captures are published.
- This entry records validation/preparation only, not completed publication or
  installer execution. Physical audio/microphone, native Windows scaling, real
  SAM inference, and installed-app runtime checks remain unverified.

## 2026-11-10 — Two recording follow-up defects ticketed

- The user asked whether further issues/tickets remained. Reviewed the live
  board and recording lifecycle, and added NE-008/009 as **Ready**, unassigned
  coding tickets. The original seven remain software verified; these are not
  claims that the earlier batch addressed the whole recording workflow.
- NE-008: controlled invocation of the actual recording methods starts at 2 s,
  moves the playhead to 7 s, and inserts narration at 7 s on completion. Capture
  and retain the recording's original timeline insertion point.
- NE-009: controlled close/finalization invocation saves before a pending
  recording is attached; delayed completion adds one live track while the saved
  project contains none. Finalize narration before final save/close, with a safe
  cancellation/error path. This demonstrates a missing saved reference, not
  deletion of the underlying audio file.
- Evidence: `desktop/docs/engineering-2026-11-10/follow-up-evidence.json`.
  Recorder/device/base widget close were mocked; no microphone, real application
  close, native preference write, or production source edit was performed.
  JSON parsing and `git diff --check` passed. No fresh full-suite result is
  claimed for this ticket/documentation-only follow-up.

## 2026-11-10 — User-approved autosave location restored

- The user approved restoring the existing
  `/Users/alangordillo/Documents/NeuroEdit/Autosave` folder after it was verified
  to contain `project.json`.
- Changed only the native `storage/projectRoot` preference. A fresh process
  using the app's `default_project_root()` resolves to the approved folder.
  Other preferences compared equal before/after, and the existing `project.json`
  SHA-256 was unchanged. No project files were moved or rewritten.
- This resolves the autosave-location follow-up in the entry below. The original
  values of the other keys touched by the earlier validation incident remain
  unknown and were not guessed. A running app keeps its current project/store;
  the restored default applies when NeuroEdit next opens or creates a project.
- Updated ticket/review status notes; `git diff --check` passed. No application
  code changed, so the earlier 327-test result was not rerun or claimed anew.

## 2026-11-10 — Coding tickets, Terra implementation, and Sol review

- Created [CODING_TICKETS.md](CODING_TICKETS.md) for the six concrete application
  issues and the confirmed screenshot-tool defect from the November 7 review.
  Two `gpt-6.1-terra` software engineers implemented the changes; a
  `gpt-6.1-sol` project manager/senior reviewer managed acceptance and reviewed
  the actual diffs. The coordinating agent checked integration and maintained
  this handoff. No external issue tracker was selected or written to.
- NE-001: import buttons now fit the media pane; export source-audio guidance
  wraps and explains that added narration/music is retained. Defaults are intact.
- NE-002/005: added audio tracks can be auditioned against timeline playback,
  including seeks, overlap, rate changes, stills, and audio-only intervals.
  Playback stops on project replacement/close and during deferred video seeks.
  Invalid audio probes no longer create guessed five-second tracks; recording
  finalization waits for the recorder to stop and validates the finished file.
- NE-003: File → Relink Unavailable Media repairs an explicitly selected
  video/image/audio/slide-image reference, validates replacement bounds, retains
  identity and edits, supports undo/save/reopen, clears caches, and resets PHI
  approvals. Split siblings are repaired individually, without silent matching.
- NE-004: video metadata import runs on a worker, commits ordered successful
  results in one undo transaction, rejects cancelled/stale results, and reuses
  stat-validated metadata for the selected preview instead of probing again on
  the UI thread. Close includes import-worker shutdown.
- NE-006: single-frame SAM cancellation is checked before/after inference and
  again when delivering a queued result. Cancelled masks are discarded without
  attaching an annotation or removing unrelated masks.
- NE-007: screenshots use an asserted temporary INI settings constructor and
  isolated storage, verify panel/dialog identity, select SAM explicitly, surface
  save failures, and restore patches/clean up on failure. Two corrected runs
  each produced 19 inspected captures, including scrolled minimum-size controls.
- Senior review and evidence:
  [desktop/docs/engineering-2026-11-10/REVIEW.md](desktop/docs/engineering-2026-11-10/REVIEW.md).
  Review caught and resolved small-seek synchronization, old narration during
  project activation, queued cancellation, source-bound expansion, duplicate
  GUI probing, and ineffective native settings isolation. A newly orphaned
  image helper was removed; the tutorial's video helper remains.
- Final combined checks from `desktop/`, using the existing isolated runtime
  `/private/tmp/neuroedit-security-20261106/bin/python`, arm64 FFmpeg via
  `PATH=/private/tmp/neuroedit-security-bin:$PATH`, `QT_QPA_PLATFORM=offscreen`,
  and `PYTHONPATH=src`: **327 passed in 139.58 s**, no skips and a clean exit;
  full Ruff, source compileall, and `git diff --check` passed. The first combined
  run had one failure in an older incomplete `MainWindow.__new__` test fixture;
  the fixture now supplies the transport collaborators required by activation.
  Production lifecycle safeguards were preserved.
- Real synthetic media checks passed: moved-video relink, undo/redo,
  save/reopen, encoded export, and decoded redaction pixels; encoded narration
  PCM was silent before/after the intended tone interval and nonzero within it.
  A real H.264 import probed once off the GUI thread, committed on the GUI thread,
  finished, and closed cleanly in about 0.3 s. Earlier polling/instrumentation
  attempts were rejected as evidence; their isolated processes were stopped.
- **Unresolved preference recovery:** an early screenshot-harness revision
  wrote `storage/projectRoot`, `storage/promptShown`, `tutorial/seen`, and
  `recentProjects` before constructor isolation was corrected. Original values
  were not recorded, so exact persistent effects are unknown. Current preferences
  include an older pytest autosave path and nonempty recents; this task cannot
  establish their origin. The user was informed and asked for the intended
  autosave folder. No guessed restoration or project migration was performed.
  Corrected success/failure tests preserve native settings, but do not undo the
  earlier incident. The software fixes are verified; this operational follow-up
  remains open.
- Physical listening/latency, Windows scaling, and real SAM inference remain
  unverified. A direct Qt audio-buffer smoke could not complete without an audio
  device and was terminated; it is not counted as successful validation. Preview
  gain is capped at 1.0 by Qt, while existing exported persisted gain can reach
  2.0; normal UI-created tracks use 0..1. No commit, push, package, tag, release,
  dependency change, or migration was made. Existing `desktop/qa/` and prior
  November 7 review artifacts were preserved.

## 2026-11-07 — Feature, implementation, and repeat-use product review

- The user requested a main-agent review coordinated with lower-cost research
  subagents, then selected **getting a small group of clinicians using NeuroEdit
  repeatedly** as the next-phase outcome. Three `gpt-6-luna` reviewers examined
  feature functionality, engineering/optimization, and current alternatives;
  the main agent checked source findings, ran controlled probes, and prioritized
  the combined results. This was a review, not a feature implementation.
- The durable report is
  [desktop/docs/review-2026-11-07/REVIEW.md](desktop/docs/review-2026-11-07/REVIEW.md),
  with seven inspected fresh offscreen screenshots and two JSON evidence files.
  It maps current features, distinguishes source confirmation from execution
  and hypotheses, and proposes a five-clinician pilot with three independent
  second-session exports within 30 days as a decision target.
- Highest-value gaps: clipped import/export guidance, absent timeline audition
  for added narration, no in-place missing-media relink, synchronous video
  probing on import, guessed audio duration after failed probing, and ineffective
  single-frame SAM cancellation. Captions use supplied/imported transcripts;
  they do not perform speech recognition. SAM remains source-build-only.
- Controlled probes confirmed that a 250 ms metadata-probe delay blocked the
  UI heartbeat, failed audio probing returned 5.0 seconds, and the real SAM
  worker emitted a successful fake result despite in-flight cancellation.
  Timeline fingerprint microbenchmarks show scaling cost but do not establish
  a user-visible performance failure or justify a general state/cache rewrite.
- Fresh full validation from `desktop/`: the existing isolated runtime at
  `/private/tmp/neuroedit-security-20261106/bin/python`, arm64 FFmpeg via
  `PATH=/private/tmp/neuroedit-security-bin:$PATH`, `QT_QPA_PLATFORM=offscreen`,
  and `PYTHONPATH=src`; `python -m pytest tests/ -q --disable-warnings
  -o faulthandler_timeout=120` passed **301 tests in 85.47 s** with no skips
  and a clean exit. Ruff and `git diff --check` passed. Screenshot capture used
  temporary INI settings and storage; the user's preferences were not changed.
- No actual SAM inference, clinical footage, packaged installation, Windows UI,
  hardware audio synchronization, or assistive-technology run was performed.
  This was not a security scan and does not replace the existing partial scan.
  No application source, dependency, release, commit, push, or tag changed.
  Existing untracked `desktop/qa/` was preserved.

## 2026-09-29 — Codex Security scan launch blocked

- Requested a Standard Codex Security scan of the whole repository through
  `start_codex_security_prompt_only_scan`.
- The launcher returned `Command failed` for `workbench_db.py
  start-prompt-only-scan`, without a scan ID or a more specific diagnostic.
  Capability preflight and source review did not begin; no security conclusions
  or completed report are available. The plugin workflow prohibits a replacement
  launch or terminal fallback after this direct-start failure.
- Separately, `git status --short` failed because the installed Xcode license
  has not been accepted. Its relationship to the launcher failure is unconfirmed.
- Only this handoff entry was changed. No application source, fixes, tests,
  commits, or releases were produced by this attempt.

## 2026-09-07 — Compact primary video storyline

- The user identified dead space as the core interaction problem. The primary
  video track is now always contiguous: loading a timeline, trimming a clip,
  deleting a clip, or completing a reorder closes unoccupied gaps.
- Dragging a video clip previews a change in sequence order. The insertion
  position follows the pointer as it crosses neighboring clip centers, so the
  result is independent of where the clip was grabbed. Release commits the
  visible order as one undoable edit; Escape cancels it.
- Full-frame slides created by Take Still remain visible project content. A
  video gap fully occupied by such slides is preserved rather than compacted.
  Reorder previews and commits preserve that occupied interval as well.
- Holding near either viewport edge scrolls during a drag. Short video blocks
  retain their true visual width and only show trim handles when wide enough.
- The earlier 2026-09-07 free-placement implementation is superseded by this
  compact storyline behavior. Wheel navigation, stacked label rows, clean split
  names, and playback transition fixes remain intact.
- Verification: focused timeline and main-window interaction suites **94
  passed**; final full desktop suite **255 passed in 97.56s**; `ruff check src
  tests scripts`; `python -m compileall -q src`; and `git diff --check`.
- Changes remain local source edits. Existing untracked `desktop/qa/` artifacts
  were preserved; no commit, push, package, tag, or release was made.

## 2026-09-07 — Timeline interaction and playback transitions

- Addressed the user's active editing reports with focused changes in
  `editor_panels.py`, `canvas.py`, and `main_window.py`; updated the tutorial and
  desktop README with the enacted controls.
- Clip dragging now previews a ghost and insertion guide without mutating the
  sequence during mouse movement. A neighbor's midpoint must be crossed using
  the moving clip's edge, independent of grab offset. Release reorders only the
  affected range, retaining its gaps and all other clip positions; Escape
  cancels the move. Trim ripple behavior is unchanged.
- Wheel/trackpad scrolling pans time. Shift-scroll reaches stacked rows.
  Overlapping annotation blocks have separate clickable rows, hidden annotations
  are marked Hidden, and hover text exposes the full name and time range.
- Splits keep the source name and remove legacy repeated `(cont.)` suffixes
  from the piece being split.
- Playback compares source URLs instead of clip IDs so same-file cuts reuse
  the decoder. Different-file loads and EndOfMedia surface resets retain the
  last valid frame until the next requested frame arrives. Real decoder testing
  also identified old-source LoadedMedia signals during setSource: deferred
  seeks now arm after source replacement and check the resulting media status.
- Verification: new behavioral regressions reproduced the original drag,
  label, wheel, naming, and source-reload failures. A real FFmpeg/Qt smoke test
  samples rendered red footage across a same-file split into a trimmed blue
  file and detects black frames between them. Offscreen timeline screenshots
  were visually inspected. Final quality checks: **244 passed in 98.28s**;
  `ruff check src tests scripts`; `python -m compileall -q desktop/src`; and
  `git diff --check`. Real-video QA used Qt's offscreen FFmpeg backend; packaged
  macOS/Windows and the user's live footage were not exercised.
- These are local source changes, not a packaged release. The user's running
  app was not restarted or modified. Different files may still pause briefly
  while loading; this change masks that load with the last frame rather than
  implementing decoder preloading/audio crossfades. Existing untracked
  `desktop/qa/` artifacts were preserved; test settings use temporary INI files.


## 2026-09-07 — Same-source trim undo preview refresh

- Reviewed automation memory plus `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`,
  `HANDOFF.md`, and the 2026-09-05 codebase review. Owner/hardware/sample-data
  gates remain open for Windows packaged smoke, signing/privacy, Intel Mac, and
  Stryker/DICOM sample work; no release tag is indicated by the roadmap.
- Fixed the remaining 2026-09-05 paused-preview follow-up: undo/redo snapshot
  restore now compares the active clip's playback window, not only its source
  path. If a same-source trim/source-bound restore changes what frame should be
  shown, NeuroEdit reloads and seeks the active preview through the existing
  active-clip path.
- Added a focused undo-history regression proving a same-source trim restore
  reloads the preview path. The existing project-end-time restore test was
  adjusted to stub preview reload because that trim restore now intentionally
  triggers it.
- Verification: focused `tests/test_undo_history.py` (`23 passed`);
  `/Library/Frameworks/Python.framework/Versions/3.13/bin/ruff check src tests
  scripts`; full desktop suite (`231 passed`); `.venv/bin/python -m compileall
  -q src`; and `git diff --check`.

## 2026-09-06 — SAM edit-race invalidation

- Reviewed automation memory plus `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`,
  `HANDOFF.md`, `README.md`, `desktop/README.md`, `desktop/CLAUDE.md`, and the
  2026-09-05 codebase review. Owner/hardware/sample-data gates remain open for
  packaged smoke, signing/privacy, Intel Mac, and Stryker/DICOM sample work; no
  release tag is indicated by the roadmap.
- Fixed the bounded SAM follow-up from the 2026-09-05 review: in-flight
  segmentation and propagation now capture a content hash of the project when
  the job starts. If the same project is trimmed or otherwise edited before the
  worker finishes, the result is discarded and generated mask files are removed
  instead of attaching stale masks to the changed timeline.
- The hash intentionally ignores transient UI state and `sam_last_run`, so
  moving the playhead while SAM runs still preserves the captured seed/window
  behavior verified in the prior review.
- Verification: focused `tests/test_sam_workflow.py` (`25 passed`) and
  `/Library/Frameworks/Python.framework/Versions/3.13/bin/ruff check src tests
  scripts`; compatibility rerun for `test_single_frame_segmentation_stamps_sam_last_run`
  plus the SAM suite (`26 passed`); full desktop suite (`230 passed`); and
  `python -m compileall -q src`. Existing untracked `desktop/qa/` artifacts were
  preserved.

## 2026-09-05 — Multi-agent stability and efficiency review

- Three focused sub-agents reviewed persistence/lifecycle, rendering/export,
  and editing/SAM. The main agent reviewed each patch, added adversarial
  regressions, completed integration, and verified the combined changes.
- Fixed saved-autosave mask deletion, failed-close timer recovery, Save As
  destination/same-file errors, busy-worker export cancellation, leaked FFmpeg
  children, fractional-cut export drift, SAM source/timeline mapping and clip
  bounds, ripple caption/mask synchronization, and eager exporter importing.
- The real 20-cut export fixture now produces the expected 66 frames instead
  of 80. Mixed fast/render export tests check decoded redaction pixels at the
  boundary; VFR SAM tests preserve the frame visible at the requested seed time.
- Verification: baseline `197 passed`; final full suite `228 passed in 69.36s`;
  `ruff check src tests scripts`; `python -m compileall -q src`; and
  `git diff --check`. Real FFmpeg and offscreen Qt were exercised. SAM inference
  was stubbed, and packaged macOS/Windows runtime checks were not performed.
- The first full run exposed deferred widget cleanup in the new cancellation
  test. Fixed teardown and verified the cancellation/main-window sequence
  (`37 passed`) before the successful full run. Added temporary INI settings
  isolation for tests so future crashes cannot alter native NeuroEdit preferences.
- **Environment follow-up pending:** the earlier crash interrupted fixture
  restoration and left the native autosave-location preference pointing at a
  temporary test folder. Asked the user which folder to restore; an existing
  saved project is present at `~/Documents/NeuroEdit/Autosave`. Do not infer a
  different custom location. Project files have not been migrated.
- [Full findings, evidence, and follow-ups](desktop/docs/CODEBASE_REVIEW_2026-09-05.md).
  Same-project edits during SAM and paused-preview synchronization after undo
  remain bounded follow-up investigations. Changes are local; no commit, push,
  tag, or release. Existing untracked `desktop/qa/` artifacts were preserved.

## 2026-09-05 — v0.5.12-alpha release

- Released the verified stability and export-timing sweep as `v0.5.12-alpha`.
  Root installer links, package metadata, the in-app version, macOS bundle
  fallback, and Windows installer fallback now match the tag.
- The tagged workflow runs the desktop quality gate before building the unsigned
  macOS DMG/ZIP and Windows installer, then attaches all three to the release.
- The published release is a standard GitHub release rather than a prerelease.
  Future version tags use the same publication state.

## 2026-09-05 — v0.5.12 stable release

- GitHub’s sidebar does not treat a tag with the `-alpha` SemVer suffix as the
  latest release, even if its prerelease flag is false. Reissued the verified
  review sweep as stable `v0.5.12` so it is shown in the repository’s Releases
  panel and becomes the normal current release.
- Version metadata, installer names, root download documentation, and the
  release workflow now use the stable version. Builds remain unsigned; this
  changes release visibility and versioning, not signing/notarization status.

## Historical entries

Entries before v0.5.12 are preserved in
[the handoff archive](desktop/docs/history/HANDOFF-before-v0.5.12.md).
