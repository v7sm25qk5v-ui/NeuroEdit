# NeuroEdit app review — 2026-11-12

Reviewed checkout: `3e00fc0` (v0.5.14-alpha, published 2026-11-10). No application
source, dependency, preference, release, commit, push, or tag was changed by this
review. Tickets are in [CODING_TICKETS.md](../../../CODING_TICKETS.md) as NE-010 to
NE-030.

## How the review was run

A coordinating agent (Claude Fable) read the repo docs and ticket history, then
fanned out seven subagents and checked their output against the source:

| Agent | Model | Scope |
|---|---|---|
| Core reviewer | Sonnet | `ui/main_window.py`, `ui/history.py`, `models.py`, `project_store.py` |
| Timeline/canvas reviewer | Sonnet | `ui/editor_panels.py`, `ui/canvas.py`, labels, tutorial |
| Export/PHI reviewer | Sonnet | `exporter.py`, export workflow/worker, `captions.py`, `ui/dialogs.py`, diagnostics |
| Audio/import/SAM reviewer | Sonnet | audio panel/preview, media import worker, SAM backend/workflow/workers, project library |
| Docs/CI auditor | Haiku | versions, dependencies, workflows, docs drift, repo hygiene |
| Test runner | Haiku | full pytest suite, lint, side-effect check on native prefs and autosave |
| Verification engineer | Sonnet | executable repro tests for the ten highest-value findings |

Reviewers were read-only and were told not to re-report the known false positives
in `desktop/CLAUDE.md`, the nine closed tickets, or the open `AudioPreview.sync`
finding in `TODO.md`. The coordinator read the cited source for every ticketed
finding and reran the failing tests itself.

Evidence labels used in the tickets:

- **Reproduced** — a test in [repros/](repros/) asserts the desired behaviour and
  fails on `3e00fc0`.
- **Source confirmed** — the code path was read end to end by the coordinator; not
  executed.
- **Unmeasured** — a plausible cost whose user impact has not been profiled.

## Current state

NeuroEdit is a single-process PySide6 desktop editor: about 15,200 lines of
application Python in 30 modules and about 6,050 lines of tests (341 collected).
Feature surface at this checkout:

| Area | State |
|---|---|
| Import, linking, project library | Solid. Off-thread probing, relink, drag-and-drop, neutral library previews. |
| Timeline (split, trim, ripple, reorder, fades, markers) | Core mechanics are sound and well tested. Ripple does not treat overlays consistently (NE-010, NE-011). |
| Annotations, slides, stills | Preview is correct. Export places non-redaction overlays in the wrong coordinate space whenever the output aspect or size differs from the source (NE-012). |
| Privacy / PHI | Redaction pixels, re-encode forcing, metadata stripping, and diagnostics are sound. Gaps are at the edges: redaction windows after edits (NE-010), attestation resets from view actions (NE-014), caption text outside every gate (NE-015). |
| Narration and audio | Recording state machine is the best-tested part of the app. Audio controls flood undo history (NE-016). |
| Captions | Transcript-driven; no speech recognition. Minor format issues (NE-029). |
| Export | Segment and timing logic is careful. Fails on a different output volume in the default configuration (NE-013); render loop is slow by construction (NE-026). |
| SAM | Source builds only; not executable in this environment (no torch). Weight and model lifecycle has several rough edges (NE-024). |
| Undo, autosave, persistence | Snapshot design is correct and capped. Two data-loss paths around the scratch autosave folder (NE-017, NE-018) and a spurious dirty mark on media load (NE-019). |
| Build, CI, distribution | Release is gated on quality; installers unsigned. Windows ships untested (NE-027). |

## Test and lint results

Run from `desktop/` with the project venv (Python 3.13.5, PySide6 6.11.1,
pytest 9.0.3), `QT_QPA_PLATFORM=offscreen`, `PYTHONPATH=src`.

- **Lint:** `ruff check src tests scripts` (ruff 0.15.16, system install) — all
  checks passed. `ruff format --check` would reformat 47 of 55 files; the project
  does not gate on formatting. Ruff is not installed in the project venv.
- **Full suite, as the machine is configured:** 341 collected, **328 passed,
  13 failed** in 370 s; the process exited 139 (segfault at interpreter exit,
  after the summary line; seen once, not rerun).
- **Cause of 12 failures:** `/usr/local/bin/ffmpeg` is an x86_64 Homebrew binary
  and this Mac is arm64 without Rosetta (`Bad CPU type in executable`). The app
  and tests take `ffmpeg` from `PATH` before the bundled `imageio-ffmpeg` binary
  (`exporter.py:165-176`). With the bundled arm64 ffmpeg first on `PATH`, all 12
  pass. This is also a product defect: see NE-023.
- **Remaining failure:** `tests/test_capture_baseline.py` times out its 30 s child
  process on this machine (three of three runs). It passes in CI. See NE-027.
- **Net:** 340 of 341 pass locally with a working ffmpeg. CI's last recorded
  result for this commit was 341 passed.
- **Side effects:** SHA-256 of the user's autosave `project.json` and both
  NeuroEdit preference plists were identical before and after every run.

