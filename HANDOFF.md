# NeuroEdit — Session Handoff

Covers work completed across sessions (accumulated):

1. **Cross-platform build & distribution** (macOS + Windows from one codebase) — the main effort.
2. **Undo/redo correctness fixes** — detailed in [desktop/HANDOFF_undo_redo.md](desktop/HANDOFF_undo_redo.md); summarized here.
3. **Windows UI fixes** — native font, high-DPI scaling, two-row toolbar.
4. **Licensing** — switched MIT → proprietary.
5. **Resize-safe UI** — stop toolbar/panel clipping when the window is narrowed.
6. **SAM3 first-run download flow** — in-app model download, weight cache management.

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

## Current state at handoff

- All work committed and pushed to `main`. Commit order (condensed):
  `e4850e9` initial → `85e6498` pipeline → `505c3c2` installer fix →
  `600a55a` Windows UI fixes → `751fb97` proprietary license →
  `030bbf6` UI polish baseline → `82c6768` resize-safe UI →
  `1ce8c02` panel-content sizing → **`23e53b8` SAM3 first-run (HEAD)**.
  Local and remote are in sync.
- Tags: **`v0.2.0-alpha`** (`505c3c2`), **`v0.2.1-alpha`** (`600a55a`),
  **`v0.2.2-alpha`** (`1ce8c02`). HEAD (`23e53b8`, SAM3 first-run) is
  **not yet tagged** — cut `v0.2.3-alpha` to ship it.
- Local working tree clean except `HANDOFF.md` and `TODO.md` (both untracked).
  macOS app builds; tests pass (6).
- **Heads-up:** work is happening in more than one tool/session. Always `git fetch`
  and check HEAD before editing (that's how `030bbf6` was caught).
- **Completed since last handoff update:**
  - ✅ `v0.2.2-alpha` tagged and released (resize-safe UI).
  - ✅ Root `README.md` with download links exists.
  - ✅ Windows `Setup.exe` installed and tested by owner — toolbar, panel sizing,
    and resize behavior all confirmed good.
  - ✅ SAM3 first-run download dialog + weight-cache cleanup (`23e53b8`).
  - ✅ `TODO.md` created at repo root with full feature roadmap and a new
    **Stryker Imaging / Video Integration** section (17 items covering DICOM
    ingest/export, fluorescence multi-stream, MWL, FHIR, PACS publish targets).
- **Outstanding / next steps:**
  - Tag **`v0.2.3-alpha`** to ship the SAM3 first-run flow.
  - Verify macOS DMG end-to-end: launch, import media, play/scrub, export MP4 +
    `.export-report.txt`.
  - Verify SAM3 download on a clean machine with a valid HF token.
  - Owner to make the repo **private** if keeping control.
  - Commit `HANDOFF.md` and `TODO.md` if you want them in version history.
