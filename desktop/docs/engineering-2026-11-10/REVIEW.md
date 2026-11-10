# NeuroEdit implementation review

Date: 2026-11-10. Reviewer: Sol. Scope: NE-001 through NE-009 in the root
`CODING_TICKETS.md`. Review is against the actual shared working-tree changes;
author reports alone are not approval. No release or clinical validation is
part of this review.

## Review state

Coordinator release validation, 2026-11-10: NE-008/009 are now software verified
after Sol review and **341 passing tests in 148.64 s**, no skips and clean exit.
Full Ruff, compilation, version-label validation, and diff checks passed. Native
preferences matched the private pre-validation snapshot. Earlier checkpoints
below are historical; release CI, installer builds, and publication are tracked
in `HANDOFF.md`. Real microphone/hardware testing is not claimed.

All seven ticket implementations are review approved and software verified after
the final integration result and unchanged-production-receiver import gate below.
The two subsequent recording follow-ups, NE-008/009, are review approved after
the focused regression checkpoint below and await fresh full integration.
The user-approved autosave location was restored after the preference-write
incident below; other original preference values remain unknown.
The coordinator
owns final full-suite/lint/diff verification and `HANDOFF.md`; engineers own
focused checks. This file will record inspected source, tests, fixes requested,
and remaining limitations after each implementation is ready.

## NE-005 — Software verified

Inspected `ui/audio_panel.py` and `tests/test_audio_preview.py`. The helper now
returns failure for nonpositive/nonfinite metadata, checks ffmpeg identified an
audio stream, and never substitutes five seconds. Failed import adds no track.
Recording finalization waits for `StoppedState`, stops its timer, probes the
finished file, preserves a failed recording for recovery, and rejects attachment
when the project changed. Existing import/recording duration and privacy behavior
otherwise stays intact.

Requested additional tests beyond the initial forced-zero stub; implemented
tests cover a generated real WAV and encoded MP3, ffmpeg timeout, video-only
metadata, NaN/infinity/nonpositive durations, and failed import/recording state.
Independent reviewer run: `pytest tests/test_audio_preview.py -q
--disable-warnings -o faulthandler_timeout=120` with the documented isolated
runtime: **9 passed in 0.21 s**, clean exit. No remaining code blocker found for
NE-005.

## NE-002 — Software verified

Inspected the new `ui/audio_preview.py`, main-window playback/refresh/activation/
close hooks, and focused audio/undo tests. Active added tracks use per-track
players, source-relative seek offsets, deferred seeks on loaded media, independent
volume, and the existing monotonic timeline clock. Invalid media is reported
without recreating the same failed player on every tick. Removed tracks and
paused/replaced projects stop and release their players. Source mute leaves
added narration active, as export does.

Review found and required two lifecycle fixes: small explicit seeks initially
used the normal 300 ms drift tolerance, and document activation could retain old
narration or autoplay the new project's tracks before validation dialogs closed.
The final code forces narration alignment on explicit timeline seek and stops
preview plus the timeline clock before replacing the project. Regression tests
exercise the ordering with a replacement project containing audio, small seek,
clock hold during source loading, and full-frame slide playback. Helper tests
cover overlapping tracks, seek offsets, playback rate, source-mute independence,
pause, removal, invalid media, and project identity change.

Independent reviewer run after these fixes: `pytest tests/test_audio_preview.py
tests/test_undo_history.py -q --disable-warnings -o faulthandler_timeout=120`:
**35 passed in 0.26 s**, clean exit. Source review found no remaining code blocker.
The coordinator subsequently completed encoded audio output evidence and full
integration, recorded below. Physical audio synchronization is unverified;
the accepted gain ceiling below also applies.

## NE-006 — Software verified

Inspected `ui/sam_workers.py`, `ui/sam_workflow.py`, and added workflow tests.
Single-frame workers now check cancellation before entering inference and after
return; the GUI receives the result with a cancellation marker so its existing
completion owner can delete the generated file. The GUI job context is marked
cancelled immediately when the user requests cancellation. That second guard
covers a successful worker result already queued before the cancel click.

