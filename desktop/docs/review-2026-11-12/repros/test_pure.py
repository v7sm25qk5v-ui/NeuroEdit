import os, types
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pytest
cv2 = pytest.importorskip("cv2")
from PySide6.QtWidgets import QApplication
from neuroedit_desktop.exporter import ExportSettings, ProjectExporter
from neuroedit_desktop.models import Annotation, ProjectState, VideoClip, new_id
from neuroedit_desktop.ui.editor_panels import TimelineCanvas


def _ann(type_, ft, dur, **kw):
    return Annotation(id=new_id(), frame_time=ft, ann_duration=dur, type=type_,
                      label="x", color=kw.pop("color", "#ff0000"), opacity=1.0, **kw)


def test_ne012_export_annotation_stays_in_source_rect(tmp_path):
    QApplication.instance() or QApplication([])
    src = tmp_path / "w.png"
    cv2.imwrite(str(src), np.full((100, 100, 3), 255, dtype=np.uint8))
    p = ProjectState()
    p.add_image_clip(src, 100, 100, display_duration=5.0)
    p.annotations.append(_ann("rect", 0.0, 0.0, geometry={"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0, "width_px": 12}))
    ex = ProjectExporter(p, ExportSettings(tmp_path / "o.mp4", 200, 100, 30, 20, "t"))
    try:
        frame = ex._render_frame(1.0)
    finally:
        ex._release_captures()
    r, g, b = (frame[..., i].astype(int) for i in range(3))
    xs = np.where((r > 200) & (g < 100) & (b < 100))[1]
    print("NE012 colored x range", xs.min() if xs.size else None, xs.max() if xs.size else None)
    assert xs.size and xs.min() >= 50 and xs.max() <= 150


# NE-010 and NE-011 repros moved to tests/test_ripple_overlays.py when fixed.
