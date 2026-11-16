# Resumed ticket implementation — 2026-11-16

Work resumes from `3e24301` plus Claude's uncommitted NE-012–NE-031 changes.
All existing work was preserved; the source remains local and uncommitted.
Terra engineers owned export, editor, lifecycle, and packaging areas. Sol
performed independent senior review; the coordinator integrated shared paths.

## Verification

- Final full `desktop/tests/`: **691 passed in 40.56 s**, then **691 passed in
  39.69 s**, clean exits and no skips. Both treat unraisable and unhandled-thread
  warnings as errors. Two existing Qt mouse-position API deprecation warnings
  remain. The engineer independently passed 691 tests in 40.02 s.
- Independent lifecycle stress: **20 fresh processes, 100 tests**, all clean
  exits, covering import cancel, late cancel, close during import, result-before-
  thread-stop, and close-before-startup.
- Ruff (`src tests scripts`), `compileall`, `pip check`, macOS build script
  `bash -n`, and `git diff --check` passed.
- Official ARM64 actionlint v1.7.12, archive SHA-256
  `aba9ced2dee8d27fecca3dc7feb1a7f9a52caefa1eb46f3271ea66b6e0e6953f`,
  validated all workflows. Five action pins were checked against their upstream
  repositories. Hosted workflows and installers were not executed.
- Regression tests reproduced the newly discovered data-loss, undo, tutorial,
  schema-warning and caption-representation defects before their corrections.
  Independent review approved the final gesture, packaging and audio import paths.
- MainWindow fixtures delete/drain Qt objects before settings restore; session
  teardown retains settings isolation. NeuroEdit-owned native settings and the
  original autosave hash match the private pre-work snapshot. OS-global fallback
  preference timestamps are excluded; no restoration/guessing of user settings.

To repeat with the project's pinned development environment, from `desktop/`:

```sh
QT_QPA_PLATFORM=offscreen QT_MEDIA_BACKEND=ffmpeg PYTHONPATH=src \
  python -m pytest tests/ -q -o faulthandler_timeout=120 \
    -W error::pytest.PytestUnraisableExceptionWarning \
    -W error::pytest.PytestUnhandledThreadExceptionWarning
python -m ruff check src tests scripts
```

The observed run used a task-local Python 3.13 runtime with the existing release
constraints. The intentional iCloud `.venv` was not relocated. FFmpeg resolution
uses the validated bundled binary before PATH candidates.

## Lifecycle investigation

An initial 689-test run passed in 38.66 s; a strict repeat then crashed natively
in Qt event processing. The exact native cause was not conclusively attributed.
Investigation independently reproduced early release of SAM worker/thread refs;
result callbacks now retain them until thread completion and native join.
Startup callbacks use parented timers stopped on close. Import cancellation uses
GUI-owned state and thread completion joins before releasing references. Added
deterministic regressions plus repeated full/stress runs passed as recorded above.
This is evidence for the repaired paths, not proof of universal native Qt stability.

## Ticket evidence

| Tickets | Implemented behavior | Regression evidence |
| --- | --- | --- |
| NE-012 | Source-space overlay composition matches fitted preview geometry | `test_export_overlay_placement.py` |
| NE-013 | Cancellable cross-volume atomic publish; one job never deletes another job's partial | `test_export_output_and_ffmpeg.py` |
| NE-014 | View-only timeline changes preserve review and undo/redo | `test_main_window_headless.py`, `test_timeline_editing.py` |
| NE-015 | Caption export/review gate includes speaker labels and literal markup | `test_caption_phi_gate.py` |
| NE-016 | One undo per gesture; separate controls and external input commit prior work first | `test_undo_coalescing.py` |
| NE-017 | Unreadable autosave survives restore, autosave, New, close, and later mask cleanup | `test_project_store_recovery.py`, `test_main_window_headless.py` |
| NE-018 | Scratch-case replacement requires confirmation, including notes-only and on-disk cases | `test_main_window_headless.py` |
| NE-019 | No-op media duration events preserve clean state and redo | `test_duration_events.py` |
| NE-020 | Take Still gap shifts captions and tracked masks consistently | `test_take_still_gap.py` |
| NE-021 | Close confirmation while export/SAM work is active | `test_main_window_headless.py` |
| NE-022 | Shape/redaction drags clamp to the picture edge | `test_canvas_drag_clamp.py` |
| NE-023 | Working bundled FFmpeg preferred; invalid candidates rejected | `test_export_output_and_ffmpeg.py`, `test_export_timing.py` |
| NE-024 | Complete weight detection, truthful deletion, model unload and partial-output cleanup | `test_sam_lifecycle.py` (stubs) |
| NE-025 | Read-only tour for existing work; pristine sample stays hands-on; switching projects ends tour | `test_tutorial_project_safety.py`, `test_main_window_headless.py` |
| NE-026 | Sequential decode with frame equivalence; measured decision against new static composition cache | `test_export_frame_selection.py`, `test_export_timing.py`, benchmark scripts/report |
| NE-027 | Shared quality recipe, informational Windows tests, pinned tools/actions, numeric version source, teardown | `test_version_consistency.py`, `test_capture_baseline.py`, actionlint |
| NE-028 | No-op rename/marker edits, label deletion, scrub/snap/theme and lane-layout polish | `test_timeline_polish.py` |
| NE-029 | Hardware-quality disclosure, even dimensions, padding, stream parsing, stderr drainage, cue/report robustness | `test_export_robustness.py` |
| NE-030 | Save As keeps history/frame; unique take names; asynchronous audio import; cached file checks; schema/errors/docs | `test_small_lifecycle_items.py`, `test_audio_import.py`, recording/lifecycle suites |
| NE-031 | Consistent upright still decoding and redaction placement across EXIF orientations | `test_still_orientation.py` |

## Measured performance and limits

The [decode benchmark](export-decode-benchmark.md) used 180 synthetic 1080p
long-GOP frames: 6.258 s seek-per-frame versus 1.200 s sequential; all rendered
RGB SHA-256 hashes matched. It compares pre-encode pixels, not encoded file bytes.
Static-image/slide profiling did not justify another invalidation-sensitive cache;
static composition memoization remains deliberately unimplemented.

Audio import cancellation discards results and prevents retry queuing until the
running probe finishes. It does not interrupt an executing file/FFmpeg probe;
its Python worker can finish after the window closes and can delay process exit.
Playback/view changes do not reject an import; document changes do. Insertion
uses the playhead position captured at the start of import.

Not verified: actual SAM/PyTorch/GPU inference, physical microphone/listening or
latency, real operative recordings, native Windows UI/scaling, hosted Windows
quality, packaged/frozen app launch, or newly built installers. Existing source
transcript cues may intentionally overlap; normalization prevents minimum padding
from creating new overlap with a later cue. Export filenames still derive from
project names. The report warns about case notes and omits the specified free-text
fields. This work does not constitute a complete security or clinical audit.

## Addendum, later on 2026-11-16 (Claude follow-up)

- Three further review findings fixed with 5 new tests: typed spinbox values are applied
  before save/export/undo/close; a label edit after review was re-confirmed resets review
  again; the unhandled-error notice is shown on the GUI thread.
- `tests/test_audio_import.py` now deletes each `AudioPanel` deterministically. Before this,
  the full suite crashed intermittently (bus error or segmentation fault during garbage
  collection in `test_real_audio_import`) on the iCloud-hosted environment: 3 of 4 full runs.
- Final: **696 passed** three times in a row (about 41 s each), clean exit each time, Ruff and
  `git diff --check` clean, NeuroEdit preferences and the autosave hash unchanged.
