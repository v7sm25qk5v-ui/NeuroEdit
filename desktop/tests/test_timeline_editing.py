from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from neuroedit_desktop.models import ProjectState, TimelineMarker, VideoClip  # noqa: E402
from neuroedit_desktop.ui import editor_panels  # noqa: E402
from neuroedit_desktop.ui.editor_panels import (  # noqa: E402
    RichTimelineWidget,
    TimelineCanvas,
    project_end_time,
)


@pytest.fixture(scope="module", autouse=True)
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _clip(clip_id: str = "clip-1", start: float = 0.0, duration: float = 10.0) -> VideoClip:
    return VideoClip(
        id=clip_id,
        path="/tmp/example.mp4",
        name="Example",
        duration=duration,
        start_time=start,
        trim_start=0.0,
        trim_end=duration,
    )


def _marker(marker_id: str = "marker-1", at: float = 2.0, label: str = "Key moment") -> TimelineMarker:
    return TimelineMarker(id=marker_id, time=at, label=label)


def _project(**kwargs) -> ProjectState:
    project = ProjectState()
    project.zoom = 100.0
    for key, value in kwargs.items():
        setattr(project, key, value)
    return project


def _press(canvas: TimelineCanvas, x: float, y: float) -> None:
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(x, y),
        QPointF(x, y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mousePressEvent(event)


# --- _snap_time -------------------------------------------------------------


def test_snap_time_snaps_to_playhead_within_threshold() -> None:
    project = _project(current_time=5.0)
    canvas = TimelineCanvas(project)
    # zoom 100 px/s -> threshold 10 px = 0.1 s
    assert canvas._snap_time(5.05, "clip", "other") == 5.0


def test_snap_time_does_not_snap_outside_threshold() -> None:
    project = _project(current_time=5.0)
    canvas = TimelineCanvas(project)
    assert canvas._snap_time(5.2, "clip", "other") == 5.2


def test_snap_time_excludes_dragged_item() -> None:
    project = _project(current_time=50.0)
    project.clips.append(_clip("clip-1", start=3.0))
    canvas = TimelineCanvas(project)
    # Another item snaps to clip-1's start edge...
    assert canvas._snap_time(3.05, "clip", "other") == 3.0
    # ...but clip-1 itself does not snap to its own edges.
    assert canvas._snap_time(3.05, "clip", "clip-1") == 3.05


def test_snap_time_respects_toggle_off() -> None:
    project = _project(current_time=5.0)
    canvas = TimelineCanvas(project)
    canvas.snap_enabled = False
    assert canvas._snap_time(5.05, "clip", "other") == 5.05


def test_snap_time_threshold_scales_with_zoom() -> None:
    project = _project(current_time=5.0)
    project.zoom = 10.0  # threshold 10 px = 1.0 s
    canvas = TimelineCanvas(project)
    assert canvas._snap_time(5.8, "clip", "other") == 5.0


# --- Zoom-to-fit ------------------------------------------------------------


def test_zoom_to_fit_and_toggle_back() -> None:
    project = _project()
    project.clips.append(_clip(duration=500.0))
    widget = RichTimelineWidget(project)
    widget.resize(1200, 400)
    widget.show()
    QApplication.processEvents()
    prior_zoom = project.zoom

    widget._zoom_to_fit()

    viewport_width = widget.scroll.viewport().width()
    assert project.zoom * project_end_time(project) <= viewport_width - TimelineCanvas.LABEL_W
    assert 2.0 <= project.zoom <= 300.0
    assert project.zoom < prior_zoom
    assert widget.scroll.horizontalScrollBar().value() == 0

    widget._zoom_to_fit()  # toggle back
    assert project.zoom == prior_zoom
    widget.hide()


# --- Marker mutations -------------------------------------------------------


def test_delete_marker_removes_it_and_emits_project_changed() -> None:
    project = _project()
    project.markers.extend([_marker("m-1"), _marker("m-2", at=4.0)])
    canvas = TimelineCanvas(project)
    emitted: list[bool] = []
    canvas.project_changed.connect(lambda: emitted.append(True))

    canvas._delete_marker(project.markers[0])

    assert [m.id for m in project.markers] == ["m-2"]
    assert emitted


def test_edit_marker_updates_label(monkeypatch) -> None:
    project = _project()
    marker = _marker("m-1", label="Old")
    project.markers.append(marker)
    canvas = TimelineCanvas(project)
    monkeypatch.setattr(
        editor_panels.QInputDialog, "getText", staticmethod(lambda *a, **k: ("New label", True))
    )

    canvas._edit_marker(marker)

    assert marker.label == "New label"


def test_edit_marker_empty_result_is_noop(monkeypatch) -> None:
    project = _project()
    marker = _marker("m-1", label="Old")
    project.markers.append(marker)
    canvas = TimelineCanvas(project)
    monkeypatch.setattr(
        editor_panels.QInputDialog, "getText", staticmethod(lambda *a, **k: ("", True))
    )
    emitted: list[bool] = []
    canvas.project_changed.connect(lambda: emitted.append(True))

    canvas._edit_marker(marker)

    assert marker.label == "Old"
    assert not emitted


def test_rename_clip_updates_name(monkeypatch) -> None:
    project = _project()
    clip = _clip()
    project.clips.append(clip)
    canvas = TimelineCanvas(project)
    monkeypatch.setattr(
        editor_panels.QInputDialog, "getText", staticmethod(lambda *a, **k: ("Renamed", True))
    )

    canvas._rename_clip(clip)

    assert clip.name == "Renamed"


# --- Selection --------------------------------------------------------------


def test_click_selects_clip_and_empty_click_clears() -> None:
    project = _project()
    project.clips.append(_clip(duration=2.0))
    canvas = TimelineCanvas(project)

    # Inside the clip block: track 0 starts below the 30 px ruler.
    _press(canvas, TimelineCanvas.LABEL_W + 100, TimelineCanvas.RULER_H + 20)
    assert canvas.selected_item == ("clip", "clip-1")

    # Empty area of the video track clears the selection (and seeks).
    _press(canvas, TimelineCanvas.LABEL_W + 900, TimelineCanvas.RULER_H + 20)
    assert canvas.selected_item is None


def test_click_selects_marker() -> None:
    project = _project()
    project.markers.append(_marker("m-1", at=2.0))
    canvas = TimelineCanvas(project)

    y_top = canvas._track_y(3)
    _press(canvas, TimelineCanvas.LABEL_W + 2.0 * project.zoom, y_top + 10)
    assert canvas.selected_item == ("marker", "m-1")


def test_stale_selection_cleared_on_refresh() -> None:
    project = _project()
    clip = _clip()
    project.clips.append(clip)
    canvas = TimelineCanvas(project)
    canvas.selected_item = ("clip", clip.id)

    project.clips.clear()
    canvas.refresh_geometry()

    assert canvas.selected_item is None


# --- Snap guide line ----------------------------------------------------------


def test_snap_engagement_arms_guide_indicator() -> None:
    project = _project(current_time=5.0)
    canvas = TimelineCanvas(project)

    canvas._snap_indicator_time = None
    assert canvas._snap_time(5.05, "clip", "other") == 5.0
    assert canvas._snap_indicator_time == 5.0

    canvas._snap_indicator_time = None
    assert canvas._snap_time(7.0, "clip", "other") == 7.0
    assert canvas._snap_indicator_time is None


# --- Keyboard delete ----------------------------------------------------------


def _key(canvas: TimelineCanvas, key: Qt.Key) -> None:
    event = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    canvas.keyPressEvent(event)


def test_delete_key_removes_selected_clip() -> None:
    project = _project()
    project.clips.append(_clip())
    project.active_clip_id = "clip-1"
    canvas = TimelineCanvas(project)
    canvas.selected_item = ("clip", "clip-1")
    emitted: list[bool] = []
    canvas.project_changed.connect(lambda: emitted.append(True))

    _key(canvas, Qt.Key.Key_Delete)

    assert project.clips == []
    assert project.active_clip_id is None
    assert canvas.selected_item is None
    assert emitted


def test_backspace_removes_selected_marker() -> None:
    project = _project()
    project.markers.extend([_marker("m-1"), _marker("m-2", at=4.0)])
    canvas = TimelineCanvas(project)
    canvas.selected_item = ("marker", "m-1")

    _key(canvas, Qt.Key.Key_Backspace)

    assert [m.id for m in project.markers] == ["m-2"]
    assert canvas.selected_item is None


def test_delete_key_without_selection_is_noop() -> None:
    project = _project()
    project.clips.append(_clip())
    canvas = TimelineCanvas(project)
    emitted: list[bool] = []
    canvas.project_changed.connect(lambda: emitted.append(True))

    _key(canvas, Qt.Key.Key_Delete)

    assert len(project.clips) == 1
    assert not emitted


# --- Static layer cache -------------------------------------------------------


def test_playhead_move_reuses_static_cache() -> None:
    project = _project()
    project.clips.append(_clip())
    canvas = TimelineCanvas(project)

    canvas.grab()  # forces a paint
    first = canvas._static_cache
    assert first is not None

    # Playhead motion must NOT invalidate the static layer...
    project.current_time = 3.0
    canvas.grab()
    assert canvas._static_cache is first

    # ...but moving a block must.
    project.clips[0].start_time = 2.0
    canvas.grab()
    assert canvas._static_cache is not first
