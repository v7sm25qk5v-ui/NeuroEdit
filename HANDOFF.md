# NeuroEdit — Session Handoff

## 2026-09-01 — Inactive-audio privacy-preflight fix

- Reviewed `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`, `HANDOFF.md`, `README.md`,
  `desktop/README.md`, `desktop/CLAUDE.md`, and recently updated project
  markdown. Remaining release, platform, Intel Mac, signing, and Stryker work is
  still owner, hardware, or sample-data gated; no release tag is indicated.
- Used the fallback review path and fixed one remaining inactive-audio
  mismatch: general consent, de-identification, and PHI-review warnings no
  longer treat muted or zero-duration audio-only placeholders as reviewable
  export media.
- Export preflight warning logic now uses the same active-audio criteria as
  export muxing for audio-only reviewability: positive duration and positive
  volume. Visual media and active narration still keep the required privacy
  prompts.
- Verification: focused `tests/test_phi_review.py` (`19 passed`), full `ruff
  check src tests scripts`, full suite (`170 passed`), and `git diff --check`.

## 2026-09-01 — Audio-panel zero-duration preservation fix

- Reviewed `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`, `HANDOFF.md`, `README.md`,
  `desktop/README.md`, `desktop/CLAUDE.md`, and recently updated project
  markdown. Remaining release, platform, Intel Mac, signing, and Stryker work is
  still owner, hardware, or sample-data gated; no release tag is indicated.
- Used the fallback review path and fixed an Audio-panel metadata mismatch:
  selecting a legacy zero-duration narration placeholder no longer displays or
  writes it back as `0.1 s`.
- Renaming or editing metadata on an empty narration placeholder now preserves
  its inactive `0.0 s` duration, so the recent inactive-audio timeline, PHI, and
  export-audio fixes are not undone by the track inspector.
- Verification: focused `tests/test_regressions.py` (`17 passed`), focused
  `ruff` on touched code/tests, full `ruff check src tests scripts`, full suite
  (`169 passed`), and `git diff --check`.

## 2026-08-27 — Inactive-audio PHI/export prompt fix

- Reviewed `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`, `HANDOFF.md`,
  `desktop/CLAUDE.md`, and recently updated project markdown. Remaining release,
  platform, Intel Mac, signing, and Stryker work is still owner, hardware, or
  sample-data gated; no release tag is indicated.
- Used the fallback review path and fixed the remaining inactive-audio UI
  mismatch: export preflight and the pre-export checklist no longer treat muted
  or zero-duration narration placeholders as exported audio.
- Spoken-PHI audio warnings, educational narration guidance, and export
  checklist visibility now share the exporter's active-audio rule: positive
  duration and positive volume. Active narration still prompts for spoken-PHI
  review.
- Verification: focused `tests/test_phi_review.py` (`18 passed`), focused
  `ruff` on touched code/tests, full `ruff check src tests scripts`, full suite
  (`168 passed`), and `git diff --check`.

## 2026-08-26 — Zero-duration audio timeline-duration fix

- Reviewed `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`, `HANDOFF.md`,
  `desktop/CLAUDE.md`, and recently updated project markdown. Remaining release,
  platform, and Stryker work is still owner, hardware, or sample-data gated; no
  release tag is indicated.
- Used the fallback review path and fixed a preview/playback duration mismatch:
  `project_end_time()` no longer assigns zero-duration audio placeholders a
  synthetic 0.1 s span.
- Legacy empty narration tracks no longer add a silent tail to the live project
  duration after export duration has already learned to ignore them.
  Positive-duration muted tracks still remain visible on the timeline for
  editing.
- Verification: focused `tests/test_timeline_editing.py` (`25 passed`), full
  `ruff check src tests scripts`, full suite (`166 passed`), and `git diff
  --check`.

## 2026-08-25 — Inactive-audio export warning fix

- Reviewed `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`, `HANDOFF.md`, `README.md`,
  `desktop/README.md`, `desktop/CLAUDE.md`, and recently updated project
  markdown. Remaining release, platform, and Stryker work is still owner,
  hardware, or sample-data gated; no release tag is indicated.
- Used the fallback review path and fixed the final inactive-audio mismatch:
  muted or zero-duration narration placeholders no longer trigger the
  "No readable audio streams were found" completion warning after a visual
  export.
- Active audio tracks with no readable stream still warn, preserving the
  user-facing signal for narration that should have contributed sound.
- Verification: focused `tests/test_regressions.py` (`16 passed`), focused
  `ruff` on touched code/tests, full `ruff check src tests scripts`, full suite
  (`165 passed`), and `git diff --check`.

## 2026-08-24 — Zero-duration slide preview/playback fix

- Reviewed `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`, `HANDOFF.md`, `README.md`,
  `desktop/README.md`, `desktop/CLAUDE.md`, and recently updated project
  markdown. Remaining release, platform, and Stryker work is still owner,
  hardware, or sample-data gated; no release tag is indicated.
- Used the fallback review path and fixed a preview/export mismatch:
  legacy/corrupt zero-duration slides now use the same 0.1 s effective span in
  canvas preview state, `MainWindow` playback sync, timeline duration, and
  export.
- This prevents a zero-duration slide from appearing in the exported MP4 while
  being invisible to live preview/playback decisions.
- Verification: focused `tests/test_undo_history.py` (`22 passed`), full `ruff
  check src tests scripts`, full suite (`163 passed`), and `git diff --check`.

## 2026-08-23 — Inactive-audio export duration fix

- Reviewed `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`, `HANDOFF.md`, `README.md`,
  `desktop/README.md`, `desktop/CLAUDE.md`, and recently updated project
  markdown. Remaining release, platform, and Stryker work is still owner,
  hardware, or sample-data gated; no release tag is indicated.
- Used the fallback review path and fixed the duration side of the inactive-audio
  mismatch: muted or zero-duration narration placeholders no longer extend the
  exported MP4 with a silent black tail.
- Export source-media preflight, export duration, and audio muxing now share the
  same active-audio criteria: positive duration and positive volume.
- Verification: focused `tests/test_regressions.py` (`14 passed`), focused
  `ruff` on touched code/tests, full `ruff check src tests scripts`, full suite
  (`162 passed`), and `git diff --check`.

## 2026-08-22 — Inactive-audio export preflight fix

- Reviewed `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`, `HANDOFF.md`, `README.md`,
  `desktop/CLAUDE.md`, and recently updated project markdown. Remaining release,
  platform, and Stryker work is still owner, hardware, or sample-data gated; no
  release tag is indicated.
- Used the fallback review path and fixed an export-preflight mismatch: muted
  or zero-duration audio tracks no longer count as required source media because
  they cannot contribute to the muxed export.
- Active missing narration still fails early before encoding, preserving the
  source-media safety guard added for audio tracks.
- Verification: focused `tests/test_regressions.py` (`13 passed`) and focused
  `ruff` on touched code/tests.

## 2026-08-21 — Zero-duration slide export fix

- Reviewed `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`, `HANDOFF.md`, `README.md`,
  `desktop/CLAUDE.md`, and recently updated project markdown. Remaining release,
  platform, and Stryker work is still owner, hardware, or sample-data gated; no
  release tag is indicated.
- Used the fallback review path and fixed an export-duration mismatch: the
  exporter now applies the same minimum slide-duration floor to content
  duration, segment boundaries, and slide lookup.
- Legacy/corrupt zero-duration slides now render during their minimum export
  span instead of extending the MP4 with black frames.
- Verification: focused `tests/test_regressions.py` (`12 passed`) and focused
  `ruff` on touched code/tests.

## 2026-08-20 — PHI readiness warning coverage fix

- Reviewed `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`, `HANDOFF.md`, `README.md`,
  `desktop/README.md`, `desktop/CLAUDE.md`, and recently updated project
  markdown. Remaining release/platform/Stryker work is still owner,
  hardware, or sample-data gated; no release tag is indicated.
- Used the fallback review path and fixed a privacy-readiness inconsistency in
  `project_preflight_warnings`: consent, de-identification, and PHI review
  warnings now apply when a project has any reviewable media surface, including
  clips, slides/stills, or audio.
- Slide/still-only exports now also receive the no-redaction-box reminder that
  clip-based visual exports already received, matching the guided PHI review and
  export checklist behavior.
- Verification: focused `tests/test_phi_review.py` (`16 passed`), focused
  `ruff` on touched code and tests, full `ruff check src tests scripts`, full
  desktop test suite, and `git diff --check`.

## 2026-08-19 — Export source-media preflight fix

- Reviewed `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`, `HANDOFF.md`, `README.md`,
  `desktop/README.md`, `desktop/CLAUDE.md`, and recently updated project
  markdown. Remaining release/platform/Stryker work is still owner,
  hardware, or sample-data gated; no release tag is indicated.
- Used the fallback review path and fixed an export-safety gap in
  `exporter.py`: export preflight now treats timeline clips, narration audio
  tracks, and slide image/still assets as source media for both missing-file
  rejection and source-overwrite rejection.
- Added focused regressions proving export rejects missing audio sources,
  missing slide image sources, and output paths that would overwrite non-clip
  source media.