## Findings by priority

Full problem statements, scope, and acceptance criteria are in the tickets.

### P1 — wrong output or privacy exposure

| Ticket | Finding | Evidence |
|---|---|---|
| NE-010 | Redactions stop covering their footage after timeline edits | Reproduced |
| NE-011 | Head-trim ripple result depends on how the handle was dragged | Reproduced |
| NE-012 | Export draws labels, arrows, and masks in output-frame space | Reproduced |
| NE-013 | Export to a different volume fails after the full render | Source confirmed |
| NE-014 | Zooming or clicking the timeline resets a completed PHI review | Reproduced |

### P2 — data loss, misleading state, or a blocked workflow

| Ticket | Finding | Evidence |
|---|---|---|
| NE-015 | Caption text reaches burned-in frames and sidecar files with no PHI gate | Source confirmed |
| NE-016 | Sliders and text fields push one undo snapshot per tick or keystroke | Reproduced (volume slider) |
| NE-017 | An unreadable autosave is overwritten by the next autosave | Reproduced |
| NE-018 | New Project reuses the scratch folder without a prompt | Reproduced |
| NE-019 | A media duration event marks the project dirty and clears redo | Reproduced (dirty mark) |
| NE-020 | Take Still leaves captions and tracked-mask frames behind | Reproduced |
| NE-021 | Closing the window cancels a running export or SAM job silently | Source confirmed |
| NE-022 | A shape or redaction released outside the frame is discarded | Reproduced |
| NE-023 | `PATH` ffmpeg is preferred over the bundled build and never validated | Observed in this run |
| NE-024 | SAM weight and model lifecycle defects | Source confirmed; not executable here |
| NE-025 | The tutorial edits the user's real project when clips exist | Source confirmed |
| NE-026 | Export render loop seeks per frame and re-renders static content | Unmeasured |

### P3 — hardening and polish

| Ticket | Finding |
|---|---|
| NE-027 | Release and CI hardening (no Windows test job, version in five places, floating action tags, tight test timeout) |
| NE-028 | Timeline polish (dead Delete on label blocks, no playhead scrub, end-edge snap, stale theme tokens, lane layout cost) |
| NE-029 | Export and caption robustness (hardware encoder ignores quality, odd dimensions, VTT escaping, report contents) |
| NE-030 | Small lifecycle and documentation items |

## Reviewed and found sound

Recorded so the next review does not repeat the work:

- Undo/redo push and pop symmetry, byte-cap eviction, `_restoring` guard, autosave
  snapshot aliasing, atomic `ProjectStore.save_data`, Save As staging and asset
  migration.
- Deferred-seek state machine, including terminal media statuses.
- Import worker lifecycle, stale-result rejection, close-time thread shutdown.
- Recording state machine (start error, stop-before-error, project change during
  recording, zero and non-finite durations, close blocking).
- `AudioPreview` teardown, seek and drift handling, volume clamp.
- SAM source-to-timeline mapping for trimmed and VFR clips, mask filename
  uniqueness, OpenCV capture release, cooperative cancel, stale-result discard.
- Redaction pixel path: interval-overlap render decision, zero-duration window as
  whole timeline, endpoint frame isolation, last-and-opaque painting, fitted
  source rect.
- Metadata stripping on every ffmpeg output; source audio dropped with `-an`;
  temp-directory cleanup and cancel handling.
- Diagnostics log holds counts and durations only.
- Project library has no thumbnail path that could show un-reviewed frames.
- Timeline static-layer cache fingerprint covers every painted field.
- Split bookkeeping, trim-end clamp, reorder compaction, single-undo drag commits.

## Not covered

No packaged installer was run. No Windows execution, physical microphone or audio
output, real SAM inference, clinical footage, or assistive-technology pass. NE-013
was not exercised on a second volume. This was not a security audit.

## Reproducing the evidence

The tests in [repros/](repros/) assert the desired behaviour, so they fail until
the matching ticket is fixed. They live outside `tests/` on purpose. From
`desktop/`:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m pytest docs/review-2026-11-12/repros -q
```

`repros/conftest.py` applies the suite's settings isolation (the redirect of
application settings to a temporary INI file) and `test_00_guard.py` asserts it
before any window is built. Expected after the NE-010/NE-011 fix: 8 failed,
1 passed (on `3e00fc0` it was 11 failed, 1 passed, with three tests since moved
to `tests/test_ripple_overlays.py`). When a ticket is fixed, move its test into
`tests/` as the regression test.

**Correction, 2026-11-12 (later the same day).** As first written, these repros
relied on a `-p conftest` flag for settings isolation, and a bare `pytest` from
`desktop/` collected them without it. One such run built MainWindow against the
native NeuroEdit preferences and rewrote
`~/Library/Preferences/com.neuroedit.Desktop.plist`. The fixtures restore the
keys they set; the file is the same size with the same keys and values as far
as can be reconstructed, but it is no longer byte-identical to the baseline
hash recorded above. The autosave project was not touched. Fixed by
`repros/conftest.py` and by `testpaths = ["tests"]` in `pyproject.toml`.
