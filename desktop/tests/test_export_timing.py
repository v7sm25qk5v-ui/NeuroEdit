"""Global frame timing and encoder lifecycle regression coverage."""
from __future__ import annotations

import os
import shutil
import subprocess

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from neuroedit_desktop.exporter import (  # noqa: E402
    ExportCancelled, ExportSettings, ProjectExporter, TimelineSegment,
)
from neuroedit_desktop.models import Annotation, ProjectState, new_id  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def ffmpeg():
    executable = shutil.which("ffmpeg")
    if executable is None:
        pytest.skip("FFmpeg is required for export timing integration coverage")
    return executable


def _exporter(project, tmp_path, monkeypatch):
    exporter = ProjectExporter(project, ExportSettings(tmp_path / "out.mp4", 64, 64, 30, 20, "test"))
    monkeypatch.setattr(exporter, "_encoder_args", lambda _ffmpeg: ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"])
    return exporter


@pytest.mark.parametrize("mixed", [False, True])
def test_fractional_cuts_keep_global_output_duration(qt_app, tmp_path, monkeypatch, ffmpeg, mixed):
    image = tmp_path / "white.png"
    cv2.imwrite(str(image), np.full((64, 64, 3), 255, dtype=np.uint8))
    video = tmp_path / "source.mp4"
    if mixed:
        subprocess.run([
            ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
            "color=c=white:s=64x64:r=30:d=1", "-c:v", "libx264", str(video),
        ], check=True, timeout=15)
    project = ProjectState()
    for index in range(20):
        if mixed and index % 2 == 0:
            clip = project.add_clip(video, 1, 64, 64)
            clip.trim_end = 0.11
        else:
            project.add_image_clip(image, 64, 64, display_duration=0.11)
    exporter = _exporter(project, tmp_path, monkeypatch)
    monkeypatch.setattr(exporter, "_find_ffmpeg", lambda: ffmpeg)
    exporter.export()
    capture = cv2.VideoCapture(str(exporter.settings.output_path))
    try:
        count = 0
        while capture.read()[0]:
            count += 1
        assert count == 66  # 20 * 0.11 seconds at 30 fps, previously 80.
        assert count / capture.get(cv2.CAP_PROP_FPS) == pytest.approx(2.2, abs=1 / 30)
    finally:
        capture.release()


def test_frame_clock_preserves_annotation_and_redaction_boundaries(qt_app, tmp_path, monkeypatch, ffmpeg):
    image = tmp_path / "white.png"
    cv2.imwrite(str(image), np.full((64, 64, 3), 255, dtype=np.uint8))
    project = ProjectState()
    for _ in range(3):
        project.add_image_clip(image, 64, 64, display_duration=0.11)
    project.annotations.append(Annotation(
        id=new_id(), frame_time=0.125, ann_duration=0.075, type="redact",
        label="Redacted", color="#000000", geometry={"x": 0, "y": 0, "width": 1, "height": 1},
    ))
    exporter = _exporter(project, tmp_path, monkeypatch)
    sampled = []
    original = exporter._render_frame

    def record_frame(time_s):
        frame = original(time_s)
        sampled.append((time_s, frame.copy()))
        return frame

    monkeypatch.setattr(exporter, "_render_frame", record_frame)
    exporter._encode_timeline_video(tmp_path / "visual.mp4", ffmpeg, tmp_path, exporter._duration())
    assert [time_s for time_s, _ in sampled] == pytest.approx([index / 30 for index in range(10)])
    for time_s, frame in sampled:
        if 0.125 <= time_s <= 0.2:
            assert frame.max() == 0
        else:
            assert frame.min() >= 250


def test_fractional_redaction_between_fast_video_segments(qt_app, tmp_path, monkeypatch, ffmpeg):
    video = tmp_path / "source.mp4"
    subprocess.run([
        ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
        "color=c=white:s=64x64:r=30:d=1", "-c:v", "libx264", str(video),
    ], check=True, timeout=15)
    project = ProjectState()
    clip = project.add_clip(video, 1, 64, 64)
    clip.trim_end = 0.33
    project.annotations.append(Annotation(
        id=new_id(), frame_time=0.125, ann_duration=0.075, type="redact",
        label="Redacted", color="#000000", geometry={"x": 0, "y": 0, "width": 1, "height": 1},
    ))
    exporter = _exporter(project, tmp_path, monkeypatch)
    monkeypatch.setattr(exporter, "_find_ffmpeg", lambda: ffmpeg)
    assert [segment.kind for segment in exporter._build_segments(0.33)] == [
        "video", "render", "video",
    ]
    exporter.export()
    capture = cv2.VideoCapture(str(exporter.settings.output_path))
    try:
        frames = []
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frames.append(frame)
        assert len(frames) == 10
        for index, frame in enumerate(frames):
            if index in (4, 5):
                assert frame.max() <= 5
            else:
                assert frame.min() >= 245
    finally:
        capture.release()


@pytest.mark.parametrize("failure", [RuntimeError("Source decoding failed"), ExportCancelled(), None])
def test_render_encoder_reaped_and_pipes_closed(qt_app, tmp_path, monkeypatch, ffmpeg, failure):
    exporter = _exporter(ProjectState(), tmp_path, monkeypatch)
    spawned = []
    popen = subprocess.Popen

    def record_process(*args, **kwargs):
        process = popen(*args, **kwargs)
        spawned.append(process)
        return process

    def render_frame(_time_s):
        if failure is not None:
            raise failure
        return np.zeros((64, 64, 3), dtype=np.uint8)

    monkeypatch.setattr("neuroedit_desktop.exporter.subprocess.Popen", record_process)
    monkeypatch.setattr(exporter, "_render_frame", render_frame)
    segment = TimelineSegment(0, 0.1, "render")
    try:
        if failure is None:
            exporter._encode_render_segment_with_ffmpeg(segment, tmp_path / "segment.mp4", ffmpeg, 0, 1)
        else:
            with pytest.raises(type(failure)) as raised:
                exporter._encode_render_segment_with_ffmpeg(segment, tmp_path / "segment.mp4", ffmpeg, 0, 1)
            assert raised.value is failure
        assert len(spawned) == 1
        assert spawned[0].poll() is not None
        assert spawned[0].stdin.closed
        assert spawned[0].stderr.closed
    finally:
        for process in spawned:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