- Verification: baseline full desktop test suite (`155 passed`), focused
  `tests/test_regressions.py` (`11 passed`), focused `ruff` on touched code and
  tests, full `ruff check src tests scripts`, full desktop test suite, and
  `git diff --check`.

## 2026-08-17 — Phase 6 roadmap status sync

- Reviewed `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`, `HANDOFF.md`, `README.md`,
  `desktop/README.md`, `desktop/CLAUDE.md`, and recently updated project
  markdown. Remaining release/platform work is still owner/hardware/sample-data
  gated; no release tag is indicated.
- Ran a fallback code-health review around the recently extracted history paths
  and current `ui/` module sizes. No owner-independent code task was safer than
  documentation synchronization in this run.
- Synchronized `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`, and `desktop/CLAUDE.md`
  so the Phase 6 `main_window.py` module-size target is closed: current
  `main_window.py` is ~2,384 lines and no `ui/` module is over ~2,500 lines.
- Verification: line-count review, focused `tests/test_undo_history.py`, full
  `ruff check src tests scripts`, full desktop test suite, and `git diff --check`.

## 2026-08-16 — Undo/autosave history mixin extraction

- Reviewed `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`, `HANDOFF.md`, `README.md`,
  `desktop/CLAUDE.md`, and recently updated project markdown. Remaining release
  gates are still owner/hardware/sample-data gated; no release tag is indicated.
- Moved `MainWindow`'s undo/redo, dirty-state marking, compact snapshot
  serialization, history stack maintenance, snapshot restore, and autosave
  controller methods to `ui/history.py` as `HistoryMixin`.
- Preserved behavior and compatibility by keeping project actions, review
  invalidation, media sync, and UI refresh ownership in `main_window.py`; the
  extraction reduces `ui/main_window.py` to ~2,384 lines.
- Verification: focused `tests/test_undo_history.py` (`21 passed`), focused
  `ruff` on touched files, full `ruff check src tests scripts`, full desktop
  test suite (`155 passed`), and `git diff --check`.

## 2026-08-14 — SAM roadmap preference-status sync

- Reviewed `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`, `HANDOFF.md`, `README.md`,
  `desktop/README.md`, `desktop/CLAUDE.md`, and recently updated project
  markdown. Remaining release and platform work is still owner/hardware/sample
  data gated; no release tag is indicated.
- Verified the stale P2/Phase 4 note about SAM track-window preference
  persistence against the live implementation in `ui/sam_panel.py` and the
  regression `tests/test_sam_workflow.py::test_track_window_prefs_persist_across_panels`.
- Synchronized `TODO.md` and `NEXT_OPTIMIZATION_PLAN.md` so the active roadmap
  now treats track-window preference persistence as complete instead of a
  remaining deferred follow-up.
- Verification: focused SAM workflow preference test, full `ruff check src tests
  scripts`, full desktop test suite, and `git diff --check`.

## 2026-08-13 — Project-library trimmed-duration metadata fix

- Reviewed `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`, `HANDOFF.md`, `README.md`,
  `desktop/CLAUDE.md`, and recently updated desktop markdown. The remaining
  roadmap work is still owner/hardware/sample-data gated or explicitly deferred
  without a safe implementation signal, so this run used the fallback review
  path.
- Fixed a Project Library metadata bug in `ui/project_library.py`: recent-case
  rows now report the timeline content end across clips, audio, and slides
  instead of summing raw source durations, and thumbnail generation seeks within
  the first clip's trimmed source range.
- Added a focused regression in `tests/test_project_library.py` for a trimmed
  clip whose source duration is much longer than its displayed range.
- Verification: focused `tests/test_project_library.py` (`7 passed`); focused
  `ruff` on touched files; full `ruff check src tests scripts`; full suite
  (`155 passed`); `git diff --check`. No release tag is indicated for this
  internal metadata correctness fix.

## 2026-08-10 — Roadmap follow-up documentation sync

- Reviewed `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`, `HANDOFF.md`, `README.md`,
  `desktop/CLAUDE.md`, and recently updated desktop markdown against the current
  code/tests. No release tag is indicated; remaining release gates are still
  owner/hardware/sample-data gated.
- Synchronized the roadmap with already-implemented follow-ups: Project Library
  search/sort, single-frame SAM `sam_last_run`, SAM busy-state list disabling,
  the inline SAM setup prompt, persisted PHI per-stop progress, and copy-only
  storage-root migration.
- Left genuinely open items open: packaged macOS/Windows runtime smoke, owner
  repository/signing decisions, Intel Mac evaluation if testers need it,
  track-window UI preference persistence, and Stryker/DICOM work pending sample
  data.
- Verification: documentation diff review, `git diff --check`, focused
  SAM/PHI/project-library tests, full `ruff check src tests scripts`, and the
  full desktop test suite. No release tag is indicated for this docs sync.

## 2026-08-09 — Project-library stale thumbnail refresh fix

- Reviewed `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`, `HANDOFF.md`, `README.md`,
  and recent desktop markdown. The live roadmap still leaves feature work
  owner/hardware/sample-data gated or explicitly deferred without a safe
  equality signal.
- Fixed a fallback review finding in `ui/project_library.py`: stale cached
  `.neuroedit-thumbnail.jpg` files are now removed before thumbnail regeneration
  and are only emitted when ffmpeg succeeds, preventing old derived previews from
  reappearing after project/media changes if refresh fails.
- Added a focused regression in `tests/test_project_library.py` that simulates a
  failed ffmpeg refresh and proves the stale thumbnail is not emitted or kept.
- Verification: focused `ruff` plus `tests/test_project_library.py` (`6
  passed`); full `ruff check src tests scripts`; full suite (`154 passed`).
  No release tag is indicated for this internal correctness fix.

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
- Test suite: **119 passing** (`ruff` clean): §12's 109, the §13 delete +
  preview-blank tests, §15's smoothness-fixture test, and §17's undo hash test.
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

## 15. Automation TODO sweep (2026-06-14)

- Re-reviewed the same roadmap/docs. Remaining owner/hardware items are still
  blocked (repo privacy, signing/notarization, packaged Windows/macOS smoke),
  and P5 remains parked pending Stryker sample data.
- Tightened the smoothness fixture generator from §12: `scripts/make_smoothness_fixture.py`
  now creates the mask output folder before writing and raises if OpenCV cannot
  write the synthetic SAM-style mask PNG.
- Added `tests/test_smoothness_fixture.py` so the fixture generator is covered
  without encoding real videos; it stubs ffmpeg media creation, opens the saved
  project via `ProjectStore`, checks the 1080p/4K/missing-media cases, and
  verifies the mask path exists.
- Documented the manual smoothness-fixture QA loop in `desktop/README.md`.
- Verification: `ruff check src tests scripts` passed and
  `python -m pytest tests/ -q` passed with **118 tests**.

## 16. Automation optimization sweep (2026-06-14, docs only)

Scheduled daily-optimization run. No code changed — planning markdown only.

