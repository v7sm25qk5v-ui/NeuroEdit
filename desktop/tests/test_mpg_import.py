"""MPG (MPEG program stream) files are converted to an MP4 working copy on import.

MPEG program streams have no seek index and timestamps that start about half a
second in. On those files Qt's player shows the next keyframe after a paused
seek and OpenCV repeats one frame for the first ~0.5 s, so the preview and the
export would disagree about which frame is on screen. An ordinary H.264 MP4 copy
behaves like every other import; the original file is never modified.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from neuroedit_desktop import media_convert
from neuroedit_desktop.exporter import ExportSettings, ProjectExporter, resolve_ffmpeg
from neuroedit_desktop.media_convert import (
    ConversionCancelled,
    ConversionFailed,
    convert_to_working_copy,
    needs_conversion,
)
from neuroedit_desktop.models import ProjectState
from neuroedit_desktop.ui import editor_panels
from neuroedit_desktop.ui import main_window as main_window_module
from neuroedit_desktop.ui.main_window_utils import VIDEO_EXTENSIONS
from neuroedit_desktop.video_probe import probe_video
from test_main_window_headless import app, window  # noqa: F401

FFMPEG = resolve_ffmpeg()
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg is required")


def _make_mpg(path: Path, *, seconds: float = 2.0, size: str = "320x240",
              extra_video: tuple[str, ...] = (), audio: bool = True) -> Path:
    """An MPEG-2 program stream like a camcorder or DVD file: GOP 15, B-frames,
    timestamps starting about half a second in, MP2 audio."""
    cmd = [FFMPEG, "-v", "error", "-y",
           "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-c:v", "mpeg2video", "-b:v", "4M", "-g", "15", "-bf", "2", *extra_video]
    cmd += ["-c:a", "mp2"] if audio else ["-an"]
    cmd += ["-metadata", "title=Patient Name 1234", "-f", "mpeg", str(path)]
    subprocess.run(cmd, check=True)
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _streams(path: Path) -> str:
    return subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)],
                          capture_output=True, text=True).stderr


@pytest.fixture(scope="module")
def mpg(tmp_path_factory) -> Path:
    if FFMPEG is None:
        pytest.skip("FFmpeg is required")
    return _make_mpg(tmp_path_factory.mktemp("mpg") / "Clinic Visit.MPG")


# --- What counts as MPG ------------------------------------------------------


def test_mpg_and_mpeg_are_importable_and_need_conversion():
    for name in ("a.mpg", "a.MPG", "a.mpeg", "a.MPEG"):
        assert needs_conversion(Path(name))
        assert Path(name).suffix.lower() in VIDEO_EXTENSIONS
    for name in ("a.mp4", "a.mov", "a.m4v", "a.avi", "a.webm"):
        assert not needs_conversion(Path(name))


def test_file_pickers_offer_mpg():
    assert {"*.mpg", "*.mpeg"} <= set(editor_panels.MediaExplorerPanel.MEDIA_NAME_FILTERS)


# --- The working copy ----------------------------------------------------------


@needs_ffmpeg
def test_working_copy_is_an_ordinary_mp4_and_the_original_is_untouched(mpg, tmp_path):
    before = _digest(mpg)
    media_dir = tmp_path / "media"

    copy, created = convert_to_working_copy(mpg, media_dir)

    assert created and copy.parent == media_dir and copy.suffix == ".mp4"
    assert _digest(mpg) == before
    info = _streams(copy)
    assert "Video: h264" in info and "Audio: aac" in info
    assert "start: 0.000000" in info
    assert "Patient Name" not in info, "source metadata must not be carried over"
    duration, width, height = probe_video(copy)
    assert duration == pytest.approx(2.0, abs=0.1)
    assert (width, height) == (320, 240)
    assert [p.name for p in media_dir.iterdir()] == [copy.name], "no temporary files left"


@needs_ffmpeg
def test_export_reads_the_right_frame_from_the_first_half_second(mpg, tmp_path):
    """On the MPG itself OpenCV returned the frame from ~0.5 s for every time
    before it. On the working copy every output time maps to its own frame."""
    copy, _ = convert_to_working_copy(mpg, tmp_path / "media")
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(mpg), "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-fps_mode", "passthrough", "-"],
                         capture_output=True, check=True).stdout
    truth = np.frombuffer(raw, np.uint8).reshape(-1, 240, 320, 3).astype(np.int16)

    project = ProjectState()
    clip = project.add_clip(copy, duration=2.0, width=320, height=240)
    exporter = ProjectExporter(project, ExportSettings(tmp_path / "o.mp4", 320, 240, 30, 20, "t"))
    try:
        for i in range(45):  # 0 .. 1.5 s at 30 fps
            time_s = i / 30
            frame = exporter._frame_for_clip(clip, time_s).astype(np.int16)
            expected = int(time_s * 25 + 0.5)
            nearest = min(range(len(truth)), key=lambda k: np.abs(truth[k] - frame).mean())
            assert nearest == expected, f"t={time_s:.3f}s shows frame {nearest}, expected {expected}"
    finally:
        exporter._release_captures()


@needs_ffmpeg
def test_anamorphic_mpg_gets_square_pixels(tmp_path):
    """DVD and camcorder MPEG-2 often stores 720 pixels for a 4:3 or 16:9 picture.
    The copy uses square pixels so the preview and the exporter, which treat pixel
    shapes differently, draw labels and redactions on the same picture."""
    source = _make_mpg(tmp_path / "wide.mpg", seconds=1.0, size="320x240",
                       extra_video=("-vf", "setsar=4/3"))

    copy, _ = convert_to_working_copy(source, tmp_path / "media")

    _duration, width, height = probe_video(copy)
    assert (width, height) == (426, 240)
    assert "SAR 1:1" in _streams(copy)


@needs_ffmpeg
def test_no_metadata_reaches_the_copy(tmp_path):
    """MPEG program streams cannot store a title, so use a container that can,
    named .mpg: whatever the source carries must not be copied."""
    source = tmp_path / "tagged.mpg"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=25:duration=1",
                    "-c:v", "mpeg2video", "-metadata", "title=Patient Name 1234",
                    "-metadata", "creation_time=2026-01-02T03:04:05Z", "-metadata", "comment=MRN 99887766",
                    "-f", "matroska", str(source)], check=True)
    assert "Patient Name" in _streams(source)

    copy, _ = convert_to_working_copy(source, tmp_path / "media")

    info = _streams(copy)
    for value in ("Patient Name", "2026-01-02", "MRN"):
        assert value not in info


@needs_ffmpeg
def test_the_copy_never_exists_half_written_under_its_final_name(mpg, tmp_path):
    media_dir = tmp_path / "media"
    final = media_convert.working_copy_path(mpg, media_dir)
    seen_while_converting = []

    convert_to_working_copy(
        mpg, media_dir,
        progress=lambda value: seen_while_converting.append(value < 1.0 and final.exists()),
    )

    assert seen_while_converting and not any(seen_while_converting)
    assert final.is_file()


@needs_ffmpeg
def test_an_edited_original_gets_a_new_copy(tmp_path):
    source = _make_mpg(tmp_path / "visit.mpg", seconds=1.0)
    media_dir = tmp_path / "media"
    first, _ = convert_to_working_copy(source, media_dir)
    _make_mpg(source, seconds=1.5)
    os.utime(source, ns=(source.stat().st_atime_ns, source.stat().st_mtime_ns + 10_000_000_000))

    second, created = convert_to_working_copy(source, media_dir)

    assert created and second != first
    assert probe_video(second)[0] == pytest.approx(1.5, abs=0.1)


@needs_ffmpeg
def test_interlaced_mpg_becomes_progressive(tmp_path):
    source = _make_mpg(tmp_path / "interlaced.mpg", seconds=1.0, size="320x240",
                       extra_video=("-flags", "+ilme+ildct", "-top", "1"))
    assert "top first" in _streams(source)

    copy, _ = convert_to_working_copy(source, tmp_path / "media")

    assert "top first" not in _streams(copy) and "bottom first" not in _streams(copy)


@needs_ffmpeg
def test_mpg_without_audio_converts(tmp_path):
    source = _make_mpg(tmp_path / "silent.mpeg", seconds=1.0, audio=False)

    copy, _ = convert_to_working_copy(source, tmp_path / "media")

    assert "Audio:" not in _streams(copy)
    assert probe_video(copy)[0] > 0


@needs_ffmpeg
def test_importing_the_same_unchanged_file_again_reuses_its_copy(mpg, tmp_path):
    media_dir = tmp_path / "media"
    first, created = convert_to_working_copy(mpg, media_dir)
    stamp = first.stat().st_mtime_ns

    again, created_again = convert_to_working_copy(mpg, media_dir)

    assert created and not created_again
    assert again == first and first.stat().st_mtime_ns == stamp


@needs_ffmpeg
def test_cancelling_a_conversion_leaves_nothing_behind(tmp_path):
    source = _make_mpg(tmp_path / "long.mpg", seconds=20.0)
    media_dir = tmp_path / "media"
    calls = []

    def cancelled():
        calls.append(True)
        return len(calls) > 1

    with pytest.raises(ConversionCancelled):
        convert_to_working_copy(source, media_dir, cancelled=cancelled)

    assert list(media_dir.iterdir()) == []


@needs_ffmpeg
def test_unreadable_file_fails_cleanly(tmp_path):
    source = tmp_path / "broken.mpg"
    source.write_bytes(b"not a video" * 1000)
    media_dir = tmp_path / "media"

    with pytest.raises(ConversionFailed):
        convert_to_working_copy(source, media_dir)

    assert list(media_dir.iterdir()) == []


@needs_ffmpeg
def test_progress_is_reported(mpg, tmp_path):
    seen: list[float] = []

    convert_to_working_copy(mpg, tmp_path / "media", progress=seen.append)

    assert seen and all(0.0 <= value <= 1.0 for value in seen)
    assert seen == sorted(seen)


def test_a_linked_media_folder_is_refused(mpg, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "media").symlink_to(elsewhere)

    with pytest.raises(ConversionFailed, match="link"):
        convert_to_working_copy(mpg, tmp_path / "project" / "media")

    assert list(elsewhere.iterdir()) == []


# --- Importing in the app ------------------------------------------------------


def _wait_for_import(window):  # noqa: F811
    for _ in range(3000):
        QApplication.processEvents()
        if getattr(window, "_import_thread", None) is None:
            return
        QTest.qWait(10)
    pytest.fail("Import did not finish")


def _media_dir(window) -> Path:  # noqa: F811
    return window.store.project_path.parent / "media"


@needs_ffmpeg
def test_importing_an_mpg_adds_a_clip_for_its_working_copy(window, mpg, monkeypatch):  # noqa: F811
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    before = _digest(mpg)
    history_before = len(window._undo_stack)

    window._import_media_files([mpg])
    _wait_for_import(window)

    clip = window.project.clips[-1]
    copy = Path(clip.path)
    assert copy.parent == _media_dir(window) and copy.suffix == ".mp4" and copy.is_file()
    assert clip.name == "Clinic Visit", "the clip keeps the original file's name"
    assert clip.duration == pytest.approx(2.0, abs=0.1)
    assert (clip.width, clip.height) == (320, 240)
    assert _digest(mpg) == before
    assert len(window._undo_stack) == history_before + 1
    assert "working copy" in window.statusBar().currentMessage()


@needs_ffmpeg
def test_cancelling_an_mpg_import_adds_nothing_and_keeps_no_copy(window, tmp_path, monkeypatch):  # noqa: F811
    source = _make_mpg(tmp_path / "long.mpg", seconds=20.0)
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)

    window._import_media_files([source])
    progress = window._import_progress
    assert progress.windowModality() == Qt.WindowModality.WindowModal
    QTest.qWait(200)
    progress.canceled.emit()
    _wait_for_import(window)

    assert window.project.clips == []
    media_dir = _media_dir(window)
    assert not media_dir.exists() or list(media_dir.iterdir()) == []


@needs_ffmpeg
def test_a_discarded_import_removes_the_copies_it_made(window, mpg, monkeypatch):  # noqa: F811
    """If the project changes while converting, the import is discarded; the
    copies it created would otherwise sit in the project folder unreferenced."""
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    real_convert = media_convert.convert_to_working_copy

    def convert_then_edit(*args, **kwargs):
        result = real_convert(*args, **kwargs)
        window._import_snapshot = b"changed"  # as if the user edited meanwhile
        return result

    monkeypatch.setattr(main_window_module, "convert_to_working_copy", convert_then_edit)

    window._import_media_files([mpg])
    _wait_for_import(window)

    assert window.project.clips == []
    assert list(_media_dir(window).iterdir()) == []


@needs_ffmpeg
def test_the_same_file_twice_then_discarded_keeps_no_copy(window, tmp_path, monkeypatch):  # noqa: F811
    source = _make_mpg(tmp_path / "dup.mpg", seconds=1.0)
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    real_convert = media_convert.convert_to_working_copy

    def convert_then_edit(*args, **kwargs):
        result = real_convert(*args, **kwargs)
        window._import_snapshot = b"changed"
        return result

    monkeypatch.setattr(main_window_module, "convert_to_working_copy", convert_then_edit)

    window._import_media_files([source, source])
    _wait_for_import(window)

    assert window.project.clips == []
    assert list(_media_dir(window).iterdir()) == []


@needs_ffmpeg
def test_cancel_and_close_stop_a_conversion_at_once(window, tmp_path, monkeypatch):  # noqa: F811
    """A polite stop takes ffmpeg many seconds on HD footage; closing used to
    give up after five and force-quit, leaving ffmpeg writing a partial copy."""
    import time

    source = _make_mpg(tmp_path / "hd.mpg", seconds=30.0, size="1280x720")
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    window._import_media_files([source])
    deadline = time.monotonic() + 30
    while not any(_media_dir(window).glob(".neuroedit-convert-*")) and time.monotonic() < deadline:
        QTest.qWait(20)
    QTest.qWait(300)

    started = time.monotonic()
    force_terminated = window._shutdown_threads()
    stopped_after = time.monotonic() - started

    assert not force_terminated
    assert stopped_after < 2.0, f"took {stopped_after:.1f} s"
    QApplication.processEvents()
    assert list(_media_dir(window).iterdir()) == []


@needs_ffmpeg
def test_a_failed_conversion_is_reported_and_keeps_no_copy(window, tmp_path, monkeypatch):  # noqa: F811
    broken = tmp_path / "broken.mpg"
    broken.write_bytes(b"not a video" * 1000)
    warnings: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2]))

    window._import_media_files([broken])
    _wait_for_import(window)

    assert window.project.clips == []
    assert warnings and "broken.mpg (could not convert" in warnings[0]
    media_dir = _media_dir(window)
    assert not media_dir.exists() or list(media_dir.iterdir()) == []


@needs_ffmpeg
def test_save_as_takes_the_working_copy_along(window, mpg, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    window._import_media_files([mpg])
    _wait_for_import(window)
    old_copy = Path(window.project.clips[-1].path)
    old_digest = _digest(old_copy)
    destination = tmp_path / "saved"
    destination.mkdir()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(destination / "Case"), ""))

    window._save_project_as()

    new_copy = Path(window.project.clips[-1].path)
    assert new_copy.parent == destination / "Case" / "media"
    assert _digest(new_copy) == old_digest
    assert old_copy.is_file() and _digest(old_copy) == old_digest, "the original folder is untouched"
    saved = json.loads((destination / "Case" / "project.json").read_text())
    assert saved["clips"][-1]["path"] == str(new_copy)


@needs_ffmpeg
def test_close_deletes_only_unreferenced_working_copies(window, mpg, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    window._import_media_files([mpg])
    _wait_for_import(window)
    kept = Path(window.project.clips[-1].path)
    stray = _media_dir(window) / "Old Visit.neuroedit-0123456789ab.mp4"
    stray.write_bytes(b"orphan")
    stale = _media_dir(window) / ".neuroedit-convert-abc123.mp4"
    stale.write_bytes(b"left by a forced quit")
    os.utime(stale, (0, 0))

    window._cleanup_orphan_masks()

    assert kept.is_file()
    assert not stray.exists()
    assert not stale.exists()


@needs_ffmpeg
def test_close_never_deletes_the_users_own_files_in_the_media_folder(window, mpg, monkeypatch):  # noqa: F811
    """`media` is a common folder name for footage. Only files the app named
    as working copies may ever be deleted from it."""
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    media_dir = _media_dir(window)
    media_dir.mkdir()
    own = [media_dir / "raw_camera_B.mp4", media_dir / "visit.mpg", media_dir / "notes.txt",
           media_dir / "clip-0123456789ab.mp4"]
    for path in own:
        path.write_bytes(b"the user's file")
    window._import_media_files([mpg])
    _wait_for_import(window)

    window._cleanup_orphan_masks()

    assert all(path.is_file() for path in own)


@needs_ffmpeg
def test_a_moved_project_folder_keeps_and_uses_its_working_copies(window, mpg, tmp_path, monkeypatch):  # noqa: F811
    from neuroedit_desktop.project_store import ProjectStore

    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    window._import_media_files([mpg])
    _wait_for_import(window)
    old_folder = window.store.project_path.parent
    window.store.save(window.project)
    moved = tmp_path / "moved-case"
    old_folder.rename(moved)

    store, project = ProjectStore.open(moved / "project.json")

    copy = Path(project.clips[-1].path)
    assert copy.parent == moved / "media" and copy.is_file()
    window._activate_project(store, project)
    window._cleanup_orphan_masks()
    assert copy.is_file()


@needs_ffmpeg
def test_a_copy_still_reachable_by_undo_is_kept(window, mpg, monkeypatch):  # noqa: F811
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    window._import_media_files([mpg])
    _wait_for_import(window)
    copy = Path(window.project.clips[-1].path)
    window.undo()  # the clip is gone from the document but redo can bring it back
    assert not window.project.clips

    window._cleanup_orphan_masks()

    assert copy.is_file()


def test_relinking_to_an_mpg_explains_how_to_add_it(window, tmp_path):  # noqa: F811
    source = tmp_path / "replacement.mpg"
    source.write_bytes(b"x")
    project = window.project
    clip = project.add_clip(tmp_path / "gone.mp4", duration=5.0, width=320, height=240)

    message = window._relink_reference(clip, "clip", source)

    assert message and "Add Video Files" in message
    assert clip.path == str(tmp_path / "gone.mp4")