Cancelled completion runs before normal success/error handling, discards the
returned mask only, clears busy/worker state, and creates no annotation or
successful run record. Existing unrelated masks remain untouched. Pre-inference,
in-inference, queued-result cancellation, and existing uncancelled behavior are
covered by the focused suite. Independent reviewer run:
`pytest tests/test_sam_workflow.py -q --disable-warnings
-o faulthandler_timeout=120`: **27 passed in 0.39 s**, clean exit. No remaining
code blocker found. An active inference still finishes cooperatively; no GPU
kernel interruption or real ML inference result is claimed.

## NE-003 — Software verified

Inspected main-window relink discovery, replacement validation/mutation, cache
invalidation, review reset, and added headless tests. The command explicitly
repairs one chosen reference. Split siblings retain their own old references;
there is no silent filename matching. Video validation requires replacement
duration to cover retained trims and source bounds. Review caught that a longer
replacement could expand the effective default bound when `source_out_limit`
was absent; the implementation now persists the old effective limit first.
Audio replacements use the validated finite duration helper; image and slide
replacements must decode as images. Audio formats match import support.

Only media path/dimensions/cache fields are changed. Clip identity, names,
timeline order, trims, markers, annotations, and unrelated references are not
rebuilt. Successful repair marks one review-relevant history step, clearing
PHI/de-identification/audio attestations and progress, thumbnail/media warning
caches, and refreshing preview. Undo/redo and save/reopen retain the repaired
path. Independent reviewer run: headless suite `-k relink`: **3 passed,
45 deselected in 0.85 s**, clean exit. No remaining code blocker found.
The coordinator subsequently completed real-media relink/export smoke to verify
encoded output, beyond the tests' stubbed video metadata, as recorded below.

## NE-004 — Software verified

Inspected `ui/media_import_worker.py`, async import/finalization/teardown hooks,
and headless tests. The worker probes metadata without document/widget mutation;
the GUI commits successful results in original input order and one history step.
Project/store identity plus document snapshot guards discard stale results.
Cancellation uses an immediate GUI callback to set the worker flag, and completion
checks that flag again, covering results emitted before a cancel click is
delivered. Window close marks `_closing`, cancels/joins the import thread via the
existing lifecycle path, and rejects any queued completion.

Review found the initial finalization still called `_load_active_clip` without
caching metadata, causing a duplicate synchronous probe on the GUI thread. The
fixed worker captures before/after file stat signatures and finalization seeds
the existing clip cache only for matching unchanged media. A regression uses
the real preview load path, records thread IDs, requires exactly one off-GUI
probe, and confirms a Qt heartbeat runs. Other tests cover partial failures,
selection order, one undo step, stale document state, cancellation after probe
but before result delivery, and close during import.

Independent reviewer run: headless suite `-k import`: **12 passed,
38 deselected in 9.76 s**, clean exit. No remaining code blocker found. This
establishes responsiveness of the bounded probe path, not representative 4K or
external-drive performance. Long blocking native probes still obey the existing
shutdown timeout policy; no broad thread framework was introduced.

A later real encoded-video import smoke did not finish within an initial
two-second harness allowance. The assertion path then aborted Qt with an active
thread. This attempt is not a passing real-media test and does not establish the
cause of the timeout. The coordinator assigned a bounded investigation with
proper `finally` cleanup and probe/finalization timing. NE-004 remains pending
that real-media gate at this checkpoint; the controlled metadata tests above
were not substituted for it. The later unchanged-production-receiver run below
resolved the real import gate.

Sol inspected `real-import-evidence.json` and the final scratch harness. The final
run used actual `MainWindow` with its signal receiver unchanged; thread logging
wrapped the downstream preview load call rather than replacing/decorating the
completion slot. One real 2 s, 64×64 H.264 probe ran on worker thread 6172094464
from 0.179–0.282 s. Preview finalization ran on GUI thread 8692662144 at 0.283 s,
one clip committed, the thread finished at 0.285 s, and the window closed cleanly
at 0.286 s; a GUI timer fired during the probe. This passes NE-004's bounded real
import gate without a production code change. Earlier repeated-QTest polling
and monkeypatched-receiver diagnostic attempts are retained as failed harness
observations, not application regression claims.

## NE-001 and NE-007 — Software verified

Inspected the shorter import titles, preserved visible by-reference hint,
wrapped export privacy explanation and checked default, capture harness, and
capture/export-dialog tests. At the 1095×600 computed minimum window size,
Media Explorer uses scrolling; the corrected captures explicitly scroll each
import action into view. Text fits horizontally. At 1440×900 both import titles
and visible keep-in-place guidance are readable. Export PHI guidance wraps
without truncation and the privacy checkbox remains checked.

