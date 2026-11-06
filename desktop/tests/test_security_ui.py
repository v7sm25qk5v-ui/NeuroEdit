"""Security boundaries for passive project display and timeline insertion."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication

from neuroedit_desktop.models import Annotation, ProjectState, VideoClip
from neuroedit_desktop.ui.editor_panels import TimelineCanvas
from neuroedit_desktop.ui.main_window import MainWindow
from neuroedit_desktop.ui.project_library import (
    ProjectLibraryDialog, _read_project_meta, _thumbnail_path,
)


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("duration", [0.0, 8.0, 4.0])
def test_insert_still_preserves_redaction_on_resumed_source(duration):
    annotation = Annotation("privacy", 0, duration, "redact", "", "#000")
    project = ProjectState(annotations=[annotation], clips=[
        VideoClip("clip", "video.mp4", "Video", duration=10, trim_end=10),
    ])
    owner = SimpleNamespace(project=project)
    owner._split_clip_for_gap = lambda clip, at, gap: MainWindow._split_clip_for_gap(
        owner, clip, at, gap
    )

    MainWindow._insert_timeline_gap(owner, 4, 5)

    assert project.clips[1].start_time == 9
    assert annotation.is_visible_at(9), "the inclusive source frame at insertion stays covered"
    if duration == 0:
        assert annotation.ann_duration == 0
        assert annotation.is_visible_at(100)
    else:
        assert annotation.is_visible_at(duration + 5)
        assert not annotation.is_visible_at(duration + 5.01)


def test_insert_still_shifts_later_redactions_and_keeps_normal_label_cap():
    privacy = Annotation("privacy", 4, 2, "redact", "", "#000")
    label = Annotation("label", 0, 8, "rect", "", "#fff")
    owner = SimpleNamespace(project=ProjectState(annotations=[privacy, label]))
    MainWindow._insert_timeline_gap(owner, 4, 5)
    assert privacy.frame_time == 9 and privacy.ann_duration == 2
    assert label.ann_duration == 4


def test_passive_timeline_load_and_refresh_preserve_reviewed_gaps():
    project = ProjectState.from_dict({
        "deidentified_confirmed": True, "phi_review_confirmed": True,
        "clips": [{"id": "clip", "path": "video.mp4", "name": "Video",
                   "duration": 2, "trim_end": 2, "start_time": 10}],
        "annotations": [{"id": "privacy", "frame_time": 10, "ann_duration": 2,
                         "type": "redact", "label": "", "color": "#000"}],
    })
    original = project.to_dict()
    canvas = TimelineCanvas(project)
    canvas.set_project(project)
    assert project.to_dict() == original


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", ["duration", "start_time", "trim_end"])
def test_nonfinite_project_timing_is_rejected(value, field):
    clip = {"id": "clip", "path": "video.mp4", "name": "Video", "trim_end": 2}
    clip[field] = value
    with pytest.raises(ValueError, match="finite"):
        ProjectState.from_dict({"clips": [clip]})


@pytest.mark.parametrize("data", [
    {"zoom": float("nan")}, {"duration": float("inf")},
    {"audio_tracks": [{"id": "a", "path": "audio.wav", "name": "Audio",
                       "start_time": 1e308, "duration": 1e308}]},
    {"slides": [{"id": "s", "title": "Slide", "duration": float("inf")}]},
])
def test_nonfinite_timing_in_other_project_tracks_is_rejected(data):
    with pytest.raises(ValueError, match="finite"):
        ProjectState.from_dict(data)


def test_library_metadata_does_not_format_nonfinite_project_duration(tmp_path):
    project = tmp_path / "project.json"
    project.write_text(json.dumps({"clips": [{"duration": float("inf")}]}))
    meta = _read_project_meta(project)
    assert meta["ok"] is False
    assert meta["total_duration"] == 0


def test_extreme_finite_duration_has_bounded_geometry_and_ruler_work():
    project = ProjectState.from_dict({"zoom": 80, "clips": [{
        "id": "clip", "path": "video.mp4", "name": "Video",
        "duration": 1e300, "trim_end": 1e300,
    }]})
    canvas = TimelineCanvas(project)
    assert canvas.width() <= 16777215

    class Painter:
        ticks = 0
        def hasClipping(self): return True
        def clipBoundingRect(self): return QRectF(1_000_000, 0, 800, 30)
        def setFont(self, *args): pass
        def setPen(self, *args): pass
        def drawText(self, *args): pass
        def drawLine(self, *args): self.ticks += 1

    painter = Painter()
    canvas._paint_ruler(painter, 80, 1e300)
    assert 1 <= painter.ticks <= 10


@pytest.mark.parametrize("source", ["http://127.0.0.1/private", "https://example.invalid/clip", "local.mp4"])
@pytest.mark.parametrize("reviewed", [True, False])
def test_library_never_extracts_original_frames_or_displays_old_cache(
    tmp_path, monkeypatch, source, reviewed,
):
    from PySide6.QtCore import QSettings

    project = tmp_path / "project.json"
    project.write_text(json.dumps({
        "deidentified_confirmed": reviewed,
        "clips": [{"path": source, "duration": 2}],
        "annotations": [{"type": "redact"}],
    }))
    thumb = _thumbnail_path(project)
    thumb.write_bytes(b"old original pixels")
    monkeypatch.setattr("subprocess.run", lambda *a, **k: pytest.fail("raw media extraction"))
    settings = QSettings("NeuroEdit", "Desktop")
    original = settings.value("recentProjects", []) or []
    settings.setValue("recentProjects", [str(project)])
    dialog = ProjectLibraryDialog()
    try:
        assert not thumb.exists()
        assert dialog.list_widget.count() == 1
    finally:
        dialog.close()
        settings.setValue("recentProjects", original)
