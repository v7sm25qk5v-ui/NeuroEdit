"""Export engine pipeline: progress, instant cancel, pre-flight checks, fewer passes,
plain-language errors and the stale temp sweep (export review findings 9-17)."""
from __future__ import annotations

import errno
import os
import stat
import subprocess
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("cv2")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from neuroedit_desktop import exporter as exporter_module  # noqa: E402
from neuroedit_desktop.exporter import (  # noqa: E402
    ExportCancelled,
    ExportError,
    ExportSettings,
    ProjectExporter,
    TimelineSegment,
    resolve_ffmpeg,
    sweep_stale_export_temp,
)
from neuroedit_desktop.models import ProjectState  # noqa: E402

SLOW = ["-c:v", "libx264", "-preset", "slow", "-crf", "20"]
VERY_SLOW = ["-c:v", "libx264", "-preset", "veryslow", "-crf", "12"]


@pytest.fixture(scope="module")
def qt_app():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def ffmpeg():
    path = resolve_ffmpeg()
    if path is None:
        pytest.skip("FFmpeg is required")
    return path


def _make_source(ffmpeg, path: Path, seconds=3, size="320x180", audio=True) -> Path:
    cmd = [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={size}:r=30:d={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast"]
    if audio:
        cmd += ["-c:a", "aac", "-shortest"]
    subprocess.run([*cmd, str(path)], check=True, timeout=60)
    return path


def _exporter(project, out: Path, monkeypatch, encoder=SLOW, size=(320, 180), **kwargs) -> ProjectExporter:
    exporter = ProjectExporter(project, ExportSettings(out, *size, 30, 20, "test"), **kwargs)
    monkeypatch.setattr(exporter, "_encoder_args", lambda _ffmpeg: list(encoder))
    return exporter


def _spy_ffmpeg_runs(exporter, monkeypatch) -> list[list[str]]:
    commands: list[list[str]] = []
    real = exporter._run_ffmpeg

    def spy(cmd, *args, **kwargs):
        commands.append(list(cmd))
        return real(cmd, *args, **kwargs)

    monkeypatch.setattr(exporter, "_run_ffmpeg", spy)
    return commands


def _stream_kinds(ffmpeg, path: Path) -> str:
    return subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True, timeout=30
    ).stderr


def _moov_before_mdat(path: Path) -> bool:
    data = path.read_bytes()
    return 0 <= data.find(b"moov") < data.find(b"mdat")


# ------------------------------------------------------------ 1. progress

def test_progress_advances_inside_an_ffmpeg_segment(qt_app, tmp_path, monkeypatch, ffmpeg):
    source = _make_source(ffmpeg, tmp_path / "long.mp4", seconds=12, audio=False)
    project = ProjectState()
    project.add_clip(source, 12, 320, 180)
    events: list[tuple[float, int, str]] = []
    exporter = _exporter(
        project, tmp_path / "out.mp4", monkeypatch, encoder=VERY_SLOW, size=(640, 360),
        progress=lambda pct, msg: events.append((time.monotonic(), pct, msg)),
    )
    exporter.export()
    pcts = [pct for _t, pct, _m in events]
    assert pcts == sorted(pcts), "progress must never go backwards"
    assert pcts[-1] == 100
    inside = [pct for pct in pcts if 1 < pct < 95]
    assert len(set(inside)) >= 3, f"an untouched clip must report while encoding: {pcts}"
    messages = [m for _t, p, m in events if 1 < p < 95]
    assert all(m.startswith("Exporting… ") and " of 0:12" in m for m in messages), messages
    assert "segment" not in " ".join(messages).lower()
    stamps = [t for t, _p, _m in events]
    assert len(events) <= (stamps[-1] - stamps[0]) * 10 + 8, "updates are limited to ~10/s"


def test_progress_is_monotonic_across_render_and_video_segments(qt_app, tmp_path, monkeypatch, ffmpeg):
    source = _make_source(ffmpeg, tmp_path / "s.mp4", seconds=3)
    project = ProjectState()
    project.add_clip(source, 3, 320, 180)
    project.add_clip(source, 3, 320, 180)
    project.clips[1].fade_in = 1.0  # forces a rendered segment after the fast one
    events: list[int] = []
    exporter = _exporter(project, tmp_path / "out.mp4", monkeypatch, progress=lambda p, _m: events.append(p))
    exporter.export()
    assert events == sorted(events) and events[-1] == 100 and events[0] == 0


# ------------------------------------------------------------ 2. cancel

def _cancel_after(delay_s: float):
    state = {"flag": False, "at": 0.0}

    def fire():
        state["at"] = time.monotonic()
        state["flag"] = True

    timer = threading.Timer(delay_s, fire)
    return state, timer


@pytest.mark.parametrize("kind", ["video", "render"])
def test_cancel_during_real_encode_returns_within_a_second(qt_app, tmp_path, monkeypatch, ffmpeg, kind):
    project = ProjectState()
    if kind == "video":
        source = _make_source(ffmpeg, tmp_path / "s.mp4", seconds=20, audio=False)
        project.add_clip(source, 20, 320, 180)
        monkeypatch.setattr(exporter_module.ProjectExporter, "_has_encoder", lambda *_a: False)
    else:
        image = tmp_path / "w.png"
        import cv2

        cv2.imwrite(str(image), np.random.randint(0, 255, (360, 640, 3), dtype=np.uint8))
        project.add_image_clip(image, 640, 360, display_duration=60)
    out = tmp_path / "dest" / "out.mp4"
    state, timer = _cancel_after(0.8)
    exporter = _exporter(
        project, out, monkeypatch, encoder=VERY_SLOW, size=(1280, 720), cancelled=lambda: state["flag"]
    )
    timer.start()
    try:
        with pytest.raises(ExportCancelled):
            exporter.export()
        latency = time.monotonic() - state["at"]
    finally:
        timer.cancel()
    assert state["flag"], "the encode finished before the cancel could fire"
    assert latency < 1.0, f"cancel took {latency:.2f}s"
    assert list(out.parent.iterdir()) == []  # no partial left in the destination


def test_probes_poll_cancel_and_do_not_wait_for_a_slow_ffmpeg(qt_app, tmp_path):
    slow = tmp_path / "slow_ffmpeg"
    slow.write_text("#!/bin/sh\nsleep 30\n")
    slow.chmod(slow.stat().st_mode | stat.S_IXUSR)
    state, timer = _cancel_after(0.3)
    exporter = ProjectExporter(
        ProjectState(), ExportSettings(tmp_path / "o.mp4", 64, 64, 30, 20, "t"),
        cancelled=lambda: state["flag"],
    )
    exporter_module.reset_ffmpeg_cache()
    timer.start()
    started = time.monotonic()
    with pytest.raises(ExportCancelled):
        exporter._has_encoder(str(slow), "h264_videotoolbox")
    assert time.monotonic() - started < 1.0
    state["flag"] = False
    state2, timer2 = _cancel_after(0.3)
    exporter.cancelled = lambda: state2["flag"]
    timer2.start()
    started = time.monotonic()
    with pytest.raises(ExportCancelled):
        exporter._has_audio_stream(tmp_path / "x.mp4", str(slow))
    assert time.monotonic() - started < 1.0
    timer.cancel()
    timer2.cancel()


def test_encoder_probe_runs_once_per_session(qt_app, tmp_path, monkeypatch, ffmpeg):
    exporter_module.reset_ffmpeg_cache()
    runs = []
    real = subprocess.Popen

    def counting(cmd, *a, **k):
        runs.append(cmd)
        return real(cmd, *a, **k)

    monkeypatch.setattr(exporter_module.subprocess, "Popen", counting)
    settings = ExportSettings(tmp_path / "o.mp4", 64, 64, 30, 20, "t")
    first = ProjectExporter(ProjectState(), settings)
    second = ProjectExporter(ProjectState(), settings)
    answer = first._has_encoder(ffmpeg, "libx264")
    assert second._has_encoder(ffmpeg, "libx264") == answer
    assert first._has_encoder(ffmpeg, "libx264") == answer
    assert len(runs) == 1
    exporter_module.reset_ffmpeg_cache()


# ------------------------------------------------------------ 3. checks

def test_unwritable_destination_is_reported_before_encoding(qt_app, tmp_path, monkeypatch, ffmpeg):
    source = _make_source(ffmpeg, tmp_path / "s.mp4", audio=False)
    project = ProjectState()
    project.add_clip(source, 3, 320, 180)
    locked = tmp_path / "Locked Folder"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        if os.access(locked, os.W_OK):
            pytest.skip("directory permissions are not enforced here")
        exporter = _exporter(project, locked / "out.mp4", monkeypatch)
        commands = _spy_ffmpeg_runs(exporter, monkeypatch)
        with pytest.raises(ExportError) as raised:
            exporter.export()
    finally:
        locked.chmod(0o700)
    assert str(raised.value) == "NeuroEdit can't save to “Locked Folder”. Choose another folder."
    assert raised.value.details
    assert commands == []


def test_not_enough_space_is_reported_with_sizes(qt_app, tmp_path, monkeypatch, ffmpeg):
    source = _make_source(ffmpeg, tmp_path / "s.mp4", audio=False)
    project = ProjectState()
    project.add_clip(source, 3, 320, 180)
    usage = type("Usage", (), {"free": 100 * 1024 * 1024, "total": 1, "used": 1})
    monkeypatch.setattr(exporter_module.shutil, "disk_usage", lambda _p: usage)
    exporter = _exporter(project, tmp_path / "out.mp4", monkeypatch)
    commands = _spy_ffmpeg_runs(exporter, monkeypatch)
    with pytest.raises(ExportError) as raised:
        exporter.export()
    message = str(raised.value)
    assert message.startswith("This export needs about ")
    assert "of free space on “" in message and "but only 100.0 MB is available" in message
    assert message.endswith("Free up space or choose another location.")
    assert commands == []


def test_same_volume_needs_final_plus_temp_space(qt_app, tmp_path, monkeypatch, ffmpeg):
    if os.stat(tmp_path).st_dev != os.stat(tempfile.gettempdir()).st_dev:
        pytest.skip("destination and temp are on different volumes here")
    project = ProjectState()
    project.add_image_clip(_png(tmp_path), 64, 64, display_duration=100)
    seen = []

    class Usage:
        free = 10**15

    monkeypatch.setattr(exporter_module.shutil, "disk_usage", lambda p: seen.append(p) or Usage)
    exporter = _exporter(project, tmp_path / "out.mp4", monkeypatch, size=(1920, 1080))
    exporter._check_free_space(tmp_path / "out.mp4", 100.0, False)
    assert len(seen) == 1  # one volume: one combined requirement
    from neuroedit_desktop.export_plan import estimate_output_bytes

    one = estimate_output_bytes(1920, 1080, 100.0, audio_kbps=None)
    monkeypatch.setattr(exporter_module.shutil, "disk_usage", lambda p: type("U", (), {"free": int(one * 1.5)}))
    with pytest.raises(ExportError, match="needs about"):
        exporter._check_free_space(tmp_path / "out.mp4", 100.0, False)  # 2x + margin > 1.5x


def _png(tmp_path) -> Path:
    import cv2

    path = tmp_path / "w.png"
    cv2.imwrite(str(path), np.full((64, 64, 3), 255, dtype=np.uint8))
    return path


def test_icloud_sources_are_downloaded_first_with_a_message(qt_app, tmp_path, monkeypatch, ffmpeg):
    source = _make_source(ffmpeg, tmp_path / "s.mp4", audio=False)
    project = ProjectState()
    clip = project.add_clip(source, 3, 320, 180)
    clip.name = "Case 12 intro"
    monkeypatch.setattr(exporter_module, "is_dataless", lambda p: Path(p) == source)
    events: list[tuple[int, str]] = []
    exporter = _exporter(project, tmp_path / "out.mp4", monkeypatch, progress=lambda p, m: events.append((p, m)))
    exporter.export()
    downloads = [(p, m) for p, m in events if "iCloud" in m]
    assert downloads == [(0, "Downloading Case 12 intro from iCloud…")]
    assert events.index(downloads[0]) < next(i for i, (_p, m) in enumerate(events) if m.startswith("Exporting"))


def test_icloud_read_failure_names_the_clip(qt_app, tmp_path, monkeypatch, ffmpeg):
    source = _make_source(ffmpeg, tmp_path / "s.mp4", audio=False)
    project = ProjectState()
    project.add_clip(source, 3, 320, 180).name = "Case 12 intro"
    monkeypatch.setattr(exporter_module, "is_dataless", lambda p: True)

    def timeout_open(*_a, **_k):
        raise OSError(errno.ETIMEDOUT, "Operation timed out")

    monkeypatch.setattr(exporter_module, "open", timeout_open, raising=False)
    exporter = _exporter(project, tmp_path / "out.mp4", monkeypatch)
    commands = _spy_ffmpeg_runs(exporter, monkeypatch)
    with pytest.raises(ExportError) as raised:
        exporter.export()
    assert "“Case 12 intro”" in str(raised.value)
    assert "timed out" in raised.value.details
    assert commands == []


def test_icloud_download_polls_cancel_between_chunks(qt_app, tmp_path, monkeypatch, ffmpeg):
    source = tmp_path / "big.mp4"
    source.write_bytes(b"x" * 100)
    project = ProjectState()
    project.add_clip(source, 3, 320, 180)
    monkeypatch.setattr(exporter_module, "is_dataless", lambda p: True)
    monkeypatch.setattr(exporter_module, "CHUNK_BYTES", 10)
    polls = []

    def cancelled():
        polls.append(1)
        return len(polls) >= 3

    exporter = _exporter(project, tmp_path / "out.mp4", monkeypatch, cancelled=cancelled)
    with pytest.raises(ExportCancelled):
        exporter.export()
    assert len(polls) == 3


# ------------------------------------------------------------ 4. passes

def test_join_and_audio_mix_are_one_pass_and_faststart_only_on_the_final_file(
    qt_app, tmp_path, monkeypatch, ffmpeg
):
    source = _make_source(ffmpeg, tmp_path / "s.mp4", seconds=3, audio=True)
    project = ProjectState()
    project.add_clip(source, 3, 320, 180)
    project.add_clip(source, 3, 320, 180)
    out_dir = tmp_path / "dest"
    out_dir.mkdir()
    out = out_dir / "out.mp4"
    exporter = _exporter(project, out, monkeypatch)
    commands = _spy_ffmpeg_runs(exporter, monkeypatch)
    exporter.export()
    assert len(commands) == 3  # two segments + ONE join-and-mix pass
    assert all("+faststart" not in cmd for cmd in commands[:2])
    final = commands[2]
    assert "+faststart" in final and "concat" in final
    assert "-c:v" in final and final[final.index("-c:v") + 1] == "copy"
    assert "-filter_complex" in final
    for flag in ("-map_metadata", "-map_chapters"):
        assert final[final.index(flag) + 1] == "-1"
    # Written straight into the destination folder as a hidden partial.
    target = Path(final[-1])
    assert target.parent == out_dir and target.name == ".out.mp4.neuroedit-partial"
    assert final[-3:-1] == ["-f", "mp4"]
    assert [p.name for p in out_dir.iterdir()] == ["out.mp4"]
    info = _stream_kinds(ffmpeg, out)
    assert "Audio: aac" in info and "Video: h264" in info
    assert "Duration: 00:00:06" in info
    assert _moov_before_mdat(out)


def test_untouched_clip_without_audio_is_a_single_ffmpeg_run(qt_app, tmp_path, monkeypatch, ffmpeg):
    source = _make_source(ffmpeg, tmp_path / "s.mp4", seconds=2, audio=True)
    project = ProjectState()
    project.add_clip(source, 2, 320, 180)
    out = tmp_path / "out.mp4"
    exporter = _exporter(project, out, monkeypatch)
    exporter.settings = ExportSettings(out, 320, 180, 30, 20, "t", mute_source_audio=True)
    commands = _spy_ffmpeg_runs(exporter, monkeypatch)
    exporter.export()
    assert len(commands) == 1 and "+faststart" in commands[0]
    assert "Audio:" not in _stream_kinds(ffmpeg, out)
    assert _moov_before_mdat(out)
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".")] == []


