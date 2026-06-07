# NeuroEdit

NeuroEdit is a standalone desktop video editor for preparing operative video for
conference, research, and educational use.

Current alpha release: [v0.2.1-alpha](https://github.com/v7sm25qk5v-ui/NeuroEdit/releases/tag/v0.2.1-alpha)

## Install The Alpha

### macOS

Download `NeuroEdit-v0.2.1-alpha-macOS-unsigned.dmg` from the release page.
Open the DMG, drag `NeuroEdit.app` into Applications, then right-click the app
and choose `Open` for the first launch.

This alpha is unsigned and not notarized, so macOS may show a developer warning.
If macOS blocks launch, open `System Settings` -> `Privacy & Security`, choose
`Open Anyway`, then right-click `NeuroEdit.app` -> `Open` again.

### Windows

Download `NeuroEdit-v0.2.1-alpha-Windows-Setup.exe` from the release page on a
Windows PC. If SmartScreen warns, choose `More info` -> `Run anyway`, then follow
the installer.

The Windows installer is built by CI from the same source as macOS. Runtime UI
verification for the Windows `v0.2.1-alpha` build is still pending; testers should
capture toolbar screenshots at 100%, 125%, and 150% display scaling.

## Clinical Disclaimer

NeuroEdit is not a medical device, is not FDA-cleared, and is not intended for
diagnosis, treatment, or clinical decision-making. Users are responsible for
patient consent, institutional authorization, de-identification, PHI review, and
compliance with all applicable policies and laws before sharing any exported
video.

## Development

The active application lives in `desktop/`.

```bash
cd desktop
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m neuroedit_desktop
```

Run the current quality checks:

```bash
cd desktop
source .venv/bin/activate
ruff check src tests
python -m pytest tests/ -q
```
