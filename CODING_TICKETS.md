# NeuroEdit coding tickets

Date: 2026-11-10. Canonical local implementation queue for the seven bounded
findings from [the November 7 review](desktop/docs/review-2026-11-07/REVIEW.md)
and confirmed follow-up defects.
Baseline checkout: `81a405f`. Preserve existing review evidence and `desktop/qa/`.
The original seven-ticket batch was local-only. The user subsequently authorized
NE-009/008 fixes and a GitHub push/tag/release; the coordinator owns those writes.
No external issue tracker was selected.

Sol owns planning and senior code review; Terra engineers own implementation
and focused regression checks. The coordinating agent owns `HANDOFF.md`, the
baseline/final full suite, integration, and final reporting. Completion requires
implementation, focused evidence, senior review, and passing integration checks.
Status **in progress** is not approval. Status progression is **Ready** →
**In progress** → **Implementation ready** (author reports code and focused
checks) → **Review approved** (Sol inspected the actual change and evidence) →
**Verified** (coordinator integration checks passed). Rejected review returns
an item to **In progress**. Author reports alone never establish completion.
Update this file as each item is verified. Where native hardware/platform
checks cannot run here, record those manual follow-ups explicitly; software
tests and the synthetic encoded fixture must still pass before code completion.

| Ticket | Priority | Assignee | Status | Dependencies |
|---|---|---|---|---|
| NE-001 Readable import/export controls | P1 | Terra media/UI | Verified (software) | Native scaling follow-up |
| NE-002 Timeline audition of added audio | P1 | Terra audio | Verified (software) | Physical audio/latency follow-up |
| NE-003 In-place missing-media relink | P1 | Terra media | Verified (software) | None |
| NE-004 Nonblocking video metadata import | P1 | Terra media | Verified (software) | Representative media/performance follow-up |
| NE-005 Reject failed audio probes | P1 | Terra audio | Verified (software) | None |
| NE-006 Truthful single-frame SAM cancellation | P2 | Terra audio/SAM | Verified (software) | Real inference follow-up |
| NE-007 Reliable isolated screenshot capture | P1 | Terra audio/QA | Verified (software) | Autosave restored; other original preference values unknown |
| NE-008 Preserve narration recording start position | P1 | Terra audio | Verified (software) | Physical microphone follow-up |
| NE-009 Finalize narration before closing/saving | P1 | Terra audio | Verified (software) | Physical microphone follow-up |

## NE-001 — Readable import and export controls

**Problem and evidence.** At 1440×900, Media Explorer import buttons are 226 px
wide while their text requires 248/301 px before padding. The export privacy
checkbox has 379 px of text in a 380 px widget before its indicator/spacing.
See review screenshots `01_empty_editor.png` and `09_export.png` and
`capture-evidence.json`. Source: `ui/editor_panels.py:113` and `ui/dialogs.py:602`.

**Reproduce.** Open the real editor and export settings in the light theme;
inspect import video/folder controls and the source-audio PHI explanation at
1440×900 and the application's computed minimum size.

**Scope.** Shorten action titles while keeping visible by-reference guidance;
make the export privacy explanation readable without changing its safe default
or saved setting semantics. Avoid layout redesign.

**Acceptance.** Settled captures at normal scale and supported minimum dimensions
show complete labels and explanation. Geometry verifies text plus control chrome
fits, or explanation is explicitly word-wrapped. Export privacy default remains
checked and narration remains included. Native Windows scaling is a documented
manual follow-up, not a claimed result of offscreen testing.

## NE-002 — Audition added narration/music on the timeline

**Problem and evidence.** `ui/main_window.py:235` connects only source video
audio to `QMediaPlayer`; `ui/audio_panel.py` adds tracks and `exporter.py:1040`
mixes them at export. There is no added-track timeline transport. Import a WAV
with a distinct onset, place it after timeline zero, and play/scrub: only export
includes it.

**Scope.** Add minimal timeline-controlled playback for active tracks. The
existing monotonic clock remains authoritative. Match export track start,
duration, and normal UI volume rules; source mute stays independent from added
narration. Handle deferred media loading and seeks without playing from source
zero. Approved implementation limit: Qt's audio output caps preview gain at 1.0;
the existing export path can amplify persisted tracks above 1.0 up to 2.0. Normal
UI tracks stay within 0..1. Document this mismatch rather than change exporter
behavior or promise full gain parity for externally edited project files.

**Acceptance.** Deterministic fake-player tests cover seek-to-track offset,
pause/resume, onset/end, overlapping tracks, volume changes including zero,
missing assets, still/full-slide/gap intervals, and audio-only tails. Undo/redo,
project replacement, track removal/relink, and close stop obsolete playback.
No thread/player survives window teardown. Synthetic WAV/tone fixture checks
transport mapping against exporter source rules; record precisely whether an
actual exported tone was measured. Physical listening and hardware latency
remain unverified unless separately performed. No ASR or new audio model.

## NE-003 — Relink missing media without rebuilding edits

**Problem and evidence.** `ui/main_window.py:1925` warns users to restore or
re-import unavailable media; `_import_media_files` adds a new clip. There is no
repair-in-place action. Reproduce with a trimmed/split synthetic clip: save,
move the source, reopen; re-import cannot restore the existing references.

**Scope.** Explicitly choose a replacement for an existing reference. Preserve
identity and edit geometry; never silently match filenames. Support missing
video/image and audio references with bounded, clear controls. Decide and expose
whether a shared split-source relink repairs all same-path references or only
the selected one. Validate readability, type, finite positive metadata, and every
retained source bound before changing the document. Do not silently shorten trims.

**Acceptance.** Move/relink a synthetic trimmed and split source; IDs, order,
trims, source bounds, annotations/redactions, slides, markers, and unrelated
assets survive. Rejected/cancelled choices change nothing. Successful repair is
one undo step, works through undo/redo and save/reopen, and export uses the
replacement. Test image/audio recovery, shorter/unreadable/wrong-type sources,
shared references, and path replacement while selected. Invalidate affected
media/thumbnails/preview caches and PHI/export approvals; the old approval cannot
authorize changed content. Audio preview ownership must refresh after repair.

## NE-004 — Probe video imports without blocking the UI

