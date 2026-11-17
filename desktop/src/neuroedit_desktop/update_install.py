"""Stage verified release assets and hand off installation after a safe close."""

from __future__ import annotations

import hashlib
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class InstallError(Exception):
    """The update cannot safely be installed automatically."""


@dataclass(frozen=True)
class InstallTarget:
    platform: str
    path: Path | None
    reason: str = ""

    @property
    def supported(self) -> bool:
        return self.path is not None and not self.reason


@dataclass(frozen=True)
class PreparedInstall:
    target: InstallTarget
    staging: Path
    payload: Path


_MAC_INSTALL_DIRS = (Path("/Applications"), Path.home() / "Applications")


def _installed_mac_copy(bundle: Path) -> Path | None:
    """Find one writable installed copy identical to a read-only running bundle."""
    try:
        info = (bundle / "Contents/Info.plist").read_bytes()
        executable = hashlib.sha256((bundle / "Contents/MacOS/NeuroEdit").read_bytes()).digest()
    except OSError:
        return None
    matches = []
    for directory in _MAC_INSTALL_DIRS:
        candidate = directory / "NeuroEdit.app"
        if (candidate.is_symlink() or not _valid_bundle(candidate)
                or not os.access(directory, os.W_OK | os.X_OK)):
            continue
        try:
            if ((candidate / "Contents/Info.plist").read_bytes() == info
                    and hashlib.sha256((candidate / "Contents/MacOS/NeuroEdit").read_bytes()).digest() == executable):
                matches.append(candidate)
        except OSError:
            continue
    return matches[0] if len(matches) == 1 else None


def inspect_install_target() -> InstallTarget:
    """Only allow installed, writable frozen applications, never a source checkout."""
    platform = sys.platform
    if not getattr(sys, "frozen", False):
        return InstallTarget(platform, None, "Automatic installation requires an installed app. Download the update manually.")
    executable = Path(sys.executable).resolve()
    if any((parent / "pyproject.toml").is_file() and (parent / "src" / "neuroedit_desktop").is_dir() for parent in executable.parents):
        return InstallTarget(platform, None, "Automatic installation is unavailable in a source checkout. Download the update manually.")
    if platform == "darwin":
        if executable.name != "NeuroEdit" or executable.parent.name != "MacOS" or executable.parent.parent.name != "Contents":
            return InstallTarget(platform, None, "The installed application bundle could not be identified. Download the update manually.")
        target = executable.parent.parent.parent
        if target.name != "NeuroEdit.app" or not _valid_bundle(target):
            return InstallTarget(platform, None, "The installed application bundle could not be verified. Download the update manually.")
        writable = os.access(target.parent, os.W_OK | os.X_OK)
        if not writable:
            installed = _installed_mac_copy(target)
            if installed is not None:
                target, writable = installed, True
    elif platform == "win32":
        if executable.name.lower() != "neuroedit.exe" or not (executable.parent / "_internal").is_dir():
            return InstallTarget(platform, None, "The installed application could not be identified. Download the update manually.")
        target = executable.parent
        writable = os.access(target, os.W_OK)
    else:
        return InstallTarget(platform, None, "Automatic installation is available on macOS and Windows only. Download the update manually.")
    if not writable:
        return InstallTarget(platform, None, "The installation location is not writable. Download the update and install it manually.")
    return InstallTarget(platform, target)


def _valid_bundle(path: Path, version: str | None = None) -> bool:
    try:
        with (path / "Contents" / "Info.plist").open("rb") as f:
            info = plistlib.load(f)
        exe = path / "Contents" / "MacOS" / "NeuroEdit"
        return (info.get("CFBundleIdentifier") == "org.neuroedit"
                and info.get("CFBundleExecutable") == "NeuroEdit"
                and (version is None or info.get("CFBundleShortVersionString") == version)
                and exe.is_file() and os.access(exe, os.X_OK))
    except (OSError, ValueError, plistlib.InvalidFileException):
        return False


def _extract_bundle(archive: Path, destination: Path) -> Path:
    # Extract regular files first and links last, so a link cannot redirect writes.
    with zipfile.ZipFile(archive) as z:
        members = z.infolist()
        if len(members) > 100_000 or sum(m.file_size for m in members) > 8 * 1024**3:
            raise InstallError("The update archive is too large.")
        seen = set()
        links = []
        for member in members:
            name = member.filename
            parts = PurePosixPath(name).parts
            if (not parts or parts[0] != "NeuroEdit.app" or name.startswith("/")
                    or "\\" in name or any(p in (".", "..") for p in name.split("/"))):
                raise InstallError("The update archive contains an unsafe path.")
            relative = PurePosixPath(*parts)
            if relative in seen:
                raise InstallError("The update archive contains duplicate paths.")
            seen.add(relative)
            output = destination.joinpath(*parts)
            mode = member.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if kind == stat.S_IFLNK:
                if member.file_size > 4096:
                    raise InstallError("The update archive contains an unsafe link.")
                link = z.read(member).decode("utf-8")
                if not link or link.startswith("/") or "\\" in link:
                    raise InstallError("The update archive contains an unsafe link.")
                links.append((output, link))
            elif member.is_dir():
                output.mkdir(parents=True, exist_ok=True)
            elif kind in (0, stat.S_IFREG):
                output.parent.mkdir(parents=True, exist_ok=True)
                with z.open(member) as source, output.open("xb") as dest:
                    shutil.copyfileobj(source, dest)
                output.chmod(mode & 0o777 if mode else 0o644)
            else:
                raise InstallError("The update archive contains an unsupported file.")
        bundle = destination / "NeuroEdit.app"
        for output, link in links:
            # Validate before creating anything: an earlier link must not redirect
            # creation of a later one outside the private staging directory.
            if (not output.parent.resolve().is_relative_to(bundle.resolve())
                    or not (output.parent / link).resolve().is_relative_to(bundle.resolve())):
                raise InstallError("The update archive contains a link outside the bundle.")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.symlink_to(link)
        for output, _ in links:
            if not output.resolve().is_relative_to(bundle.resolve()):
                raise InstallError("The update archive contains a link outside the bundle.")
        return bundle