def test_overwrite_stays_atomic_and_cancel_keeps_old_file(qt_app, tmp_path, monkeypatch, ffmpeg):
    source = _make_source(ffmpeg, tmp_path / "s.mp4", seconds=2, audio=False)
    project = ProjectState()
    project.add_clip(source, 2, 320, 180)
    out = tmp_path / "out.mp4"
    out.write_bytes(b"old")
    seen_during = []
    real_replace = os.replace

    def watching(src, dst, *a, **k):
        seen_during.append((Path(src).name, out.read_bytes()))
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(exporter_module.os, "replace", watching)
    _exporter(project, out, monkeypatch).export()
    assert seen_during == [(".out.mp4.neuroedit-partial", b"old")]  # old file intact until the rename
    assert out.read_bytes() != b"old"

    out.write_bytes(b"old")
    exporter = _exporter(project, out, monkeypatch, cancelled=lambda: True)
    with pytest.raises(ExportCancelled):
        exporter.export()
    assert out.read_bytes() == b"old"
    assert [p.name for p in tmp_path.iterdir() if p.name != "s.mp4"] == ["out.mp4"]


def test_faststart_not_applied_to_intermediate_segments(qt_app, tmp_path, monkeypatch, ffmpeg):
    exporter = _exporter(ProjectState(), tmp_path / "o.mp4", monkeypatch)
    commands = _spy_ffmpeg_runs(exporter, monkeypatch)
    monkeypatch.setattr(exporter, "_render_frame", lambda _t: np.zeros((180, 320, 3), np.uint8))
    segment = TimelineSegment(0, 0.2, "render")
    spawned: list[list[str]] = []
    real = subprocess.Popen
    monkeypatch.setattr(
        exporter_module.subprocess, "Popen", lambda cmd, *a, **k: spawned.append(cmd) or real(cmd, *a, **k)
    )
    exporter._encode_render_segment_with_ffmpeg(segment, tmp_path / "seg.mp4", ffmpeg, 0, 1)
    exporter._encode_render_segment_with_ffmpeg(segment, tmp_path / "fin.mp4", ffmpeg, 0, 1, final=True)
    assert "+faststart" not in spawned[0] and "+faststart" in spawned[1]
    assert commands == []