**Problem and evidence.** `_import_media_files` directly invokes `_add_video_clip`
and `probe_video` on the UI thread (`ui/main_window.py:1637–1700`). The controlled
250 ms injected probe recorded 255.43 ms elapsed and zero 10 ms heartbeat
callbacks before the method returned (`probe-evidence.json`). Event processing
between files does not make an individual probe asynchronous.

**Scope.** Probe metadata on a worker; perform Qt widget and document mutations
on the GUI thread. Preserve selection order, mixed image/video behavior, one
final selected preview, and one import/history transaction. Provide explicit
failure/cancel handling without a generalized background-job framework.

**Acceptance.** A blocked fake probe leaves a GUI heartbeat running. Successful
results commit in input order with one undo step; partial failures have clear
feedback and no guessed unreadable video. Cancellation before commit changes
nothing. Switching/loading projects, relevant intervening edits, and closing
must reject stale results and safely release worker/thread objects. No
`QThread: Destroyed while thread is still running` or post-close mutation.
Exercise a real synthetic video import; external-drive and representative 4K
timing claims require actual measurements.

## NE-005 — Reject audio with unknown duration

**Problem and evidence.** `AudioPanel._probe_audio_duration` returns `5.0` when
WAV and ffmpeg probing fail (`ui/audio_panel.py:415`); a controlled failed probe
returned exactly five seconds. Import corrupt audio and a plausible-looking
five-second track is appended, causing misleading editing and export bounds.

**Scope.** Represent probe failure explicitly, show a useful unreadable-audio
message, and append no track. Validate finite positive duration. Apply the
same rule to recording finalization if it uses the duration helper.

**Acceptance.** Failed/timeout/corrupt/empty probes and nonfinite or nonpositive
durations add no track, leave history/duration unchanged, and show an actionable
message. Valid WAV and compressed-audio duration imports remain supported;
focused synthetic audio/export tests confirm no five-second fallback. Preserve
the existing bundled ffmpeg lookup and avoid external dependencies.

## NE-006 — Discard cancelled single-frame SAM results

**Problem and evidence.** `SamSegmentWorker.cancel()` sets `_cancelled` but
`run()` never reads it (`ui/sam_workers.py:65`). The existing fake inference
probe requested cancellation during execution and still received success.
`_on_segment_finished` checks project context but not cancelled job status.

**Scope.** Check cancellation before and after inference, discard only files
created by that job through the GUI completion owner, signal cancelled completion, and
clear busy state. Explain that an active inference may need to finish; do not
promise interruption of GPU kernels. Preserve uncancelled/stale-context paths.

**Acceptance.** Tests cancel before start and during blocked fake inference:
no annotation, success history, error dialog, or orphan job output remains;
pre-existing unrelated masks survive. Busy/thread state clears after completion.
Uncancelled inference still attaches its result. Check queued-result cancellation
and project replacement lifecycle. Actual SAM weights/inference are out of scope.

## NE-007 — Capture isolated, correctly labeled UI states

**Problem and evidence.** `scripts/capture_baseline_screenshots.py` switches
panels, runs `processEvents()` once, and immediately grabs without asserting the
rendered state. It then sets the SAM explainer without selecting SAM after Audio,
so the file labeled `panel_sam_missing_backend` can show Audio. The reviewed
baseline states were separately recaptured. The script also temporarily writes
four keys in real native `QSettings`, which fails full preference isolation and
can leave user settings changed after abnormal termination.

**Scope.** Isolate all settings/storage before constructing the application;
wait for the intended panel/dialog state to settle; select SAM explicitly;
restore any monkeypatches and finish worker cleanup even on capture failure.
Use a deterministic state check or bounded event-loop settling, not a blind
single event pump. Report failed captures as failures.

**Acceptance.** Run the script twice with synthetic data; inspect all outputs
and verify each panel/dialog matches its filename, especially Audio versus SAM
unavailable. Verify every output is nonempty, failures surface, and the process
exits cleanly. Demonstrate native settings bytes/values are unchanged, including
in an induced failure path; temporary settings/storage are cleaned up. Include
state assertions/evidence rather than relying on filename existence alone.

## NE-008 — Preserve the timeline position where recording started

**Confirmed follow-up, 2026-11-10.** `AudioPanel._start_recording` captures the
project and wall-clock start, but not the timeline start position. Finalization
uses `self.project.current_time` when the recorder stops. A controlled probe of
the actual controller methods pressed Record at 2 s, moved the playhead to 7 s,
and delivered StoppedState: the inserted track started at 7 s instead of 2 s.
Device/recorder operations were mocked; no microphone or native settings were used.

**Scope.** Capture the timeline insertion point with the recording context and
use it when the completed recording is attached. Preserve current project-change
guards, validated file duration, and the existing handling of failed recordings.

**Acceptance.** Record at 2 s and advance/seek to 7 s before Stop: the completed
track starts at 2 s and retains its measured duration. Cover unchanged playhead,
delayed completion, failed recording, and project replacement. Verify both
preview and export use that retained start. No automatic transcription or new
serialized project field is required.

## NE-009 — Finalize pending narration before closing and saving

**Confirmed follow-up, 2026-11-10.** `MainWindow.closeEvent` saves before stopping
the audio recorder or waiting for its delayed StoppedState callback. Tracks are
attached only by `AudioPanel._recording_state_changed`. A controlled probe of
these actual methods saved while a recording was pending, then delivered the
completion: memory contained one narration track but saved `project.json`
contained zero. The base widget close and recorder/device were mocked; no
physical recording or user settings were involved. This reproduces a lost
project reference, not proof that the underlying audio file is deleted.

**Scope.** Define a safe close path for active/finalizing recording. Complete
recording attachment before the final save, or let the user cancel closing.
Keep the UI responsive and preserve the existing failed-save close behavior.
Do not silently discard or delete a recording.

Implementation decision: refuse the close request while recording or its
completion is pending, with an actionable explanation to stop and wait before
retrying. Keep the window and timers/workers open; do not introduce an automatic
close retry or nested wait loop. This satisfies the window-remains-open acceptance
path and avoids reentrant save/finalization races.

**Acceptance.** Close while recording and immediately after Stop with delayed
completion: either the window remains open or the validated track is included
in the saved project and survives reopen. Cover failed duration probing,
recording errors, cancellation of closing, save failure, and repeated close
requests without duplicate tracks or saves. A real microphone smoke remains
necessary after deterministic controller coverage.

## Shared validation and scope limits