The corrected harness redirects the exact application `QSettings` constructor
to a concrete temporary INI and checks `fileName()` before writing. It restores
the constructor/backend monkeypatches, closes the window, and removes temporary
storage in `finally`. It explicitly selects SAM before capturing the unavailable
explanation and checks the intended current widget/visibility after settling.
Failed PNG writes surface as errors. Source tests exercise both a successful
capture and injected failure in the same process with an explicitly native
settings snapshot unchanged and temporary storage removed.

Sol visually inspected all 19 corrected run-one images in `screenshots/`;
every panel/dialog matches its filename, including SAM unavailable and Audio.
Two corrected runs each produced 19 images; dimensions and scoped native-settings
checks are recorded in `capture-evidence.json`. Independent reviewer run:
`pytest tests/test_capture_baseline.py tests/test_export_dialog.py -q
--disable-warnings -o faulthandler_timeout=120`: **8 passed in 2.96 s**, clean
exit. No remaining implementation blocker found for NE-001 or corrected NE-007.
Native scaling and assistive-technology checks remain unperformed.

## Earlier settings-write incident — autosave location restored

An early harness revision used `QSettings.setDefaultFormat`/`setPath`, which
does not redirect the explicit native macOS organization/application constructor.
Before this was caught in review, it wrote four native preference keys without
an original snapshot: `storage/projectRoot`, `storage/promptShown`,
`tutorial/seen`, and `recentProjects`. Their exact original values and any
persistent impact are unknown. During investigation, native preferences contained an older
pytest temporary autosave path and nonempty recents; available evidence cannot
establish whether that state predates this task. No guessed restoration was
made. The coordinator notified the user and asked for their intended autosave
path. The corrected tests prove preservation only for the corrected runs;
they do not establish that earlier validation preserved preferences or resolve
the operational follow-up.

Coordinator update, 2026-11-10: the user approved restoring the existing
`~/Documents/NeuroEdit/Autosave` folder. Only the native
`storage/projectRoot` preference was changed. A fresh process calling the app's
`default_project_root()` confirms the folder; all other preferences compared
unchanged, and the existing `project.json` hash was preserved. No media or
project files were migrated. The autosave-location follow-up is resolved;
the other original preference values remain unknown and were not reconstructed.

## Integration checkpoint

The coordinator's first full integration run finished with **326 passed,
1 failed in 141.47 s**, with a clean failure exit. The failure was the saved-mask
cleanup test's deliberately incomplete `MainWindow.__new__` fixture, which lacked
the timer/preview/play-button collaborators now required by real document
activation. The minimal test-only correction adds those collaborators; it does
not weaken production activation shutdown. Sol reviewed the correction and
independently ran the lifecycle suite: **8 passed in 0.09 s**, clean exit.

The coordinator's subsequent complete integration run passed **327 tests in
139.58 s**, with no skips and a clean exit. Full Ruff, compileall, and diff check
also passed. NE-001/002/003/005/006/007 are now software verified against the
reviewed tree and scoped evidence. NE-004 also passed its additional actual
encoded import gate with the production receiver unchanged; the settings incident and manual/hardware limits remain
separate unresolved follow-ups.

Sol also reviewed `integration-evidence.json`: the coordinator exercised a real
moved-video relink, identity/trim/annotation preservation, review reset,
undo/redo, save/reopen, and encoded export with redaction pixel checks. A separate
encoded tone fixture measured zero PCM RMS before and after the intended tone
and 0.03533 during it with source audio muted. These are encoded-output checks.
The direct Qt audio-buffer preview attempt had no available audio device,
did not finish, and was terminated; it is explicitly not preview/hardware proof.

The import change newly orphaned `_add_image_clip`; its definition was removed
after reference search. `_add_video_clip` remains used by the tutorial and was
preserved. This is cleanup caused by this change, not unrelated refactoring.

## NE-008 and NE-009 — Review approved, pending fresh integration

The user authorized both recording follow-ups before the next release. Terra
reported three expected failing reproductions before implementation: recording
started at 2 s but attached at 7 s after moving the playhead, and both active and
finalizing close paths attempted to save before attaching narration. Sol reviewed
the actual new regression tests and source changes; approval is not based on
the author report alone.

