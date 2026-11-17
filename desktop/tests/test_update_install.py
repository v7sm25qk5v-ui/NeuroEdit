import hashlib
import plistlib
import stat
import subprocess
import zipfile
from types import SimpleNamespace

import pytest

from neuroedit_desktop import update_install as updater


def bundle_zip(path, extra=None, version="1.2.3"):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("NeuroEdit.app/Contents/Info.plist", plistlib.dumps({"CFBundleIdentifier": "org.neuroedit", "CFBundleExecutable": "NeuroEdit", "CFBundleShortVersionString": version}))
        executable = zipfile.ZipInfo("NeuroEdit.app/Contents/MacOS/NeuroEdit")
        executable.create_system = 3
        executable.external_attr = (stat.S_IFREG | 0o755) << 16
        z.writestr(executable, b"binary")
        z.writestr("NeuroEdit.app/Contents/Frameworks/Test.framework/Versions/A/Test", b"lib")
        link = zipfile.ZipInfo("NeuroEdit.app/Contents/Frameworks/Test.framework/Versions/Current")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(link, "A")
        if extra:
            z.writestr(*extra)


def release(path):
    return SimpleNamespace(tag_name="v1.2.3-alpha.2", asset=SimpleNamespace(sha256=hashlib.sha256(path.read_bytes()).hexdigest()))


def test_prepare_preserves_safe_framework_link_and_existing_app(tmp_path):
    asset = tmp_path / "update.zip"
    bundle_zip(asset)
    target = tmp_path / "NeuroEdit.app"
    target.mkdir()
    marker = target / "original"
    marker.write_text("untouched")
    prepared = updater.prepare_install(asset, release(asset), updater.InstallTarget("darwin", target))
    assert marker.read_text() == "untouched"
    assert (prepared.payload / "Contents/Frameworks/Test.framework/Versions/Current").is_symlink()
    assert (prepared.payload / "Contents/MacOS/NeuroEdit").stat().st_mode & stat.S_IXUSR
    updater.discard_prepared_install(prepared)
    assert not prepared.staging.exists()


@pytest.mark.parametrize("name", ["NeuroEdit.app/../../outside", "/NeuroEdit.app/absolute"])
def test_rejects_unsafe_archive_paths_and_cleans_staging(tmp_path, name):
    asset = tmp_path / "update.zip"
    bundle_zip(asset, extra=(name, b"bad"))
    with pytest.raises(updater.InstallError):
        updater.prepare_install(asset, release(asset), updater.InstallTarget("darwin", tmp_path / "NeuroEdit.app"))
    assert not list(tmp_path.glob(".neuroedit-update-*"))


def test_rejects_escaping_symlink(tmp_path):
    asset = tmp_path / "update.zip"
    link = zipfile.ZipInfo("NeuroEdit.app/Contents/escape")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    bundle_zip(asset, extra=(link, "../../../outside"))
    with pytest.raises(updater.InstallError, match="outside"):
        updater.prepare_install(asset, release(asset), updater.InstallTarget("darwin", tmp_path / "NeuroEdit.app"))


def test_digest_and_bundle_version_are_checked(tmp_path):
    asset = tmp_path / "update.zip"
    bundle_zip(asset, version="9.9.9")
    target = updater.InstallTarget("darwin", tmp_path / "NeuroEdit.app")
    info = release(asset)
    with pytest.raises(updater.InstallError, match="version"):
        updater.prepare_install(asset, info, target)
    info.asset.sha256 = "0" * 64
    with pytest.raises(updater.InstallError, match="integrity"):
        updater.prepare_install(asset, info, target)


def test_source_checkout_is_unsupported(monkeypatch):
    monkeypatch.setattr(updater.sys, "frozen", False, raising=False)
    assert not updater.inspect_install_target().supported


@pytest.fixture
def translocated_install(tmp_path, monkeypatch):
    running = tmp_path / "AppTranslocation" / "random" / "d" / "NeuroEdit.app"
    installed = tmp_path / "Applications" / "NeuroEdit.app"
    user_apps = tmp_path / "user" / "Applications"
    info = plistlib.dumps({"CFBundleIdentifier": "org.neuroedit", "CFBundleExecutable": "NeuroEdit", "CFBundleShortVersionString": "0.5.20"})
    for bundle in (running, installed):
        (bundle / "Contents/MacOS").mkdir(parents=True)
        (bundle / "Contents/Info.plist").write_bytes(info)
        executable = bundle / "Contents/MacOS/NeuroEdit"
        executable.write_bytes(b"the running application")
        executable.chmod(0o755)
    access = updater.os.access
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater.sys, "platform", "darwin")
    monkeypatch.setattr(updater.sys, "executable", str(running / "Contents/MacOS/NeuroEdit"))
    monkeypatch.setattr(updater, "_MAC_INSTALL_DIRS", (installed.parent, user_apps))
    monkeypatch.setattr(updater.os, "access", lambda path, mode: False if path == running.parent else access(path, mode))
    return running, installed, user_apps


@pytest.mark.parametrize("user_install", [False, True])
def test_translocated_app_updates_its_identical_installed_copy(translocated_install, tmp_path, user_install):
    running, installed, user_apps = translocated_install
    if user_install:
        user_apps.mkdir(parents=True)
        installed = installed.rename(user_apps / "NeuroEdit.app")
    target = updater.inspect_install_target()
    assert target.supported and target.path == installed
    asset = tmp_path / "update.zip"
    bundle_zip(asset)
    prepared = updater.prepare_install(asset, release(asset), target)
    assert prepared.staging.parent == installed.parent
    assert prepared.target.path == installed
    assert (installed / "Contents/MacOS/NeuroEdit").read_bytes() == b"the running application"
    assert (running / "Contents/MacOS/NeuroEdit").read_bytes() == b"the running application"
    updater.discard_prepared_install(prepared)


