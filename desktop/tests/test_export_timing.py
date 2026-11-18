"""Global frame timing and encoder lifecycle regression coverage."""
from __future__ import annotations

import os
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
    from neuroedit_desktop.exporter import resolve_ffmpeg

    executable = resolve_ffmpeg()
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
            if index in (4, 5, 6):
                assert frame.max() <= 5
            else:
                assert frame.min() >= 245
    finally:
        capture.release()


@pytest.mark.parametrize("speed", [0.25, 4.0])
def test_clip_speed_retimes_trimmed_video_and_source_audio(qt_app, tmp_path, monkeypatch, ffmpeg, speed):
    source = tmp_path / "source.mp4"
    subprocess.run([
        ffmpeg, "-v", "error", "-y",
        "-f", "lavfi", "-i", "color=c=red:s=64x64:r=30:d=1",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=30:d=1",
        "-f", "lavfi", "-i", "sine=frequency=880:duration=1",
        "-filter_complex", "[0:v][1:a][2:v][3:a]concat=n=2:v=1:a=1[v][a]",
        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-c:a", "aac", str(source),
    ], check=True, timeout=30)
    project = ProjectState()
    clip = project.add_clip(source, 2, 64, 64)
    clip.trim_start, clip.trim_end, clip.speed = 0.2, 1.8, speed
    retimed_duration = 1.6 / speed
    following = project.add_clip(source, 2, 64, 64)
    following.trim_end = 0.2
    project.annotations.append(Annotation(
        id=new_id(), type="redact", label="Redacted", color="#000000",
        frame_time=retimed_duration * 0.25, ann_duration=retimed_duration * 0.2,
        geometry={"x": 0, "y": 0, "width": 1, "height": 1},
    ))
    if speed == 0.25:
        project.annotations.append(Annotation(
            id=new_id(), type="redact", label="Redacted", color="#000000",
            frame_time=(1.0 - 0.2) / speed, ann_duration=0.1,
            geometry={"x": 0, "y": 0, "width": 1, "height": 1},
        ))
    exporter = _exporter(project, tmp_path, monkeypatch)
    assert [segment.kind for segment in exporter._build_segments(exporter._duration())] == [
        "render", "video",
    ]
    exporter.export()

    capture = cv2.VideoCapture(str(exporter.settings.output_path))
    frames = []
    try:
        while (sample := capture.read())[0]:
            frames.append(sample[1][32, 32].copy())
    finally:
        capture.release()
    retimed_frames = round(retimed_duration * 30)
    assert len(frames) == retimed_frames + 6
    assert frames[0][2] > 220  # Source starts inside the red section.
    assert frames[int(retimed_frames * 0.35)].max() < 10  # Redaction stays on the timeline.
    if speed == 0.25:
        # Frame 95 precedes the nominal redaction at 3.2s, but the nearest
        # source frame carries PTS 1s and must already be protected.
        assert frames[93][2] > 220
        assert frames[95].max() < 10
    assert frames[retimed_frames - 1][0] > 220  # Trimmed source ends in blue.
    assert frames[retimed_frames][2] > 220  # The following unsped clip starts on time.

    sample_rate = 8_000
    decoded = subprocess.run([
        ffmpeg, "-v", "error", "-i", str(exporter.settings.output_path),
        "-map", "0:a:0", "-ac", "1", "-ar", str(sample_rate), "-f", "f32le", "-",
    ], stdout=subprocess.PIPE, check=True, timeout=30).stdout
    samples = np.frombuffer(decoded, dtype="<f4")
    assert len(samples) / sample_rate == pytest.approx(retimed_duration + 0.2, abs=0.04)

    def pitch(start_s, end_s):
        window = samples[round(start_s * sample_rate):round(end_s * sample_rate)]
        spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window))))
        return int(np.argmax(spectrum)) * sample_rate / len(window)

    assert pitch(retimed_duration * 0.12, retimed_duration * 0.35) == pytest.approx(440, abs=15)
    assert pitch(retimed_duration * 0.65, retimed_duration * 0.88) == pytest.approx(880, abs=15)
    assert pitch(retimed_duration + 0.05, retimed_duration + 0.15) == pytest.approx(440, abs=15)


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
        assert spawned[0].stderr is None  # NE-029: stderr is a temp file, not a pipe
    finally:
        for process in spawned:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)

