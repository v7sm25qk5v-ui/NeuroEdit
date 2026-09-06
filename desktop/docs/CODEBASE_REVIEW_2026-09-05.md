# Codebase review — 2026-09-05

## Scope and method

Reviewed the active native desktop application using three focused sub-agent
reviews: persistence/lifecycle, rendering/export efficiency, and editing/SAM.
The main agent reviewed the patches, challenged edge cases, completed integration,
and ran the verification gates. The superseded browser prototype and existing
untracked `desktop/qa/` artifacts were outside this pass.

The baseline suite passed all 197 tests. Changes address reproduced defects;
there are no new dependencies, project-format fields, or release-version changes.

## Findings fixed

| Area | Reproduced failure | Change and evidence |
| --- | --- | --- |
| Saved-mask recovery | New → Close could delete masks referenced by the prior autosave's still-current `project.json`. | Cleanup now includes persisted references alongside live state and undo/redo. Tests retain saved masks, remove genuine orphans, and skip deletion on invalid saved JSON. |
| Failed close | A save error canceled closing but left autosave and SAM heartbeat timers stopped. | Stop timers only after the dirty save succeeds; regression checks the continuing session retains both timers. |
| Save As | Destination creation errors escaped the error dialog; copying managed assets onto themselves raised `SameFileError`. | Create the destination inside the existing failure handler and skip same-file copies, including symlink/hardlink aliases. Current state remains intact on failure. |
| Export cancellation | Cancel was queued behind the busy worker's export operation. | Deliver the flag-only cancellation method directly. A real Qt worker-thread regression proves cancellation reaches an in-progress export. |
| Export timing and excess work | Twenty 0.11-second clips produced 80 frames instead of 66 at 30 fps. | Use one output-frame clock across segment boundaries. Real all-rendered and mixed video/image exports now produce 66 frames: 14 unnecessary frames removed, without claiming a wall-clock speedup. |
| Encoder lifecycle | A decoder/painter exception left FFmpeg alive with open pipes. | Reap the child and close pipes on success, cancellation, and failure. Real-process tests preserve the original exception. |
| SAM source/timeline mapping | A clip starting at timeline 10 s, trimmed from source 4 s, sampled source 12 s at playhead 12 s instead of source 6 s. Re-track could use an unrelated selected clip. | Resolve the clip at the seed/annotation time, translate requests to source time and results back to timeline time, and bound propagation to the clip window. Reject seeds in gaps/full-frame slides. Preserve short windows and precise SAM1 seed timestamps. |
| Ripple synchronization | Moving narration/masks from 10 s to 8 s left captions at 10 s and tracked samples at 10/11 s. | Linked captions follow their audio track, independent captions follow the edit, and mask samples follow the annotation's actual shift. Tests cover both directions, clamping at zero, and captions belonging to an unmoved track. |
| Startup imports | Importing `MainWindow` eagerly loaded the exporter despite the documented deferred-import boundary. | Make its type-only workflow import conditional on `TYPE_CHECKING`; a fresh-process test verifies export code remains unloaded until needed. |
| Test isolation | Native preference changes could survive a crashing test process. | Session-wide test configuration redirects NeuroEdit QSettings to a temporary INI file. Explicit per-file settings tests keep their own paths. |

## Main-agent adversarial checks

- Real exported video transitions from fast encoding into a fractional-time
  redaction and back. The decoded output contains exactly ten frames; the two
  covered frames are black and their neighbors remain visible.
- Rendered frame timestamps stay on the global frame clock through fractional
  cuts. Existing redaction tests remain part of the full gate.
- A VFR seek can return the frame already visible before the requested seed
  timestamp. Added a failing regression against the initial SAM patch and kept
  that first mask at the requested timeline start instead of discarding it.
- SAM completion uses the captured job offset/window even when the playhead
  changes. Empty bounded results replace a stale success status with an error.
- Reviewed direct cancellation for cross-thread safety: `cancel()` only sets a
  Python flag and performs no Qt/UI work.
- Saved-mask cleanup reads persisted references before deleting anything. A
  failed JSON read aborts cleanup through the existing close-time exception guard.
- The first full run exposed deferred widget destruction in the new cancellation
  test. Explicit Qt teardown fixed the crash; the cancellation/main-window
  sequence then passed all 37 tests. Native settings isolation was added after
  the interrupted fixture left an autosave preference pointing at a test folder.

## Verification

Final gate: **228 tests passed in 69.36 seconds**, `ruff check src tests scripts`,
`python -m compileall -q src`, and `git diff --check`. New coverage is in
`test_export_timing.py`, `test_export_workflow.py`,
`test_project_lifecycle_review.py`, `test_sam_workflow.py`, and
`test_timeline_editing.py`.

Real FFmpeg encoding and offscreen Qt behavior were exercised. SAM inference was
stubbed; no PyTorch model-download or hardware-inference validation was performed.
Packaged Windows/macOS smoke tests and sustained large-project performance
measurements remain separate work. No commit, push, tag, or release was requested
or performed.

## Follow-ups

- **SAM results during document edits (fixed 2026-09-06):** job completion now
  rejects same-project content edits as well as replacement project objects.
  Segmentation and propagation capture a document-content hash at start, ignore
  transient UI state such as playhead movement, and discard/unlink stale masks
  if the timeline changes before completion.
- **Paused preview after undo (candidate, not reproduced):** history restore only
  reloads media when the active source path changes. A same-source trim undo may
  leave the displayed source frame stale. Reproduce with actual paused media
  before changing player synchronization.
- **Performance measurement:** retain diagnostics-based measurement of large
  projects, external-drive probing, undo serialization, and optional SAM memory
  usage. The restored lazy import boundary is verified structurally; this pass
  does not establish a cold-start latency improvement.
