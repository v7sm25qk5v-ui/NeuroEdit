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
