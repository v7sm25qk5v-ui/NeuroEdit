"""PHI-redaction guarantees for the export pipeline.

These tests prove the two properties that make the Redact tool safe:
1. A redaction burns the underlying pixels to opaque black in the rendered frame.
2. A redaction forces every overlapping timeline segment down the re-encode path,
   so the "fast" stream-copy export can never leak the original PHI frames.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from neuroedit_desktop.exporter import ExportSettings, ProjectExporter  # noqa: E402
from neuroedit_desktop.models import Annotation, ProjectState, new_id  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def _redaction(x: float, y: float, w: float, h: float) -> Annotation:
    return Annotation(
        id=new_id(),
        frame_time=0.0,
        ann_duration=0.0,  # whole timeline
        type="redact",
        label="Redacted",
        color="#000000",
        visible=True,
        opacity=1.0,
        geometry={"x": x, "y": y, "width": w, "height": h},
    )


def test_redaction_blacks_out_region(qt_app, tmp_path):
    # A solid-white image clip so any black pixel must come from the redaction.
    src = tmp_path / "white.png"
    cv2.imwrite(str(src), np.full((100, 200, 3), 255, dtype=np.uint8))

    project = ProjectState()
    project.add_image_clip(src, 200, 100, display_duration=5.0)
    project.annotations.append(_redaction(0.0, 0.0, 0.5, 1.0))  # left half

    settings = ExportSettings(tmp_path / "out.mp4", 200, 100, 30, 20, "test")
    exporter = ProjectExporter(project, settings)
    try:
        frame = exporter._render_frame(1.0)  # RGB, HxWx3
    finally:
        exporter._release_captures()

    # Columns away from the antialiased boundary at x=100.
    assert frame[:, :90].max() == 0, "redacted region must be fully opaque black"
    assert frame[:, 110:].min() >= 250, "non-redacted region must keep original pixels"


def test_redaction_forces_reencode_segments(tmp_path):
    # A 'video' clip that exists on disk — without a redaction this region would
    # qualify for the fast stream-copy path.
    vid = tmp_path / "clip.mp4"
    vid.write_bytes(b"\x00")

    project = ProjectState()
    project.add_clip(vid, duration=5.0, width=200, height=100)
    project.annotations.append(_redaction(0.0, 0.0, 1.0, 1.0))  # full frame

    settings = ExportSettings(tmp_path / "out.mp4", 200, 100, 30, 20, "test")
    exporter = ProjectExporter(project, settings)
    segments = exporter._build_segments(exporter._duration())

    assert segments, "expected at least one timeline segment"
    assert all(
        seg.kind == "render" for seg in segments
    ), "a redacted timeline must re-render every segment, never stream-copy the source"


def test_subframe_redaction_window_still_forces_render(tmp_path):
    # A redaction window so short the timeline-boundary dedup collapses its splits:
    # the midpoint heuristic alone would miss it and stream-copy the original PHI.
    # _redaction_overlaps must still force a re-render of the overlapping segment.
    vid = tmp_path / "clip.mp4"
    vid.write_bytes(b"\x00")

    project = ProjectState()
    project.add_clip(vid, duration=10.0, width=200, height=100)
    redaction = _redaction(0.0, 0.0, 1.0, 1.0)
    redaction.frame_time = 3.0
    redaction.ann_duration = 0.0004  # sub-millisecond window
    project.annotations.append(redaction)

    settings = ExportSettings(tmp_path / "out.mp4", 200, 100, 30, 20, "test")
    exporter = ProjectExporter(project, settings)
    segments = exporter._build_segments(exporter._duration())

    leaking = [
        seg for seg in segments
        if seg.kind == "video" and seg.start < 3.0004 and 3.0 < seg.end
    ]
    assert not leaking, "a segment overlapping the redaction window must never stream-copy"

@pytest.mark.parametrize("source_size", [(100, 100), (80, 160), (160, 80)])
def test_redaction_tracks_actual_fitted_source(qt_app, tmp_path, source_size):
    width, height = source_size
    src = tmp_path / "white.png"
    cv2.imwrite(str(src), np.full((height, width, 3), 255, dtype=np.uint8))
    project = ProjectState()
    clip = project.add_image_clip(src, width, height, display_duration=5.0)
    # Metadata may be stale: the decoded image determines the fit.
    clip.width, clip.height = 200, 100
    project.annotations.append(_redaction(0.0, 0.0, 0.25, 1.0))
    exporter = ProjectExporter(project, ExportSettings(tmp_path / "out.mp4", 200, 100, 30, 20, "test"))
    frame = exporter._render_frame(1.0)
    scale = min(200 / width, 100 / height)
    fitted_w, fitted_h = round(width * scale), round(height * scale)
    x, y = (200 - fitted_w) // 2, (100 - fitted_h) // 2
    assert frame[y:y + fitted_h, x:x + int(fitted_w * 0.25)].max() == 0
    assert frame[y:y + fitted_h, x + int(fitted_w * 0.5):x + fitted_w].min() >= 250


def test_full_frame_slide_redaction_uses_output_coordinates(qt_app, tmp_path):
    from neuroedit_desktop.models import Slide

    project = ProjectState()
    project.slides.append(Slide(id="slide", title="", duration=5, start_time=0, background="#ffffff"))
    project.annotations.append(_redaction(0.0, 0.0, 0.25, 1.0))
    exporter = ProjectExporter(project, ExportSettings(tmp_path / "out.mp4", 200, 100, 30, 20, "test"))
    frame = exporter._render_frame(1.0)
    assert frame[:, :50].max() == 0
    assert frame[:, 100:].min() >= 250


def test_redaction_uses_each_clip_fit_with_overlay_slide(qt_app, tmp_path):
    from neuroedit_desktop.models import Slide

    project = ProjectState()
    for name, shape in [("square", (100, 100)), ("portrait", (160, 80))]:
        src = tmp_path / f"{name}.png"
        cv2.imwrite(str(src), np.full((*shape, 3), 255, dtype=np.uint8))
        project.add_image_clip(src, shape[1], shape[0], display_duration=1.0)
    project.slides.append(Slide(id="overlay", title="", duration=2, start_time=0, overlay=True))
    project.annotations.append(_redaction(0.0, 0.0, 0.25, 1.0))
    exporter = ProjectExporter(project, ExportSettings(tmp_path / "out.mp4", 200, 100, 30, 20, "test"))
    for time_s, x in [(0.5, 50), (1.5, 75)]:
        frame = exporter._render_frame(time_s)
        assert frame[50, x:x + 12].max() == 0
        assert frame[50, x + 30:x + 40].min() >= 250


def test_finite_redaction_endpoint_is_not_fast_exported(tmp_path):
    vid = tmp_path / "clip.mp4"
    vid.write_bytes(b"\x00")
    project = ProjectState()
    project.add_clip(vid, duration=2, width=200, height=100)
    redaction = _redaction(0, 0, 1, 1)
    redaction.frame_time, redaction.ann_duration = 0.125, 0.075
    project.annotations.append(redaction)
    exporter = ProjectExporter(project, ExportSettings(tmp_path / "out.mp4", 200, 100, 30, 20, "test"))
    segments = exporter._build_segments(2)
    assert next(seg for seg in segments if seg.start <= 0.2 < seg.end).kind == "render"
    assert segments[-1].kind == "video"