Release integration checkpoint, 2026-11-10: after NE-008/009 implementation and
Sol review, the coordinator passed **341 tests in 148.64 s**, no skips and clean
exit, plus full Ruff, compileall, version-label checks, and diff validation.
All nine coding tickets are software verified. Native preferences matched the
private pre-validation snapshot, including the approved autosave folder.
Tag/installer/publication results are recorded separately in `HANDOFF.md`.

Follow-up review checkpoint, 2026-11-10: the user authorized NE-009 and NE-008
before the next release. Terra audio reproduced three expected pre-fix failures
(moved recording anchor, active-close save, finalizing-close save), then fixed
them. Sol inspected the actual source and tests and independently ran recording,
project lifecycle, and audio preview suites: **31 passed in 0.45 s**, clean exit.
Both tickets are **Review approved**, pending the coordinator's new full-suite
and release checks. Recording still anchors at Record time after playhead moves;
close is refused before saving while recording/finalization is pending, and the
user retries after completion. Error-first/state-first errors, synchronous stop,
immediate start error, delayed completion, repeated/reentrant close, failed
probe/save, stale project, save/reopen, and preview/export anchor are covered
without a microphone. Tests use isolated application settings and do not alter
the user-approved autosave location. Their initial controlled evidence remains in
`desktop/docs/engineering-2026-11-10/follow-up-evidence.json`.

Final integration checkpoint, 2026-11-10: the coordinator reports **327 passed
in 139.58 s**, no skips and clean exit, with full Ruff, compileall, and diff check
passing. Combined with senior review and the scoped evidence below, all seven
tickets are **Verified (software)**. NE-004's real encoded import gate passed
with the unchanged production receiver: one worker probe, GUI finalization,
heartbeat, one committed clip, and clean thread/window shutdown. See
`desktop/docs/engineering-2026-11-10/real-import-evidence.json`.
Native/manual limits remain. The user-approved autosave location has been
restored; other original preference values from the earlier incident remain
unknown. Earlier checkpoints
below retain the evidence sequence and are superseded by this final suite result.

2026-11-10 review checkpoint: Sol inspected NE-005's duration/import/recording
changes and regression cases and independently ran `tests/test_audio_preview.py`:
**9 passed in 0.21 s**, clean exit. This includes generated WAV/MP3 duration,
timeout/video-only metadata rejection, nonfinite/nonpositive results, and no
track after failed import/recording probe. NE-005 awaits final integration before
**Verified**. After inspecting NE-002's main-window hooks and requiring fixes
for small seeks and immediate project-activation shutdown, Sol independently ran
`test_audio_preview.py` plus `test_undo_history.py`: **35 passed in 0.26 s**, clean
exit. NE-002 is review approved pending the coordinator's synthetic encoded
preview/export smoke and final integration.

NE-006 review checkpoint: Sol inspected worker cancellation checks and the GUI
job-context cancellation guard, including cancellation after result emission
before delivery. Independent `tests/test_sam_workflow.py`: **27 passed in
0.39 s**, clean exit. Only the returned job mask is discarded; unrelated masks
are retained. Actual SAM inference remains untested.

NE-003 review checkpoint: per-reference relink is explicit (a split sibling is
not silently repaired). Sol required preservation of a legacy/default source
extent on longer replacement and finite audio validation; both are fixed.
Independent headless `-k relink`: **3 passed, 45 deselected in 0.85 s**, clean
exit, covering source bounds/sibling isolation, privacy invalidation, undo/redo,
save/reopen, missing audio, and slide image recovery. Final real-media
relink/export smoke remains the coordinator's verification gate.

NE-004 review checkpoint: Sol caught and required removal of the final selected
clip's duplicate GUI-thread metadata probe. Worker stat signatures now seed the
existing media cache only while the file is unchanged. Independent headless
`-k import`: **12 passed, 38 deselected in 9.76 s**, clean exit, including real
preview loading with no GUI-thread probe, heartbeat, partial failure/order,
single undo, stale state, cancellation before delivery, and close during import.
Those tests use controlled metadata. A subsequent real encoded import smoke did
not finish within the initial two-second harness allowance; assertion-driven
teardown aborted with its thread still active. This is not a passing real import
check. A later bounded QEventLoop run resolved this gate: the unchanged production
receiver committed the real 2 s H.264 clip, probing once on a worker thread and
loading preview on the GUI thread. Import started at 0.178 s, worker completed
at 0.282 s, thread finished at 0.285 s, and window closed cleanly at 0.286 s;
the GUI timer fired during probing. Repeated QTest polling had stalled worker
execution in the failed harness attempt. No production change was required.

NE-001/007 review checkpoint: Sol inspected all 19 corrected capture images,
including each labeled panel/dialog, scrolled minimum-size import buttons, and
wrapped export privacy explanation. Independent capture success/failure and
export-dialog tests: **8 passed in 2.96 s**, clean exit. Corrected repeated runs
use verified temporary INI settings and preserve native settings snapshots;
this statement applies only to corrected runs. Evidence is retained in
`desktop/docs/engineering-2026-11-10/screenshots/` and `capture-evidence.json`.

**Preference incident and autosave recovery.** An early harness revision used
`setDefaultFormat`/`setPath`, which did not redirect the explicit native macOS
constructor. It wrote `storage/projectRoot`, `storage/promptShown`,
`tutorial/seen`, and `recentProjects` without recording the original values.
The exact original values and any persistent impact are unknown. During the
investigation, native preferences included an older pytest autosave path and nonempty
recents; their origin cannot be established from this task's evidence. The
coordinator informed the user and requested their intended autosave location.
No guessed restoration was made. Corrected isolation tests do not establish
that the earlier validation preserved preferences or resolve this incident.

On 2026-11-10, the user approved restoring the existing
`~/Documents/NeuroEdit/Autosave` folder. Only
`storage/projectRoot` was changed; fresh-process app resolution confirms the
folder, other preferences compared unchanged, and `project.json` retained its
hash. The autosave-location follow-up is resolved. Other original preference
values remain unknown and were left unchanged.

Focused tests run in the isolated runtime from `desktop/` with
`PATH=/private/tmp/neuroedit-security-bin:$PATH`, `QT_QPA_PLATFORM=offscreen`,
`PYTHONPATH=src`, and `/private/tmp/neuroedit-security-20261106/bin/python`.
The coordinator runs final `pytest tests/ -q --disable-warnings
-o faulthandler_timeout=120`, `ruff check src tests scripts`, and
`git diff --check`; require a clean process exit and report skips accurately.

