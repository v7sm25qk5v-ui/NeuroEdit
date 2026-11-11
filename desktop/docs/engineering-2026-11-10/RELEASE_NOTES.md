# NeuroEdit v0.5.14-alpha

This alpha improves the local teaching-video editing workflow.

- **Narration preview:** added narration/music follows timeline playback,
  seeking, overlapping tracks, speed changes, and still intervals.
- **Recording placement and safe closing:** recordings retain the timeline
  position where Record was pressed. Closing is blocked while recording or
  finalization is pending, with guidance to finish recording and retry.
  Recording errors do not attach invalid tracks or delete existing recording files.
- **Missing-media recovery:** File → Relink Unavailable Media repairs one
  selected video/image/audio/slide-image reference, preserves edits and source
  bounds, supports undo, and resets privacy review approvals. Split references
  are repaired individually.
- **Responsive import:** metadata probing runs in the background; successful
  imports retain input order and one undo transaction. Cancelled/stale results
  are discarded and the preview reuses validated metadata.
- **Audio validation:** unreadable or unknown-duration audio is rejected instead
  of creating a guessed five-second track.
- **SAM cancellation:** cancelled single-frame results are discarded, including
  results already queued for delivery. Optional SAM remains source-build-only.
- **Readable controls and safer QA tooling:** import/export text fits, source
  audio removal is clearly distinguished from added narration, and screenshot
  capture uses isolated preferences and verified panel states.

## Downloads

- [macOS DMG](https://github.com/v7sm25qk5v-ui/NeuroEdit/releases/download/v0.5.14-alpha/NeuroEdit-v0.5.14-alpha-macOS-unsigned.dmg)
- [macOS ZIP](https://github.com/v7sm25qk5v-ui/NeuroEdit/releases/download/v0.5.14-alpha/NeuroEdit-v0.5.14-alpha-macOS-unsigned.zip)
- [Windows installer](https://github.com/v7sm25qk5v-ui/NeuroEdit/releases/download/v0.5.14-alpha/NeuroEdit-v0.5.14-alpha-Windows-Setup.exe)

These installers are unsigned editor-only alpha builds. macOS may require
right-click → Open or Privacy & Security → Open Anyway. Windows may show
SmartScreen. The installers do not include the optional SAM/PyTorch stack.

## Validation and limits

Local quality checks passed **341 tests**, no skips and clean process exit,
plus Ruff, source compilation, and diff/version checks. Native app preferences
were unchanged by this validation. GitHub CI/build/publication results are
recorded in `HANDOFF.md`.

The [tagged installer workflow](https://github.com/v7sm25qk5v-ui/NeuroEdit/actions/runs/42927955107)
passed Ruff and all **341 tests**, then built both platform installers and
published all three downloads successfully. The final main-branch quality gate
also passed all 341 tests. Both runs used commit
`c28bf019b1da3f05f85b62d30abef0eee1813bed`.

Final local and CI validation are recorded in `HANDOFF.md`. Regression coverage
includes recording start position, active/finalizing close, error ordering,
repeated close, saved-project recovery, source mapping, and preservation of the
existing editing/export/privacy workflows.

Physical audio listening/latency, Windows display scaling, and actual SAM
inference were not verified in this work. Preview gain is capped at 1.0 by Qt;
existing export gain can reach 2.0 for externally edited projects. Captions use
supplied/imported transcripts and do not perform speech recognition. The
historical security scan remains partial; this release is not a completed audit.
