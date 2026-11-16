"""NE-013 (output on another volume) and NE-023 (shared, validated ffmpeg resolver)."""
from __future__ import annotations

import errno
import os
import stat
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from neuroedit_desktop import exporter as exporter_module
from neuroedit_desktop.exporter import ExportCancelled, ExportSettings, ProjectExporter
from neuroedit_desktop.models import ProjectState


@pytest.fixture(scope="module")
def qt_app():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _fresh_ffmpeg_cache():
    exporter_module.reset_ffmpeg_cache()
    yield
    exporter_module.reset_ffmpeg_cache()


# ---------------------------------------------------------------- NE-013

def _image_project(tmp_path) -> ProjectState:
    image = tmp_path / "white.png"
    cv2.imwrite(str(image), np.full((64, 64, 3), 255, dtype=np.uint8))
    project = ProjectState()
    project.add_image_clip(image, 64, 64, display_duration=0.3)
    return project


def _exdev_across_dirs(monkeypatch):
    real = os.replace
    calls = []

    def fake(src, dst, *a, **k):
        calls.append((str(src), str(dst)))
        if Path(src).parent != Path(dst).parent:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(exporter_module.os, "replace", fake)
    return calls


def _export(tmp_path, monkeypatch, out_dir, **kwargs):
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "out.mp4"
    exporter = ProjectExporter(
        _image_project(tmp_path), ExportSettings(out, 64, 64, 30, 20, "test"), **kwargs
    )
    monkeypatch.setattr(
        exporter, "_encoder_args", lambda _f: ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
    )
    return exporter, out


def test_export_lands_when_replace_crosses_volumes(qt_app, tmp_path, monkeypatch):
    _exdev_across_dirs(monkeypatch)
    exporter, out = _export(tmp_path, monkeypatch, tmp_path / "ext")
    exporter.export()
    assert out.stat().st_size > 0
    assert cv2.VideoCapture(str(out)).isOpened()
    assert [p.name for p in out.parent.iterdir()] == ["out.mp4"]


def test_exdev_replaces_existing_output_only_with_complete_file(qt_app, tmp_path, monkeypatch):
    _exdev_across_dirs(monkeypatch)
    exporter, out = _export(tmp_path, monkeypatch, tmp_path / "ext")
    out.write_bytes(b"old")
    exporter.export()
    assert out.read_bytes() != b"old"
    assert [p.name for p in out.parent.iterdir()] == ["out.mp4"]


def test_failed_copy_keeps_old_output_and_leaves_no_partial(qt_app, tmp_path, monkeypatch):
    _exdev_across_dirs(monkeypatch)

    def boom(src, dst, *a, **k):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(exporter_module.shutil, "copymode", boom)
    exporter, out = _export(tmp_path, monkeypatch, tmp_path / "ext")
    out.write_bytes(b"old")
    with pytest.raises(OSError):
        exporter.export()
    assert out.read_bytes() == b"old"
    assert [p.name for p in out.parent.iterdir()] == ["out.mp4"]


def _staged(dir_: Path):
    return [p for p in dir_.iterdir() if p.name != "out.mp4"]


def test_cancel_leaves_nothing_in_output_dir(qt_app, tmp_path, monkeypatch):
    _exdev_across_dirs(monkeypatch)
    exporter, out = _export(tmp_path, monkeypatch, tmp_path / "ext", cancelled=lambda: True)
    with pytest.raises(ExportCancelled):
        exporter.export()
    assert list(out.parent.iterdir()) == []


def test_mux_path_survives_exdev(qt_app, tmp_path, monkeypatch):
    import wave

    wav = tmp_path / "a.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 4000)
    from neuroedit_desktop.models import AudioTrack

    project = _image_project(tmp_path)
    project.audio_tracks.append(AudioTrack(id="t", name="n", path=str(wav), duration=0.5))
    _exdev_across_dirs(monkeypatch)
    out_dir = tmp_path / "ext"
    out_dir.mkdir()
    out = out_dir / "out.mp4"
    exporter = ProjectExporter(project, ExportSettings(out, 64, 64, 30, 20, "test"))
    monkeypatch.setattr(
        exporter, "_encoder_args", lambda _f: ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
    )
    exporter.export()
    assert out.stat().st_size > 0
    assert [p.name for p in out_dir.iterdir()] == ["out.mp4"]


def _pair(tmp_path, size=10, name="out.mp4"):
    src = tmp_path / "tmpdir" / "visual.mp4"
    src.parent.mkdir(exist_ok=True)
    src.write_bytes(b"x" * size)
    dest_dir = tmp_path / "ext2"
    dest_dir.mkdir(exist_ok=True)
    return src, dest_dir / name


