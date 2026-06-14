# NeuroEdit — Session Handoff

Covers work completed across sessions (accumulated):

1. **Cross-platform build & distribution** (macOS + Windows from one codebase) — the main effort.
2. **Undo/redo correctness fixes** — detailed in [desktop/HANDOFF_undo_redo.md](desktop/HANDOFF_undo_redo.md); summarized here.
3. **Windows UI fixes** — native font, high-DPI scaling, two-row toolbar.
4. **Licensing** — switched MIT → proprietary.
5. **Resize-safe UI** — stop toolbar/panel clipping when the window is narrowed.
6. **SAM3 first-run download flow** — in-app model download, weight cache management.
7. **P1 timeline editing + P2 SAM mask workflow** — selection/snapping/rename,
   clinician-style mask list, re-track, status, propagation window, and mask colors.
8. **P3 privacy/PHI review + P4 captions/export polish** (§11) — guided PHI
   review, pre-export checklist, storage location, captions with SRT/VTT,
   export history, advanced export settings, and the quality test batch.

Repo: https://github.com/v7sm25qk5v-ui/NeuroEdit. Default branch `main`.
**Visibility: still PUBLIC** — recommended to make private (commercialization intent); pending owner action in GitHub settings.

---

## 1. Cross-platform build & distribution

### Goal
Ship a Windows version that non-technical users can install by double-clicking,
built from the **same source** as the macOS app so every code change reaches both
platforms automatically. Distribute via GitHub Releases.

### Approach (the key idea)
One source tree, two packaging targets, automated by GitHub Actions. There is **no
Windows fork** — only the *packaging* step branches by OS. Feature work in
`desktop/src/` carries to both platforms because both installers are built from the
same commit on each tagged release.

```
GitHub repo (source of truth)
   │  push tag v*  ──►  GitHub Actions
   │                      ├── macOS runner   → PyInstaller → .app → .dmg + .zip
   │                      └── Windows runner  → PyInstaller → folder → Inno Setup → Setup.exe
   └──────────────────►  GitHub Release  (both installers attached)
```

### Files added / changed
| File | Purpose |
|------|---------|
| [desktop/NeuroEdit.spec](desktop/NeuroEdit.spec) | Made cross-platform. Branches on `sys.platform`: `BUNDLE` → `.app` on macOS; `COLLECT` folder (`dist/NeuroEdit/NeuroEdit.exe`) on Windows. Also **explicitly bundles the imageio-ffmpeg binary** so export/probe work with no system ffmpeg (mandatory on Windows). |
| [desktop/installer/NeuroEdit.iss](desktop/installer/NeuroEdit.iss) | Inno Setup script → friendly **per-user** `Setup.exe` (no admin/UAC), Start-menu shortcut, optional desktop shortcut, uninstaller. |
| [desktop/scripts/build_alpha_windows.ps1](desktop/scripts/build_alpha_windows.ps1) | Windows build script mirroring `build_alpha_macos.sh`: venv → `pip install -e ".[package]"` → PyInstaller → Inno Setup. Aborts on native-tool failure (checks `$LASTEXITCODE`). |
| [.github/workflows/build.yml](.github/workflows/build.yml) | CI: on tag `v*` (or manual dispatch) builds both installers on macOS + Windows runners; on tags also publishes a GitHub Release with all assets. |
| [desktop/WINDOWS_DISTRIBUTION.md](desktop/WINDOWS_DISTRIBUTION.md) | Tester install steps + code-signing notes. |
| [.gitignore](.gitignore) (root) | New. Ignores venvs, build output, `release/`, `.claude/`, `.DS_Store`, iCloud `* 2.py` conflict copies. |

### Why ffmpeg "just works" on Windows
The app already falls back to `imageio_ffmpeg.get_ffmpeg_exe()` in
[desktop/src/neuroedit_desktop/exporter.py](desktop/src/neuroedit_desktop/exporter.py)
(`_find_ffmpeg`) when no system ffmpeg is present, and the Mac-only
`h264_videotoolbox` encoder has a fallback. The spec bundles that binary, so the
Windows build is self-contained. Verified bundled in the macOS build locally
(`ffmpeg-macos-aarch64-v7.1` inside the `.app`); the Windows wheel ships the
Windows equivalent.

### How to operate it
**Build test artifacts (no release):** Actions tab → "Build alpha installers" →
"Run workflow" (Branch: `main`). Artifacts attach to the run.

**Cut a release (publishes downloads):**
```bash
git tag v0.3.0-alpha
git push origin v0.3.0-alpha
```
→ Release appears at https://github.com/v7sm25qk5v-ui/NeuroEdit/releases with
`*-macOS-unsigned.dmg`, `*-macOS-unsigned.zip`, and `*-Windows-Setup.exe`.

**Local Windows build (optional, needs a Windows machine):**
```powershell
cd desktop
.\scripts\build_alpha_windows.ps1 -Version alpha-001   # needs Python 3.12 + Inno Setup 6
```

### Gotchas learned this session
- **Re-running a failed run rebuilds the OLD commit.** After pushing a fix, start a
  *fresh* "Run workflow" (or push a new tag) — don't click "Re-run jobs". Verify the
  commit SHA shown at the top of the run.
- **`git push` of a branch does not trigger the workflow** — only tag pushes and
  manual dispatch do.
- **Inno Setup `[Tasks]` uses `Flags: unchecked`**, not `GroupFlags` (that's
  `[Components]`-only). This was the bug that failed the first Windows builds.
- **PowerShell does not auto-throw on native non-zero exits** — the script now
  checks `$LASTEXITCODE` after PyInstaller and Inno Setup.
- **GitHub auth:** pushing the workflow file needs a PAT with **`workflow`** scope
  (plus `repo`); credential cached in macOS keychain after first push.
- **Release job needs write permission.** If it 403s: repo Settings → Actions →
  General → Workflow permissions → "Read and write permissions", then re-push the tag.

### Verified vs. not
- ✅ macOS PyInstaller build runs locally and bundles ffmpeg; existing `release/` dmg untouched.
- ✅ Windows CI: pip install, PyInstaller `NeuroEdit.exe`, all PySide6/OpenCV/ffmpeg hooks, and Inno Setup compile all pass.
- ⏳ **Runtime not yet verified** — building ≠ running. Next real test: install the
  `Setup.exe` on an actual Windows PC and confirm the app launches, imports video, and exports.