Senior review is recorded in
`desktop/docs/engineering-2026-11-10/REVIEW.md`, with file/line evidence and any
unresolved risk. Tests establish software behavior, not clinical validity,
complete de-identification, native platform/hardware behavior, or clinician
benefit. ASR, cloud processing, speculative performance/cache rewrites, code
signing, and manual hardware/platform certification are excluded.

---

# 2026-11-12 review batch — NE-010 to NE-030

Source: [the November 12 app review](desktop/docs/review-2026-11-12/REVIEW.md) at
baseline `3e00fc0` (v0.5.14-alpha). Four Sonnet reviewers, a Haiku docs/CI
auditor, a Haiku test runner, and a Sonnet verification engineer; the
coordinator read the cited source for every ticket. All tickets are **Ready**
and unassigned. Nothing here has been implemented. The status progression at
the top of this file applies.

Evidence labels: **Reproduced** means a test in
`desktop/docs/review-2026-11-12/repros/` asserts the desired behaviour and fails
on `3e00fc0`; move that test into `desktop/tests/` as the regression test when
the ticket is fixed. **Source confirmed** means the path was read end to end
but not executed. **Unmeasured** means the cost is plausible but not profiled.

| Ticket | Priority | Evidence | Status |
|---|---|---|---|
| NE-010 Redactions keep covering their footage across timeline edits | P1 | Reproduced | Review approved |
| NE-011 Head-trim ripple independent of drag path | P1 | Reproduced | Review approved |
| NE-012 Export paints overlays in source-frame space | P1 | Reproduced | Ready |
| NE-013 Export succeeds when output is on another volume | P1 | Source confirmed | Ready |
| NE-014 View-only timeline actions leave PHI review and undo alone | P1 | Reproduced | Ready |
| NE-015 Caption text passes a PHI gate before leaving the app | P2 | Source confirmed | Ready |
| NE-016 One undo step per slider drag or text edit | P2 | Reproduced | Ready |
| NE-017 Preserve an unreadable autosave | P2 | Reproduced | Ready |
| NE-018 New Project does not overwrite the scratch case silently | P2 | Reproduced | Ready |
| NE-019 Media duration events do not dirty an unchanged project | P2 | Reproduced | Ready |
| NE-020 Take Still shifts captions and tracked-mask frames | P2 | Reproduced | Ready |
| NE-021 Confirm before closing during export or SAM | P2 | Source confirmed | Ready |
| NE-022 Shape drags released outside the frame clamp to the edge | P2 | Reproduced | Ready |
| NE-023 Prefer and validate the bundled ffmpeg | P2 | Observed in test run | Ready |
| NE-024 SAM weight and model lifecycle | P2 | Source confirmed | Ready |
| NE-025 Tutorial runs without changing the user's project | P2 | Source confirmed | Ready |
| NE-026 Export render-loop cost | P2 | Unmeasured | Ready (measure first) |
| NE-027 Release and CI hardening | P3 | Verified by reading | Ready |
| NE-028 Timeline polish | P3 | Source confirmed | Ready |
| NE-029 Export and caption robustness | P3 | Source confirmed | Ready |
| NE-030 Small lifecycle and documentation items | P3 | Source confirmed | Ready |

Suggested order: NE-010 and NE-011 together (same function), then NE-012,
NE-014, NE-013. NE-016, NE-019, and NE-014 share the "what counts as a document
edit" question and are cheapest to settle in one design pass.

## NE-010 — Redactions keep covering their footage across timeline edits

**Status 2026-11-12: Review approved (uncommitted; not yet checked in the running app).** Fixed in `desktop/src/neuroedit_desktop/models.py` and `ui/editor_panels.py`. Regression tests: `desktop/tests/test_ripple_overlays.py` (40). Full suite on the finished change: 380 passed, 1 failed (the known `test_capture_baseline` 30 s timeout, NE-027). An independent Sonnet review ran randomized property tests (28,000 single edits, 10,000 edit chains, 14,000 mouse drags) and found no case where a redaction stops covering footage it covered; its two actionable findings are fixed (see below).
- Rules implemented: a redaction strictly after the edit point follows its footage; one that touches or spans a point where footage is revealed keeps its start and grows; when a range is removed, start and end are mapped through the removal; a finite window never becomes 0 (unlimited); a redaction only on removed footage is left in place.
- Reorder: `ProjectState.move_redactions_with_clips` moves each redaction to the smallest single window holding every piece it covered. A redaction spanning two clips that are reordered apart widens over what lies between (accepted trade-off; splitting it in two would be exact).
- Deviation from the scope text: unlimited redactions are not "never moved". They move earlier when footage before them is removed (otherwise footage is exposed) and stay put when footage is revealed at or before their start.
- Not done: no export preflight warning; rendered export frames were not compared with preview (both read the same `is_visible_at`).

**Problem and evidence.** `ProjectState.ripple_after` (`models.py:316-358`) shifts
every annotation whose `frame_time >= anchor` and never changes `ann_duration`.
Redactions go through the same branch as ordinary labels.

- Whole-timeline redaction (`frame_time=0, ann_duration=0`, the Redact tool's
  default). Dragging the head handle of a clip at timeline 0 to the left calls
  `ripple_after(0, +delta)` (`ui/editor_panels.py:1227-1232`). The redaction's
  `frame_time` becomes `delta`, so `is_visible_at` is False for the first
  `delta` seconds and the exporter (`exporter.py:999`) leaves them unredacted.
  **Reproduced:** `test_pure.py::test_ne010a_redaction_covers_after_head_extend`
  (`frame_time` 0 → 2.0).
- Finite redaction spanning the edit point. Extending the clip before it pushes
  later footage right while the redaction's end stays put, exposing the last
  `delta` seconds it used to cover. **Reproduced:**
  `test_pure.py::test_ne010b_redaction_covers_after_ripple`.
- Clip delete and drag-reorder (`ui/editor_panels.py:979-985`, `_commit_clip_move`)
  leave a windowed redaction at its old timeline position, now over different
  footage. Reviewer reproduced delete at the model level; reorder is source
  confirmed.