- **Reviewed the source for fresh, code-grounded optimization targets** (not
  already shipped in §12's Phases 1–5). Findings: `ui/main_window.py` is ~6,500
  lines and bundles `MainWindow`, `VideoGraphicsView`, `AnnotationGraphicsItem`,
  the three SAM worker QObjects, the Project Library dialog, and most dialogs;
  undo/redo stores full `ProjectState.to_dict()` snapshots (cap 50) deduped by
  full-dict `==` on every push; the iCloud conflict copies (`* 2.py`) are still
  physically present under `src/`. The mask-overlay LRU cache and timeline
  static-layer cache from earlier sessions are already in place, so the canvas
  paint path is not a fresh target.
- **Added Phase 6 — Code health and runtime cost** to
  [NEXT_OPTIMIZATION_PLAN.md](NEXT_OPTIMIZATION_PLAN.md): modularize
  `main_window.py`, reduce undo-snapshot cost, audit cold-start imports, and
  drop the conflict copies. Every item is measurement-first and
  behavior-preserving. Mirrored as a new **P4.5** section in
  [TODO.md](TODO.md).
- **Markdown consistency pass.** Corrected the handoff's current-state test
  count (117 → **118**, matching §15 and `pytest --collect-only`); normalized
  the lint command in the TODO Quality gate and the plan's release gate to
  `ruff check src tests scripts` (the form already used in `desktop/README.md`
  and §12+). Historical per-session entries left as written.
- Did **not** run the suite this sweep (docs-only change); `pytest
  --collect-only` reports **118 tests** collected. The plan-listed work remains
  unimplemented by design — this run only updated the markdown.

## 17. Automation TODO implementation sweep (2026-06-14)

Implemented the first low-risk Phase 6 code-health items from `TODO.md` /
`NEXT_OPTIMIZATION_PLAN.md`:

- **Project Library extraction:** moved `ProjectLibraryDialog`,
  `ThumbnailWorker`, metadata reads, thumbnail placeholder creation, and the
  shared relative-time formatter into
  `desktop/src/neuroedit_desktop/ui/project_library.py`. `main_window.py`
  imports/re-exports `ProjectLibraryDialog`, so existing tests and callers that
  import from `neuroedit_desktop.ui.main_window` remain stable. This is a
  mechanical move only; behavior and UI strings are preserved.
- **Undo dedup cost:** undo/redo history still stores the same snapshot dicts,
  but now tracks parallel BLAKE2 snapshot hashes so `_push_history()` can skip
  net-zero history entries without comparing full nested project dictionaries.
  Existing undo semantics and mask-cleanup snapshot scanning are unchanged.
- **Housekeeping:** removed the four iCloud conflict copies under `desktop/src`
  (`__init__ 2.py`, `__main__ 2.py`, `video_probe 2.py`,
  `ui/__init__ 2.py`).
- **Roadmap status:** `TODO.md` now marks only the conflict-copy cleanup as
  complete; the larger `main_window.py` modularization and undo memory cap /
  measurement work remain open.
- Verification: `ruff check src tests scripts` passed and
  `python -m pytest tests/ -q` passed with **119 tests**.

## 18. Automation optimization sweep (2026-06-15, docs only)

Scheduled daily-optimization run. No code changed — planning markdown only.

- **Re-measured the Phase 6 targets against the current tree** (`wc -l`,
  `pytest --collect-only`). Findings: `ui/main_window.py` is now **6,114 lines**
  (down from the ~6,500 recorded before the Project Library extraction);
  `ui/editor_panels.py` is **2,963 lines** and is *also* over the plan's
  ~2,500-line `ui/` ceiling, with `AudioPanel` (~970 lines) its largest
  extractable class; the suite collects **119 tests**; the iCloud `* 2.py`
  conflict copies are confirmed gone.
- **Code-grounded refinement of the undo item.** `_push_history` still calls
  `_snapshot()` (full `ProjectState.to_dict()` + `json.dumps`) on every dirty
  tick *before* the BLAKE2 hash decides whether to discard a net-zero edit — so
  a no-op edit still pays an O(project size) serialize. Recorded a pre-serialize
  short-circuit as the next concrete sub-task alongside the still-open
  compact-storage and cumulative-size-cap work.
- **Markdown updates** (planning files only): corrected the stale `~6,500`
  main_window figure to `~6,100` in [TODO.md](TODO.md) P4.5 and
  [NEXT_OPTIMIZATION_PLAN.md](NEXT_OPTIMIZATION_PLAN.md) Phase 6; added
  `editor_panels.py` / `AudioPanel` as an explicit second modularization target
  in both; marked the conflict-copy housekeeping done in the plan (it was
  already `[x]` in the TODO); sharpened the undo-cost item with the
  pre-serialize finding. This §16-style historical entry and earlier
  per-session entries are left as written.
- Did **not** run the suite this sweep (docs-only change); `pytest
  --collect-only` reports **119 tests** collected. The plan-listed work remains
  unimplemented by design — this run only updated the markdown.

## 19. Automation TODO implementation sweep (2026-06-15)

Implemented the `ui/editor_panels.py` modularization item from `TODO.md` /
`NEXT_OPTIMIZATION_PLAN.md`:

- **Audio panel extraction:** moved `AudioPanel` into
  `desktop/src/neuroedit_desktop/ui/audio_panel.py` and kept
  `neuroedit_desktop.ui.editor_panels.AudioPanel` available as a re-export for
  existing imports.
- **Shared timeline helpers:** moved `fmt_time` and `project_end_time` into
  `desktop/src/neuroedit_desktop/ui/timeline_utils.py`, then imported them from
  both `editor_panels.py` and `audio_panel.py` to avoid circular imports.
- **Roadmap status:** `TODO.md` now marks the `editor_panels.py` / `AudioPanel`
  modularization item complete. `main_window.py` modularization remains open.
  Current line counts: `editor_panels.py` **2,245**, `audio_panel.py` **727**,
  `timeline_utils.py` **22**.
- Verification: `ruff check src tests scripts` passed and
  `python -m pytest tests/ -q` passed with **119 tests**.

## 20. Automation TODO implementation sweep (2026-06-16)

Implemented the next `ui/main_window.py` modularization slice from `TODO.md` /
`NEXT_OPTIMIZATION_PLAN.md`:

- **Canvas extraction:** moved `AnnotationGraphicsItem`, `VideoGraphicsView`,
  and the canvas-only distance helper into
  `desktop/src/neuroedit_desktop/ui/canvas.py`. `main_window.py` imports and
  re-exports the classes so existing import paths stay stable.
- **SAM worker extraction:** moved `SamProbeWorker`, `SamSegmentWorker`,
  `SamPropagationWorker`, and `SamDownloadWorker` into
  `desktop/src/neuroedit_desktop/ui/sam_workers.py`; `main_window.py` keeps
  re-exporting them.
- **Roadmap status:** `main_window.py` is now ~4,764 lines, with `canvas.py`
  ~1,238 lines and `sam_workers.py` ~146 lines. Remaining Phase 6
  modularization work is the dialog/MainWindow split; undo snapshot cost and
  cold-start import audit remain open.
- Verification: `ruff check src tests scripts` passed and
  `.venv/bin/python -m pytest tests/ -q` passed with **119 tests**.

## 21. Automation optimization sweep (2026-06-17, docs only)

Scheduled daily-optimization run — first run with the **Optimization Automation
Memory** section live in `desktop/CLAUDE.md` (marker was empty → treated as a
full sweep). No code changed; planning/memory markdown only.

- **Reviewed range:** through `22085f9` (canvas + SAM-worker extraction, §20).
  Confirmed against the tree: `main_window.py` **4,764** lines, `canvas.py`
  1,238, `sam_workers.py` 146, `audio_panel.py` 726, `editor_panels.py` 2,244;
  suite collects **119 tests**.
- **Fresh finding → TODO Optimization Backlog:** `_tick_timeline_playback`
  (`ui/main_window.py:3953`) recomputes `project_end_time()` (four list
  comprehensions over clips+audio+slides+markers, `ui/timeline_utils.py:13`) and
  unconditionally calls `timeline.refresh()` + `video_view.update_annotations()`
  on every 33 ms playback tick. Low-priority steady CPU that scales with timeline
  length; mitigation = cache `project_end_time` (invalidate on edit) and skip the
  refresh when the visible frame is unchanged. The major code-health work
  (dialog/MainWindow split, undo triple-serialize, cold-start import audit)
  stays tracked in **P4.5** and was not duplicated.
- **Memory:** set "Last reviewed" to `22085f9` (2026-06-17); recorded
  out-of-scope paths, two false positives (per-paint Qt allocations in
  `canvas.py`; linear `_clip_at_time` scans), and high-signal architecture
  bullets so the next run can go incremental.
- **Markdown consistency:** fixed the stale "~6,100 lines" current-state figure
  for `main_window.py` (now 4,764) in `TODO.md` P4.5 and
  `NEXT_OPTIMIZATION_PLAN.md` §1 header, and rewrote the modularize item's lead
  so it no longer lists the already-extracted canvas/SAM pieces as open work.
  Historical per-session entries (incl. 117/118 test counts) left as written.
- Did **not** run the suite (docs-only); `pytest --collect-only` = 119.

## 22. Automation TODO implementation sweep (2026-06-17)

Implemented the next low-risk `ui/main_window.py` modularization slice from
`TODO.md` / `NEXT_OPTIMIZATION_PLAN.md`:

- **Dialog extraction:** moved `SamSetupDialog`, `StorageLocationDialog`,
  `PhiReviewDialog`, `ExportChecklistDialog`, `ExportDialog`, and
  `ExportHistoryDialog` into
  `desktop/src/neuroedit_desktop/ui/dialogs.py`.
- **Shared dialog helpers:** moved `legacy_project_root`,
  `recommended_project_root`, `default_project_root`, `migrate_storage_root`,
  export-history helpers, and `recommended_preset_key` with the dialogs.
  `main_window.py` imports and re-exports the public names so existing tests and
  callers that import from `neuroedit_desktop.ui.main_window` remain stable.
- **Roadmap status:** `main_window.py` is now ~4,020 lines and `dialogs.py` is
  ~798 lines. Remaining Phase 6 modularization work is the still-large
  `MainWindow` class; undo snapshot cost, cold-start import audit, and the
  lower-priority playback-loop optimization remain open.
- **Verification:** `ruff check src tests scripts` passed; focused
  export/PHI/regression tests passed with 37 tests; full suite passed with
  **119 tests** via `.venv/bin/python -m pytest tests/ -q`.

## 23. Automation optimization sweep (2026-06-18, docs only)

Scheduled daily-optimization run — first **incremental** run (prior marker
`22085f9` set a full-sweep baseline). No code changed; markdown only.

- **Reviewed range:** `22085f9..873b74d` — a single commit, the dialog
  extraction (§22). The diff is a pure mechanical move: 799 lines of dialog
  classes/helpers added to `ui/dialogs.py`, the same removed from
  `ui/main_window.py`, and a 13-name import/re-export block added back. No new
  logic, so **no new optimization findings**. That code was already in scope
  during the `22085f9` full sweep, so it needed no re-review beyond confirming
  the move.
- **Backlog:** the one open finding (`_tick_timeline_playback` recomputes
  `project_end_time()` + double-repaints per 33 ms tick) is unchanged and stays
  in TODO. Its line reference `ui/main_window.py:3208` is now correct again —
  the extraction shifted the method back up from §21's `:3953`. Major
  code-health work stays in **P4.5** (dialog/MainWindow split, undo
  triple-serialize, cold-start import audit).
- **Line counts confirmed:** `main_window.py` 4,019, `dialogs.py` 799 — matches
  the `~4,020` / `~798` figures already in `TODO.md` and
  `NEXT_OPTIMIZATION_PLAN.md`; no markdown drift to fix.
- **Memory:** set "Last reviewed" to `873b74d` (2026-06-18), switched mode to
  incremental, and recorded `ui/dialogs.py` as a "skip — verbatim move" entry so
  the next run doesn't re-review it unless its logic changes.
- Did **not** run the suite (docs-only); no `.py` files touched.

## 24. Automation TODO implementation sweep (2026-06-18)

Implemented the next low-risk Phase 6 undo-cost slice from `TODO.md` /
`NEXT_OPTIMIZATION_PLAN.md`:

- **Autosave snapshot reuse:** `_push_history()` now builds the full
  `ProjectState.to_dict()` once, derives the transient-stripped undo snapshot
  from that dict, and caches the full dict for the next autosave. If a later
  UI-only or direct dirty path changes project state without a history snapshot,
  the cache is invalidated so autosave falls back to the live project.
- **ProjectStore save helper:** added `ProjectStore.save_data()` so autosave can
  persist a known-current project dict without calling `to_dict()` again. The
  on-disk JSON format is unchanged.
- **Coverage:** added undo-history tests proving autosave reuses the cached
  snapshot after a history push and invalidates it after a UI-only dirty change.
- **Roadmap status:** `TODO.md` and `NEXT_OPTIMIZATION_PLAN.md` now record this
  sub-slice as complete. The pre-serialize short-circuit, compact history
  storage, cumulative-size cap, smoothness-fixture timing/memory measurement,
  `MainWindow` class split, cold-start import audit, and playback-loop
  optimization remain open.
- Verification: `ruff check src tests scripts` passed; focused
  `tests/test_undo_history.py` passed with 6 tests; full suite passed with
  **121 tests** via `.venv/bin/python -m pytest tests/ -q`.

## 25. Automation optimization sweep (2026-06-19, docs only)

Scheduled daily-optimization run — incremental. No code changed; markdown only.

- **Reviewed range:** `873b74d..HEAD` (`6700b67`) — a single commit, the
  autosave snapshot reuse implemented in §24. Deep-dived `main_window.py`,
  `project_store.py`, `test_undo_history.py`, plus the one-hop callers of the
  changed undo/autosave paths.
- **Correctness audit (the one real risk in this change):** verified every path
  that sets `self.dirty = True` also refreshes or nulls `_autosave_snapshot`, so
  autosave can never persist a snapshot older than the latest edit. All five
  `dirty = True` sites are in `main_window.py` and each is handled; no other
  module sets `dirty` directly (panels route through `_mark_dirty`). The
  shallow-copy undo snapshot aliases nested dicts with the cached autosave dict,
  but neither is mutated in place — safe. **No new finding.**
- **Backlog:** no new items. The one open automation finding
  (`_tick_timeline_playback` recomputes `project_end_time()` + double-repaints
  per tick) is unchanged; its line reference drifted `:3208 → :3224` from this
  commit and was corrected in `TODO.md`. Major code-health work stays in
  **P4.5** (`MainWindow` split, remaining undo serialize cost, cold-start audit).
- **Memory:** set "Last reviewed" to `6700b67` (2026-06-19); refined the
  undo/redo architecture note to reflect that autosave now reuses the cached
  `to_dict()` via `ProjectStore.save_data()`; recorded the autosave-reuse audit
  as a "no re-audit unless a new dirty write path is added" entry.
- Did **not** run the suite (docs-only); no `.py` files touched.

## 26. Automation TODO implementation sweep (2026-06-19)

Implemented the smallest actionable Phase 6 runtime-cost item from `TODO.md` /
`NEXT_OPTIMIZATION_PLAN.md`: remove the playback loop's repeated
`project_end_time()` scan.

- **Project end-time cache:** `MainWindow` now keeps a private
  `_project_end_time_cache` and routes seek/playback/export duration reads through
  `_project_end_time()`. The helper still writes `project.duration`, preserving
  the existing behavior of callers that expect that field to stay current.
- **Invalidation:** document edits via `_mark_dirty()` / `_mark_project_dirty()`,
  new/open project flows, undo/redo snapshot restores, and still insertion clear
  the cache before the next read. UI-only invalidation is intentionally harmless
  and keeps the rule simple.
- **Coverage:** `tests/test_undo_history.py` gained focused headless tests for
  cache reuse, dirty invalidation, and playback ticks reusing the cached end
  time. The focused undo/playback test file now has 8 tests.
- **Roadmap status:** `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`, and
  `desktop/CLAUDE.md` now mark the `project_end_time()` playback scan as done.
  Remaining Phase 6 work: mechanical `MainWindow` class split, remaining
  undo-history memory/serialize reductions, cold-start import audit, and the
  playback-loop repaint-throttling follow-up.
- Verification: `ruff check src tests scripts` passed; focused
  `tests/test_undo_history.py` passed with 8 tests; full suite passed with
  **123 tests** via `.venv/bin/python -m pytest tests/ -q`.

## 27. Undo/redo project-end-time cache fix (2026-06-20)

Implemented the correctness finding from the incremental optimization review.

- **Reviewed range:** `6700b67..HEAD` (`cbe6679`) — one commit, the playback
  project-end-time cache (implemented in §26). Deep-dived `main_window.py` (the
  cache + all invalidation/read sites), `ui/timeline_utils.py` (`project_end_time`),
  the undo/redo path (`undo`/`redo`/`_apply_snapshot`), and `test_undo_history.py`.
- **Fix:** `_apply_snapshot()` now clears `_project_end_time_cache` immediately
  after replacing `self.project`, matching the invalidation already performed
  for normal document edits and project load/new flows.
- **Coverage:** `test_apply_snapshot_invalidates_project_end_time_cache` first
  caches a shortened project duration, restores a longer snapshot, and proves
  the next duration read recomputes to the restored value. The focused
  undo/playback file now has 9 tests; the full suite has **124 tests**.
- **Roadmap:** marked the cache correctness item complete in `TODO.md`. Next
  Phase 6 work remains the `MainWindow` class split, remaining undo history
  cost reductions, cold-start import audit, and playback repaint throttling.
- **Verification:** `ruff check src tests scripts` passed; focused
  `tests/test_undo_history.py` passed with 9 tests; full suite passed with
  **124 tests** via `.venv/bin/python -m pytest tests/ -q`.

## 28. Optimization automation sweep (2026-06-21, docs-only)

Incremental optimization scan ran over `cbe6679..35447b8` (one commit:
`35447b8`, the `_apply_snapshot` project-end-time cache invalidation — the fix
the prior sweep recommended). No code changed in this run.

- **Verified the fix:** `_apply_snapshot` clears `_project_end_time_cache` after
  the project swap; the focused regression test is present and the item is
  checked off in `TODO.md`.
- **One-hop audit** of every `_project_end_time_cache` read/write/invalidation
  site (`ui/main_window.py`) found one low-priority consistency gap:
  `_open_recent_project` (`:2484`) does not call `_invalidate_project_end_time()`
  immediately after swapping `self.project`, unlike `_open_project` (`:2383`),
  `_new_project` (`:2364`), and `_apply_snapshot` (`:2110`). Currently masked by
  the trailing `_mark_dirty()` (nothing in between reads the cache) — recorded as
  a new unchecked item in the `TODO.md` Optimization Backlog, not a live bug.
- **Markdown consistency:** fixed a stale `123-test` → `124-test` reference in
  `NEXT_OPTIMIZATION_PLAN.md:197` (present-tense gate). Left the historical
  `123 tests` in HANDOFF §26 as written (per-run record).
- **Memory:** advanced the "Last reviewed" marker to `35447b8` (2026-06-21) and
  noted the intentional trailing-`_mark_dirty()` pattern in `desktop/CLAUDE.md`.

## 29. Recent-project duration cache defense (2026-06-21)

Completed the low-priority cache-consistency item added by the optimization
sweep.

- **Implementation:** `_open_recent_project()` now calls
  `_invalidate_project_end_time()` immediately after `ProjectStore.open()`
  replaces the project, matching the dialog-open and new-project paths.
- **Regression coverage:** added a focused test proving invalidation occurs
  before loaded-project validation, so a future helper inserted before the
  trailing `_mark_dirty()` cannot observe the previous project's duration.
- **Verification:** `ruff check src tests scripts` passed; focused
  `tests/test_undo_history.py` passed with 10 tests; full suite passed with
  **125 tests** via `.venv/bin/python -m pytest tests/ -q`.
- **Next optimization task:** reduce playback repaint work by skipping timeline
  and annotation refreshes when the visible frame has not changed, or continue
  the measurement-first undo snapshot/cold-start work in Phase 6.

## 30. Playback loop-at-still bug fix (2026-06-21)

Fixed a bug where, after a video clip played, playback looped back to the start
of that clip instead of advancing to the following still/clip (reproduced via
the Take Still feature, which splits a clip and inserts a slide-filled gap).

- **Root cause:** when the playhead advances into a gap with no video clip,
  `_sync_player_to_timeline` clears the player source (`setSource(QUrl())`).
  QMediaPlayer then emits `positionChanged(0)`, and `_position_changed` mapped
  that stale event onto `current_time = active_clip.start_time - trim_start`
  (≈ 0), snapping the playhead back to the clip's start. The next tick replayed
  the clip — an infinite loop that never reached the still. The same class of
  spurious event (`setSource`/`setPosition` during a clip transition) also
  risked a backward jump on the next clip.
- **Fix:** `_position_changed` now returns early unless the player has a
  non-empty source **and** is in `PlayingState`, so only genuine playback drives
  the playhead. File: `desktop/src/neuroedit_desktop/ui/main_window.py`.
- **Regression coverage:** `test_position_changed_ignored_when_source_cleared`
  in `tests/test_main_window_headless.py` — active clip, source cleared,
  `_position_changed(0)` must leave `current_time` unchanged.
- **Verification:** `ruff check src tests scripts` passed; full suite passed
  with **126 tests** via `.venv/bin/python -m pytest tests/ -q`. Also verified
  headlessly against the real autosaved project (`Patient_1_v9.mov`, 114 s):
  pre-fix, a scrub into the still region snapped the playhead backward
  (`t=4.0 → 5.0`, i.e. `clip2.start 6.865 − trim_start 1.865`; `→ 0.0` when the
  active clip was clip1); post-fix every seek stays where placed (4.0, 10, 30,
  50). This was the same defect behind the user-reported "can't scrub from the
  still to the next clip" and "can't click on the second clip" (double-clicking
  clip2 seeks to its start, then the stray event bounced the playhead back into
  the still) — both resolved by the §30 guard.