### Open follow-ups
- **Code signing** (removes Windows SmartScreen / macOS Gatekeeper warnings):
  Authenticode cert for Windows (~$200–400/yr); structured so signing drops into the
  workflow with no app-code change. Alpha ships unsigned with "Run anyway" instructions.
- **Node 20 action deprecation warnings** (harmless until ~Sept 2026): bump
  `actions/checkout`, `actions/setup-python`, `actions/upload-artifact` when convenient.
- **Architectures:** macOS = arm64 (Apple Silicon), Windows = x64. Intel Macs not covered.
- Optional: root `README.md` with download links + tester instructions.

---

## 2. Undo/redo correctness fixes

Full detail in [desktop/HANDOFF_undo_redo.md](desktop/HANDOFF_undo_redo.md). Summary:

- **Transient UI state no longer pollutes undo.** `_snapshot()` in
  [desktop/src/neuroedit_desktop/ui/main_window.py](desktop/src/neuroedit_desktop/ui/main_window.py)
  strips `active_panel`, `active_tool`, `current_time`, `scroll_left`,
  `selected_annotation_id`, `zoom` before snapshotting. Tool/panel/selection changes
  call `_mark_dirty(history=False)` — dirty for autosave, no undo entry, no redo clobber.
- **Net-zero edits clear redo.** `_push_history()` now calls `_redo_stack.clear()`
  *before* its dedup early-return.
- **Tests:** `desktop/tests/test_undo_history.py` (3 tests) plus existing suite — all
  6 pass via `cd desktop && source .venv/bin/activate && python -m pytest tests/ -q`.
- Prior session's move/resize-as-one-undo-step work (`annotation_mutated` during drag,
  `edit_committed` on release) is also documented in that file.

---

## 3. Windows UI fixes (commit `600a55a`)

The first Windows build launched but the toolbar overflowed and text
clipped/overlapped. Three root causes, all fixed:

- **Font:** [desktop/src/neuroedit_desktop/ui/styles.py](desktop/src/neuroedit_desktop/ui/styles.py)
  hardcoded `.AppleSystemUIFont`, which doesn't exist off macOS → Qt fell back to an
  oversized face. Now platform-native: **Segoe UI 9** on Windows, system font on macOS,
  Sans Serif on Linux (`_ui_font()`).
- **High-DPI:** [desktop/src/neuroedit_desktop/__main__.py](desktop/src/neuroedit_desktop/__main__.py)
  now sets `HighDpiScaleFactorRoundingPolicy.PassThrough` *before* `QApplication` is
  created, so fractional Windows scaling (125%/150%) no longer overflows fixed layouts.
- **Two-row toolbar:** `_build_header()` in
  [desktop/src/neuroedit_desktop/ui/main_window.py](desktop/src/neuroedit_desktop/ui/main_window.py)
  was one over-packed row. Split into row 1 (identity, history, project name/type,
  panel tabs, Export) and row 2 (drawing tools). Header sizeHint width dropped from
  ~1400px to ~965px; height 56→88. Removed the now-unused `QSizePolicy` import.
- Verified: tests pass, `MainWindow` constructs headlessly, ruff clean on changes.
- **Not yet visually confirmed on Windows** — awaiting a screenshot from the
  `v0.2.1-alpha` build to verify the toolbar renders cleanly.

## 4. Licensing (commit `751fb97`)

- Replaced the MIT license with a **proprietary "all rights reserved"** [LICENSE](LICENSE),
  because the goal is to commercialize / keep control (MIT lets anyone use/sell the code).
- Added a **medical/clinical disclaimer** (not a medical device, not FDA-cleared) and a
  **third-party-components** clause (bundled Qt/FFmpeg/OpenCV/NumPy keep their own licenses).
- Caveats noted to owner: MIT grants on already-published versions (`v0.2.0`/`v0.2.1`,
  earlier commits) are likely irrevocable for those versions; making the repo private is
  the real control lever; private repos meter Actions minutes (macOS 10×, Windows 2×);
  a lawyer + an end-user EULA are recommended before any real launch.

## 5. Resize-safe UI (commit `82c6768`)