`_insert_timeline_gap` (`ui/main_window.py:1968-1979`) already handles the
redaction case correctly for Take Still; `ripple_after` does not. No test in
`tests/test_timeline_editing.py` involves a redaction.

**Scope.** In `ripple_after`: never move a redaction with `ann_duration == 0`;
when a finite redaction spans the anchor and `delta > 0`, extend its duration by
`delta`. For delete and reorder, either move finite redactions with the footage
they were placed on or, at minimum, keep them over-covering and add an export
preflight warning when a redaction window was affected by an edit. Over-redact
is the safe direction. No new serialized field is required for the first two.

**Acceptance.** Both repro tests pass. New tests cover delete-before and reorder
with a windowed redaction. Preview and export agree. Existing ripple tests for
labels, captions, and masks still pass.

## NE-011 — Head-trim ripple independent of drag path

**Status 2026-11-12: Review approved (uncommitted; not yet checked in the running app).** Fixed in `desktop/src/neuroedit_desktop/models.py` and `ui/editor_panels.py`. Regression tests: `desktop/tests/test_ripple_overlays.py` (40). Full suite on the finished change: 380 passed, 1 failed (the known `test_capture_baseline` 30 s timeout, NE-027). An independent Sonnet review ran randomized property tests (28,000 single edits, 10,000 edit chains, 14,000 mouse drags) and found no case where a redaction stops covering footage it covered; its two actionable findings are fixed (see below).
- Both trim handles snapshot `ProjectState.timeline_positions()` at press and re-apply one ripple from that state on every move (`_rewind_trim_drag`). The tail handle had the same defect and is fixed too.
- Review follow-ups fixed: snap targets are now read from the press-time timeline (with snapping on, the default, the handle used to stick to its previous position); dropping a trim drag on the trash deletes the clip as it was at press.
- Left as is: an item added to the project in the middle of a drag is not in the snapshot (rare).

**Problem and evidence.** `TimelineCanvas._apply_trim_start`
(`ui/editor_panels.py:1210-1232`) runs on every mouse-move. It computes the
ripple anchor from the drag origin but the delta from the previous move, so the
set of items shifted changes as the anchor advances. **Reproduced:**
`test_pure.py::test_ne011_trim_start_path_independent` — a 4 s head trim leaves
a label at 10.0 when applied in one step and at 12.0 when applied in eight
0.5 s steps. Real drags are always stepped, so labels, markers, slides, and
finite redactions inside the trimmed clip end up late relative to their footage.

**Scope.** Snapshot the positions of downstream items at press and recompute
from that snapshot on every move, or apply the ripple once on release against
the origin. Keep the single undo step per drag.

**Acceptance.** The repro test passes. A drag right then back left returns every
item to its starting position. Do this with NE-010; both change the same call.

## NE-012 — Export paints overlays in source-frame space

**Problem and evidence.** The preview paints annotations in the video's native
pixel space (`ui/canvas.py:94-122`, sized from the video item). The exporter
letterboxes the source with `_fitted_source_rect` (`exporter.py:674-678`) but
`_paint_qt` passes that rectangle only to `_paint_redactions`
(`exporter.py:717-726`); `_paint_annotations(painter, time_s, width, height)`
uses the whole output frame, and masks are drawn with
`painter.drawImage(QRectF(0, 0, w, h), mask)` (`exporter.py:834`). Export presets
are 16:9. **Reproduced:**
`test_pure.py::test_ne012_export_annotation_stays_in_source_rect` — a full-frame
rectangle on a square source exported at 2:1 spans x 0..199 instead of 50..150.

For any source that is not the output aspect (4:3 or 5:4 endoscopy towers,
1920×1200 capture, portrait), rectangles, ellipses, arrows, brush strokes, text,
labels, and SAM masks are stretched and offset from the anatomy they mark, while
the preview looked correct. `width_px` and `font_size` are also used unscaled, so
a 4K source exported at 1080p draws lines and labels about twice as heavy as in
the preview. Only `test_redaction_tracks_actual_fitted_source` covers
letterboxing, and only for redactions.

**Scope.** In `_paint_annotations`, translate and scale the painter to
`source_rect` and scale stroke and font by fitted height over native height; draw
masks into `source_rect`. Keep slide and full-frame-still behaviour (output
coordinates) as tested by `test_full_frame_slide_redaction_uses_output_coordinates`.
Take Still shares `_render_frame`, so it inherits the fix.

**Acceptance.** The repro test passes for square, portrait, and wide sources.
A pixel comparison at matching aspect is unchanged. Stroke weight relative to
frame height matches the preview at 720p, 1080p, and 4K output.

## NE-013 — Export succeeds when output is on another volume

**Problem and evidence.** The export renders into `tempfile.TemporaryDirectory`
on the system volume and finishes with `os.replace(tmp_video,
self.settings.output_path)` (`exporter.py:125`). The audio path stages
`muxed.mp4` beside `tmp_video` and also ends in `os.replace`
(`exporter.py:1109`, `:1165`). `os.replace` cannot cross filesystems. Saving to
an external drive, USB stick, or network share therefore fails with
`Invalid cross-device link` after the whole render, and the user sees a raw
errno. The no-audio branch is the default configuration (source audio muted, no
narration). **Source confirmed**; not exercised on a second volume, and no test
covers it.

**Scope.** Write the final file to a `.partial` name in the output directory,
then `os.replace` within that directory. For the no-audio branch, copy the temp
video to the partial name first. Remove the partial file on failure or cancel.

**Acceptance.** A test that makes the first `os.replace` raise `EXDEV` still ends
with a complete output and no leftover partial file. A manual export to an
external volume succeeds. Cancel leaves nothing in the output directory.

## NE-014 — View-only timeline actions leave PHI review and undo alone

**Problem and evidence.** `RichTimelineWidget.project_changed` is wired to
`_mark_review_relevant_project_dirty` (`ui/main_window.py:832`), which calls
`_invalidate_review_attestations` (`:1069-1080`) and pushes history. The signal
is emitted by `_set_zoom` (`ui/editor_panels.py:1572-1575`), by pressing any clip
block (`:770-772`), and by releasing any block, including a plain click
(`:940-944`). **Reproduced:** `test_window.py::test_ne014_zoom_does_not_reset_review`
— after one zoom change `phi_review_confirmed` and `deidentified_confirmed` are
False and the undo stack grew by one.

