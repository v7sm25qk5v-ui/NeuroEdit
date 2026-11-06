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
    TranscriptSegment,
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


@pytest.mark.parametrize("delta, expected_start", [(-2.0, 8.0), (2.0, 12.0), (-20.0, 0.0)])
def test_ripple_keeps_mask_samples_and_captions_with_their_owner(delta, expected_start):
    project = ProjectState(
        audio_tracks=[
            AudioTrack(id="later", path="voice.wav", name="Later", start_time=10, duration=2),
            AudioTrack(id="early", path="other.wav", name="Earlier", start_time=0, duration=20),
        ],
        transcript_segments=[
            TranscriptSegment("linked", "later", 10, 11, "Linked caption"),
            TranscriptSegment("unlinked", None, 10, 11, "Independent caption"),
            TranscriptSegment("unmoved", "early", 10, 11, "Unmoved narration"),
        ],
        annotations=[Annotation(
            id="tracked", frame_time=10, ann_duration=2, type="tracked-mask",
            label="Tracked", color="#fff", mask_frames=[
                {"time": 10, "mask_path": "first.png"},
                {"time": 11, "mask_path": "second.png"},
            ],
        )],
    )

    project.ripple_after(5, delta)

    assert project.audio_tracks[0].start_time == expected_start
    for segment in project.transcript_segments[:2]:
        assert segment.start_time == expected_start
        assert segment.end_time == expected_start + 1
    assert project.transcript_segments[2].start_time == 10
    annotation = project.annotations[0]
    assert annotation.frame_time == expected_start
    assert annotation.mask_path_at(expected_start + 1) == "second.png"
    assert [frame["time"] for frame in annotation.mask_frames] == [expected_start, expected_start + 1]


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
    project.clips.extend([
        _clip("preceding", start=0.0, duration=3.0),
        _clip("clip-1", start=3.0),
    ])
    canvas = TimelineCanvas(project)
    # Another item snaps to clip-1's unique end edge...
    assert canvas._snap_time(12.95, "clip", "other") == 13.0
    # ...but clip-1 itself does not snap to its own edge.
    assert canvas._snap_time(12.95, "clip", "clip-1") == 12.95


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

    y_top = canvas._track_y(4)
    _press(canvas, TimelineCanvas.LABEL_W + 2.0 * project.zoom, y_top + 10)
    assert canvas.selected_item == ("marker", "m-1")


def test_click_annotation_selects_and_seeks_to_its_start() -> None:
    project = _project()
    project.clips.append(_clip(duration=8.0))
    project.annotations.append(
        Annotation(
            id="label-1", frame_time=2.0, ann_duration=3.0, type="rect",
            label="Optic nerve", color="#00e5ff",
        )
    )
    canvas = TimelineCanvas(project)
    seeks: list[float] = []
    canvas.seek_requested.connect(seeks.append)

    y_top = canvas._track_y(3)
    _press(canvas, TimelineCanvas.LABEL_W + 2.5 * project.zoom, y_top + 10)

    assert canvas.selected_item == ("annotation", "label-1")
    assert seeks == [2.0]


def test_timeline_canvas_ends_at_project_content() -> None:
    project = _project(zoom=100.0)
    project.clips.append(_clip(duration=5.0))
    canvas = TimelineCanvas(project)

    assert canvas.width() == TimelineCanvas.LABEL_W + 501


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


def _move(canvas, x, y):
    canvas.mouseMoveEvent(QMouseEvent(
        QEvent.Type.MouseMove, QPointF(x, y), QPointF(x, y),
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    ))


def test_canvas_preserves_existing_dead_space_until_an_explicit_edit():
    project = _project(clips=[_clip('a', 0, 5), _clip('b', 10, 5), _clip('c', 20, 5)])
    TimelineCanvas(project)

    assert [(c.id, c.start_time) for c in project.clips] == [
        ('a', 0), ('b', 10), ('c', 20),
    ]


def test_full_frame_slide_time_is_not_treated_as_dead_space():
    project = _project(
        clips=[_clip('left', 0, 4), _clip('right', 9, 4)],
        slides=[Slide(id='still', title='', start_time=4, duration=5, overlay=False)],
    )

    TimelineCanvas(project)

    assert [(clip.id, clip.start_time) for clip in project.clips] == [
        ('left', 0), ('right', 9),
    ]