def test_cancel_during_cross_volume_copy(tmp_path, monkeypatch):
    _exdev_across_dirs(monkeypatch)
    monkeypatch.setattr(exporter_module, "_COPY_CHUNK", 4)
    src, dest = _pair(tmp_path)
    dest.write_bytes(b"old")
    polls = []

    def cancelled():
        polls.append(1)
        return len(polls) > 1  # allow the first chunk, then cancel

    with pytest.raises(ExportCancelled):
        exporter_module._publish_file(src, dest, cancelled)
    assert len(polls) == 2
    assert dest.read_bytes() == b"old"
    assert [p.name for p in dest.parent.iterdir()] == ["out.mp4"]
    # Source is left for the caller's TemporaryDirectory, like a same-volume cancel.
    assert src.exists()


def test_other_staged_files_and_unrelated_dotfiles_are_kept(tmp_path, monkeypatch):
    _exdev_across_dirs(monkeypatch)
    src, dest = _pair(tmp_path)
    stale = dest.parent / ".neuroedit-export-abcd1234.partial"
    stale.write_bytes(b"half")
    other = dest.parent / ".DS_Store"
    other.write_bytes(b"keep")
    other2 = dest.parent / ".out.mp4.partial"
    other2.write_bytes(b"keep")
    exporter_module._publish_file(src, dest)
    assert stale.read_bytes() == b"half"
    assert other.exists() and other2.exists()
    assert dest.read_bytes() == b"x" * 10


def test_long_output_name_cross_volume(tmp_path, monkeypatch):
    _exdev_across_dirs(monkeypatch)
    src, dest = _pair(tmp_path, name="a" * 236 + ".mp4")
    exporter_module._publish_file(src, dest)
    assert dest.read_bytes() == b"x" * 10


def test_cross_volume_publish_mode_and_source_removed(tmp_path, monkeypatch):
    _exdev_across_dirs(monkeypatch)
    src, dest = _pair(tmp_path)
    src.chmod(0o644)
    exporter_module._publish_file(src, dest)
    assert (dest.stat().st_mode & 0o777) == 0o644
    assert not src.exists()


def test_non_exdev_error_is_raised_without_copy(tmp_path, monkeypatch):
    src, dest = _pair(tmp_path)

    def deny(*a, **k):
        raise OSError(errno.EACCES, "denied")

    monkeypatch.setattr(exporter_module.os, "replace", deny)
    monkeypatch.setattr(
        exporter_module.tempfile, "mkstemp", lambda *a, **k: pytest.fail("copy path taken")
    )
    with pytest.raises(OSError) as info:
        exporter_module._publish_file(src, dest)
    assert info.value.errno == errno.EACCES
    assert src.exists()


# ---------------------------------------------------------------- NE-023

def _script(path: Path, body: str) -> str:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def _good(path: Path) -> str:
    return _script(path, "#!/bin/sh\necho ffmpeg version test\nexit 0\n")


def _bad_cpu(path: Path) -> str:
    # Not a valid executable image: exec fails with ENOEXEC, like "Bad CPU type".
    path.write_bytes(b"\x00\x01\x02not-an-executable")
    path.chmod(0o755)
    return str(path)


@pytest.mark.skipif(sys.platform == "win32", reason="posix shell scripts")
def test_unrunnable_path_ffmpeg_is_skipped_for_working_one(tmp_path, monkeypatch):
    bad_dir, good_dir = tmp_path / "bad", tmp_path / "good"
    bad_dir.mkdir()
    good_dir.mkdir()
    _bad_cpu(bad_dir / "ffmpeg")
    good = _good(good_dir / "ffmpeg")
    monkeypatch.setattr(exporter_module, "_bundled_ffmpeg", lambda: None)
    monkeypatch.setenv("PATH", f"{bad_dir}{os.pathsep}{good_dir}")
    assert exporter_module.resolve_ffmpeg() == good


@pytest.mark.skipif(sys.platform == "win32", reason="posix shell scripts")
def test_bundled_is_preferred_over_path(tmp_path, monkeypatch):
    bundled = _good(tmp_path / "bundled")
    (tmp_path / "p").mkdir()
    _good(tmp_path / "p" / "ffmpeg")
    monkeypatch.setattr(exporter_module, "_bundled_ffmpeg", lambda: bundled)
    monkeypatch.setenv("PATH", str(tmp_path / "p"))
    assert exporter_module.resolve_ffmpeg() == bundled