@pytest.mark.parametrize("with_audio", [False, True])
def test_export_does_not_copy_source_stream_metadata(qt_app, tmp_path, monkeypatch, ffmpeg, with_audio):
    source = tmp_path / "source.mp4"
    subprocess.run([
        ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
        "color=c=white:s=64x64:r=30:d=1", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=1", "-c:v", "libx264", "-c:a", "aac",
        "-metadata:s:v:0", "handler_name=PRIVATE_PATIENT_NAME", "-shortest", str(source),
    ], check=True, timeout=15)
    probe = subprocess.run([ffmpeg, "-hide_banner", "-i", str(source)],
                           capture_output=True, text=True, timeout=15)
    assert "PRIVATE_PATIENT_NAME" in probe.stderr
    project = ProjectState()
    project.add_clip(source, 1, 64, 64)
    exporter = _exporter(project, tmp_path, monkeypatch)
    monkeypatch.setattr(exporter, "_find_ffmpeg", lambda: ffmpeg)
    if not with_audio:
        monkeypatch.setattr(exporter, "_audio_sources", lambda _: [])
    exporter.export()
    result = subprocess.run([ffmpeg, "-hide_banner", "-i", str(exporter.settings.output_path)],
                            capture_output=True, text=True, timeout=15)
    assert "PRIVATE_PATIENT_NAME" not in result.stderr


def test_concat_does_not_copy_source_stream_metadata(tmp_path, monkeypatch, ffmpeg):
    source = tmp_path / "source.mp4"
    subprocess.run([
        ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
        "color=c=white:s=64x64:r=30:d=1", "-c:v", "libx264",
        "-metadata:s:v:0", "handler_name=PRIVATE_PATIENT_NAME", str(source),
    ], check=True, timeout=15)
    probe = subprocess.run([ffmpeg, "-hide_banner", "-i", str(source)],
                           capture_output=True, text=True, timeout=15)
    assert "PRIVATE_PATIENT_NAME" in probe.stderr
    exporter = _exporter(ProjectState(), tmp_path, monkeypatch)
    output = tmp_path / "joined.mp4"
    exporter._concat_video_segments([source, source], output, ffmpeg, tmp_path)
    result = subprocess.run([ffmpeg, "-hide_banner", "-i", str(output)],
                            capture_output=True, text=True, timeout=15)
    assert "PRIVATE_PATIENT_NAME" not in result.stderr


def test_audio_mux_does_not_copy_video_stream_metadata(tmp_path, monkeypatch, ffmpeg):
    from neuroedit_desktop.exporter import AudioSource

    source = tmp_path / "source.mp4"
    subprocess.run([
        ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
        "color=c=white:s=64x64:r=30:d=1", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=1", "-c:v", "libx264", "-c:a", "aac",
        "-metadata:s:v:0", "handler_name=PRIVATE_PATIENT_NAME", "-shortest", str(source),
    ], check=True, timeout=15)
    probe = subprocess.run([ffmpeg, "-hide_banner", "-i", str(source)],
                           capture_output=True, text=True, timeout=15)
    assert "PRIVATE_PATIENT_NAME" in probe.stderr
    exporter = _exporter(ProjectState(), tmp_path, monkeypatch)
    output = tmp_path / "muxed-result.mp4"
    exporter._mux_audio(source, output, [AudioSource(source, 0, 0, 1, 1)], ffmpeg, 1)
    result = subprocess.run([ffmpeg, "-hide_banner", "-i", str(output)],
                            capture_output=True, text=True, timeout=15)
    assert "PRIVATE_PATIENT_NAME" not in result.stderr