def test_reorder_preview_preserves_full_frame_slide_time():
    project = _project(
        clips=[_clip('left', 0, 4), _clip('right', 9, 4)],
        slides=[Slide(id='still', title='', start_time=4, duration=5, overlay=False)],
    )
    canvas = TimelineCanvas(project)

    canvas._preview_clip_move('right', 0)

    assert canvas._clip_preview_positions == {'right': 0, 'left': 9}


@pytest.mark.parametrize('grab_offset', [0.2, 4.8])
def test_drag_reorders_compact_storyline_from_pointer(grab_offset):
    project = _project(clips=[_clip('a', 0, 5), _clip('b', 5, 5), _clip('c', 10, 5)])
    canvas = TimelineCanvas(project)
    y = canvas._track_y(0) + 20
    x = canvas.LABEL_W + grab_offset * project.zoom
    _press(canvas, x, y)
    drop_x = canvas.LABEL_W + 9 * project.zoom
    _move(canvas, drop_x, y)

    assert canvas._clip_preview_positions == {'b': 0, 'a': 5, 'c': 10}
    assert [c.start_time for c in project.clips] == [0, 5, 10]

    _release(canvas, drop_x, y)
    assert [(c.id, c.start_time) for c in project.clips] == [
        ('b', 0), ('a', 5), ('c', 10),
    ]


def test_long_clip_uses_pointer_to_choose_storyline_position():
    project = _project(clips=[_clip('a', 0, 20), _clip('b', 20, 1), _clip('c', 21, 1)])
    canvas = TimelineCanvas(project)
    y = canvas._track_y(0) + 20
    _press(canvas, canvas.LABEL_W + 100, y)
    _move(canvas, canvas.LABEL_W + 500, y)
    assert canvas._clip_preview_positions == {'a': 0, 'b': 20, 'c': 21}
    _release(canvas, canvas.LABEL_W + 500, y)
    assert [(c.id, c.start_time) for c in project.clips] == [
        ('a', 0), ('b', 20), ('c', 21),
    ]


def test_drag_can_return_without_an_edit():
    project = _project(clips=[_clip('a', 0, 5), _clip('b', 5, 5)])
    canvas = TimelineCanvas(project)
    y = canvas._track_y(0) + 20
    x = canvas.LABEL_W + 100
    _press(canvas, x, y)
    _move(canvas, x, y - 20)
    assert canvas._clip_preview_start is not None
    _move(canvas, x + 800, y)
    _move(canvas, x, y)
    _release(canvas, x, y)
    assert [(c.id, c.start_time) for c in project.clips] == [('a', 0), ('b', 5)]


def test_reorder_left_closes_unoccupied_gaps():
    project = _project(clips=[_clip('a', 0, 5), _clip('b', 5, 3), _clip('c', 20, 2)])
    canvas = TimelineCanvas(project)
    y = canvas._track_y(0) + 20
    x = canvas.LABEL_W + 6 * project.zoom
    _press(canvas, x, y)
    _move(canvas, x - 500, y)
    _release(canvas, x - 500, y)
    assert [(c.id, c.start_time) for c in project.clips] == [
        ('b', 0), ('a', 3), ('c', 8),
    ]


def test_overlapping_labels_are_separately_visible_and_clickable():
    project = _project(clips=[_clip()], annotations=[
        Annotation(id=str(i), frame_time=1, ann_duration=3, type='rect',
                   label=f'Label {i}', color='#fff', visible=i != 1)
        for i in range(3)
    ])
    canvas = TimelineCanvas(project)
    for i in range(3):
        y = canvas._track_y(3) + i * canvas.TRACK_H + 20
        _press(canvas, canvas.LABEL_W + 2 * project.zoom, y)
        assert canvas.selected_item == ('annotation', str(i))
    assert canvas._track_y(4) >= canvas._track_y(3) + 3 * canvas.TRACK_H


def test_repeated_splits_keep_source_name():
    project = _project(clips=[_clip()])
    widget = RichTimelineWidget(project)
    for t in [2, 4, 6]:
        project.current_time = t
        widget._cut_active_clip()
    assert [c.name for c in project.clips] == ['Example'] * 4


