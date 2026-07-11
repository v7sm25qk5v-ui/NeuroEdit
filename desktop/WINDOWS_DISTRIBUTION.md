# NeuroEdit Unsigned Windows Alpha

The Windows alpha is built from the **same source** as the macOS alpha — there is
no separate Windows codebase. A shared PyInstaller spec (`NeuroEdit.spec`) plus an
Inno Setup script (`installer/NeuroEdit.iss`) turn that source into a friendly
double-click installer. The app is **not** code-signed yet, so Windows SmartScreen
will warn testers (the Windows equivalent of macOS Gatekeeper).

## How it gets built

You do **not** need a Windows machine. GitHub Actions builds both installers in
the cloud (`.github/workflows/build.yml`):

- Push a version tag and both the macOS `.dmg` and Windows `Setup.exe` are built
  from that commit and attached to a GitHub Release:
  ```bash
  git tag v0.2.0-alpha
  git push origin v0.2.0-alpha
  ```
- Or use the Actions tab -> "Build alpha installers" -> "Run workflow" to produce
  test artifacts without cutting a release.

### Building locally on Windows (optional)

If you ever have a Windows machine, from the `desktop` folder:

```powershell
.\scripts\build_alpha_windows.ps1 -Version alpha-001
```

Requires Python 3.12 and [Inno Setup 6](https://jrsoftware.org/isdl.php). Produces
`release\NeuroEdit-alpha-001-Windows-Setup.exe`.

## Tester Install Instructions

1. Download `NeuroEdit-<version>-Windows-Setup.exe` from the Release page.
2. Double-click it.
3. If a blue "Windows protected your PC" SmartScreen box appears, click
   **More info**, then **Run anyway**. (This appears only because the alpha is
   unsigned.)
4. Follow the wizard: Next -> Install -> Finish. No administrator password is
   needed — it installs just for the current user.
5. Launch NeuroEdit from the Start menu (or the desktop shortcut if chosen).

To remove it later: Settings -> Apps -> NeuroEdit -> Uninstall.

## What Is Not Included

Same as the macOS alpha: this is an editor-only build. The optional SAM/PyTorch
runtime and model weights are excluded to keep the download small. The editor
workflow, timeline, labels, slides, audio, transcript editing, and export all
work without them. `ffmpeg` **is** bundled (via `imageio-ffmpeg`), so export
works with no extra install.

## Removing the SmartScreen warning later

To ship without the warning to non-technical users, sign the installer with an
**Authenticode code-signing certificate** (OV ~$200-400/yr, or EV to clear the
warning immediately). The build is structured so signing can be added as one extra
step in the workflow once a certificate is available — no app-code changes needed.

## Known limitation

The macOS build targets Apple Silicon (arm64); the Windows build targets x64.
Both cover the overwhelming majority of modern machines.