A clinician who completes the guided PHI review and then zooms or clicks the
timeline has silently un-confirmed it. That teaches people to re-tick the
attestation without re-reviewing. Each zoom tick also serializes and hashes the
whole project and resyncs the player; selecting a non-active clip adds an undo
step with no visible change.

**Scope.** Split the timeline's signal into a view-state signal (zoom, scroll,
selection, active clip) that marks metadata dirty without history or attestation
changes, and a content signal for real edits. Emit the content signal on release
only when the document changed.

**Acceptance.** The repro test passes. Zoom, Fit, click, and select leave the
attestations, the undo stack, and the redo stack untouched. Trim, move, split,
delete, and fade edits still invalidate review and create exactly one undo step.

## NE-015 — Caption text passes a PHI gate before leaving the app

**Problem and evidence.** The export checklist's audio item is driven by
`project_export_includes_audio` (`ui/export_workflow.py:68-77` and the checklist
in `ui/dialogs.py`). With source audio muted (the default) and no narration
track, that is False, so the audio/PHI check is hidden even when Burn captions is
on. Guided review has no transcript stop. `_export_captions`
(`ui/export_workflow.py:108-137`) writes SRT/VTT with no check at all. Transcript
text is typed or imported from OR audio and can contain names or dates; once
burned in it cannot be covered after the fact unless the user knows to redact
the caption area. **Source confirmed.**

**Scope.** Treat non-empty transcript text as reviewable content: show a caption
review item in the checklist when captions are burned in, add a transcript stop
to guided review, and ask for confirmation once in `_export_captions`. No
automatic PHI detection.

**Acceptance.** With source audio muted, no tracks, and Burn captions on, the
checklist shows the caption item and blocks until it is ticked. Sidecar export
asks once per project state. Editing transcript text resets the confirmation.

## NE-016 — One undo step per slider drag or text edit

**Problem and evidence.** `AudioPanel` connects `volume_slider.valueChanged`,
spinbox `valueChanged`, and the transcript `textChanged` signals straight to
handlers that emit `project_changed` (`ui/audio_panel.py:102-104`, `:159-162`,
`:489-501`), which is wired to `_mark_review_relevant_project_dirty`
(`ui/main_window.py:898`). The slide editor does the same for title and body
text and its spinboxes (`ui/editor_panels.py:1823-1830`). **Reproduced:**
`test_window.py::test_ne016_slider_does_not_flood_undo` — 50 slider steps add 49
undo entries. The history cap is 50, so one volume drag or one typed sentence
evicts every earlier edit. Each step also serializes the project, resets review
attestations, and resyncs the player.

**Scope.** Mutate the model live with a history-less dirty mark during the
gesture and push one snapshot on `sliderReleased` / `editingFinished` /
focus-out; set `setKeyboardTracking(False)` on spinboxes. Apply to the audio
panel, slide editor, and labels panel inspectors. The canvas already does this
with `annotation_mutated` and `edit_committed`.

**Acceptance.** The repro test passes. Typing a 30-character slide title and
pressing Undo once restores the previous title. Live preview during the gesture
is unchanged.

## NE-017 — Preserve an unreadable autosave

**Problem and evidence.** At startup `MainWindow.__init__` tries
`ProjectStore.open` on the autosave file and on any exception only shows a
warning (`ui/main_window.py:204-208`). `self.store` still points at the same
path and `self.project` is blank, so the first edit autosaves over the only copy
(`ui/history.py:213-224`, `project_store.py:46`). **Reproduced:**
`test_window.py::test_ne017_unreadable_autosave_preserved`. A truncated file, a
field a newer build wrote differently, or a non-finite number is enough to
trigger the failure; the file may have been recoverable by hand or by a later
build.

**Scope.** On restore failure, rename the file to
`project.json.unreadable-<timestamp>` before continuing, tell the user where it
is, and exclude the project's `masks/`, `audio/`, and `stills/` from orphan
cleanup for that session.

**Acceptance.** The repro test passes. The warning names the preserved file.
Orphan-mask cleanup at close does not delete assets the preserved file may
reference.

## NE-018 — New Project does not overwrite the scratch case silently

**Problem and evidence.** `_confirm_project_replacement` returns True whenever
`dirty` is False (`ui/main_window.py:1105-1106`); autosave clears `dirty` every
two seconds. `_new_project` then creates the new store in the same
`default_project_root()` folder (`:1364-1367`), so the next autosave replaces the
previous case's `project.json`, and close-time cleanup removes its masks as
orphans. **Reproduced:** `test_window.py::test_ne018_new_project_does_not_reuse_scratch`
— no prompt, identical project path. A user who works in the default autosave
folder and has not used Save As loses the case with one menu click.

**Scope.** When the current store is under the default root and the project is
not empty, ask Save As / Discard / Cancel before New Project. Alternatively move
the old scratch project into a dated sibling folder and add it to recents.
Decide which with the owner; the first is smaller.

**Acceptance.** The repro test passes. A named project saved elsewhere still
switches without an extra prompt when clean. Nothing is deleted without an
explicit Discard.

## NE-019 — Media duration events do not dirty an unchanged project

**Problem and evidence.** `_duration_changed` (`ui/main_window.py:2400-2422`)
calls `_mark_dirty()` for every positive `durationChanged`, whether or not any
clip field changed. Qt emits that signal each time a source loads: on project
open, on undo/redo that changes the active source, and at each clip boundary
during playback across files. **Reproduced:**
`test_window.py::test_ne019_duration_event_does_not_dirty`.

Consequences, source confirmed: the project is dirty immediately after open
(contradicting the architecture note in `desktop/CLAUDE.md`) and is rewritten
within two seconds; `_push_history` clears the redo stack before its no-op and
duplicate checks (`ui/history.py:104-123`), so an undo that changes the active
source can drop redo; playback pays a full `refresh()` and serialize at clip
boundaries.

**Scope.** Mark dirty only when `duration`, `trim_*`, or a source limit actually
changed, and without a history entry. In `_push_history`, clear redo only when a
new snapshot is appended.

**Acceptance.** The repro test passes. Open a saved project: title shows no
unsaved marker and the file's mtime does not change. Undo then Redo across a
source change works. A genuinely corrected duration is still saved.

## NE-020 — Take Still shifts captions and tracked-mask frames