`AudioPanel._start_recording` now captures a scalar timeline insertion point and
its originating project. Completion uses that anchor, validates the finished
file, and clears the anchor/project/path state after handling the result. A
different project never receives an old capture. `recording_pending` remains
true through duration probing and track attachment. `MainWindow.closeEvent`
checks it before any save, timer shutdown, or worker shutdown, gives a nonmodal
Stop/wait/retry message, and ignores the close request. It does not auto-close
or enter a nested wait loop. Repeated and reentrant close requests therefore do
not save a project missing its pending narration. Once completion succeeds, the
ordinary final save includes the track; failed saves retain the existing open
window behavior.

Review required handling the recorder's error-state ordering as well as its
error signal. Completion checks both the cached message and
`recorder.error()/errorString()`, so StoppedState arriving before errorOccurred
cannot attach a failed capture. Known recorder errors skip the duration probe;
errors already in StoppedState finalize immediately rather than permanently
blocking close. Failed probes/errors leave any recording file untouched and
show its expected path for recovery. Immediate start errors cannot re-enable
an active-looking recording UI after their synchronous callback returns.

New deterministic tests cover anchor movement and unchanged playhead, preview
and exporter source onset, delayed completion, synchronous stop, immediate start
error, state-first/error-first completion, failed duration, replaced project,
repeated close, reentrant close during probing, save failure, and a real-window
close/save/reopen controller path. Device/recorder operations are fake and all
application preferences are redirected by the established test fixture.
Independent reviewer run: `pytest tests/test_recording_lifecycle.py
tests/test_project_lifecycle_review.py tests/test_audio_preview.py -q
--disable-warnings -o faulthandler_timeout=120`: **31 passed in 0.45 s**, clean
exit. No remaining code blocker found. The coordinator owns the fresh full suite
and release; physical microphone recording and device latency remain unverified.
The existing bounded synchronous duration probe was not redesigned in this
close-guard fix; known error paths avoid invoking it.

## Reviewed source anchors

| Ticket | Main inspected source |
|---|---|
| NE-001 | `ui/editor_panels.py:113`; `ui/dialogs.py:633` |
| NE-002 | `ui/audio_preview.py:9`; `ui/main_window.py:1122`, `:2209`, `:2635` |
| NE-003 | `ui/main_window.py:1774` |
| NE-004 | `ui/media_import_worker.py:8`; `ui/main_window.py:1666`, `:1702` |
| NE-005 | `ui/audio_panel.py:431`, `:445` |
| NE-006 | `ui/sam_workers.py:38`; `ui/sam_workflow.py:96`, `:319` |
| NE-007 | `scripts/capture_baseline_screenshots.py:76`, `:82`, `:131` |
| NE-008 | `ui/audio_panel.py:346`, `:383` |
| NE-009 | `ui/audio_panel.py:373`, `:376`, `:383`; `ui/main_window.py:2635` |

`ui/` paths are relative to `desktop/src/neuroedit_desktop/`. Line references
describe the reviewed working tree on 2026-11-10 and may move with later edits.

## Review gates

- Audio preview follows the monotonic timeline clock, defers seek until loaded,
  responds to explicit small seeks, and removes old players on project/history
  replacement, pause, end, and close. Source mute does not mute narration.
- Relink preserves clip identity/source bounds/edits, rejects unsuitable media,
  creates one undo operation, resets PHI/export attestations, and refreshes
  caches and preview. Recovery includes image/audio references.
- Async import does not mutate documents until accepted completion, preserves
  selection order, rejects stale/cancelled results, and cleans threads safely.
- Failed audio probes never invent a duration or attach invalid tracks.
- Single-frame SAM cancellation discards queued/inference results and only its
  own output, clears busy state, and preserves uncancelled behavior.
- Screenshot capture isolates native preferences and proves each captured state
  matches its label; visual evidence is inspected after settling.

## Accepted bounded limitation

Qt `QAudioOutput` caps added-audio preview gain at 1.0. The existing exporter
supports persisted track gain up to 2.0. UI-created tracks use 0..1, and the
coordinator approved retaining this limit rather than changing export behavior.
Preview/export gain parity above 1.0 is not claimed.

## Verification limits

Offscreen/software checks and synthetic encoded media can validate state,
transport mapping, and export behavior. They do not establish physical speaker
latency, real listening synchronization, native Windows scaling, real SAM
inference, clinical efficacy, or complete de-identification. These limits must
remain explicit in the final handoff.