@pytest.mark.parametrize("difference", ["executable", "metadata", "missing", "ambiguous", "read_only", "symlink"])
def test_translocated_app_never_guesses_an_install_target(translocated_install, monkeypatch, difference):
    import shutil

    _, installed, user_apps = translocated_install
    if difference == "executable":
        (installed / "Contents/MacOS/NeuroEdit").write_bytes(b"a different application")
    elif difference == "metadata":
        path = installed / "Contents/Info.plist"
        info = plistlib.loads(path.read_bytes())
        info["CFBundleShortVersionString"] = "0.5.19"
        path.write_bytes(plistlib.dumps(info))
    elif difference == "missing":
        shutil.rmtree(installed)
    elif difference == "ambiguous":
        shutil.copytree(installed, user_apps / "NeuroEdit.app")
    elif difference == "read_only":
        access = updater.os.access
        monkeypatch.setattr(updater.os, "access", lambda path, mode: False if path == installed.parent else access(path, mode))
    elif difference == "symlink":
        other = installed.with_name("Other.app")
        installed.rename(other)
        installed.symlink_to(other, target_is_directory=True)
    assert not updater.inspect_install_target().supported


def test_writable_running_app_does_not_search_other_installations(translocated_install, monkeypatch):
    running, _, _ = translocated_install
    monkeypatch.setattr(updater.os, "access", lambda path, mode: True)
    monkeypatch.setattr(updater, "_installed_mac_copy", lambda path: pytest.fail("already writable"))
    target = updater.inspect_install_target()
    assert target.supported and target.path == running


def test_windows_launch_is_detached_and_waits_for_pid(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))
    prepared = updater.PreparedInstall(updater.InstallTarget("win32", tmp_path / "install here"), tmp_path, tmp_path / "setup.exe")
    updater.launch_prepared_install(prepared)
    args, options = calls[0]
    assert args[0][0].replace("\\", "/").endswith("System32/WindowsPowerShell/v1.0/powershell.exe")
    assert "WaitForExit" in args[0][-1]
    assert "/NEUROEDIT_RESTART=1" in args[0][-1]
    assert "-PassThru -ErrorAction Stop" in args[0][-1]
    assert "$setup.WaitForExit()" in args[0][-1]
    assert "if ($setup.ExitCode -ne 0)" in args[0][-1]
    assert "Start-Process -FilePath $app" in args[0][-1]
    assert "Show-Failure" in args[0][-1]
    assert options["env"]["NEUROEDIT_UPDATE_DIR"] == str(tmp_path / "install here")
    assert "-ExecutionPolicy" not in args[0]


def test_mac_helper_replaces_only_after_process_exit(tmp_path):
    target = tmp_path / "NeuroEdit.app"
    target.mkdir()
    (target / "old").write_text("old")
    staging = tmp_path / "stage"
    staging.mkdir()
    payload = staging / "NeuroEdit.app"
    payload.mkdir()
    (payload / "new").write_text("new")
    opener = tmp_path / "open"
    opener.write_text("#!/bin/sh\nexit 0\n")
    opener.chmod(0o755)
    helper = updater._MAC_HELPER.replace("/usr/bin/open", str(opener)).replace("/usr/bin/osascript", "/usr/bin/true")
    subprocess.run(["/bin/sh", "-c", helper, "test", "99999999", str(target), str(payload), str(staging)], check=True)
    assert (target / "new").read_text() == "new"
    assert not staging.exists()


def test_mac_helper_rolls_back_when_relaunch_fails(tmp_path):
    target = tmp_path / "NeuroEdit.app"
    target.mkdir()
    (target / "old").write_text("old")
    staging = tmp_path / "stage"
    staging.mkdir()
    payload = staging / "NeuroEdit.app"
    payload.mkdir()
    (payload / "new").write_text("new")
    opener = tmp_path / "open"
    opener.write_text("#!/bin/sh\nexit 1\n")
    opener.chmod(0o755)
    helper = updater._MAC_HELPER.replace("/usr/bin/open", str(opener)).replace("/usr/bin/osascript", "/usr/bin/true")
    subprocess.run(["/bin/sh", "-c", helper, "test", "99999999", str(target), str(payload), str(staging)], check=False)
    assert (target / "old").read_text() == "old"
    assert (payload / "new").read_text() == "new"


def test_mac_helper_reopens_original_if_initial_move_fails(tmp_path):
    target = tmp_path / "NeuroEdit.app"
    target.mkdir()
    (target / "old").write_text("old")
    staging = tmp_path / "stage"
    staging.mkdir()
    payload = staging / "NeuroEdit.app"
    payload.mkdir()
    marker = tmp_path / "reopened"
    opener = tmp_path / "open"
    opener.write_text(f'#!/bin/sh\ntouch "{marker}"\n')
    opener.chmod(0o755)
    helper = updater._MAC_HELPER.replace("/usr/bin/open", str(opener)).replace("/usr/bin/osascript", "/usr/bin/true")
    helper = helper.replace('mv "$target" "$backup"', "false", 1)
    result = subprocess.run(["/bin/sh", "-c", helper, "test", "99999999", str(target), str(payload), str(staging)], check=False)
    assert result.returncode == 1
    assert marker.exists()
    assert (target / "old").read_text() == "old"
    assert staging.exists()
