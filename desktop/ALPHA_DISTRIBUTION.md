# NeuroEdit Unsigned macOS Alpha

This alpha path does not require an Apple Developer account. The app is ad-hoc signed for local macOS compatibility, but it is not Developer ID signed or notarized. The tradeoff is that macOS Gatekeeper will warn testers.

## Build

From the `desktop` folder:

```bash
./scripts/build_alpha_macos.sh alpha-001
```

The script creates:

- `dist/NeuroEdit.app`
- `release/NeuroEdit-alpha-001-macOS-unsigned.zip`
- `release/NeuroEdit-alpha-001-macOS-unsigned.dmg`

Send testers the DMG first. If a tester has trouble with the DMG, send the zip.

## Tester Install Instructions

1. Download `NeuroEdit-alpha-001-macOS-unsigned.dmg`.
2. Double-click the DMG.
3. Drag `NeuroEdit.app` into `Applications`.
4. Open `Applications`.
5. Right-click `NeuroEdit.app` and choose `Open`.
6. If macOS warns that the developer cannot be verified, choose `Open` again.

After the first successful launch, the app should open normally.

## If macOS Blocks the App

Ask the tester to try:

1. Open `System Settings`.
2. Go to `Privacy & Security`.
3. Scroll to the security warning for `NeuroEdit`.
4. Click `Open Anyway`.
5. Launch `NeuroEdit` again with right-click -> `Open`.

If macOS still says the app cannot be opened, ask the tester to run this in Terminal:

```bash
xattr -dr com.apple.quarantine /Applications/NeuroEdit.app
open /Applications/NeuroEdit.app
```

That removes the download quarantine flag from this unsigned alpha only.

## What Is Not Included

This unsigned alpha intentionally does not bundle SAM/ML model weights. That keeps the app small enough for testing the editor workflow, timeline, labels, slides, audio, transcript editing, and export.

## Test Feedback To Request

Ask testers to report:

- macOS version and Mac model.
- Whether the app opened without extra help.
- Whether video import, playback, labels, slides, audio, transcript editing, and export worked.
- Any crash or freeze, with the action immediately before it happened.
- The exported MP4 and `.export-report.txt` if export fails or looks wrong.