**Problem and evidence.** `_insert_timeline_gap` (`ui/main_window.py:1949-1979`)
shifts clips, slides, audio tracks, markers, and annotation start times, but not
`transcript_segments` and not `annotation.mask_frames[*]["time"]`.
`ripple_after` handles both (`models.py:340-358`). **Reproduced:**
`test_window.py::test_ne020_gap_shifts_captions_and_mask_frames`. After a still
is inserted before narration, captions are five seconds early against their
audio in preview and in SRT/VTT; a tracked mask after the playhead freezes on
its last frame because `mask_path_at` sees every frame time as past.

**Scope.** Reuse `ripple_after` for the downstream shift and keep the existing
clip-split, redaction-extend, and label-capping logic specific to the gap.

**Acceptance.** The repro test passes. Existing Take Still tests still pass.
Undo restores captions and mask frame times.

## NE-021 — Confirm before closing during export or SAM

**Problem and evidence.** `_has_active_background_job` guards project switching
(`ui/main_window.py:1082-1104`) but `closeEvent` (`:2635-2670`) does not consult
it; `_shutdown_threads` cancels the export or SAM worker with no prompt. Closing
the window or pressing Cmd+Q during a long export discards it. **Source
confirmed.**

**Scope.** In `closeEvent`, if a result-producing job is running, ask whether to
cancel it and quit; ignore the event on No. Keep the existing save-first order
and the recording guard.

**Acceptance.** With a running export and the prompt answered No, the window
stays open and the worker is not cancelled. Answering Yes behaves as today.

## NE-022 — Shape drags released outside the frame clamp to the edge

**Problem and evidence.** `_scene_to_norm` returns None outside 0..1
(`ui/canvas.py:957-966`; the clamp on the following line is unreachable for
those points). `mouseReleaseEvent` treats None as "drop the shape"
(`:1103-1112`), and `mouseMoveEvent` freezes the preview at the last inside
point (`:1069-1075`). **Reproduced:**
`test_window.py::test_ne022_release_outside_frame_emits_clamped`. Identifiers on
surgical video usually sit in a corner banner, so dragging a redaction to the
edge and overshooting by a few pixels silently creates nothing. The brush tool
already tolerates this.

**Scope.** Once a drag has started, clamp to the frame instead of returning
None, for rect, ellipse, arrow, and redact. Keep rejecting a press that starts
outside the frame.

**Acceptance.** The repro test passes. The preview follows the pointer along the
frame edge during an overshoot.

## NE-023 — Prefer and validate the bundled ffmpeg

**Problem and evidence.** `ProjectExporter._find_ffmpeg` returns
`shutil.which("ffmpeg")` first and falls back to the pinned `imageio-ffmpeg`
binary only when nothing is on `PATH` (`exporter.py:165-176`). It never checks
that the binary runs. `ui/audio_panel.py:471` uses the bundled binary directly,
so the two paths disagree. **Observed in this review's test run:** this Mac has
an x86_64 Homebrew ffmpeg at `/usr/local/bin` and no Rosetta; 12 export tests
failed with `Bad CPU type in executable` and passed once the bundled arm64
binary was first on `PATH`. A source-run export on this machine fails the same
way. On Windows, GUI apps inherit the user `PATH`, so an old or differently
built ffmpeg (no libx264, different VideoToolbox/encoder set) silently replaces
the tested one, and any directory on `PATH` can substitute the binary that
processes patient video.

**Scope.** Resolve ffmpeg once, shared by exporter and audio panel: bundled
binary first, `PATH` second; verify with a short `-version` call and skip a
candidate that does not execute. Report the chosen path in Performance
Diagnostics (path of the tool only, no media paths).

**Acceptance.** With a non-executable `ffmpeg` first on `PATH`, export and audio
probing use the bundled binary. With no bundled binary, a working `PATH` ffmpeg
is used. The full suite passes on this Mac without adjusting `PATH`.

## NE-024 — SAM weight and model lifecycle

**Problem and evidence.** Source confirmed; torch is not installed here, so none
of this was executed.

- `is_weights_cached` is true as soon as `snapshots/` has any entry
  (`sam_backend.py:68-70`). An interrupted download leaves config files there,
  so the next launch reports ready and the first Segment click resumes a
  multi-gigabyte download inside the segment worker with only a "Running
  segmentation" status. That Hugging Face creates the snapshot entry per
  completed file is from knowledge of its cache layout, not from a run.
- Delete Weights calls `shutil.rmtree(cache, ignore_errors=True)` inside a
  `try` whose `except` can never fire, then reports success
  (`ui/sam_workflow.py:253-260`). Loaded models stay in memory and the SAM1
  fallback weights are never removed.
- Warm-up loads the video model; single-frame segmentation loads a separate
  tracker model from the same checkpoint (`sam_backend.py:100-107`, `:150-186`,
  `:224-241`). The first click after "ready" pays a second full load and both
  copies stay resident.
- A cancelled or failed propagation, or a SAM3-to-SAM1 fallback mid-run, leaves
  partial mask PNGs in `masks/` until a clean close; a crash or forced
  termination leaves them permanently (`sam_backend.py:227-238`, `:320-338`).

**Scope.** Require a complete weight file (and no `.incomplete` blob) before
reporting cached. Handle delete errors and re-check the cache; drop loaded
models after delete. Warm the model the first click will use and show a
"Loading model" status in the segment path. Unlink written frames on cancel,
failure, and fallback.

**Acceptance.** Stubbed-backend tests for each bullet. A real-inference smoke on
a source build remains a manual follow-up.

## NE-025 — Tutorial runs without changing the user's project

**Problem and evidence.** `_load_tutorial_video` adds the sample clip only when
the project has no clips (`ui/main_window.py:1160-1172`). Otherwise the
walkthrough (`ui/tutorial.py:430-636`) runs on the open project: its practice
steps add rectangle, arrow, and brush annotations, a SAM point, a marker, and a
Take Still slide, all autosaved. The step text says it uses the sample clip.
Practice marks can reach an export. **Source confirmed.**

**Scope.** Snapshot the project when the tutorial starts and restore it when it
finishes or is skipped, or run the tour in a temporary project and return to the
user's project afterwards. Correct the step text either way.

**Acceptance.** Starting and finishing the tutorial on a project with clips
leaves annotation, marker, and slide counts unchanged and adds no undo entries.

## NE-026 — Export render-loop cost

