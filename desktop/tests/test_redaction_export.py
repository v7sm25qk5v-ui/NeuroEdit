"""PHI-redaction guarantees for the export pipeline.

These tests prove the two properties that make the Redact tool safe:
1. A redaction burns the underlying pixels to opaque black in the rendered frame.
2. A redaction forces every overlapping timeline segment down the re-encode path,
   so the "fast" stream-copy export can never leak the original PHI frames.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

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