# ------------------------------------------------------------ 5. errors

def test_error_mapping_is_plain_and_keeps_raw_text_in_details():
    no_space = exporter_module._error_from_text("av_interleaved_write_frame(): No space left on device", "x")
    assert "ran out of disk space" in str(no_space) and "No space left" in no_space.details
    denied = exporter_module._error_from_text("/Volumes/USB/out.mp4: Permission denied", "x")
    assert "isn't allowed to save" in str(denied) and "Permission denied" in denied.details
    bad = exporter_module._error_from_text(
        "[mov,mp4 @ 0x1] moov atom not found\n/a/b.mp4: Invalid data found", "x", "Case 12", "/a/b.mp4"
    )
    assert str(bad) == "“Case 12” can't be read. It may be damaged or still copying."
    assert "moov atom" in bad.details and "moov atom" not in str(bad)
    unreadable_source = exporter_module._error_from_text("/a/b.mp4: Permission denied", "x", "Case 12", "/a/b.mp4")
    assert "“Case 12” can't be read" in str(unreadable_source)
    other = exporter_module._error_from_text("Unknown encoder 'zzz'", "FFmpeg video export failed")
    assert "Unknown encoder 'zzz'" in str(other)
    assert isinstance(other, RuntimeError)
    assert ExportError("m").details == ""