**Problem and evidence.** Unmeasured. Any segment with a redaction, caption,
slide, or fade is rendered frame by frame in Python, and the default redaction
covers the whole timeline. Each frame calls `cap.set(CAP_PROP_POS_MSEC)` before
`cap.read()` (`exporter.py:664-665`), which seeks to a keyframe and decodes
forward; cost grows with GOP length. Static content (image clips, slides, held
frames) is resized, font-fitted, and copied again for every output frame
(`exporter.py:681-692`, `:733-789`).

**Scope.** Measure first with `scripts/make_smoothness_fixture.py` and one
long-GOP recording: frames per second for a fully redacted 1080p export. If the
seek dominates, read sequentially when the next target is within about one and a
half source-frame intervals and seek only on discontinuities; verify VFR frame
selection with the existing timing tests. Memoize the composed frame for static
intervals.

**Acceptance.** Recorded before and after numbers. Output frames identical for
the constant-frame-rate fixture; VFR tests unchanged.

## NE-027 — Release and CI hardening

- Pytest runs only on `macos-15` (`.github/workflows/build.yml`,
  `quality.yml`); the Windows job only builds. Add a Windows test job, even if
  it starts with the non-GUI subset.
- The version literal is repeated in `pyproject.toml`, `__init__.py`,
  `NeuroEdit.spec`, `build_alpha_windows.ps1`, and `installer/NeuroEdit.iss`.
  Derive it from one place. A manual `workflow_dispatch` build defaults to
  `dev`, which flows into the macOS bundle version (`NeuroEdit.spec:14`, `:119`);
  the Windows script passes the raw tag, including the leading `v`, to Inno
  Setup (`build_alpha_windows.ps1:67`). Both inferred from reading, not built.
- Actions use floating tags, `choco install innosetup` is unpinned, the build
  and release jobs have no timeout, and `pytest`/`ruff` are not in
  `requirements-release.txt`.
- `quality.yml` and the quality job in `build.yml` duplicate the same steps.
- `tests/test_capture_baseline.py` gives its child process 30 s; it timed out
  three of three runs on this Mac (cold iCloud venv) and passes in CI. Raise
  the limit or mark it as slow.
- The local full-suite process exited 139 after printing its summary (once; not
  rerun). CI reports a clean exit on Python 3.12. Check Qt teardown under
  Python 3.13.
- The project venv has no ruff; the documented lint command only works with a
  system install. Install the `dev` extra there or document the system tool.

## NE-028 — Timeline polish

- Delete and the trash control do nothing for label blocks:
  `_delete_selected_item` ends in `else: return` for the annotation kind
  (`ui/editor_panels.py:998-999`).
- The playhead cannot be drag-scrubbed; only a click seeks. The tutorial tells
  the user to drag it (`ui/tutorial.py:507`).
- End-edge snapping never engages: `_snap_time` accepts `duration` but no caller
  passes it (`ui/editor_panels.py:1127`, calls at `:816-839`).
- `labels_panel.py` and `tutorial.py` bind theme tokens at import, so preset
  buttons and the tutorial card keep the old colours after a theme switch; there
  is no handler for the system colour scheme changing while running. Traced, not
  seen on screen.
- Annotation lane layout is recomputed per annotation during hit-testing and
  static paints (`ui/editor_panels.py:491-499`, `:667-698`). A reviewer
  micro-benchmark gave 9 ms at 300 annotations and 34 ms at 600 per full scan;
  each brush stroke is an annotation. Compute lanes once per call.

## NE-029 — Export and caption robustness

- With VideoToolbox present the encoder uses a fixed bitrate by resolution and
  ignores the Quality (CRF) control and the frame rate (`exporter.py:525-536`).
  Map quality to bitrate, or disclose it in the dialog.
- Advanced width or height can be odd; libx264 then fails at the end of the run.
  Round to even on input.
- The fast path caps frames with `-frames:v` and has no tail padding
  (`exporter.py:367-402`). If the probed duration overestimates the stream, the
  segment is short and later segments drift against audio. Mechanism is certain;
  frequency unmeasured. Consider `tpad=stop_mode=clone`.
- `_has_audio_stream` matches the text `Audio:` in ffmpeg's banner, which
  includes the input file name (`exporter.py:1097`).
- Render-segment stderr is read only after the write loop (`exporter.py:465`);
  a very chatty ffmpeg could fill the pipe.
- WebVTT output does not escape `&`, `<`, or `-->`; minimum cue padding can make
  a short cue overlap the next one (`captions.py:69-85`, `:108-125`).
- The export report and default file name include the project name and
  storyboard free text (`ui/export_workflow.py:99-100`, `:235-277`), and the
  report sits beside the MP4. Add a "contains case notes" header or leave the
  free text out by default.

## NE-030 — Small lifecycle and documentation items

- Save As reseeds undo history and stops the player without reloading the frame
  (`ui/main_window.py:1453-1455` via `_activate_project`). History loss is
  certain; the blank preview is inferred.
- Recording file names use one-second resolution
  (`ui/audio_panel.py:352`); two takes in the same second share a file.
- Audio duration probing runs ffmpeg on the UI thread with a 10 s timeout
  (`ui/audio_panel.py:467-478`).
- Any document edit during a background metadata import discards the whole
  import with a five-second status message (`ui/main_window.py:1708-1714`); the
  progress dialog is non-modal. Make it window-modal or say so in a dialog.
- Over image clips and gaps every 33 ms tick re-runs
  `_sync_player_to_timeline`, including a `stat` of the clip file
  (`ui/main_window.py:2288-2295`). Same class as the open `AudioPreview.sync`
  item in `TODO.md`; fix them together.
- The library's "Opened …" label shows the file's modification time
  (`ui/project_library.py:199`, `:246`).
- `project.json` has no schema version; `_from_dict_tolerant` drops unknown keys
  and the next save removes them (`models.py:30-35`).
- No `sys.excepthook`: an exception in a Qt slot goes to stderr only, which a
  packaged build never shows (`__main__.py`).
- Docs: `desktop/CLAUDE.md:66-67` and `:305` describe a root React/Vite
  prototype that is not in the repository; `desktop/WINDOWS_DISTRIBUTION.md:20`
  names a workflow that is now called "Build installers"; distribution docs
  still use `alpha-001` examples; `HANDOFF.md` is 174 KB and could move entries
  older than v0.5.12 to an archive file; `desktop/.venv 2` is a dangling
  symlink.
