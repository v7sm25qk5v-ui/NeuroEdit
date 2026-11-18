"""The sequential decode path must pick exactly the frame a timestamp seek picks."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from neuroedit_desktop.exporter import ExportSettings, ProjectExporter, resolve_ffmpeg  # noqa: E402
from neuroedit_desktop.models import ProjectState  # noqa: E402

DURATION = 6.0


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    ffmpeg = resolve_ffmpeg()
    if ffmpeg is None:
        pytest.skip("FFmpeg is required")
    root = tmp_path_factory.mktemp("frame_selection")
    src = f"testsrc2=s=64x64:r=60:d={DURATION}"
    common = ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-sc_threshold", "0"]
    files = {
        "cfr_long": ["-vf", "fps=30", *common, "-g", "300", "-keyint_min", "300"],
        "cfr_short": ["-vf", "fps=30", *common, "-g", "7", "-keyint_min", "7"],
        "cfr_2997": ["-vf", "fps=30000/1001", *common, "-g", "50"],
        "vfr": ["-vf", "select='not(mod(n,5))+gt(n,200)*not(mod(n,2))'", "-fps_mode", "vfr",
                *common, "-g", "40"],
    }
    paths = {}
    for name, args in files.items():
        out = root / f"{name}.mp4"
        subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", src, *args, str(out)],
                       check=True, timeout=60)
        paths[name] = str(out)
    return paths


def _exporter(project, tmp_path, fps=30):
    return ProjectExporter(project, ExportSettings(tmp_path / "o.mp4", 64, 64, fps, 20, "t"))


def _reference(path):
    """The original behaviour: seek by timestamp, then read, for every frame."""
    cap = cv2.VideoCapture(path)

    def get(local_s):
        cap.set(cv2.CAP_PROP_POS_MSEC, local_s * 1000.0)
        ok, bgr = cap.read()
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB) if ok else None
    return get, cap


def _clip(project, path, trim_start=0.0, trim_end=DURATION - 0.5, start_time=0.0):
    clip = project.add_clip(Path(path), DURATION, 64, 64)
    clip.trim_start, clip.trim_end, clip.start_time = trim_start, trim_end, start_time
    return clip


@pytest.mark.parametrize("name", ["cfr_long", "cfr_short", "cfr_2997", "vfr"])
@pytest.mark.parametrize("fps", [24, 30, 60])
@pytest.mark.parametrize("trim_start", [0.0, 1.37])
def test_frames_match_seek_per_frame(qt_app, tmp_path, media, name, fps, trim_start):
    project = ProjectState()
    clip = _clip(project, media[name], trim_start=trim_start)
    exporter = _exporter(project, tmp_path, fps)
    ref, cap = _reference(media[name])
    try:
        count = int(clip.display_duration * fps)
        assert count > 50
        for i in range(count):
            t = i / fps
            got = exporter._frame_for_clip(clip, t)
            want = ref(clip.trim_start + t)
            assert np.array_equal(got, want), (name, fps, trim_start, i)
    finally:
        cap.release()
        exporter._release_captures()


@pytest.mark.parametrize(("name", "speed"), [("cfr_2997", 4.0), ("vfr", 0.25)])
def test_retimed_frames_match_source_timestamp_seeks(qt_app, tmp_path, media, name, speed):
    project = ProjectState()
    clip = _clip(project, media[name], trim_start=0.37, start_time=1.85)
    clip.speed = speed
    exporter = _exporter(project, tmp_path, fps=24)
    ref, cap = _reference(clip.path)
    try:
        for i in range(24):
            time_s = clip.start_time + i / 24
            source_time = clip.trim_start + (time_s - clip.start_time) * speed
            assert np.array_equal(exporter._frame_for_clip(clip, time_s), ref(source_time)), i
    finally:
        cap.release()
        exporter._release_captures()


@pytest.mark.parametrize("name", ["cfr_long", "vfr"])
def test_two_clips_alternating_from_one_file(qt_app, tmp_path, media, name):
    project = ProjectState()
    a = _clip(project, media[name], trim_start=0.0, trim_end=2.0, start_time=0.0)
    b = _clip(project, media[name], trim_start=3.1, trim_end=5.1, start_time=2.0)
    exporter = _exporter(project, tmp_path)
    ref, cap = _reference(media[name])
    try:
        for i in range(60):
            for clip in (a, b):
                t = clip.start_time + i / 30
                got = exporter._frame_for_clip(clip, t)
                assert np.array_equal(got, ref(clip.trim_start + i / 30)), (clip.trim_start, i)
    finally:
        cap.release()
        exporter._release_captures()


@pytest.mark.parametrize("name", ["cfr_long", "vfr"])
def test_restart_after_release_matches(qt_app, tmp_path, media, name):
    project = ProjectState()
    clip = _clip(project, media[name], trim_start=0.4)
    exporter = _exporter(project, tmp_path)
    ref, cap = _reference(media[name])
    try:
        for i in list(range(0, 40)) + list(range(10, 25)):  # a cancel, then a re-render
            if i == 40 - 1:
                exporter._release_captures()
            got = exporter._frame_for_clip(clip, i / 30)
            assert np.array_equal(got, ref(clip.trim_start + i / 30)), i
        for i in (150, 20, 21, 21, 90, 0):  # jumps and repeats
            assert np.array_equal(exporter._frame_for_clip(clip, i / 30), ref(clip.trim_start + i / 30)), i
    finally:
        cap.release()
        exporter._release_captures()


def test_constant_rate_files_are_read_forward_not_seeked(qt_app, tmp_path, media):
    project = ProjectState()
    clip = _clip(project, media["cfr_long"])
    exporter = _exporter(project, tmp_path)
    exporter._frame_for_clip(clip, 0.0)
    seeks = []

    class Spy:
        def __init__(self, cap):
            self._cap = cap

        def set(self, *args):
            seeks.append(args)
            return self._cap.set(*args)

        def __getattr__(self, name):
            return getattr(self._cap, name)

    exporter._captures[clip.path] = Spy(exporter._captures[clip.path])
    try:
        for i in range(1, 60):
            exporter._frame_for_clip(clip, i / 30)
        assert seeks == []
    finally:
        exporter._release_captures()


def test_variable_rate_files_keep_seeking(qt_app, tmp_path, media):
    project = ProjectState()
    clip = _clip(project, media["vfr"])
    exporter = _exporter(project, tmp_path)
    try:
        # The file is trusted only until a frame's timestamp disagrees with
        # index / fps; a variable-rate file fails that within a few frames.
        for i in range(30):
            exporter._frame_for_clip(clip, i / 30)
        assert exporter._video_states[clip.path]["cfr"] is False
    finally:
        exporter._release_captures()