### 30a. Follow-up: same bounce during PLAYBACK (2026-06-21)

The §30 guard fixed scrubbing (player paused, `play=False`) but the user
reported the bounce still happened during **playback**: starting from the
beginning and letting it play, the playhead reached the still→clip2 boundary
(~6.865 s) and bounced back into the still, never entering clip2.

- **Why §30 missed it:** during playback the player IS in `PlayingState`, so the
  `!= PlayingState` guard let the transient through. Crossing into clip2,
  `_sync_player_to_timeline` does `setSource(clip2)` + a seek to the clip's
  `trim_start`; before that seek lands QMediaPlayer emits `positionChanged(0)`,
  which — while playing — maps to `start_time − trim_start` (6.865 − 1.865 =
  5.0), a point back inside the still.
- **Fix:** `_position_changed` now also drops a **large backward jump** while the
  mapped time is more than 0.2 s before the current playhead
  (`if mapped < current_time - 0.2: return`). Real playback only advances, so the
  transient reset is ignored until the seek to `trim_start` settles and position
  moves forward again. Same file.
- **Regression coverage:** `test_position_changed_ignores_backward_jump_during_playback`
  (monkeypatches `playbackState`→Playing + a non-empty source; `_position_changed(0)`
  must not move the playhead off 6.9, and a real forward position is still honored).
