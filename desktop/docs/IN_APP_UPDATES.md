# In-app updates

Introduced in v0.5.19-alpha, from `codex/in-app-updates` based on the
v0.5.18-alpha release record. Install v0.5.19-alpha manually once to get this
feature. It reports up to date until a newer release is published; subsequent
releases can update in the app. Publication results are recorded in HANDOFF.md.

## User flow

1. Choose **Help → Check for Updates…**. No update request runs at startup.
2. Read the installed/new version and plain release notes. Choose **Download**.
3. Download progress supports Cancel; incomplete or unverified files are removed.
4. Choose **Install and Restart**. Finish recording/import/export/SAM work first.
   Saving or closing failure prevents handoff. The editor saves edited work and
   remembers the current saved project, then exits normally.
5. The helper waits for process exit, installs, and restarts NeuroEdit. The saved
   project reopens once. Source checkouts and read-only installations offer
   **Open Releases** with manual-install instructions.

Only public release metadata/assets are requested. No videos, audio, project
content, GitHub account or credentials are sent. Existing unsigned-build OS
restrictions still apply; the updater does not bypass them or force-kill the app.

## Implementation contracts

- `update_release.py`: fixed repository and expected asset names/URLs, bounded
  sizes, valid SHA-256 digest, numeric/alpha tag comparison.
- `update_service.py`: QtNetwork on the GUI event loop, HTTPS redirects without
  downgrade, metadata/download bounds and timeouts, streaming hash, private temp
  files, cancellation and stale-reply identity guards.
- `update_install.py`: rechecks digest, privately stages without changing the app.
  macOS ZIP files/links stay inside NeuroEdit.app; bundle ID, version and executable
  are checked. Staging is on the installation volume for atomic renames. The
  detached helper waits for exit, renames with rollback, and asks Launch Services
  to reopen. Windows runs the current-repo installer using system PowerShell,
  preserving install directory and the per-user/OS policy, with an explicit Inno
  restart switch. Installer failures attempt to reopen the existing app and show
  a visible message.
- `ui/update_dialog.py`: display/signals only; release notes render as plain text.
- `ui/update_workflow.py`: threaded disk preparation, editor save/close guards,
  helper ownership, temp cleanup, one-time saved-project reopening. Existing
  clean project files are not rewritten, including unknown newer-schema fields.

The GitHub Latest release must keep standard asset names:
`NeuroEdit-<tag>-macOS-unsigned.zip` and
`NeuroEdit-<tag>-Windows-Setup.exe`, with GitHub `sha256:` digests. The macOS DMG
remains available for manual installation; the updater uses the ZIP. Preserve
the fixed repository validation; never run commands from release notes.

Build scripts supply `NEUROEDIT_RELEASE_TAG`; the PyInstaller spec generates
`neuroedit_desktop/resources/build_info.json` with `tag`. This preserves full
alpha.N ordering while numeric bundle/app versions derive from pyproject. Source
checkouts fall back to installed numeric metadata. The Inno installer restarts
after `/NEUROEDIT_RESTART=1`; normal manual installer behavior stays the same.

## Verification on 2026-11-17

- Full suite: **765 passed**, two pre-existing Qt deprecation warnings, 117.04 s,
  clean exit. Unraisable and unhandled-thread warnings were treated as errors.
- **42 updater tests** pass; independent Sol review reports no blocking finding.
- Ruff, Bash syntax, dependency and diff checks pass.
- One real Qt HTTPS request returned up-to-date against the current GitHub release.
- The new service then downloaded the real 117620203-byte macOS release ZIP,
  followed GitHub/CDN redirects, verified size and SHA-256, and deleted the file
  without running or installing it.
- A real temporary macOS app built using pinned PyInstaller 6.20.0; all five updater
  modules and build-tag resource were bundled. Its normal ditto ZIP was staged
  through the updater, passed `codesign --verify --deep --strict`, preserved the
  original bundle, and cleaned staging. No real installed app was replaced.
- Temporary-bundle helper tests cover actual rename and rollback. Windows helper
  launch/switches/failure behavior are checked with mocks/structural assertions.
- App-owned native preferences and existing autosave hashes are unchanged. The
  workspace's intentional iCloud `.venv` was not changed.

## Remaining native smoke checks

On macOS, manually install the first updater-enabled build into a writable
location and publish a newer genuine release. Check/update with an edited named
project; verify saved content, restart, version and reopened project. Test a
failed save and cancellation; check read-only/DMG locations use the manual path.

On Windows, repeat with a real per-user Inno install, a path containing spaces,
and the supported OS policies. Verify PowerShell helper launch, silent progress,
existing directory, automatic restart, project recovery, and failed installer
feedback. The former pytest path-separator setup assertion is corrected locally;
no native Windows suite/build/install has run for this feature yet.

Rollback covers failed replacement or rejected OS launch. A successful macOS
`open` request is not proof that the new app stays healthy; there is no post-start
health monitor or automatic rollback of a later application crash.
