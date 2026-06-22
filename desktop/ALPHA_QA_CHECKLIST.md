# NeuroEdit Alpha QA Checklist

This file is a **per-release template**. For each release tag, copy it to
`qa/QA_<tag>.md` (e.g. `qa/QA_v0.4.0-alpha.md`), fill in the header and the
Result column, and commit it alongside the tag. Do not include
patient-identifying media in screenshots or bug reports.

## Release under test

| Field | Value |
|---|---|
| Tag | `vX.Y.Z-alpha` |
| Commit SHA | `         ` |
| Fill date | YYYY-MM-DD |
| Tester | |
| Build artifact(s) | DMG / Setup.exe filename(s) |

Result column values: **Pass**, **Fail** (link an issue/note), **Skip** (say why).

## macOS Smoke Test

| Step | Result | Notes |
|---|---|---|
| Install from the unsigned DMG. | | |
| Launch with right-click → Open and note any Gatekeeper prompts. | | |
| Start from the restored project prompt or create/open a project. | | |
| Import a short non-PHI video and image. | | |
| Drag a non-PHI video and image from Finder into the app; both appear on the timeline. | | |
| Play a variable-frame-rate screen recording; video and playhead advance smoothly through static sections. | | |
| Playback controls work: play, pause, prev/next frame, scrub. | | |
| Switch every right-side panel: SAM, Labels, Tips, Slides, Audio. | | |
| Add one rectangle annotation and edit its label. | | |
| Add one Redact PHI box and confirm it renders above other overlays. | | |
| Add a marker and cut at the playhead. | | |
| Run Edit → Guided PHI Review through all sections. | | |
| Add a transcript segment, enable captions, confirm canvas preview. | | |
| Export captions as `.srt` and `.vtt`; open both in a text editor. | | |
| Export MP4 (complete the pre-export checklist) and confirm `.export-report.txt` is written with the PHI flags. | | |
| Use Reveal MP4 / Reveal Report buttons on the completion dialog. | | |
| Open File → Export History and reveal the export. | | |
| Reopen the app and confirm autosave/recent project behavior. | | |

## Windows Tester Checklist

Run this only on a Windows PC or Windows test environment. Do not download or
run the Windows installer on macOS for runtime validation.

| Step | Result | Notes |
|---|---|---|
| Install `NeuroEdit-<version>-Windows-Setup.exe`. | | |
| Note Windows version, CPU arch, resolution, and display scaling. | | |
| Capture full-window toolbar screenshots at 100%, 125%, 150% scaling. | | |
| App launches from the Start menu and optional desktop shortcut. | | |
| Import a short non-PHI video and image. | | |
| Drag a non-PHI video and image from File Explorer into the app; both appear on the timeline. | | |
| Play a variable-frame-rate screen recording; video and playhead advance smoothly through static sections. | | |
| Playback controls work: play, pause, prev/next frame, scrub. | | |
| Switch every right-side panel: SAM, Labels, Tips, Slides, Audio. | | |
| Add one rectangle annotation and edit its label. | | |
| Add one Redact PHI box and confirm it renders above other overlays. | | |
| Add a transcript segment, enable captions, confirm canvas preview. | | |
| Export MP4 (complete the pre-export checklist) and confirm `.export-report.txt` is written. | | |
| Use Reveal MP4 / Reveal Report and File → Export History. | | |
| Uninstall from Windows Settings → Apps → NeuroEdit. | | |

## Feedback To Capture

- App version and installer filename.
- Operating system version and display scaling.
- Whether unsigned-app warnings were understandable.
- Any clipping, overlap, or unreadable toolbar/panel text.
- Any crash or freeze, with the action immediately before it happened.
- Exported MP4 and export report only when they contain no PHI.