- **Verification:** `ruff check src tests` clean; full suite **127 tests** green.
  Headless playback across the boundary now crosses 6.865 into clip2 instead of
  snapping to 5.0 (confirmed against the real `Patient_1_v9.mov` project); clip1→
  still still works (the position-0 reset at clip1's trimmed end is ignored too).
  Forward decode *through* clip2 can't be fully exercised offscreen (QMediaPlayer
  doesn't reliably advance position without a render surface) — needs a real-app
  confirmation. NOTE: do not launch a second app instance to test — it races the
  user's running instance on the shared `~/Documents/NeuroEdit/Autosave/project.json`.

### 30b. ACTUAL root cause + real fix: seek dropped after setSource (2026-06-21)

§30/§30a were treating symptoms. Driving the real app on a render surface (an
isolated, save-disabled instance — see the §30a NOTE) and logging
`player.position()` exposed the true cause: **a seek issued immediately after
`setSource()` is silently dropped because the media isn't loaded yet, so a
trimmed clip plays from source-time 0 instead of its `trim_start`.** For the
`(after still)` clip (`start_time 6.865`, `trim_start 1.865`) the player ran 0→
~1.8 s while `_position_changed` mapped that to `6.865 + pos − 1.865` = 5.0→6.6,
i.e. *behind* the playhead. The §30a backward-jump guard then froze/oscillated
`current_time` at the boundary (6.76↔6.89), re-entering the still each cycle —
exactly the user's "bounces back, never reaches the last clip."

- **Fix (the real one):** defer the seek until the media reports loaded.
  - `_build_media` connects `mediaStatusChanged` → `_media_status_changed` and
    adds `_pending_seek_ms` / `_pending_play`.
  - `_sync_player_to_timeline`, when it sets a **fresh** source, stashes the
    target ms + play intent and `pause()`s instead of seeking/playing now.
  - `_media_status_changed` applies `setPosition(_pending_seek_ms)` (and plays
    if still in playback) once status is `LoadedMedia`/`BufferedMedia`.
  - `_tick_timeline_playback` and `_position_changed` bail while
    `_pending_seek_ms` is outstanding, so nothing advances/re-plays-at-0 during
    the brief load.
  - The §30a backward-jump heuristic was **removed** (it caused the freeze); the
    §30 source-empty + PlayingState guards stay.
- **Regression coverage:** replaced the backward-jump test with
  `test_position_changed_ignored_while_seek_pending` and
  `test_media_status_applies_pending_seek_only_when_loaded`. `_window()` helper in
  `test_undo_history.py` now seeds `_pending_seek_ms`/`_pending_play`.
- **Verification (real render surface, real `Patient_1_v9.mov`):** full timeline
  now plays through — clip1 (pos 340→1833) → still1 (playhead 2.1→6.6) → clip2
  **enters at pos 1872 = trim_start and advances** 6.87→8.8 → still2 → clip3
  **enters at pos 4052 = its trim_start** and advances 14→20 s. Also confirmed an
  adjacent same-source Cut (no still between) still crosses its boundary
  seamlessly (`setSource(same URL)` re-fires `LoadedMedia`; pending never stuck).
  `ruff check src tests` clean; full suite **128 tests** green.

## 31. Variable-frame-rate playback smoothing (2026-06-21)

Fixed the reported pauses and timeline jumps when playing a macOS screen
recording.

- **Reproduction evidence:** the imported recording is H.264 variable-frame-rate
  media with 254 frames over 11.955 s. Consecutive frame timestamps range from
  8.3 ms to 1.63 s apart, which is normal for static screen-recording regions.
- **Root cause:** while a video was playing, `_tick_timeline_playback` returned
  early and `_position_changed` made sparse `QMediaPlayer.positionChanged`
  callbacks authoritative for `current_time`. The playhead therefore held and
  jumped at the recording's frame timestamps.
- **Fix:** the existing monotonic 33 ms timeline clock now advances
  `current_time` for video as well as slides/images/gaps. Media-position events
  are ignored while timeline playback is active. The player is not reseeked on
  ordinary same-clip ticks; synchronization still runs at clip/slide/gap
  boundaries and while the player is not playing.
- **Regression coverage:**
  `test_timeline_clock_advances_while_variable_frame_rate_video_is_playing`
  proves a sparse 5 s media-position event cannot jump a 2 s playhead and the
  next 33 ms clock tick advances smoothly without a player resync.
- **Verification:** `ruff check src tests scripts` passed; focused playback and
  headless MainWindow tests passed with 26 tests; full suite passed with
  **129 tests** via `.venv/bin/python -m pytest tests/ -q`.
- **Remaining optimization:** measure and reduce redundant annotation repaint
  work. Do not gate timeline playhead refreshes on decoded-frame changes because
  VFR static regions intentionally have sparse frames.

## 32. Finder drag-and-drop media import (2026-06-21)

Added the expected ability to drag media files from Finder into NeuroEdit.

- `MainWindow` now accepts drops anywhere in the app and routes supported local
  files through the existing `_import_media_file` path, preserving the same
  probing, active-clip selection, preview loading, dirty state, and undo behavior
  as Media Explorer imports.
- Supported video types are `.mp4`, `.mov`, `.m4v`, `.avi`, and `.webm`;
  supported images are `.png`, `.jpg`, `.jpeg`, `.heic`, `.bmp`, and `.webp`.
  Unsupported files, remote URLs, and folders are not accepted.
- The Media Explorer hint now advertises drag-and-drop.
- Regression coverage proves a mixed drop imports the supported local video and
  image while ignoring an unsupported text file.
- Verification: `ruff check src tests scripts` passed; focused headless and
  playback tests passed with 27 tests; full suite passed with **130 tests** via
  `.venv/bin/python -m pytest tests/ -q`.

## 33. v0.5.3-alpha release (2026-06-21)

Prepared and tagged the next patch release for the playback and media-import
fixes completed in §§31–32.

- Version bumped from `0.5.2-alpha` to `0.5.3-alpha` in
  `desktop/src/neuroedit_desktop/__init__.py`.
- Root `README.md` now points to the `v0.5.3-alpha` release and installer names,
  with a concise What's New section for smooth variable-frame-rate playback and
  drag-and-drop import.
- `desktop/README.md` documents the monotonic playback clock and supported
  import entry points. `desktop/ALPHA_QA_CHECKLIST.md` adds macOS and Windows
  checks for drag-and-drop and variable-frame-rate screen recordings.
- Release gate: `ruff check src tests scripts`, 130-test full suite, and
  `git diff --check` all passed before the release commit and annotated tag.
- CI release path: pushing `v0.5.3-alpha` triggers `.github/workflows/build.yml`
  to build the unsigned macOS DMG/ZIP and Windows installer, then publish the
  GitHub Release with those artifacts.

## 34. Optimization automation run (2026-06-22)

Daily optimization scan (no code changes; markdown only). Reviewed
`35447b8..86aca4f` (v0.5.1→v0.5.3-alpha: `_open_recent_project` cache
invalidation, §30b deferred-seek-after-`setSource`, §31 VFR playback smoothing,
§32 Finder drag-and-drop).

- The prior run's `_open_recent_project` consistency finding is now fixed
  (`51778da`) and checked off in the TODO backlog.
- Two new findings filed under TODO.md → Optimization Backlog:
  1. A clip that never reaches `LoadedMedia` leaves `_pending_seek_ms` stuck →
     permanent playback freeze; no `InvalidMedia`/`errorOccurred` handler clears
     the pending seek (correctness/robustness).
  2. Multi-file Finder drop runs N serial blocking probes + N preview reloads +
     N undo snapshots via the per-file `_import_media_file` loop (perf/UX).
- CLAUDE.md "Optimization Automation Memory" marker advanced to `86aca4f`
  (2026-06-22); added architecture notes for the deferred-seek state machine and
  the drag-and-drop import path.

## 35. Terminal media-status playback recovery (2026-06-22)

Implemented the first actionable correctness finding from §34.

- `MainWindow._media_status_changed()` now clears `_pending_seek_ms` and
  `_pending_play` when `QMediaPlayer` reports terminal `NoMedia` or
  `InvalidMedia`. The next timeline-clock tick can therefore advance beyond an
  unloadable clip instead of returning forever on the deferred seek.
- Recoverable statuses remain pending, and `LoadedMedia`/`BufferedMedia` still
  apply the deferred seek before optionally resuming playback.
- Added parameterized headless regressions covering both terminal statuses;
  the suite now contains 132 tests.
- Next code-ready optimization item: batch multi-file Finder drop so one gesture
  performs one preview load and one undo snapshot after its imports. Keep the
  synchronous probe behavior as a separate measurement-first follow-up.

## 36. Overlay-slide video playback fix (2026-06-22)

Fixed the miniplayer freezing video whenever a slide overlapped a clip.

- `MainWindow._sync_player_to_timeline()` now pauses only for full-frame slides;
  `Slide.overlay=True` continues through the normal video seek/play path.
- `_tick_timeline_playback()` now treats a playing video beneath an overlay as
  already synchronized instead of re-entering the sync path every tick.
- `_position_changed()` retains its full-frame-slide pause guard but does not
  pause video for overlays.
- Added focused regressions for starting playback within an overlay and
  continuing an already-playing video through one. The suite now has 134 tests.
- Export behavior was already correct: overlay slides composite over the source
  frame, while full-frame slides replace it.

## 37. v0.5.4-alpha release (2026-06-22)

Prepared the next patch release for the identity refresh and playback fixes.

- Replaced the prior raster identity with the aperture-and-scalpel mark: live
  theme-aware SVG header/About lockups, regenerated PNG/iconset assets, macOS
  `.icns`, and multi-resolution Windows `.ico`.
- Added `scripts/generate_icons.py` so packaged icon assets can be reproduced
  from `resources/neuroedit-appicon.svg`; removed the obsolete
  `logo_wordmark.png`.
- Included terminal invalid-media recovery (§35) and continuous video playback
  beneath overlay slides (§36).
- Version and release documentation advanced from `v0.5.3-alpha` to
  `v0.5.4-alpha`. Pushing the annotated tag triggers the existing GitHub Actions
  workflow to build and publish macOS and Windows installers.

## 38. Bundled Space Grotesk wordmark font (2026-06-22)

- Bundled Space Grotesk Medium/Bold static TTFs under `resources/fonts/` with
  the upstream SIL Open Font License 1.1. The files come from the Space Grotesk
  upstream repository.
- `_load_wordmark_font_family()` registers the font data with
  `QFontDatabase.addApplicationFontFromData()` before constructing the live
  wordmark. No system font installation or missing-family alias lookup is
  required; the active Qt font remains a failure-only fallback.
- Added focused headless coverage proving the live wordmark resolves to the
  bundled Space Grotesk family. The suite now has 135 tests.

## 39. Optimization automation sweep (2026-06-23, docs-only)

Scheduled daily-optimization run — incremental over `86aca4f..0050a42` (2 commits
plus the uncommitted §38 font work): §35 invalid/no-media pending-seek recovery,
§36 overlay-slide playback, §37 identity/icon refresh, §38 bundled Space Grotesk
TTFs. No code changed; planning/memory markdown only.

- **No new backlog findings.** The diff is correctness fixes already tracked
  (§35 and §36 implement the two findings from the §34 sweep — both `[x]` in the
  TODO Optimization Backlog) plus non-perf-critical identity UI (theme-matched
  SVG marks rasterized at DPR; bundled wordmark font loaded once via
  `QFontDatabase.addApplicationFontFromData`). The two real open items —
  playback repaint throttling and multi-file Finder-drop batching — are untouched
  by this diff and stay open.
- **Reviewed for fresh targets and dismissed three:** the SVG re-render on theme
  toggle / About open is marginal (rare, user-driven, not a paint path); §36 adds
  no per-tick `_slide_at_time` cost (`active_slide`/`next_slide` computed once and
  reused); §35's terminal-status handler covers the unloadable-clip case so a
  separate `errorOccurred` slot would be redundant. Recorded all three in
  `desktop/CLAUDE.md` so future runs don't re-flag them.
- **Markdown consistency:** corrected the `main_window.py` line figure from
  `~4,050` to **~4,240** (the §37/§38 code added ~190 lines) in `TODO.md` P4.5,
  `NEXT_OPTIMIZATION_PLAN.md` §1 + Phase 6, and `desktop/CLAUDE.md`. Present-state
  test-count references already read 135 everywhere.
- **Memory:** advanced the `desktop/CLAUDE.md` "Last reviewed" marker to `0050a42`
  (2026-06-23) and added an identity-assets architecture bullet.
- Did **not** run the suite (docs-only; no `.py` files touched).

## 40. Batched multi-file Finder drop (2026-06-23)

- Added `_import_media_files()` as the shared import path. Media Explorer keeps
  its existing single-file behavior by passing a one-item list.
- `dropEvent()` now passes the full accepted path list into that helper. The
  files retain their drop order, the last successful import becomes active, and
  the gesture performs one preview load plus one dirty/history operation.
- Synchronous `probe_video` calls remain serial and unchanged; moving probes off
  the UI thread requires separate measurement and lifecycle design.
- Added focused coverage for batch filtering, import order, active selection,
  and the single preview/dirty calls. The suite now has 136 tests.
- Remaining code-ready optimization target: measure and reduce redundant
  annotation repaint work without gating the clock-driven playhead on decoded
  frame changes.

## 41. Optimization automation run (2026-06-24, docs-only)

Scheduled daily-optimization run — incremental over `0050a42..188e3c2` (1 commit:
§38 bundled fonts + §40 batch media drops, now committed; the §39 run had already
analyzed this content as uncommitted work). No code changed; markdown only.

- **One new backlog finding:** batch media import (`_import_media_files`,
  `ui/main_window.py:2671`) probes every dropped video synchronously on the UI
  thread via `probe_video` → `cv2.VideoCapture` (`video_probe.py:6`) with no
  progress feedback, so a large multi-file drop freezes the UI for the sum of all
  probe times. This is the measurement-first follow-up §40 foreshadowed, now
  recorded as its own unchecked item in the TODO Optimization Backlog.
- **Verified §40's single-history claim:** `_add_video_clip`/`_add_image_clip`
  only mutate the model; the lone trailing `_mark_dirty()` (`:2690`) is the only
  history/dirty op for the gesture. Added a confirmation note under the checked-off
  §40 backlog item.
- **Memory:** advanced the `desktop/CLAUDE.md` "Last reviewed" marker to `188e3c2`
  (2026-06-24); next deep-dive starts after `188e3c2` plus one hop.
- Markdown language consistency: the two touched docs (`ASSET_CHECKLIST.md`,
  `DESIGN_LANGUAGE.md`) describe the bundled-font change consistently — no fixes.
- Did **not** run the suite (docs-only; no `.py` files touched).

## 42. Multi-video import probe feedback (2026-06-24)

- Measured `probe_video()` against the generated smoothness fixture: 1080p was
  3.3 ms median and 4K was 9.9 ms median across five probes, with an 85.8 ms
  cold outlier. Those bounded calls did not justify adding asynchronous worker
  lifecycle and cancellation state.
- Multi-video imports now show a window-modal, determinate metadata progress
  dialog and process Qt events between probes. Single-video imports retain their
  existing direct path. Probe duration is also recorded as the PHI-safe
  `media_probe` diagnostics event without logging filenames or paths.
- Preserved the §40 contract: import order, last successful active clip, one
  preview load, and one dirty/history operation per batch.
- Added focused progress coverage. Verification: `ruff check src tests scripts`,
  21 headless main-window tests, `137 passed` for the full suite, and
  `git diff --check`.
- Next code-ready optimization target remains measurement-first annotation
  repaint reduction; keep the monotonic playhead clock independent of decoded
  frame events.

## Automation: optimization scan (2026-06-25)

- Daily optimization automation ran incrementally over `188e3c2..HEAD`
  (1 commit: `491c910` §42 multi-video probe progress). No code modified —
  markdown only.
- **New backlog item** (TODO.md → Optimization Backlog): §42's probe
  `QProgressDialog` only reaches drag-and-drop. One-hop caller tracing showed
  `_import_video` (`ui/main_window.py:2614`) — wired to File → Import Video
  (`:1405`) and the Media Explorer "Import Videos" button (`:1872`) — and
  `_import_image` (`:2630`) still duplicate the `_import_media_files` loop inline,
  so multi-video selection from the menu/button freezes the UI with no feedback.
  Suggested fix: delegate both to `_import_media_files`.
- Verified §42 itself is correct and matches its checked-off backlog entry.
- CLAUDE.md "Last reviewed" advanced to `491c910` (2026-06-25); added the
  import-path centralization-gap architecture note.

## 43. Centralized menu/button media imports (2026-06-25)

- `_import_video` and `_import_image` now delegate selected file-dialog paths to
  `_import_media_files` instead of duplicating the add/load/dirty loop inline.
  File -> Import Video and the Media Explorer multi-import buttons now share the
  same multi-video metadata progress dialog, active-clip selection, preview load,
  and single dirty/history operation that drag-and-drop already used.
- Added focused headless regressions for both dialog entry points, alongside the
  existing batch import and probe-progress coverage.
- Verification: `ruff check src tests scripts`; `python -m pytest tests/ -q`
  (139 passed); `git diff --check`.
- Next code-ready optimization target remains measurement-first annotation
  repaint reduction; keep the monotonic playhead clock independent of decoded
  frame events.

## 44. Playback canvas repaint reduction (2026-06-27)

- `_tick_timeline_playback()` continues refreshing the timeline/playhead on
  every monotonic 33 ms tick; decoded video-frame events do not gate it.
- `VideoGraphicsView` now requests an annotation-layer repaint only when the
  rendered time state changes: annotation visibility or tracked-mask frame,
  active slide, caption cue, or fade opacity. Static overlay intervals no
  longer repaint at 30 Hz.
- Deterministic measurement over a 10 s synthetic clip with one static
  annotation: 1 canvas repaint request across 300 ticks, avoiding 299 redundant
  requests.
- Focused tests cover stable annotation intervals, annotation boundaries, and
  continuously changing fades. Verification: `ruff check src tests scripts`;
  `python -m pytest tests/test_undo_history.py -q` (15 passed);
  `python -m pytest tests/ -q` (141 passed); `git diff --check`.
- Next code-ready Phase 6 options are the documented `MainWindow` mechanical
  split, undo snapshot measurement/reduction, or cold-start import audit.

## 45. Playback repaint change published (2026-06-28)

- Re-ran the documented gate against `9033fb3`: `ruff check src tests scripts`,
  15 focused undo/playback tests, the full 141-test suite, and
  `git diff --check` all passed.
- Pushed `9033fb3` to `origin/main`. No release tag was created because this is
  an internal behavior-preserving optimization with no version or release
  instruction.
- The next code-ready Phase 6 choices remain the `MainWindow` mechanical split,
  measurement-led undo snapshot work, or the cold-start import audit.

## 46. Cold-start import audit completed (2026-06-29)

- Audited the `main_window` startup graph. `torch` was already lazy; the export
  pipeline was pulled in eagerly by export settings even though export and still
  capture are user-triggered paths.
- Deferred exporter imports to export, still capture, worker execution, and
  export-settings creation. Live-caption helpers remain eager because the canvas
  uses them during normal preview.
- Five-process warm import measurements held a 0.17 s median before and after,
  while the exporter (about 45 ms cumulative in the import trace) is no longer in
  the startup module graph.
- Verification: `ruff check src tests scripts`; 42 focused caption/export/window
  tests; full 141-test suite; `git diff --check`.
- Next code-ready Phase 6 options are the `MainWindow` mechanical split or
  measurement-led undo snapshot reduction. No release is indicated for this
  internal behavior-preserving optimization.

## 47. Undo-history cumulative-size cap (2026-07-01)

- Added compact-payload byte accounting to the existing dictionary-based undo
  snapshots. History now evicts oldest states above 64 MiB as well as above 50
  entries, while always retaining the current state.
- Undo/redo transfers the corresponding size metadata with each snapshot, and a
  new document edit clears redo size metadata alongside the redo stack/hashes.
- Kept restore, autosave-reuse, transient-key, and mask-cleanup semantics
  unchanged; compact string storage and pre-serialize short-circuiting remain
  separate measurement-led follow-ups.
- Verification: `ruff check src tests scripts`; 17 focused undo/playback tests;
  full 143-test suite; `git diff --check`.
- Next code-ready Phase 6 choices are the mechanical `MainWindow` split or the
  remaining measured undo serialization/storage work. No release is indicated
  for this internal behavior-preserving optimization.

## 48. Publication blocked by GitHub authentication (2026-07-01)

- Committed the undo-history cap as `13e3411` (`perf: bound undo history memory`).
- Local `main` is two commits ahead of `origin/main`, including the previously
  completed `94181d6` cold-start import optimization.
- `git push origin main` could not authenticate to the HTTPS remote; `gh` is not
  installed and the existing SSH identity is also unauthorized. Re-authenticate
  GitHub in this environment, then run `git push origin main`.
- No release tag was created because neither behavior-preserving optimization
  changes release state or carries a release instruction.

## 49. Compact undo-history storage (2026-07-02)

- Reused the compact JSON payload already produced during each history push as
  the stored undo/redo entry, removing the duplicate nested-dictionary history
  representation. Autosave reuse and the on-disk project format are unchanged.
- Undo/redo decodes entries only when restoring. Close-time orphan-mask cleanup
  decodes retained history before collecting referenced mask paths, preserving
  session-long mask undo safety.
- On 50 edits to the generated smoothness fixture, traced retained memory fell
  from 0.631 MiB to 0.400 MiB (36.6%); median history-push time stayed flat at
  0.640 ms before and 0.629 ms after.
- Verification: `ruff check src tests scripts`; 27 focused undo/SAM tests;
  full suite (`143 passed`); `git diff --check`.
- Remaining code-ready Phase 6 choices are the mechanical `MainWindow` split or
  careful evaluation of a pre-serialize change check. No release is indicated.

## 50. Publication still blocked (2026-07-02)

- The compact-history work is committed locally; `main` is now four commits
  ahead of `origin/main`, including the three previously unpublished commits.
- `git push origin main` still cannot authenticate to the HTTPS remote. Install
  or configure GitHub credentials in this environment, then push `main`.
- No release tag was created because the current work is an internal optimization
  and neither the roadmap nor repository version state indicates a release.

## 51. Export worker extraction (2026-07-03)

- Moved `ExportWorker` from `ui/main_window.py` to `ui/export_worker.py` as a
  mechanical Phase 6 modularization slice. `main_window.py` re-exports the class,
  and `ProjectExporter` remains imported only inside `run()`, preserving startup
  behavior and existing import compatibility.
- Deferred the undo pre-serialize short-circuit: the current model has no cheap
  document revision signal, so adding mutation bookkeeping would risk undo
  correctness for an unmeasured micro-optimization.
- Found an unused legacy `TimelineWidget` in `main_window.py`; left it untouched
  pending an explicit compatibility check in a separate cleanup.
- Verification: `ruff check src tests scripts`; full suite; lazy-import/re-export
  probe; `git diff --check`.
- Publication remains blocked because the HTTPS remote has no configured GitHub
  credentials. No release tag is indicated for this internal code move.

## 52. Optimization backlog published (2026-07-03)

- Configured Git to use the authenticated GitHub CLI credential helper and
  pushed the five queued commits (`94181d6` through `6796314`) to `origin/main`.
- Verified local `main` and `origin/main` both resolved to `6796314` after the
  push. The cold-start, bounded/compact undo-history, and export-worker changes
  are now published.
- No release tag was created because these commits are internal, behavior-
  preserving optimization and refactoring work; the current release remains
  `v0.5.4-alpha`.

## 53. SAM panel extraction (2026-07-04)

- Moved `SamPanel` from `ui/main_window.py` to `ui/sam_panel.py` as the next
  mechanical Phase 6 modularization slice. `main_window.py` re-exports the
  class, preserving existing imports and behavior.
- `main_window.py` is now about 3,870 lines (down from about 4,260). The broader
  `MainWindow` split remains open; the undo pre-serialize shortcut remains
  deferred because there is no safe cheap document-revision signal.
- Verification: `ruff check src tests scripts`; focused SAM workflow tests;
  `SamPanel` re-export identity probe; full suite; `git diff --check`.
- No release tag is indicated for this internal refactor. The current release
  remains `v0.5.4-alpha`.

## 54. Labels panel extraction (2026-07-05)

- Moved `LabelsPanel`, label-preset definitions, and custom-preset persistence
  from `ui/main_window.py` to `ui/labels_panel.py` as the next mechanical Phase
  6 modularization slice. `main_window.py` re-exports `LabelsPanel` and imports
  the shared preset data used by the toolbar, preserving behavior and imports.
- Added a re-export identity regression. `main_window.py` is now about 3,390
  lines and `labels_panel.py` is about 525; the broader `MainWindow` split
  remains open.
- Verification: `ruff check src tests scripts`; 24 focused headless main-window
  tests; `LabelsPanel` re-export identity probe; full suite (144 passed in
  23.88 s); `git diff --check`.
- No release tag is indicated for this internal refactor. The current release
  remains `v0.5.4-alpha`.

## 55. Legacy timeline cleanup (2026-07-06)

- Removed the unused `TimelineWidget` from `ui/main_window.py` after a
  repository-wide reference check found no imports or runtime uses;
  `RichTimelineWidget` remains the live timeline implementation.
- Removed the now-unused Qt `Signal` import. `main_window.py` is now about 3,350
  lines; the broader mechanical `MainWindow` split remains the next code-health
  task.
- Verification: `ruff check src tests scripts`; full suite (144 passed in
  98.74 s); `git diff --check`.
- No release tag is indicated for this internal dead-code cleanup. The current
  release remains `v0.5.4-alpha`.

## 56. Branding helper extraction (2026-07-07)

- Moved the header/About identity helpers from `ui/main_window.py` to
  `ui/branding.py` as a mechanical Phase 6 modularization slice. The new module
  owns the theme-matched SVG mark path/rasterization and bundled Space Grotesk
  wordmark font loading.
- `main_window.py` imports those helpers, so existing direct imports such as
  `neuroedit_desktop.ui.main_window._wordmark_font` continue to resolve.
  `main_window.py` is now about 3,282 lines; the broader mechanical
  `MainWindow` split remains the next code-health task.
- Verification: `ruff check src tests scripts`; full suite (144 passed in
  62.08 s); `git diff --check`; branding helper re-export compatibility probe.
- No release tag is indicated for this internal refactor. The current release
  remains `v0.5.4-alpha`.

## 57. MainWindow utility helper extraction (2026-07-08)

- Moved pure `MainWindow` utility constants/helpers from `ui/main_window.py` to
  `ui/main_window_utils.py` as a mechanical Phase 6 modularization slice. The new
  module owns the mask palette, supported media extension sets, time/color
  formatting helpers, SAM propagation-window math, and orphan-mask cleanup
  helpers.
- `main_window.py` imports and re-exports those names, so existing direct imports
  such as `neuroedit_desktop.ui.main_window.delete_orphan_masks` and
  `MASK_PALETTE` continue to resolve. `main_window.py` is now about 3,232 lines;
  the broader mechanical `MainWindow` split remains the next code-health task.
- Added a re-export identity regression alongside the existing SAM/orphan-mask
  behavior tests.
- Verification: `ruff check src tests scripts`; focused SAM/design-token tests
  (28 passed); full suite (145 passed in 34.30 s); `git diff --check`;
  utility re-export compatibility probe.
- No release tag is indicated for this internal refactor. The current release
  remains `v0.5.4-alpha`.

## 58. SAM workflow mixin extraction (2026-07-09)

- Moved the SAM workflow orchestration methods from `ui/main_window.py` to
  `ui/sam_workflow.py` as `SamWorkflowMixin`. The moved methods cover SAM point
  controls, backend probing, setup/download, segmentation, propagation,
  re-track, heartbeat status, and weight deletion.
- `MainWindow` now inherits the mixin while keeping the same signal wiring and
  compatibility re-exports for SAM workers/dialogs. `main_window.py` is now
  about 2,742 lines; one more mechanical slice should bring it below the
  ~2,500-line `ui/` module target.
- Verification: `ruff check src tests scripts`; focused SAM/headless coverage
  (`35 passed`); full suite (`145 passed in 22.89 s`); `git diff --check`;
  `MainWindow`/`SamWorkflowMixin` import compatibility probe.
- No release tag is indicated for this internal refactor. The current release
  remains `v0.5.4-alpha`.

## 59. Export workflow mixin extraction (2026-07-10)

- Moved the MP4 export, caption export, export history, reveal, progress, and
  export-report controller methods from `ui/main_window.py` to
  `ui/export_workflow.py` as `ExportWorkflowMixin`.
- `MainWindow` now inherits the export mixin alongside `SamWorkflowMixin`.
  Existing export button/menu signal wiring and compatibility re-exports for
  export dialogs/workers remain in place. `main_window.py` is now about 2,447
  lines, below the Phase 6 ~2,500-line `ui/` module target.
- Verification: `ruff check` on changed export/headless files; export-focused
  tests (`34 passed`); full `ruff check src tests scripts`; full suite
  (`145 passed in 23.41 s`); `git diff --check`.
- No release tag is indicated for this internal refactor. The current release
  remains `v0.5.4-alpha`.

## 60. Cached undo no-op serialization skip (2026-07-11)

- Implemented the safe part of the remaining undo-cost item: `_push_history()`
  now compares the freshly built `ProjectState.to_dict()` result with the cached
  autosave dict before building the compact JSON payload and BLAKE2 hash. When
  they match, the no-op history push returns early after clearing redo
  bookkeeping, preserving the existing net-zero-edit semantics and autosave
  reuse.
- Added focused coverage proving the cached no-op path skips payload
  reserialization and still clears `_redo_stack`, `_redo_hashes`, and
  `_redo_sizes`.
- Deferred a true pre-`to_dict()` shortcut: the current model has no trustworthy
  document revision signal, and adding broad mutation bookkeeping is not worth
  the correctness risk for this micro-optimization.
- Verification: focused undo/playback suite (`18 passed`). Full lint/suite
  results are recorded with the commit for this run.
- No release tag is indicated for this internal optimization. The current
  release remains `v0.5.4-alpha`.

## 61. Codebase review integrity fixes (2026-07-11)

- Implemented the review findings across project state, privacy, VFR media
  handling, SAM assets, export safety, thumbnails, and release packaging.
  Project replacement now prompts for unsaved work, does not cross-contaminate
  undo history, and Save As stages a new project while copying `masks/`,
  `audio/`, and `stills/` assets. Content-changing media/timeline/audio actions
  clear PHI/de-identification/audio-review attestations.
- Export and SAM frame selection now seek by media timestamp rather than an
  average-FPS frame index. SAM masks have run-unique filenames and stale async
  results are discarded. Exports reject missing inputs and source-overwriting
  targets; audio muxing writes a staged file before atomically replacing output.
- Project-library thumbnail generation is disabled until de-identification is
  confirmed. Packaged alpha builds are documented as editor-only (SAM requires
  a source `[sam]` build). CI runs the quality suite before installer/release
  jobs; version plumbing now follows the release version, and packaging uses
  release constraints.
- Verification: `ruff check src tests scripts`; full suite (`153 passed in
  26.27 s`); `git diff --check`; `.venv/bin/python -m compileall -q src`.
  The expected Qt missing-media diagnostic appeared in a fixture test; all tests
  passed. Released as `v0.5.5-alpha` after the final documentation/version sync.

## 62. v0.5.5-alpha release (2026-07-11)

- Released the codebase-review integrity fixes as `v0.5.5-alpha`. The root
  README's installer names and release notes, Python/package version, macOS
  bundle version, and Windows installer version are aligned to this tag.
- The tagged CI workflow runs lint and the full test suite before producing the
  macOS and Windows alpha installers and publishing the prerelease assets.

## 63. Post-release roadmap/docs consistency pass (2026-07-12)

- Reviewed `TODO.md`, `NEXT_OPTIMIZATION_PLAN.md`, `HANDOFF.md`, and
  `desktop/CLAUDE.md` after the `v0.5.5-alpha` integrity release. The remaining
  open roadmap work is still owner/hardware/sample-data gated or explicitly
  measurement-first; no new surgical code change was justified by the live docs.
- Synchronized active roadmap guidance to the current 153-test baseline while
  leaving historical session entries unchanged.
- Verification target for this docs-only pass remains `ruff check src tests
  scripts`, the full desktop suite, `git diff --check`, and a no-tag push unless
  a release-relevant change appears.