A screen recording showed that narrowing the window clipped toolbar controls and
panel buttons (e.g. the SAM panel's "Point Placement On"). Root causes: the window
had **no minimum size**, the two-row header wasn't scrollable, the video pane had no
minimum, and the side panels had horizontal scrolling turned off. An audit of all UI
regions produced a minimal 5-change fix (all in
[desktop/src/neuroedit_desktop/ui/main_window.py](desktop/src/neuroedit_desktop/ui/main_window.py)
except the last, in `editor_panels.py`):

- `MainWindow.setMinimumSize(960, 600)` — was none; window could go off-screen.
- Header wrapped in a horizontal `QScrollArea` — the toolbar (natural width ~1022px)
  scrolls below that width instead of clipping its right-hand controls. Visible height
  unchanged (the global 8px scrollbar overlays the header's bottom margin).
- `video_column.setMinimumWidth(360)` — video pane can't be squeezed to nothing.
- Media + right panel: horizontal scrollbar `AlwaysOff → AsNeeded` — narrow panels
  scroll instead of clipping (fixes the SAM/Labels/Slides/Audio/Tips forms).
- `editor_panels.py` RichTimelineWidget: removed `toolbar_widget.setMinimumWidth(sizeHint)`
  that defeated the timeline toolbar's own scroll area.
- Verified headlessly: window `minimumSizeHint` (858×554) ≤ the 960×600 floor (so the
  toolbar scrolls rather than forcing the window wider); resize 960..1500px no crash;
  tests pass (6); ruff clean. **Not yet visually confirmed on Windows.**

> Process note: this fix was produced by a parallel audit workflow (4 region agents →
> 1 design synthesis) before implementing — useful pattern for UI-wide changes.

### 5b. Follow-up — panels still scrolled (commit `1ce8c02`)

After `82c6768`, the SAM panel *still* showed a horizontal scrollbar even at normal
sizes. Root cause found by measuring each panel's `minimumSizeHint().width()`: the
right panel is a **QStackedWidget whose min width is the MAX of all 5 panels**. The
wide Slides/Tips/Audio forms (486/445/345px — Slides' `QFormLayout`, Tips' long
consent checkboxes, Audio's 3-button rows) forced the whole stack — including the
206px SAM panel — to 486 and scrolled. New approach: **never let a pane be narrower
than its content.**
- Pin `panel_scroll` minimum width to the stacked panels' real min (now 445) and
  seed the splitter with it.
- Compute the **window minimum from actual pane widths** (media 250 + video 360 +
  panel 445 + slack) at the end of `_build_central_ui` → **1085×600**; this also
  exceeds the header's 1022px, so the toolbar no longer scrolls either.
- `SlideEditorPanel` form → `QFormLayout.WrapAllRows` (labels stack above fields):
  486 → 414, keeping the side panel from being needlessly wide.
- Verified headlessly: panel pane (445) ≥ stacked content (445) → no panel scroll;
  header (1022) < 1085 → no header scroll; resize cycles fine; tests pass; ruff clean.
- **Trade-off:** the window can no longer be narrowed below **1085px** (deliberate —
  it can't be shrunk into a clipped state). Tips' consent checkboxes (`QCheckBox`
  can't word-wrap) are the widest remaining driver (445). To allow a *smaller* min
  window later, shorten/restructure those labels and Audio's button rows, then lower
  `panel_min`. **Visually confirmed by the user on macOS (run from source).** Windows
  rendering still pending a build.

---

## 6. SAM3 first-run download flow (commit `23e53b8`)

Before this commit, users with no SAM3 weights had no in-app path to get them —
they had to run `hf auth login` manually. This commit adds a full first-run flow:

- **`SamDownloadWorker`** (`main_window.py:1912-1971`) — background worker that
  calls `sam_backend.warmup()` to download ~3.2 GB of weights from Hugging Face.
  Accepts an HF token via a new "Set Up SAM3" dialog with a token field.
- **Status-bar wiring** (`main_window.py:4044-4091`) — progress, failure, and
  "ready" messages surface in the status bar during and after download.
- **Weight cache cleanup** (`main_window.py:4096-4115`) — new "Delete SAM3
  weights?" action under the SAM panel for users who want to reclaim disk space.
- `sam_backend.py:57` — `weights_cached()` check gates the flow so already-
  downloaded weights don't re-trigger the setup dialog.
- Verified: first-run dialog opens when weights are absent; download progress
  surfaces in the status bar; cache-delete action removes the weights directory.
  **Full end-to-end download not yet verified on a clean machine** (would need
  a valid HF token and ~3.2 GB of bandwidth).

---

## 7. Project Library / Recent Cases dialog improvements (uncommitted)

All changes are in `desktop/src/neuroedit_desktop/ui/main_window.py`.

### What was added

**New top-level helpers (lines ~2124–2189):**
- `_relative_time(ts)` — converts a unix timestamp to "Opened today", "Opened yesterday", "Opened N days ago", "Opened last week", "Opened X weeks ago", or a full date string ("Mar 14, 2025") for items 28+ days old.
- `_read_project_meta(path)` — opens `project.json` once and extracts: `project_name`, `total_duration` (sum of all clip durations), `media_count` (clips + audio_tracks + slides), `missing_count` (paths that fail `os.path.exists`), `first_source_path` + `first_clip_duration` for thumbnail generation. Returns an `ok: False` sentinel if the file is unreadable; never raises.
- `_make_gray_placeholder()` — renders a solid `#2c3340` 160×90 `QPixmap` used as the thumbnail placeholder while the background thread works (or as the fallback if ffmpeg fails).

**New class `ThumbnailWorker(QObject)` (lines ~2192–2230):**
- Runs on a background `QThread` spawned by `ProjectLibraryDialog`.
- For each `(project_path, source_path, clip_dur)` task: checks for a cached `.thumb.jpg` that is newer than the project file; if fresh, emits it immediately. Otherwise calls `imageio_ffmpeg.get_ffmpeg_exe()` + `subprocess.run` to extract a single frame at 15% of the clip's duration (or 5 s if duration is 0). Caches as `<project_path>.thumb.jpg`.
- Gracefully skips any task where ffmpeg isn't available or fails; emits `thumbnail_ready(project_path, thumb_path)` for successes only.
- Has a `stop()` flag so the thread can be cleanly cancelled when the dialog re-populates or closes.

**`ProjectLibraryDialog` — rewritten `_populate`, extended class (lines ~2233–2461):**
- Each item now shows 3 lines: project name, relative timestamp, and a detail line (`M:SS  •  N clips, N audio, N slides`).
- A gray placeholder icon is set immediately at populate time; the background worker replaces it when a real thumbnail arrives (`_on_thumbnail_ready`).
- Icon size set to `QSize(160, 90)`.
- Missing-file indicator: if the JSON parsed OK and 1+ files are missing, appends `⚠ N source file(s) missing` to the item text and colors it red (`#F44336`). If all files present, name is green (`#4CAF50`). If the project file itself is gone, gray (`#6b7280`).
- Right-click context menu (`_show_context_menu`) adds "Open", "Reveal in Finder" / "Reveal in Explorer" / "Open folder" (platform-aware), and "Remove from List". Uses `QDesktopServices.openUrl(QUrl.fromLocalFile(...))`.
- `closeEvent` calls `_stop_thumb_thread()` so the worker is always cleaned up.

**New imports added at file top:**
- stdlib: `datetime`, `json`, `subprocess`, `sys`
- Qt: `QSize` (QtCore), `QDesktopServices` (QtGui), `QMenu` (QtWidgets)

### What each card now shows
```
[160×90 thumbnail or gray placeholder]  Project Name
                                         Opened today
                                         1:23  •  3 clips, 1 audio
```
or with a warning:
```
[gray placeholder]  My Project  ⚠ 2 source files missing
                    Opened 3 days ago
                    2:47  •  2 clips
```

### Edge cases handled
- JSON unreadable / project file missing → shows folder name, gray, "(not found)" suffix, no crash
- No clips / duration = 0 → detail line omitted or shows only media count
- Thumbnail ffmpeg failure → placeholder persists; no crash, no broken icon
- Dialog closed while thumbnails are generating → `_stop_thumb_thread` cancels cleanly
- Cached thumbnail newer than project file → served immediately without re-running ffmpeg
- Windows paths with spaces → source path quoted in ffmpeg command

### Edge cases left as TODO
- The dialog reads each project file twice (once in `_read_project_meta`, once in `_populate` for the parts breakdown). Could be collapsed into one read with a minor refactor, but it's fast enough for the typical handful of recent projects.
- Thumbnail `.thumb.jpg` files accumulate next to the project files indefinitely. A cache-eviction pass (e.g., delete thumbs for removed-from-recents projects) would be a polish step.

### Verification
- `ruff check src tests` — All checks passed (zero errors)
- `python -m pytest tests/ -q` — 6 passed

---

## 8. Annotation workflow improvements (uncommitted)

All changes in `desktop/src/neuroedit_desktop/ui/main_window.py` and `desktop/src/neuroedit_desktop/models.py`.

### Feature 1: Duplicate annotation at playhead (Cmd+D)
- `LabelsPanel` gains `duplicate_requested = Signal(str)` and a **Duplicate** button in the inspector's action row.
- `MainWindow._duplicate_annotation(annotation_id)` does `copy.deepcopy(ann)`, assigns a new UUID, sets `frame_time = current_time`, appends to the list, selects the copy, pushes to undo.
- `MainWindow._duplicate_selected_annotation()` is the Cmd+D handler — guards against `QLineEdit`/`QTextEdit` focus, then delegates.
- `QAction("Duplicate Annotation at Playhead")` with shortcut `Ctrl+D` added to the Edit menu.

### Feature 2: Delete button in inspector + keyboard shortcut
- A red **Delete** button (`color: #F44336`) added to the inspector's action row alongside Duplicate.
- Keyboard Delete/Backspace already handled by `VideoGraphicsView.keyPressEvent` (unchanged — works when the canvas has focus). The inspector button routes through `LabelsPanel._delete_selected → delete_requested signal → MainWindow._delete_annotation`.
- `QAction("Delete Annotation")` added to Edit menu (no shortcut — canvas keyPressEvent is the shortcut; adding a global shortcut would conflict with text editing).

### Feature 3: Custom label preset management
- `CUSTOM_PRESETS_PATH = Path.home() / ".neuroedit" / "custom_label_presets.json"` — JSON array of strings.
- `_load_custom_presets()` / `_save_custom_presets()` module-level helpers (safe: returns `[]` on any error).
- Presets section in `LabelsPanel` now shows: **Built-in** grid (no × button), **Custom** section with a row per preset (preset button + × remove button), and a **text field + Add button** at the bottom.
- `_refresh_custom_grid()` rebuilds the custom section from `self._custom_presets`.
- `_add_custom_preset()` deduplicates case-insensitively against built-ins and existing custom entries.
- `_remove_custom_preset(label)` removes and immediately saves to JSON.
- Toolbar label `QComboBox` also pre-loads custom presets at header-build time (`_load_custom_presets()`).
- `_BUILTIN_PRESET_LABELS` set used for the duplicate guard.

### Feature 4: Default annotation color → `#00E5FF` (cyan)
- `models.py`: `draw_color: str = "#00e5ff"` (was `"#22d3ee"`).
- `SWATCH_COLORS` in `main_window.py`: first entry changed from `"#22d3ee"` to `"#00e5ff"` so the swatch toolbar and inspector color swatches match the new default.

### Feature 5: "Set start/end to playhead" buttons in inspector
- `LabelsPanel` gains `set_start_to_playhead = Signal(str)` and `set_end_to_playhead = Signal(str)`.
- Two buttons **"◀ Set start"** and **"Set end ▶"** placed in a row below the Duration field.
- `start_time_label` (role=muted) shows `"Start: M:SS.S"` above the Duration field; updated in `_load_selected()`.
- `MainWindow._set_annotation_start_to_playhead(id)` → `ann.frame_time = current_time`, `_mark_dirty()`.
- `MainWindow._set_annotation_end_to_playhead(id)` → `ann.ann_duration = max(0.1, current_time - ann.frame_time)`, `_mark_dirty()`.
- Both mutations go through `_mark_dirty()` → `_push_history()` → undoable.

### Verification
- `ruff check src tests` → **All checks passed** (zero errors)
- `python -m pytest tests/ -q` → **6 passed**
- Syntax-checked both changed files with `py_compile.compile`.

---

## 9. Codebase review + optimization pass (2026-06-09, uncommitted)

A full-codebase review fixed these bugs (all in `desktop/src/neuroedit_desktop/`):

- **`editor_panels.py` `AudioPanel._delete_selected`** — deleting any audio track
  also deleted every *unattached* transcript segment (`audio_track_id is None`).
- **`editor_panels.py` `_cut_active_clip`** — the right piece of a Cut dropped
  `media_type` (cut image clips became unloadable "videos") and fade fields;
  fade-out now moves to the right piece.
- **Export duration ratchet** — `project_end_time` fed `project.duration` and
  `current_time + 1` back into itself, so each seek-to-end grew the timeline by
  1 s and exports gained a black/silent tail. Both it and
  `ProjectExporter._duration` now derive from content ends only.
- **`exporter.py` ffmpeg pipe deadlocks** — `_run_ffmpeg` polled without
  draining stdout/stderr (hard hang once the pipe buffer filled); render
  segments now survive ffmpeg dying mid-stream (BrokenPipeError handled).
- **Windows bugs** — `ThumbnailWorker` wrapped paths in literal quote chars
  (broke any path with spaces); `_relative_time` used `strftime("%-d")` which
  raises on Windows.
- **`models.py`** — `from_dict` draw_color default didn't match the dataclass
  default; nested dataclasses now drop unknown keys so newer saves open in
  older builds (`_from_dict_tolerant`).
- **Half-open intervals** — `MainWindow._clip_at_time`/`_slide_at_time` now use
  `start <= t < end` to match the exporter at boundary frames.
- **SAM3 setup dialog** — HF token field now uses Password echo mode.
- **Thumbnail thread teardown** — closing the Project Library mid-thumbnail
  could destroy a running QThread; stuck threads are parked until finished.
- **Weight cache path** — `SamBackend.weights_cache_dir()` respects
  HF_HOME/HF_HUB_CACHE and is shared by the cache check and the delete action.

Optimizations:

- **SAM3 propagation frame loading** (`sam_backend._load_video_window`): one
  seek + sequential `read()`/`grab()` instead of a decoder seek per frame
  (large speedup on long-GOP H.264), and frames are downscaled to ≤1920 long
  side (4K propagation no longer holds ~6 GB of frames in RAM).
- **Mask overlay cache** capped at 48 pixmaps (LRU) — long tracked-mask
  playback used to pin ~8 MB per propagated frame indefinitely.
- **Canvas drags** no longer rebuild the Labels list + timeline per mouse-move
  (`_on_annotation_mutated` is now dirty-flag only; full refresh on commit).
- **Undo history** — draw-tool settings (color/width/label/opacity) are now
  transient like tool/panel state: the width slider used to push one snapshot
  per drag tick and flush real edits out of the 50-entry history.
- **Timeline slide lanes** memoized (paints were O(slides²)).
- **Project Library** reads each `project.json` once (was twice).
- **Imported audio duration** (m4a/mp3) is now probed via bundled ffmpeg — the
  hardcoded 5.0 s guess silently truncated imported audio in the export mix.
- `neuroedit_desktop.__version__` added ("0.2.3-alpha"); About dialog uses it.

Verification: `ruff check src tests` clean; all files `py_compile` clean.
**pytest could NOT run** — see the environment warning below.

### ⚠ Dev environment broken (action required)

`~/Documents/Claude/venv` (the `desktop/.venv` symlink target) points at a
Python 3.13 framework that has been **uninstalled** from this Mac
(`/Library/Frameworks/Python.framework/Versions/3.13` no longer exists). The
app and the test suite cannot run; only system Python 3.9.6 remains. Either
reinstall Python 3.13 (revives the existing venv, including the installed
torch/SAM stack) or install Python 3.12 and recreate the venv in place
(`python3.12 -m venv ~/Documents/Claude/venv && pip install -e ".[sam]"` —
re-downloads everything). Then run the test suite to validate this session's
changes.

## 10. P1 + P2 feature implementation (2026-06-10)

Both feature tracks were implemented in isolated git worktrees and merged
to `main`. The venv (Python 3.13 revived by fresh installer) and all 27 tests
pass; ruff clean.

### P1 — Timeline editing (`editor_panels.py`, `styles.py`)

- **Selection outline**: click any clip, audio block, slide, or marker → 2px
  `#FFD60A` outline + `QColor.lighter(112)` brightness lift. Markers got a
  proper ±12px hit area. `SELECTION_OUTLINE` constant added to `styles.py`.
- **Marker edit/delete**: right-click → Edit / Delete / Delete All (confirm
  dialog); double-click opens edit dialog. All mutations emit `project_changed`.
- **Clip rename**: right-click → "Rename Clip…" via `QInputDialog.getText`.
  Intentionally not on double-click (conflicts with seek).
- **Zoom-to-fit**: "Fit" QPushButton + `Shift+Z` shortcut; second press
  restores prior zoom + scroll (Resolve toggle-back pattern).
  `fit_zoom = (viewport − LABEL_W − 24) / max(0.5, end_time)`, clamped [2, 300].
- **Snapping**: 10-screen-px threshold scales with zoom so it never fights
  frame-level nudges; snap targets are playhead, t=0, clip/audio/slide edges,
  marker times; hold Shift to bypass; magnet toggle button (default on).
  Playhead scrubbing never snaps.
- 13 new tests in `desktop/tests/test_timeline_editing.py`.

### P2 — SAM mask workflow (`main_window.py`, `sam_backend.py`, `models.py`)

- **Mask list** in SamPanel: color swatch, inline rename, visibility checkbox,
  frame-count suffix, right-click context menu.
- **Delete + orphan cleanup**: PNGs swept at app close only; sweep respects
  undo + redo stacks so nothing still reachable gets deleted.
- **Re-track**: replays stored `prompt_points`, replaces `mask_frames`/
  `mask_path`/`score`/`sample_rate` in place; explicit-only (never auto).
- **`sam_last_run`** persisted in `ProjectState`; shown as a status row in
  the SAM panel that survives project close/reopen.
- **Missing-backend explainer**: plain-English panel with Install/Download
  buttons replaces cryptic status line when SAM deps or weights are absent.
- **Track window**: "To clip end" checkbox (default on) + 1–120 s spinbox.
- **8-color mask palette** (`MASK_PALETTE`, no red) auto-assigned by index,
  burned into saved PNGs so canvas and export match.
- `Annotation.prompt_points` and `ProjectState.sam_last_run` added to
  `models.py` with defaults; `_from_dict_tolerant` ensures old saves load.
- 8 new tests in `desktop/tests/test_sam_workflow.py`.

### Version and CI

- `__version__` bumped to `"0.3.0-alpha"` in `neuroedit_desktop/__init__.py`.
- `.github/workflows/quality.yml` added: runs ruff + pytest on every push to
  `main` (Python 3.12, `QT_QPA_PLATFORM=offscreen`).
- `.github/workflows/build.yml` added: builds macOS DMG + Windows EXE on
  `v*` tag push, publishes GitHub Release.
- Follow-up CI fix: `422674f` changed mask PNG saving to use OpenCV instead
  of Pillow, because the quality workflow installs `.[dev]` and Pillow is only
  in the optional `sam` extra.

### Known deferred items (intentional — see TODO.md P2 section)

- `sam_last_run` not stamped for single-frame segmentation yet.
- Mask-list rows not disabled while a SAM job is running.
- Startup with deps-but-no-weights shows both the new explainer *and* the
  pre-existing `SamSetupDialog` — one of them should be removed.
- Marker dragging, multi-select, keyboard-delete, snap guide line deferred.

## 11. P3 + P4 feature implementation (2026-06-10, second session)

Both remaining roadmap tracks implemented and tested. Market research
(confirmation-fatigue / soft-stop literature for clinical software; caption
accessibility conventions; Premiere/Resolve caption-workflow complaints;
preset-vs-CRF export UX) drove the design choices noted inline below.

### P3 — Privacy and PHI review (`models.py`, `main_window.py`, `editor_panels.py`)

- **Guided PHI Review** (Edit menu → `PhiReviewDialog`): builds one review
  stop per clip/slide/audio track (sorted by start), seeks the playhead via
  `seek_requested`, shows a what-to-look-for hint per media kind. Marking
  every stop reviewed emits `review_completed` → sets
  `phi_review_confirmed`; any skip leaves it unconfirmed (status-bar message,
  deliberately no extra modal).
- **Pre-export checklist** (`ExportChecklistDialog`): single attestation
  dialog between the Export settings dialog and the save-location picker.
  Three required checkboxes (PHI review / de-identification / consent) gate
  Continue; pre-filled from project state so re-exports don't re-ask. The
  audio item ("audio reviewed for spoken PHI") warns amber but never blocks
  (per TODO). It **replaces** the old keep-original-audio QMessageBox.
  A "Run Guided PHI Review…" button appears when PHI review is unconfirmed
  (sets `guided_review_requested`, caller opens the stepper).
- **`audio_reviewed_for_phi`** on `ProjectState` (+ `from_dict`); checkbox in
  the Audio panel; new preflight warning; new line in the export report.
- **Reveal MP4 / Reveal Report** buttons on the export-complete box via
  `MainWindow._reveal_path` (`open -R` on macOS, `explorer /select,` on
  Windows, folder-open fallback).
- **Configurable storage root**: `default_project_root()` now reads
  `QSettings storage/projectRoot`; `recommended_project_root()` returns a
  non-cloud-synced per-OS location (`~/Library/Application Support/NeuroEdit/
  Autosave`, `%LOCALAPPDATA%`, `~/.local/share`). `StorageLocationDialog`
  runs once on first launch (`storage/promptShown`, chained before the
  tutorial prompt so modals never stack) and any time from File → Project
  Storage Location…. Changing it re-targets the store only for an untouched
  scratch project; existing autosave contents are not migrated (deferred).
- 9 tests in `tests/test_phi_review.py`.

### P4 — Captions + export polish (`captions.py` NEW, `exporter.py`, UI files)

- **`captions.py`**: `build_caption_cues` converts transcript segments into
  cues (≤42 chars/line, ≤2 lines/cue, long segments split sequentially with
  duration proportional to chunk characters, `Speaker: ` prefixes, empty
  segments skipped); `cues_to_srt` / `cues_to_vtt`; `paint_caption` is the
  ONE renderer used by both the canvas item and the exporter (white bold
  text, optional #000 @165 alpha rounded box, 5% safe-area margin,
  bottom/top center, font = fraction of frame height).
- **Canvas preview**: `AnnotationGraphicsItem._paint_captions` (gated on
  `project.captions_enabled`, cue list memoized on a segment fingerprint).
  Paints after fade, before redactions, and also on the full-frame-slide
  early-return path.
- **Burn-in export**: `ExportSettings.burn_captions`. Cue spans force
  `_segment_needs_render` True and add `_timeline_boundaries` entries so
  stream-copy can never drop captions. Painted under redactions.
- **Caption style fields** on `ProjectState`: `captions_enabled`,
  `caption_size` (small/medium/large), `caption_position` (bottom/top),
  `caption_background` — controls in the Audio panel under "Captions".
- **Sidecar export**: File → Export Captions (SRT/VTT)… +
  `AudioPanel.export_captions_requested` button. Extension follows the
  chosen filter.
- **Export history**: `record_export_history`/`load_export_history`
  (QSettings JSON, deduped by path, capped 20) recorded on every successful
  export; File → Export History… (`ExportHistoryDialog`) lists name /
  relative time / preset label / folder with Reveal File + Reveal Report;
  missing files grayed.
- **Advanced export group** (collapsed by default): CRF 12–32, fps
  24/25/30/50/60, width/height spinners, AAC bitrate 128/192/256 (new
  `ExportSettings.audio_bitrate_k`, used by `_mux_audio`). `_preset_changed`
  re-glues every advanced field to the preset.
- `ALPHA_QA_CHECKLIST.md` → per-tag template (tag/SHA/date/tester header,
  result columns) including the new caption + PHI flows.
- 11 tests in `tests/test_captions.py`.

### Quality/regression coverage (TODO "Quality" section)

- `tests/test_regressions.py`: audio-track delete keeps unattached
  transcripts; Cut preserves `media_type` and moves fade-out to the right
  piece; `ProjectExporter._duration()` ignores the ratcheted
  `project.duration`; `from_dict` drops unknown top-level and nested keys;
  ExportDialog defaults (mute source audio) yield zero audio sources.
- `tests/test_main_window_headless.py`: full `MainWindow()` construction
  (autosave root redirected to tmp via `storage/projectRoot` — tests never
  touch real storage), 5-panel switching, resize at 1085×600/1280×720/
  1920×1080 asserting `panel_scroll.horizontalScrollBar().maximum() == 0`,
  autosave round trip, `_new_project` reset, export-report PHI flag block.
- **Real bug found by the resize test**: `panel_min` ignored the vertical
  scrollbar + QScrollArea frame, so the right panel always scrolled
  sideways by ~20 px whenever the vertical scrollbar was visible. Fixed in
  `_build_central_ui` (adds `verticalScrollBar().sizeHint().width() +
  2*frameWidth()`); window minimum grows correspondingly.
- Teardown note: the window fixture waits for `_sam_probe_thread` before
  closing, else Qt aborts with "QThread: Destroyed while thread is still
  running" (this DID abort a bare script; pytest survived but don't rely
  on it).

## 13. Timeline clip deletion + preview-blanking fix (2026-06-12, v0.5.1-alpha)

Two user-reported gaps after the v0.5.0 theming pass, both in
`ui/editor_panels.py` / `ui/main_window.py`.

### Multiple ways to delete a timeline element

Previously a clip could only be removed by the keyboard shortcut (easy to
miss). Added, all routed through `TimelineCanvas._delete_selected_item` (so
they reset `active_clip_id`, recompute duration, and stay undoable):

- **Right-click → Delete** on any block: "Delete Clip" (+ Rename), "Delete
  Audio Track", "Delete Slide". Markers already had Delete / Delete All.
- **Floating round red trash button** (`TrashDropTarget`, overlaid bottom-right
  of the timeline scroll): appears only while something is selected. Click to
  delete the selection.
- **Drag-to-dump**: drag a clip/audio/slide block onto the trash and release to
  delete it; the target brightens to solid red with a white ring + red glow
  while a drag hovers it (`set_armed`). Detected via `_point_over_trash`
  (global-coord hit test) during the canvas drag; the drop is handled in
  `mouseReleaseEvent` (`_over_trash`).
- Delete/Backspace keyboard shortcut retained.
- New `TimelineCanvas.selection_changed(bool)` signal drives trash
  show/hide/reposition from `RichTimelineWidget`; all selection writes go
  through `_set_selection`.

### Preview blanks to black when the playhead has no clip

Deleting the clip under the playhead left its last decoded frame frozen in the
preview, because `_mark_project_dirty` refreshed the overlay/timeline but never
re-synced the player. Fixes:

- `_mark_project_dirty` now calls `_sync_player_to_timeline(play=...)` after
  every timeline edit, so the preview always reflects what is under the
  playhead (also handles a *different* clip ending up there after a move).
- `_sync_player_to_timeline` splits out the "no clip under playhead" case:
  pause, drop the player source, and call the new
  `VideoGraphicsView.show_black()` (hides video + image items so the black
  background shows). Full-frame slides still paint on top.
- `show_black()` is idempotent/guarded so empty-gap playback stays cheap.

### Verification

- `ruff check src tests scripts` clean; **117 tests pass** (+9 vs §12's 108):
  audio/slide delete, selection signal, trash arm, drag-drop-deletes,
  release-off-trash-keeps, trash visibility follows selection, plus two
  preview-blank regression tests (real delete path + direct no-clip sync).
- Offscreen renders confirmed: armed trash button shows on selection; preview
  is solid black after deleting the clip under the playhead.
- Version bumped to **0.5.1-alpha**.

## 12. Optimization + refinement batch from NEXT_OPTIMIZATION_PLAN.md (2026-06-11/12)

Implements every code-implementable task in [NEXT_OPTIMIZATION_PLAN.md](NEXT_OPTIMIZATION_PLAN.md)
(Phases 1–5). **All changes are deliberately uncommitted and unpushed — the
owner asked to test first.** `git add -A && git commit` once satisfied.

### Phase 1 — measurement

- **`diagnostics.py` (NEW)** — dev-only perf log: Help → "Performance
  Diagnostics (Developer)" (persisted in QSettings, or `NEUROEDIT_DIAGNOSTICS=1`),
  plus Help → "Reveal Diagnostics Log". Logs timeline/canvas paint timing
  (immediate when a paint blows the 33 ms budget, avg/max summary every 120
  paints), project-load duration+counts, export start / first-progress /
  finish, SAM job lifecycle (probe/segment/propagate/download), and panel
  switches. Writes to `~/Library/Logs/NeuroEdit` (per-OS equivalent) — never
  inside project folders; **no media paths or project names are ever logged**.
- **`scripts/make_smoothness_fixture.py` (NEW)** — builds the repeatable QA
  project: synthetic 1080p + 4K clips and a sine narration (bundled ffmpeg,
  zero patient content), a deliberately missing clip, all annotation types
  incl. a generated SAM-style mask PNG, 2 slides, 3 markers, transcript +
  captions on. `--register` adds it to Recent Projects. **Verified end-to-end**
  (generated to /tmp, reopened via ProjectStore, all content present).
- **`scripts/capture_baseline_screenshots.py` (NEW)** — offscreen capture of
  16 surfaces (window/header/timeline/5 panels/SAM-missing state/7 dialogs)
  into `desktop/qa/screenshots/<timestamp>/` (gitignored). Saves/restores the
  user's QSettings; autosaves into a temp dir. **Verified: all 16 PNGs render.**

### Phase 2 — brand system

- **`ui/styles.py`** — semantic tokens (`SURFACE*`, `ACCENT_PRIMARY`,
  `ACCENT_CLINICAL`, `ACCENT_SLIDES`, `BORDER_SUBTLE`, `FOCUS_RING`, `DANGER`,
  `WARNING`, `SUCCESS`), radius/spacing/icon scales, and new QSS
  `:pressed`/`:focus`/`:disabled`/checkbox-hover states. One-off hexes in
  `main_window.py`/`editor_panels.py` replaced with tokens (slides violet,
  library green/red/gray, inspector Delete now uses the `danger` variant).
- **Contrast fixes from the audit**: `TEXT_MUTED` `#64748b→#8093ab` (was
  3.4–3.9:1, now ≥4.5:1 on all surfaces), `TEXT_DIM` `#475569→#64748b`
  (ruler timestamps were 2.45:1), emerald-button hover label white→`#052e16`
  (white on emerald was 2.5:1).
- **`tests/test_design_tokens.py` (NEW)** — WCAG contrast audit (body ≥4.5,
  muted ≥4.5, dim ≥3.0, accent-fill labels ≥3.0, indicators ≥3.0), danger
  hue-distinct from primary, MASK_PALETTE contains no red. Known deviation
  documented: white-on-brand-blue = 3.7:1 (large-text floor; a 4.5 fix is a
  Figma-level brand decision).
- **Docs (NEW)**: [desktop/docs/DESIGN_LANGUAGE.md](desktop/docs/DESIGN_LANGUAGE.md)
  (visual grammar + surface→token map; note: **Figma Make files cannot be read
  via the Figma API/MCP** — values must be transcribed manually),
  [desktop/docs/ASSET_CHECKLIST.md](desktop/docs/ASSET_CHECKLIST.md) (identity
  assets: what exists, what's placeholder, export sizes/paths),
  [desktop/docs/VISUAL_QA_CHECKLIST.md](desktop/docs/VISUAL_QA_CHECKLIST.md)
  (17-item visual regression list keyed to the capture filenames).
- **Warm light theme pass**: `ui/styles.py` now owns light/dark theme tokens,
  `appearance/themeMode` in `QSettings`, and semantic timeline colors. Light is
  the default Figma-inspired cream/bone/earth-accent direction; dark preserves
  the previous high-contrast palette. `__main__.py` prompts first-run users to
  choose Light/Dark/System before importing `MainWindow`; View → Appearance can
  change the saved preference later. The video canvas remains dark in both
  themes.

### Phase 3 — smoothness

- **Timeline static-layer cache** (`editor_panels.TimelineCanvas`): ruler,
  lanes, blocks, markers render into a device-pixel-ratio-aware QPixmap keyed
  by a content fingerprint that deliberately excludes `current_time` — playhead
  motion during playback/scrub is now one blit + two lines instead of a full
  repaint. Cache skipped above 4M px (very long/zoomed timelines) to bound
  memory. Paint timing feeds the diagnostics budget (33 ms).
- **Snap guide line**: dashed `SELECTION_OUTLINE` vertical line at the engaged
  snap target during drags (clears on release/Shift-bypass).
- **Keyboard delete**: Delete/Backspace removes the selected timeline item
  (clip/audio/slide/marker); canvas is click-to-focus so text fields are safe.
- **Hover states**: timeline blocks/markers lift subtly under the pointer;
  QSS pressed/focus states cover buttons/tabs/list rows app-wide.
- **Marker dragging intentionally NOT added** — the plan gates it on
  paint-budget measurements from the fixture; measure first.
- **Cancellable SAM jobs**: "Cancel SAM Job" button (danger variant) appears
  in the SAM panel while busy; cooperative cancel of segment/propagate/probe
  workers (HF download has no cancel hook).
- Export button disabled during a running export.

### Phase 4 — workflow refinement

- **Project Library search/sort**: search box + sort combo (Recently opened /
  Name A–Z / Missing media first). Metadata is read from disk once per open
  (`_reload`) and re-filtered in memory; thumbnails cached in
  `_thumb_pixmaps` so re-filtering never re-runs ffmpeg.
- **SAM follow-ups**: `sam_last_run` now stamped for single-frame segmentation
  (success and error); track-window prefs persist via QSettings
  (`sam/trackToEnd`, `sam/trackWindowS`); mask list disabled while a job runs;
  **auto-shown SamSetupDialog removed** — the inline explainer's "Download
  Weights" button is the single setup entry point.
- **PHI per-stop progress**: new `ProjectState.phi_review_progress`
  ({item_id: True}); the stepper resumes at the first unreviewed stop, partial
  progress persists on pause (status-bar "N of M reviewed"), stale ids from
  deleted media are ignored. `phi_review_confirmed` remains the completion flag.
- **Storage migration**: changing the storage root with existing autosave data
  now offers to **copy (never move)** the old tree to the new root
  (`migrate_storage_root`); originals stay until the user deletes them; the
  open scratch store is re-pointed when it lived under the old root.
- **Export preset recommendation** (`recommended_preset_key`): never
  upscales — <1080p source → 720p; 4K source recommends 4K only for
  conference/standalone-publication goals; else 1080p. Dialog preselects it
  and shows a one-line "★ Recommended for this project" reason; advanced
  settings stay collapsed, privacy default unchanged.

### Verification

- `ruff check src tests scripts` clean; **109 tests pass** (was 60): +5
  timeline (keyboard delete, snap guide, static-cache reuse), +6 diagnostics,
  +17 design/theme tokens, +1 appearance action, +6 export recommendation,
  +5 project library, +2 SAM (busy state, prefs persistence), +6 PHI
  progress/migration, +1 single-frame stamp round-trip.
- Both new scripts executed successfully (see above); latest main-window
  screenshot visually inspected at
  `desktop/qa/screenshots/20260612_025650/window_1440x900.png` — warm light
  theme renders correctly offscreen.
- Version bumped to **0.5.0-alpha**.
- **Not yet verified**: behavior in the packaged builds; Windows high-DPI
  (offscreen capture can't reproduce fractional scaling — checklist item);
  real SAM runs with torch installed (workers stubbed in tests); export
  diagnostics timing on a real export.

### Gotchas for the next session

- `TimelineCanvas._static_fingerprint` must include anything the static layer
  draws (it already covers clips/audio/slides/markers/selection/hover/drag/
  goal settings) — if a new visual is added to `_paint_tracks`, add its inputs
  to the fingerprint or it will paint stale.
- `PhiReviewDialog.stops` tuples grew from 3 to 4 fields (`item_id` first) —
  anything unpacking them must use 4 fields.
- `ruff` is NOT in the venv — use the global `ruff` on PATH
  (`/Library/Frameworks/Python.framework/Versions/3.13/bin/ruff`).
- SamPanel now reads/writes QSettings in `__init__` — tests that construct it
  and change track-window state must save/restore those keys (see
  `test_track_window_prefs_persist_across_panels`).

## Current state at handoff (updated 2026-06-12)

- `main`: section 12 (optimization batch + Codex theming) released as
  `v0.5.0-alpha`; section 13 (clip-delete options + preview-blank fix) on top.
- Version: `0.5.1-alpha` in `neuroedit_desktop/__init__.py`.
- **Released 2026-06-12**: tag `v0.5.1-alpha` — §13 clip-deletion UX (right-
  click delete, floating trash button, drag-to-dump) + the preview-blanks-to-
  black fix when the playhead has no clip. Built/published via `build.yml`.
- Earlier 2026-06-12: tag `v0.5.0-alpha` — optimization batch (diagnostics,
  timeline paint cache, snap guide/keyboard delete/hover, library search/sort,
  SAM follow-ups, PHI resume + storage migration, export recommendation) plus
  the light/dark/system theming pass.
- 2026-06-11: tag `v0.4.0-alpha` (at `ffeb7f9`) —
  https://github.com/v7sm25qk5v-ui/NeuroEdit/releases/tag/v0.4.0-alpha
  with the macOS DMG/zip and Windows Setup.exe.
- Test suite: **117 passing** (`ruff` clean): §12's 109 plus the §13 delete +
  preview-blank tests.
- Remote auth: SSH remote failed (no key); remote switched to HTTPS
  (`https://github.com/v7sm25qk5v-ui/NeuroEdit.git`), PAT cached in keychain.
- Roadmap status: P0 partially owner-blocked (repo visibility, signing, DMG
  smoke test), P1–P4 shipped, P5 (Stryker/DICOM) parked pending sample data.
- **Immediate next steps:**
  1. **Verify the `v0.5.0-alpha` release built green**: watch the `build.yml`
     run on the tag (Actions tab), confirm the macOS DMG/zip + Windows Setup.exe
     attached to the release, then visually smoke-test the packaged builds
     (light + dark first-run chooser, theme switch from View → Appearance) per
     [desktop/docs/VISUAL_QA_CHECKLIST.md](desktop/docs/VISUAL_QA_CHECKLIST.md).
  2. Plan items that need the owner / hardware (not doable from this machine):
     Windows installer smoke pass at 100/125/150% scaling; Figma Make asset
     exports per [ASSET_CHECKLIST.md](desktop/docs/ASSET_CHECKLIST.md) and the
     exact frame names for the design-language map; repo-privacy and
     code-signing decisions; Intel Mac evaluation (deferred unless testers ask).
  3. After the Figma token values land in `styles.py`, re-run
     `pytest tests/test_design_tokens.py` + the screenshot capture and compare
     against the pre-brand baseline.
  4. Marker dragging: measure timeline paint with the fixture first (plan
     gates it on the paint budget), then implement if headroom allows.
- Heads-up: always `git fetch` and check HEAD before editing across sessions.

## 14. Automation TODO sweep (2026-06-14)

- Reviewed `TODO.md` plus recently updated markdown (`README.md`,
  `NEXT_OPTIMIZATION_PLAN.md`, `desktop/README.md`, and `desktop/docs/*`).
  No code-ready TODO was available: P1-P4 are shipped, P5 remains parked
  pending Stryker sample data, and remaining P0/release items require owner
  decisions or packaged-build/hardware smoke testing.
- Fetched `origin`; local `main` matched `origin/main`, and latest release tag
  `v0.5.1-alpha` is already on `HEAD`, so no release tag was needed.
- Verification rerun: `ruff check src tests scripts` passed, and
  `.venv/bin/python -m pytest tests/ -q` passed with 117 tests. Plain
  `python` is not on PATH in this shell; use the checked-in `.venv` symlink or
  `python3` after installing dev dependencies.