@pytest.mark.skipif(sys.platform == "win32", reason="posix shell scripts")
def test_broken_bundled_falls_back_to_path(tmp_path, monkeypatch):
    bundled = _bad_cpu(tmp_path / "bundled")
    (tmp_path / "p").mkdir()
    good = _good(tmp_path / "p" / "ffmpeg")
    monkeypatch.setattr(exporter_module, "_bundled_ffmpeg", lambda: bundled)
    monkeypatch.setenv("PATH", str(tmp_path / "p"))
    assert exporter_module.resolve_ffmpeg() == good


def test_no_working_ffmpeg_gives_clear_error(tmp_path, monkeypatch):
    (tmp_path / "p").mkdir()
    _bad_cpu(tmp_path / "p" / "ffmpeg")
    monkeypatch.setattr(exporter_module, "_bundled_ffmpeg", lambda: None)
    monkeypatch.setenv("PATH", str(tmp_path / "p"))
    assert exporter_module.resolve_ffmpeg() is None
    with pytest.raises(RuntimeError, match="(?i)no working ffmpeg"):
        exporter_module.require_ffmpeg()


@pytest.mark.skipif(sys.platform == "win32", reason="posix shell scripts")
def test_resolution_is_cached_and_shared(tmp_path, monkeypatch, qt_app):
    good = _good(tmp_path / "bundled")
    monkeypatch.setattr(exporter_module, "_bundled_ffmpeg", lambda: good)
    runs = []
    real = exporter_module._ffmpeg_runs
    monkeypatch.setattr(exporter_module, "_ffmpeg_runs", lambda p: runs.append(p) or real(p))
    exporter = ProjectExporter(ProjectState(), ExportSettings(tmp_path / "o.mp4", 64, 64, 30, 20, "t"))
    assert exporter._find_ffmpeg() == good
    assert exporter._find_ffmpeg() == good
    assert exporter_module.resolve_ffmpeg() == good
    assert runs == [good]


@pytest.mark.skipif(sys.platform == "win32", reason="posix shell scripts")
def test_failure_is_not_cached_and_recovers(tmp_path, monkeypatch):
    good = _good(tmp_path / "bundled")
    monkeypatch.setattr(exporter_module, "_bundled_ffmpeg", lambda: good)
    monkeypatch.setenv("PATH", "")
    state = {"ok": False}
    runs = []

    def runs_fn(path):
        runs.append(path)
        return state["ok"]

    monkeypatch.setattr(exporter_module, "_ffmpeg_runs", runs_fn)
    assert exporter_module.resolve_ffmpeg() is None
    state["ok"] = True
    assert exporter_module.resolve_ffmpeg() == good
    assert len(runs) == 2
    assert exporter_module.resolve_ffmpeg() == good
    assert len(runs) == 2


@pytest.mark.skipif(sys.platform == "win32", reason="posix shell scripts")
def test_relative_path_entry_gives_absolute_candidate(tmp_path, monkeypatch):
    (tmp_path / "rel").mkdir()
    _good(tmp_path / "rel" / "ffmpeg")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "rel")
    found = exporter_module._path_ffmpegs()
    assert found and all(os.path.isabs(p) for p in found)


@pytest.mark.skipif(sys.platform == "win32", reason="posix shell scripts")
def test_ffmpeg_runs_rejects_nonzero_exit(tmp_path):
    ok = _good(tmp_path / "ok")
    fail = _script(tmp_path / "fail", "#!/bin/sh\nexit 3\n")
    assert exporter_module._ffmpeg_runs(ok) is True
    assert exporter_module._ffmpeg_runs(fail) is False


def test_audio_panel_probe_uses_require_ffmpeg(tmp_path, monkeypatch):
    import imageio_ffmpeg
    import shutil

    from neuroedit_desktop.ui import audio_panel

    seen = []
    monkeypatch.setattr(exporter_module, "require_ffmpeg", lambda: "/sentinel/ffmpeg")
    monkeypatch.setattr(imageio_ffmpeg, "get_ffmpeg_exe", lambda: pytest.fail("bypassed resolver"))
    monkeypatch.setattr(shutil, "which", lambda *a, **k: pytest.fail("bypassed resolver"))

    class Proc:
        stderr = "Duration: 00:00:02.50, start\n  Stream #0:0: Audio: aac\n"

    def fake_run(cmd, *a, **k):
        seen.append(cmd[0])
        return Proc()

    monkeypatch.setattr(audio_panel.subprocess, "run", fake_run)
    duration = audio_panel.AudioPanel._ffmpeg_audio_duration(None, tmp_path / "a.m4a")
    assert seen == ["/sentinel/ffmpeg"]
    assert duration == pytest.approx(2.5)
