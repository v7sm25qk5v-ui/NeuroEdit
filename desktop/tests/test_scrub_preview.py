from __future__ import annotations

import subprocess
from pathlib import Path
from time import monotonic, sleep

import pytest
from PySide6.QtCore import QPointF, QEvent, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtMultimedia import QVideoFrame
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from neuroedit_desktop.exporter import resolve_ffmpeg
from neuroedit_desktop.models import Annotation, VideoClip
from neuroedit_desktop.ui.scrub_preview import ScrubFrame
from test_main_window_headless import app, window  # noqa: F401


def _send(canvas, event, time_s, button, buttons):
    point = QPointF(canvas.LABEL_W + time_s * canvas.project.zoom, canvas.RULER_H / 2)
    QApplication.sendEvent(canvas, QMouseEvent(
        event, point, point, button, buttons, Qt.KeyboardModifier.NoModifier,
    ))


def _wait(check, *, timeout=5):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        QTest.qWait(10)
        sleep(0)  # Let the Python decoder run even with an offscreen event pump.
        if check():
            return True
    return False


def _color(item):
    image = item.pixmap().toImage()
    if image.isNull():
        return QColor()
    return image.pixelColor(image.width() // 2, image.height() // 2)


def test_real_drag_shows_new_long_gop_frames_before_release(window, tmp_path):  # noqa: F811
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        pytest.skip("Real video preview test requires FFmpeg")
    path = tmp_path / "preview.mp4"
    subprocess.run([
        ffmpeg, "-v", "error",
        "-f", "lavfi", "-i", "color=red:s=320x180:r=30:d=2",
        "-f", "lavfi", "-i", "color=blue:s=320x180:r=30:d=4",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0", "-c:v", "libx264",
        "-g", "1000", "-pix_fmt", "yuv420p", str(path),
    ], check=True, timeout=30)
    window.project.clips = [VideoClip(
        id="a", path=str(path), name="Trimmed", trim_start=1, trim_end=6,
        duration=6, width=320, height=180,
    )]
    window.project.active_clip_id = "a"
    window.project.zoom = 100
    window._invalidate_project_end_time()
    window.refresh()
    window._load_active_clip()
    canvas = window.timeline.canvas
    left = Qt.MouseButton.LeftButton
    none = Qt.MouseButton.NoButton

    _send(canvas, QEvent.Type.MouseButtonPress, 0.4, left, left)
    assert _wait(lambda: _color(window.video_view.scrub_item).red() > 180)
    _send(canvas, QEvent.Type.MouseMove, 2.2, none, left)
    assert _wait(lambda: _color(window.video_view.scrub_item).blue() > 180)
    assert window.project.current_time == pytest.approx(2.2)
    assert window.video_view.showing_scrub_frame

    # Commit a position which had no preceding mouse move.
    _send(canvas, QEvent.Type.MouseButtonRelease, 2.5, left, none)
    assert window.project.current_time == pytest.approx(2.5)
    assert _wait(lambda: window.player.position() == 3500 and not window.video_view.showing_scrub_frame)
    assert window.video_view.video_item.isVisible()
    assert window._scrub_decoder is None


def test_scrub_frame_never_bypasses_redaction_when_rounded_ms_matches(window):  # noqa: F811
    window.project.clips = [VideoClip(id="a", path="/tmp/preview.mp4", name="Video", trim_end=3)]
    window.project.annotations = [
        Annotation(id="r", frame_time=1, ann_duration=1, type="redact", label="", color="#000000"),
    ]
    target = window._scrub_target_at(0.9998)
    assert target is not None and target.source_ms == 1000
    frame = ScrubFrame(target, QImage(32, 18, QImage.Format.Format_RGB32), 1000, (32, 18))
    assert not window._can_show_scrub_frame(frame, target, 0.9998)
    assert window._can_show_scrub_frame(frame, target, 1.0)


def test_native_handoff_can_use_matching_same_position_frame(window):  # noqa: F811
    view = window.video_view
    image = QImage(32, 18, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.blue)
    frame = QVideoFrame(image)
    frame.setStartTime(1_000_000)
    frame.setEndTime(1_033_333)
    view.video_item.videoSink().setVideoFrame(frame)
    view.show_scrub_frame(None)
    view.arm_scrub_seek(1010, use_current_frame=True)
    assert not view.showing_scrub_frame and view.video_item.isVisible()


def test_cross_source_scrub_handoff_accepts_sparse_portrait_video(window, tmp_path):  # noqa: F811
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        pytest.skip("Real video preview test requires FFmpeg")
    a, b = (tmp_path / name for name in ('a.mp4', 'b.mp4'))
    for source, label, size in [(a, 'red', '320x180'), (b, 'blue', '160x260')]:
        options = ['-vf', "select='not(mod(n,7))'", '-fps_mode', 'vfr'] if label == 'blue' else []
        subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
                        f'color={label}:s={size}:r=30:d=3', *options, '-c:v', 'libx264',
                        '-g', '1000', '-pix_fmt', 'yuv420p', str(source)], check=True, timeout=30)
    window.project.clips = [VideoClip(id='a', path=str(a), name='a', trim_end=1,
                                     duration=3, width=320, height=180),
                            VideoClip(id='b', path=str(b), name='b', start_time=1, trim_end=2,
                                      duration=3, width=160, height=260)]
    window.project.active_clip_id = 'a'
    window.project.zoom = 100
    window._invalidate_project_end_time()
    window.refresh()
    window._load_active_clip()
    canvas = window.timeline.canvas
    left, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    _send(canvas, QEvent.Type.MouseButtonPress, .4, left, left)
    assert _wait(lambda: _color(window.video_view.scrub_item).red() > 180)
    _send(canvas, QEvent.Type.MouseMove, 1.55, none, left)
    assert _wait(lambda: _color(window.video_view.scrub_item).blue() > 180)
    assert window.video_view.sceneRect().width() == 160
    assert window.video_view.sceneRect().height() == 260
    _send(canvas, QEvent.Type.MouseButtonRelease, 1.41, left, none)
    assert _wait(lambda: window.player.position() == 410 and not window.video_view.showing_scrub_frame)
    assert window.video_view.video_item.isVisible()
    assert Path(window.player.source().toLocalFile()) == b
