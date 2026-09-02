from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from neuroedit_desktop.models import (  # noqa: E402
    Annotation,
    AudioTrack,
    ProjectState,
    Slide,
    TimelineMarker,
    VideoClip,
)
from neuroedit_desktop.ui import editor_panels  # noqa: E402
from neuroedit_desktop.ui.editor_panels import (  # noqa: E402
    RichTimelineWidget,
    TimelineCanvas,
    TrashDropTarget,
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


def _release(canvas: TimelineCanvas, x: float, y: float) -> None:
    event = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(x, y),
        QPointF(x, y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    canvas.mouseReleaseEvent(event)


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


def test_project_end_time_ignores_zero_duration_audio_placeholders() -> None:
    project = _project()
    project.clips.append(_clip(duration=5.0))
    project.audio_tracks.append(
        AudioTrack(
            id="empty",
            path="/tmp/empty.m4a",
            name="Empty",
            start_time=40.0,
            duration=0.0,
        )
    )

    assert project_end_time(project) == pytest.approx(5.0)


def test_project_end_time_is_not_extended_by_markers() -> None:
    project = _project()
    project.clips.append(_clip(duration=5.0))
    project.markers.append(_marker(at=5.0))

    assert project_end_time(project) == pytest.approx(5.0)


def test_trim_end_ripples_later_clips_and_updates_total() -> None:
    project = _project()
    first = _clip("first", start=0.0, duration=5.0)
    second = _clip("second", start=5.0, duration=5.0)
    project.clips.extend([first, second])
    canvas = TimelineCanvas(project)

    canvas._apply_trim_end(first, 3.0)

    assert first.display_duration == pytest.approx(3.0)
    assert second.start_time == pytest.approx(3.0)
    assert project_end_time(project) == pytest.approx(8.0)


def test_trim_ripple_shifts_downstream_timeline_items() -> None:
    project = _project()
    first = _clip("first", start=0.0, duration=5.0)
    second = _clip("second", start=5.0, duration=5.0)
    project.clips.extend([first, second])
    project.slides.append(Slide(id="slide", title="Still", start_time=5.0))
    project.audio_tracks.append(
        AudioTrack(id="audio", path="/tmp/a.m4a", name="Audio", start_time=5.0, duration=2.0)
    )
    project.markers.append(_marker(at=5.0))
    project.annotations.append(
        Annotation(
            id="ann", frame_time=5.0, ann_duration=1.0, type="arrow",
            label="Target", color="#fff",
        )
    )
    canvas = TimelineCanvas(project)

    canvas._apply_trim_end(first, 3.0)

    assert second.start_time == pytest.approx(3.0)
    assert project.slides[0].start_time == pytest.approx(3.0)
    assert project.audio_tracks[0].start_time == pytest.approx(3.0)
    assert project.markers[0].time == pytest.approx(3.0)
    assert project.annotations[0].frame_time == pytest.approx(3.0)


def test_trim_start_ripples_clip_to_primary_track_start() -> None:
    project = _project()
    first = _clip("first", start=0.0, duration=5.0)
    second = _clip("second", start=5.0, duration=5.0)
    project.clips.extend([first, second])
    canvas = TimelineCanvas(project)

    canvas._apply_trim_start(first, 2.0)

    assert first.trim_start == pytest.approx(2.0)
    assert first.start_time == pytest.approx(0.0)
    assert second.start_time == pytest.approx(3.0)
    assert project_end_time(project) == pytest.approx(8.0)


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


def test_delete_clip_ripples_later_clips_to_start() -> None:
    project = _project()
    project.clips.extend([
        _clip("first", start=0.0, duration=5.0),
        _clip("second", start=5.0, duration=5.0),
    ])
    canvas = TimelineCanvas(project)
    canvas.selected_item = ("clip", "first")

    canvas._delete_selected_item()

    assert len(project.clips) == 1
    assert project.clips[0].id == "second"
    assert project.clips[0].start_time == pytest.approx(0.0)
    assert project_end_time(project) == pytest.approx(5.0)


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


def test_delete_selected_item_audio_and_slide() -> None:
    project = _project()
    project.audio_tracks.append(
        AudioTrack(id="a1", path="/tmp/a.m4a", name="A", start_time=0.0, duration=3.0)
    )
    project.slides.append(Slide(id="s1", title="S", start_time=1.0))
    canvas = TimelineCanvas(project)

    canvas.selected_item = ("audio", "a1")
    canvas._delete_selected_item()
    assert project.audio_tracks == []

    canvas.selected_item = ("slide", "s1")
    canvas._delete_selected_item()
    assert project.slides == []


# --- Selection signal ---------------------------------------------------------


def test_selection_changed_signal_emits_on_change_only() -> None:
    project = _project()
    project.clips.append(_clip())
    canvas = TimelineCanvas(project)
    events: list[bool] = []
    canvas.selection_changed.connect(events.append)

    canvas._set_selection(("clip", "clip-1"))
    canvas._set_selection(("clip", "clip-1"))  # unchanged → no emit
    canvas._set_selection(None)

    assert events == [True, False]


# --- Floating trash delete target ---------------------------------------------


def test_trash_target_arms_and_disarms() -> None:
    trash = TrashDropTarget()
    assert trash._armed is False
    trash.set_armed(True)
    assert trash._armed is True
    trash.set_armed(False)
    assert trash._armed is False


def test_drag_drop_on_trash_deletes_dragged_item() -> None:
    project = _project()
    project.clips.append(_clip())
    project.active_clip_id = "clip-1"
    canvas = TimelineCanvas(project)
    canvas.trash_target = TrashDropTarget()
    # Simulate an in-progress drag that is hovering the trash on release.
    canvas.selected_item = ("clip", "clip-1")
    canvas._drag = ("clip", "clip-1", 0.0, 0.0)
    canvas._over_trash = True
    emitted: list[bool] = []
    canvas.project_changed.connect(lambda: emitted.append(True))

    _release(canvas, 500, 40)

    assert project.clips == []
    assert project.active_clip_id is None
    assert emitted


def test_drag_release_off_trash_keeps_item() -> None:
    project = _project()
    project.clips.append(_clip())
    canvas = TimelineCanvas(project)
    canvas.trash_target = TrashDropTarget()
    canvas.selected_item = ("clip", "clip-1")
    canvas._drag = ("clip", "clip-1", 0.0, 0.0)
    canvas._over_trash = False

    _release(canvas, 500, 40)

    assert len(project.clips) == 1  # a normal move, not a delete


def test_richtimeline_trash_visibility_follows_selection(app) -> None:
    project = _project()
    project.clips.append(_clip())
    widget = RichTimelineWidget(project)
    # isHidden() reflects the explicit show/hide state without needing a shown
    # parent window.
    assert widget.trash.isHidden()

    widget.canvas._set_selection(("clip", "clip-1"))
    assert not widget.trash.isHidden()

    widget.canvas._set_selection(None)
    assert widget.trash.isHidden()


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
