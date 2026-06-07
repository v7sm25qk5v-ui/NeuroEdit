# NeuroEdit Alpha QA Checklist

Use this checklist for each alpha release before sending builds to broader
testers. Do not include patient-identifying media in screenshots or bug reports.

## macOS Smoke Test

- Install from the unsigned DMG.
- Launch with right-click -> Open and note any Gatekeeper prompts.
- Start from the restored project prompt or create/open a project.
- Import a short non-PHI video and image.
- Confirm playback controls render and work: play, pause, previous frame, next frame, scrub.
- Switch every right-side panel: SAM, Labels, Tips, Slides, Audio.
- Add one rectangle annotation and edit its label.
- Add one Redact PHI box and confirm it appears above other overlays.
- Add a marker and cut at the playhead.
- Open the export dialog, export MP4, and confirm the `.export-report.txt` is written.
- Reopen the app and confirm autosave/recent project behavior is understandable.

## Windows Tester Checklist

Run this only on a Windows PC or Windows test environment. Do not download or run
the Windows installer on macOS for runtime validation.

- Install `NeuroEdit-<version>-Windows-Setup.exe`.
- Note Windows version, CPU architecture, display resolution, and display scaling.
- Capture full-window toolbar screenshots at 100%, 125%, and 150% scaling.
- Confirm the app launches from the Start menu and optional desktop shortcut.
- Import a short non-PHI video and image.
- Confirm playback controls render and work: play, pause, previous frame, next frame, scrub.
- Switch every right-side panel: SAM, Labels, Tips, Slides, Audio.
- Add one rectangle annotation and edit its label.
- Add one Redact PHI box and confirm it appears above other overlays.
- Open the export dialog, export MP4, and confirm the `.export-report.txt` is written.
- Uninstall from Windows Settings -> Apps -> NeuroEdit.

## Feedback To Capture

- App version and installer filename.
- Operating system version and display scaling.
- Whether unsigned-app warnings were understandable.
- Any clipping, overlap, or unreadable toolbar/panel text.
- Any crash or freeze, with the action immediately before it happened.
- Exported MP4 and export report only when they contain no PHI.