def prepare_install(asset_path: Path, release, target: InstallTarget) -> PreparedInstall:
    """Recheck the downloaded digest and stage a private copy; never alter the app."""
    if not target.supported or target.path is None:
        raise InstallError(target.reason or "Automatic installation is unavailable.")
    staging = Path(tempfile.mkdtemp(prefix=".neuroedit-update-", dir=target.path.parent if target.platform == "darwin" else None))
    try:
        asset_path = Path(asset_path)
        copy = staging / ("update.zip" if target.platform == "darwin" else "setup.exe")
        digest = hashlib.sha256()
        with asset_path.open("rb") as source, copy.open("xb") as dest:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                dest.write(chunk)
        if digest.hexdigest().lower() != release.asset.sha256.lower():
            raise InstallError("The downloaded update failed its integrity check.")
        if target.platform == "darwin":
            payload = _extract_bundle(copy, staging)
            match = re.fullmatch(r"v?(\d+\.\d+\.\d+)(?:[-+][0-9A-Za-z.-]+)?", release.tag_name)
            if not match or not _valid_bundle(payload, match.group(1)):
                raise InstallError("The update does not contain the expected NeuroEdit application and version.")
            copy.unlink()
        elif target.platform == "win32":
            payload = copy
        else:
            raise InstallError("This platform is not supported.")
        return PreparedInstall(target, staging, payload)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def discard_prepared_install(prepared: PreparedInstall) -> None:
    shutil.rmtree(prepared.staging, ignore_errors=True)


_MAC_HELPER = r'''pid=$1; target=$2; payload=$3; staging=$4
failure() {
    /usr/bin/osascript -e 'display dialog "NeuroEdit could not install the update. Please download and install it manually." buttons {"OK"} default button "OK" with icon caution' >/dev/null 2>&1
}
count=0
while kill -0 "$pid" 2>/dev/null; do
    if [ "$count" -ge 120 ]; then failure; exit 1; fi
    sleep 1
    count=$((count + 1))
done
backup="$staging/previous.app"
if ! mv "$target" "$backup"; then
    [ ! -d "$target" ] || /usr/bin/open "$target"
    failure
    exit 1
fi
if mv "$payload" "$target"; then
    if /usr/bin/open "$target"; then
        rm -rf "$staging"
        exit 0
    fi
    if ! mv "$target" "$payload"; then failure; exit 1; fi
fi
if mv "$backup" "$target"; then /usr/bin/open "$target"; fi
failure
exit 1
'''

_WINDOWS_HELPER = r'''$p = Get-Process -Id ([int]$env:NEUROEDIT_UPDATE_PID) -ErrorAction SilentlyContinue
function Show-Failure {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show('NeuroEdit could not install the update. Please download and install it manually.', 'NeuroEdit Update') | Out-Null
}
if ($p) {
    try { $p.WaitForExit(120000) | Out-Null } catch { Show-Failure; exit 1 }
    if (!$p.HasExited) { Show-Failure; exit 1 }
}
try {
    $dirArg = '/DIR="' + $env:NEUROEDIT_UPDATE_DIR + '"'
    $setup = Start-Process -FilePath $env:NEUROEDIT_UPDATE_SETUP -ArgumentList @($dirArg, '/SILENT', '/NORESTART', '/NOCLOSEAPPLICATIONS', '/NOFORCECLOSEAPPLICATIONS', '/NEUROEDIT_RESTART=1') -PassThru -ErrorAction Stop
    $setup.WaitForExit()
    if ($setup.ExitCode -ne 0) { throw 'Installer failed' }
    Remove-Item -LiteralPath $env:NEUROEDIT_UPDATE_STAGE -Recurse -Force -ErrorAction SilentlyContinue
} catch {
    $app = Join-Path $env:NEUROEDIT_UPDATE_DIR 'NeuroEdit.exe'
    if (Test-Path -LiteralPath $app -PathType Leaf) { Start-Process -FilePath $app -ErrorAction SilentlyContinue }
    Show-Failure
    exit 1
}
'''


def launch_prepared_install(prepared: PreparedInstall) -> None:
    """Start a helper only after the caller has accepted the normal close flow."""
    target = prepared.target
    if not target.supported or target.path is None:
        raise InstallError("Automatic installation is unavailable.")
    if target.platform == "darwin":
        subprocess.Popen(["/bin/sh", "-c", _MAC_HELPER, "neuroedit-update", str(os.getpid()), str(target.path), str(prepared.payload), str(prepared.staging)], start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif target.platform == "win32":
        env = os.environ.copy()
        env.update(NEUROEDIT_UPDATE_PID=str(os.getpid()), NEUROEDIT_UPDATE_DIR=str(target.path), NEUROEDIT_UPDATE_SETUP=str(prepared.payload), NEUROEDIT_UPDATE_STAGE=str(prepared.staging))
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        subprocess.Popen([str(powershell), "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", _WINDOWS_HELPER], env=env, creationflags=0x00000008 | 0x08000000, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        raise InstallError("This platform is not supported.")