def test_os_errors_get_plain_messages(tmp_path):
    full = exporter_module._error_from_oserror(OSError(errno.ENOSPC, "No space left on device"))
    assert full is not None and "ran out of disk space" in str(full)
    denied = exporter_module._error_from_oserror(OSError(errno.EACCES, "denied"), tmp_path / "Reports")
    assert str(denied) == "NeuroEdit can't save to “Reports”. Choose another folder."
    assert exporter_module._error_from_oserror(OSError(errno.ENOENT, "gone")) is None


def test_damaged_source_names_the_clip(qt_app, tmp_path, monkeypatch, ffmpeg):
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"\x00\x00\x00\x18ftypmp42" + os.urandom(2000))
    project = ProjectState()
    project.add_clip(broken, 3, 320, 180).name = "Case 12 intro"
    out = tmp_path / "out.mp4"
    exporter = _exporter(project, out, monkeypatch)
    with pytest.raises(ExportError) as raised:
        exporter.export()
    assert str(raised.value) == "“Case 12 intro” can't be read. It may be damaged or still copying."
    assert raised.value.details
    assert not out.exists() and [p.name for p in tmp_path.iterdir()] == ["broken.mp4"]


def test_os_error_during_publish_becomes_a_plain_error(qt_app, tmp_path, monkeypatch, ffmpeg):
    project = ProjectState()
    project.add_image_clip(_png(tmp_path), 64, 64, display_duration=0.3)
    exporter = _exporter(project, tmp_path / "out.mp4", monkeypatch, size=(64, 64))

    def full(*_a, **_k):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(exporter_module.os, "replace", full)
    with pytest.raises(ExportError, match="ran out of disk space"):
        exporter.export()


# ------------------------------------------------------------ 6. sweep

def test_sweep_removes_only_old_export_temp_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    old = tmp_path / "neuroedit_export_old"
    fresh = tmp_path / "neuroedit_export_fresh"
    other = tmp_path / "somebody_else"
    for folder in (old, fresh, other):
        folder.mkdir()
        (folder / "segment.mp4").write_bytes(b"x")
    stray_file = tmp_path / "neuroedit_export_file"
    stray_file.write_text("keep")
    long_ago = time.time() - 7 * 3600
    os.utime(old, (long_ago, long_ago))
    os.utime(other, (long_ago, long_ago))
    os.utime(stray_file, (long_ago, long_ago))
    assert sweep_stale_export_temp() == 1
    assert not old.exists() and fresh.exists() and other.exists() and stray_file.exists()
    assert sweep_stale_export_temp(max_age_s=0) == 1 or not fresh.exists()
    assert sweep_stale_export_temp() == 0


def test_sweep_ignores_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path / "does-not-exist"))
    assert sweep_stale_export_temp() == 0