def test_mouse_wheel_scrolls_timeline_horizontally():
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QWheelEvent
    project = _project(clips=[_clip(duration=60)])
    widget = RichTimelineWidget(project)
    widget.resize(900, 400)
    widget.show()
    QApplication.processEvents()
    event = QWheelEvent(QPointF(200, 100), QPointF(200, 100), QPoint(), QPoint(0, -120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget.scroll.viewport(), event)
    assert widget.scroll.horizontalScrollBar().value() > 0
    assert project.current_time == 0
    widget.close()


def test_escape_cancels_reorder_without_moving_clips():
    project = _project(clips=[_clip('a', 0, 5), _clip('b', 5, 5)])
    canvas = TimelineCanvas(project)
    y = canvas._track_y(0) + 20
    x = canvas.LABEL_W + 100
    _press(canvas, x, y)
    _move(canvas, x + 600, y)
    _key(canvas, Qt.Key.Key_Escape)
    _release(canvas, x + 600, y)
    assert [(c.id, c.start_time) for c in project.clips] == [('a', 0), ('b', 5)]


def test_split_removes_accumulated_legacy_continuation_suffix():
    clip = _clip()
    clip.name = 'Example (cont.) (cont.)'
    project = _project(clips=[clip], current_time=5)
    RichTimelineWidget(project)._cut_active_clip()
    assert [c.name for c in project.clips] == ['Example', 'Example']


def test_short_split_clips_do_not_overlap_their_click_targets():
    project = _project(zoom=10, clips=[_clip('a', 0, 1), _clip('b', 1, 1), _clip('c', 2, 1)])
    canvas = TimelineCanvas(project)
    y = canvas._track_y(0) + 20
    for i, clip in enumerate(project.clips):
        _press(canvas, canvas.LABEL_W + (i + 0.5) * project.zoom, y)
        assert canvas.selected_item == ('clip', clip.id)
        assert canvas._drag[0] == 'clip'  # narrow clips are not all trim handles
        _release(canvas, canvas.LABEL_W + (i + 0.5) * project.zoom, y)


def test_clip_drag_scrolls_at_viewport_edge_and_stops_on_cancel():
    project = _project(clips=[_clip('a', 0, 5), _clip('b', 5, 55)])
    widget = RichTimelineWidget(project)
    widget.resize(900, 400)
    widget.show()
    QApplication.processEvents()
    canvas = widget.canvas
    y = canvas._track_y(0) + 20
    _press(canvas, canvas.LABEL_W + 100, y)
    viewport = widget.scroll.viewport()
    from PySide6.QtCore import QPoint
    pointer = viewport.mapToGlobal(QPoint(viewport.width() - 4, y))
    local = canvas.mapFromGlobal(pointer)
    canvas.mouseMoveEvent(QMouseEvent(
        QEvent.Type.MouseMove, QPointF(local), QPointF(pointer),
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    ))
    before = widget.scroll.horizontalScrollBar().value()
    canvas._autoscroll_clip_drag()
    assert widget.scroll.horizontalScrollBar().value() > before
    assert canvas._clip_scroll_timer.isActive()
    _key(canvas, Qt.Key.Key_Escape)
    assert not canvas._clip_scroll_timer.isActive()
    widget.close()


@pytest.mark.parametrize('snap_enabled', [True, False])
def test_video_storyline_stays_magnetic_when_snap_toggle_changes(snap_enabled):
    project = _project(clips=[_clip('moving', 0, 2), _clip('next', 2, 2)])
    canvas = TimelineCanvas(project)
    canvas.snap_enabled = snap_enabled
    y = canvas._track_y(0) + 20
    _press(canvas, canvas.LABEL_W + 100, y)
    x = canvas.LABEL_W + 350
    canvas.mouseMoveEvent(QMouseEvent(
        QEvent.Type.MouseMove, QPointF(x, y), QPointF(x, y),
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    ))
    assert canvas._clip_preview_positions == {'next': 0, 'moving': 2}
    _release(canvas, x, y)
    assert [(clip.id, clip.start_time) for clip in project.clips] == [
        ('next', 0), ('moving', 2),
    ]


def test_drag_beyond_end_previews_append_then_escape_restores_order():
    project = _project(clips=[_clip('a', 0, 2)])
    canvas = TimelineCanvas(project)
    original_width = canvas.width()
    y = canvas._track_y(0) + 20
    _press(canvas, canvas.LABEL_W + 100, y)
    _move(canvas, canvas.LABEL_W + 500, y)
    assert canvas.width() == original_width
    assert canvas._clip_preview_positions == {'a': 0}
    _key(canvas, Qt.Key.Key_Escape)
    assert canvas.width() == original_width
    assert project.clips[0].start_time == 0
