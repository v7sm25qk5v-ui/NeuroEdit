import subprocess
from threading import Event, get_ident
from time import monotonic

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea

from neuroedit_desktop.models import Annotation, ProjectState, VideoClip
from neuroedit_desktop.ui import timeline_thumbnails
from neuroedit_desktop.ui.editor_panels import TimelineCanvas


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_filmstrip_uses_trimmed_source_times_in_the_visible_viewport(app):
    canvas = TimelineCanvas(ProjectState())
    band = canvas._filmstrip_band()
    view = QRect(canvas.LABEL_W + 10_000, band.top(), 320, band.height())
    videos = (("/tmp/long.mp4", 0, 100, 2000), ("/tmp/offscreen.mp4", 2200, 0, 10))
    for zoom in (20.0, 80.0):
        tiles = canvas._layout_filmstrip(view, zoom, videos, (), ())
        assert 1 <= len(tiles) <= 10
        for (path, source_ms), tile in tiles:
            assert path == "/tmp/long.mp4"
            assert tile.intersects(view)
            expected_ms = 100_000 + (tile.center().x() + 0.5 - canvas.LABEL_W) / zoom * 1000
            assert expected_ms - 1 <= source_ms <= expected_ms
        covers = ((0.0, 2000.0),)
        assert canvas._layout_filmstrip(view, zoom, videos, (), covers) == []


def test_redaction_drops_raw_linked_clip_thumbnails_even_after_caching(app, monkeypatch):
    main_thread = get_ident()
    decode_threads = []

    def decode(path, times, _stop):
        decode_threads.append(get_ident())
        image = QImage(96, 54, QImage.Format.Format_RGB32)
        image.fill(QColor("#fa1251"))
        return {ms: image for ms in times}

    monkeypatch.setattr(timeline_thumbnails, "_decode_thumbnails", decode)
    clips = [
        VideoClip(id="a", path="/tmp/same.mp4", name="First", trim_end=2),
        VideoClip(id="b", path="/tmp/same.mp4", name="Second", start_time=2, trim_start=2, trim_end=4),
    ]
    project = ProjectState(clips=clips, zoom=80.0)
    canvas = TimelineCanvas(project)
    scroll = QScrollArea()
    scroll.resize(500, 280)
    scroll.setWidget(canvas)
    scroll.show()
    try:
        deadline = monotonic() + 5
        point = (canvas.LABEL_W + 25, canvas._filmstrip_band().center().y())
        while canvas.grab().toImage().pixelColor(*point) != QColor("#fa1251"):
            assert monotonic() < deadline, "The background decoder did not paint a thumbnail"
            QTest.qWait(25)
        assert decode_threads and all(thread != main_thread for thread in decode_threads)
        assert canvas._static_cache is not None
        cache_key = canvas._static_cache.cacheKey()
        canvas._refresh_filmstrip()
        QTest.qWait(10)
        assert canvas._static_cache.cacheKey() == cache_key

        # A redaction in the first clip hides the same source in the second.
        project.annotations.append(Annotation(
            id="redact", frame_time=0.5, ann_duration=0.5, type="redact", label="", color="#000000",
        ))
        canvas.set_project(project)
        image = canvas.grab().toImage()
        assert image.pixelColor(*point) != QColor("#fa1251")
        assert canvas._filmstrip_tiles == []
    finally:
        scroll.close()


def test_decoder_returns_small_stills_at_the_requested_source_times(tmp_path):
    from neuroedit_desktop.exporter import resolve_ffmpeg

    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        pytest.skip("The real thumbnail decoder test requires FFmpeg")
    path = tmp_path / "colors.mp4"
    subprocess.run([
        ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=red:s=200x120:d=1:r=15",
        "-f", "lavfi", "-i", "color=blue:s=200x120:d=1:r=15",
        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", str(path),
    ], check=True, timeout=30)
    images = timeline_thumbnails._decode_thumbnails(str(path), [500, 1500], Event())
    assert set(images) == {500, 1500}
    red, blue = images[500].pixelColor(25, 20), images[1500].pixelColor(25, 20)
    assert red.red() > 180 and red.blue() < 40
    assert blue.blue() > 180 and blue.red() < 40
    assert all(image.width() <= 96 and image.height() <= 54 for image in images.values())


def test_hiding_the_timeline_stops_its_active_thumbnail_batch(app, monkeypatch):
    started = Event()
    finished = Event()

    def decode(_path, _times, stop):
        started.set()
        if stop.wait(2):
            finished.set()
        return {}

    monkeypatch.setattr(timeline_thumbnails, "_decode_thumbnails", decode)
    canvas = TimelineCanvas(ProjectState(clips=[
        VideoClip(id="a", path="/tmp/source.mp4", name="Clip", trim_end=8),
    ], zoom=80.0))
    canvas.show()
    try:
        deadline = monotonic() + 5
        while not started.is_set():
            assert monotonic() < deadline, "The background decoder did not start"
            QTest.qWait(20)
        canvas.hide()
        assert finished.wait(1)
    finally:
        canvas.close()
