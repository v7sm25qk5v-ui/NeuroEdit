"""Timeline edits keep overlays with their footage (NE-010, NE-011).

NE-011: a trim drag must give the same result however many mouse moves it
takes, and dragging back must restore every item.
NE-010: a redaction must keep covering the footage it covered before a trim,
delete, or reorder. Over-covering is acceptable; exposing footage is not.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
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
from neuroedit_desktop.ui.editor_panels import TimelineCanvas  # noqa: E402

ZOOM = 100.0


@pytest.fixture(scope="module", autouse=True)
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _clip(clip_id: str, start: float, trim_start: float, trim_end: float) -> VideoClip:
    return VideoClip(
        id=clip_id, path=f"/tmp/{clip_id}.mp4", name=clip_id, duration=60.0,
        start_time=start, trim_start=trim_start, trim_end=trim_end,
    )


def _ann(ann_id: str, start: float, duration: float, kind: str = "rect") -> Annotation:
    return Annotation(
        id=ann_id, frame_time=start, ann_duration=duration, type=kind,
        label=ann_id, color="#fff",
        geometry={"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5},
    )


def _redact(start: float, duration: float, ann_id: str = "redact") -> Annotation:
    return _ann(ann_id, start, duration, "redact")


def _mouse(kind: QEvent.Type, x: float, y: float, button, buttons) -> QMouseEvent:
    return QMouseEvent(
        kind, QPointF(x, y), QPointF(x, y), button, buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def _press(canvas: TimelineCanvas, x: float, y: float) -> None:
    canvas.mousePressEvent(_mouse(
        QEvent.Type.MouseButtonPress, x, y,
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
    ))


def _move(canvas: TimelineCanvas, x: float, y: float) -> None:
    canvas.mouseMoveEvent(_mouse(
        QEvent.Type.MouseMove, x, y,
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
    ))


def _release(canvas: TimelineCanvas, x: float, y: float) -> None:
    canvas.mouseReleaseEvent(_mouse(
        QEvent.Type.MouseButtonRelease, x, y,
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
    ))


def _x(canvas: TimelineCanvas, time_s: float) -> float:
    return canvas.LABEL_W + time_s * ZOOM


def _two_clip_project() -> ProjectState:
    """first = timeline 0-10, second = timeline 10-20, both trimmable both ways,
    with one of every item type sitting inside the second clip."""
    project = ProjectState()
    project.zoom = ZOOM
    project.clips = [_clip("first", 0.0, 5.0, 15.0), _clip("second", 10.0, 5.0, 15.0)]
    project.annotations = [
        _ann("label-first", 9.7, 0.2),
        _ann("label-second", 14.0, 2.0),
        Annotation(
            id="tracked", frame_time=14.0, ann_duration=2.0, type="tracked-mask",
            label="tracked", color="#fff", mask_frames=[
                {"time": 14.0, "mask_path": "a.png"},
                {"time": 15.0, "mask_path": "b.png"},
            ],
        ),
        _redact(13.0, 4.0, "redact-second"),
        _redact(8.0, 4.0, "redact-spanning"),
        _redact(0.0, 0.0, "redact-all"),
    ]
    project.markers = [TimelineMarker(id="marker", time=14.5, label="m")]
    project.slides = [Slide(id="slide", title="s", start_time=15.0, overlay=True)]
    project.audio_tracks = [
        AudioTrack(id="voice", path="/tmp/v.m4a", name="v", start_time=14.0, duration=2.0)
    ]
    project.transcript_segments = [
        TranscriptSegment("linked", "voice", 14.0, 15.0, "linked"),
        TranscriptSegment("free", None, 16.0, 17.0, "free"),
    ]
    return project


def _positions(project: ProjectState) -> dict:
    return {
        "clips": {c.id: (c.start_time, c.trim_start, c.trim_end) for c in project.clips},
        "annotations": {
            a.id: (a.frame_time, a.ann_duration, [f["time"] for f in a.mask_frames])
            for a in project.annotations
        },
        "markers": [m.time for m in project.markers],
        "slides": [s.start_time for s in project.slides],
        "audio": [t.start_time for t in project.audio_tracks],
        "captions": [(s.start_time, s.end_time) for s in project.transcript_segments],
    }


def _approx_equal(actual: dict, expected: dict) -> None:
    assert actual["clips"].keys() == expected["clips"].keys()
    for clip_id, values in expected["clips"].items():
        assert actual["clips"][clip_id] == pytest.approx(values), clip_id
    for ann_id, (start, duration, frames) in expected["annotations"].items():
        got_start, got_duration, got_frames = actual["annotations"][ann_id]
        assert got_start == pytest.approx(start), ann_id
        assert got_duration == pytest.approx(duration), ann_id
        assert got_frames == pytest.approx(frames), ann_id
    for key in ("markers", "slides", "audio"):
        assert actual[key] == pytest.approx(expected[key]), key
    for got, want in zip(actual["captions"], expected["captions"], strict=True):
        assert got == pytest.approx(want)


def _drag(handle_time: float, targets: list[float], *, release: bool = True) -> ProjectState:
    """Press the trim handle that sits at `handle_time`, visit each target."""
    project = _two_clip_project()
    canvas = TimelineCanvas(project)
    canvas.snap_enabled = False
    y = canvas._track_y(0) + 20
    _press(canvas, _x(canvas, handle_time), y)
    for target in targets:
        _move(canvas, _x(canvas, target), y)
    if release:
        _release(canvas, _x(canvas, targets[-1]), y)
    return project


# --- NE-011: trim drags are path independent --------------------------------

HEAD = 10.02   # just inside the second clip's head handle
TAIL = 9.98    # just inside the first clip's tail handle


def test_head_trim_is_the_same_in_one_move_or_many() -> None:
    one = _drag(HEAD, [14.0])
    many = _drag(HEAD, [10.5 + 0.5 * step for step in range(8)])

    assert one.clips[1].trim_start == pytest.approx(9.0)
    by_id = {a.id: a for a in one.annotations}
    # 4 s into the second clip before the trim -> now at that clip's head.
    assert by_id["label-second"].frame_time == pytest.approx(10.0)
    assert [f["time"] for f in by_id["tracked"].mask_frames] == pytest.approx([10.0, 11.0])
    _approx_equal(_positions(many), _positions(one))


def test_head_extend_is_the_same_in_one_move_or_many() -> None:
    one = _drag(HEAD, [7.0])
    many = _drag(HEAD, [9.5, 9.0, 8.5, 8.0, 7.5, 7.0])

    assert one.clips[1].trim_start == pytest.approx(2.0)
    _approx_equal(_positions(many), _positions(one))


def test_tail_trim_is_the_same_in_one_move_or_many() -> None:
    one = _drag(TAIL, [8.5])
    many = _drag(TAIL, [9.5, 9.0, 8.5])

    assert one.clips[0].trim_end == pytest.approx(13.5)
    by_id = {a.id: a for a in one.annotations}
    assert by_id["label-second"].frame_time == pytest.approx(12.5)
    _approx_equal(_positions(many), _positions(one))


@pytest.mark.parametrize("handle, path", [
    (HEAD, [12.0, 14.0, 11.0, 10.0]),
    (HEAD, [8.0, 6.5, 9.0, 10.0]),
    (HEAD, [13.0, 8.0, 10.0]),
    (TAIL, [9.0, 8.0, 9.5, 10.0]),
    (TAIL, [11.0, 12.5, 10.0]),
    (TAIL, [8.0, 12.0, 10.0]),
])
def test_dragging_a_trim_handle_back_restores_every_item(handle, path) -> None:
    before = _positions(_two_clip_project())

    after = _drag(handle, path)

    _approx_equal(_positions(after), before)


def test_trim_without_a_drag_still_applies_one_ripple() -> None:
    """Direct calls (no press) keep working from the current state."""
    project = _two_clip_project()
    canvas = TimelineCanvas(project)

    canvas._apply_trim_start(project.clips[1], 12.0)
    canvas._apply_trim_start(project.clips[1], 12.0)

    assert project.clips[1].trim_start == pytest.approx(9.0)
    assert project.clips[1].start_time == pytest.approx(10.0)


# --- NE-010: redactions keep covering their footage -------------------------


def _covers(annotation: Annotation, start: float, end: float) -> bool:
    return annotation.is_visible_at(start) and annotation.is_visible_at(end)


def test_whole_timeline_redaction_stays_at_zero_when_head_is_extended() -> None:
    project = ProjectState()
    clip = _clip("c", 0.0, 2.0, 10.0)
    project.clips = [clip]
    redaction = _redact(0.0, 0.0)
    project.annotations = [redaction]

    clip.trim_start = 0.0
    project.ripple_after(0.0, 2.0, excluded_clip_id=clip.id)

    assert (redaction.frame_time, redaction.ann_duration) == (0.0, 0.0)
    assert redaction.is_visible_at(0.0)


def test_redaction_spanning_an_extended_clip_grows_with_it() -> None:
    project = ProjectState()
    first, second = _clip("a", 0.0, 0.0, 5.0), _clip("b", 5.0, 0.0, 10.0)
    project.clips = [first, second]
    redaction = _redact(0.0, 10.0)
    project.annotations = [redaction]

    first.trim_end += 2.0
    project.ripple_after(5.0, 2.0, excluded_clip_id=first.id)

    # It covered the first 5 s of `second`; it still must.
    assert _covers(redaction, 0.0, second.start_time + 5.0)


def test_redaction_touching_the_edit_point_covers_revealed_footage() -> None:
    project = ProjectState()
    ends_at_edit, starts_at_edit = _redact(2.0, 3.0, "ends"), _redact(5.0, 3.0, "starts")
    project.annotations = [ends_at_edit, starts_at_edit]

    project.ripple_after(5.0, 2.0)

    assert _covers(ends_at_edit, 2.0, 7.0)
    assert _covers(starts_at_edit, 5.0, 10.0)


def test_redaction_after_the_edit_point_moves_with_its_footage() -> None:
    project = ProjectState()
    finite, unlimited = _redact(12.0, 4.0, "finite"), _redact(12.0, 0.0, "unlimited")
    project.annotations = [finite, unlimited]

    project.ripple_after(5.0, 2.0)
    assert (finite.frame_time, finite.ann_duration) == pytest.approx((14.0, 4.0))
    assert (unlimited.frame_time, unlimited.ann_duration) == pytest.approx((14.0, 0.0))

    project.ripple_after(5.0, -2.0)
    assert (finite.frame_time, finite.ann_duration) == pytest.approx((12.0, 4.0))
    assert (unlimited.frame_time, unlimited.ann_duration) == pytest.approx((12.0, 0.0))


@pytest.mark.parametrize("start, duration, expected", [
    (4.0, 4.0, (3.0, 3.0)),    # starts on removed footage, ends after it
    (2.0, 6.0, (2.0, 4.0)),    # spans the whole cut
    (2.0, 2.0, (2.0, 1.0)),    # ends on removed footage
    (3.5, 1.0, (3.5, 1.0)),    # entirely on removed footage: left over-covering
    (3.0, 2.0, (3.0, 2.0)),    # exactly the removed footage: left over-covering
    (1.0, 1.5, (1.0, 1.5)),    # entirely before the cut
    (6.0, 2.0, (4.0, 2.0)),    # entirely after the cut
])
def test_finite_redaction_follows_footage_when_a_range_is_removed(start, duration, expected) -> None:
    """Timeline 3-5 is removed; later footage moves 2 s earlier."""
    project = ProjectState()
    redaction = _redact(start, duration)
    project.annotations = [redaction]

    project.ripple_after(5.0, -2.0)

    assert (redaction.frame_time, redaction.ann_duration) == pytest.approx(expected)
    assert redaction.ann_duration > 0  # 0 would silently mean "whole timeline"


@pytest.mark.parametrize("start, expected", [(0.0, 0.0), (2.0, 2.0), (4.0, 3.0), (9.0, 7.0)])
def test_unlimited_redaction_never_exposes_footage_when_a_range_is_removed(start, expected) -> None:
    project = ProjectState()
    redaction = _redact(start, 0.0)
    project.annotations = [redaction]

    project.ripple_after(5.0, -2.0)

    assert (redaction.frame_time, redaction.ann_duration) == pytest.approx((expected, 0.0))


def test_finite_redaction_never_collapses_to_unlimited() -> None:
    project = ProjectState()
    redaction = _redact(10.0, 2.0)
    project.annotations = [redaction]

    project.ripple_after(5.0, -20.0)

    assert redaction.frame_time == pytest.approx(0.0)
    assert redaction.ann_duration > 0


def test_ordinary_labels_ripple_as_before() -> None:
    project = ProjectState()
    spanning, later = _ann("spanning", 4.0, 4.0), _ann("later", 6.0, 2.0)
    project.annotations = [spanning, later]

    project.ripple_after(5.0, -2.0)

    assert (spanning.frame_time, spanning.ann_duration) == pytest.approx((4.0, 4.0))
    assert (later.frame_time, later.ann_duration) == pytest.approx((4.0, 2.0))


def _three_clip_canvas(*annotations: Annotation) -> tuple[ProjectState, TimelineCanvas]:
    project = ProjectState()
    project.zoom = ZOOM
    project.clips = [
        _clip("a", 0.0, 0.0, 5.0), _clip("b", 5.0, 0.0, 5.0), _clip("c", 10.0, 0.0, 5.0),
    ]
    project.annotations = list(annotations)
    canvas = TimelineCanvas(project)
    canvas.snap_enabled = False
    return project, canvas


def test_deleting_an_earlier_clip_keeps_redactions_on_their_footage() -> None:
    on_c = _redact(11.0, 3.0, "on-c")
    b_into_c = _redact(8.0, 4.0, "b-into-c")
    a_into_b = _redact(4.0, 4.0, "a-into-b")
    project, canvas = _three_clip_canvas(on_c, b_into_c, a_into_b)

    canvas.selected_item = ("clip", "b")
    canvas._delete_selected_item()

    assert [c.id for c in project.clips] == ["a", "c"]
    assert project.clips[1].start_time == pytest.approx(5.0)
    assert (on_c.frame_time, on_c.ann_duration) == pytest.approx((6.0, 3.0))
    # Covered the first 2 s of c; c now starts at 5.
    assert _covers(b_into_c, 5.0, 7.0)
    # Covered the last second of a, which did not move.
    assert _covers(a_into_b, 4.0, 5.0)


def _reorder(canvas: TimelineCanvas, from_time: float, to_time: float) -> None:
    y = canvas._track_y(0) + 20
    _press(canvas, _x(canvas, from_time), y)
    _move(canvas, _x(canvas, to_time), y)
    _release(canvas, _x(canvas, to_time), y)


def test_reordering_a_clip_moves_its_redaction_with_it() -> None:
    on_a = _redact(1.0, 3.0, "on-a")
    whole = _redact(0.0, 0.0, "whole")
    label = _ann("label", 1.0, 3.0)
    project, canvas = _three_clip_canvas(on_a, whole, label)

    _reorder(canvas, 2.5, 14.0)

    assert [c.id for c in project.clips] == ["b", "c", "a"]
    assert project.clips[2].start_time == pytest.approx(10.0)
    assert (on_a.frame_time, on_a.ann_duration) == pytest.approx((11.0, 3.0))
    assert (whole.frame_time, whole.ann_duration) == (0.0, 0.0)
    # Ordinary labels are anchored to the timeline, not the clip (unchanged).
    assert (label.frame_time, label.ann_duration) == pytest.approx((1.0, 3.0))


def test_reordering_widens_a_redaction_that_spans_two_clips() -> None:
    spanning = _redact(3.0, 5.0)   # last 2 s of a, first 3 s of b
    project, canvas = _three_clip_canvas(spanning)

    _reorder(canvas, 2.5, 14.0)    # a moves to the end: b=0-5, c=5-10, a=10-15

    assert _covers(spanning, 0.0, 3.0)     # b's first 3 s
    assert _covers(spanning, 13.0, 15.0)   # a's last 2 s
    assert spanning.ann_duration > 0


def test_reordering_moves_an_unlimited_redaction_start_with_its_first_clip() -> None:
    from_b = _redact(5.0, 0.0)             # everything from b onward
    project, canvas = _three_clip_canvas(from_b)

    _reorder(canvas, 12.5, 1.0)            # c moves to the front: c=0-5, a=5-10, b=10-15

    assert [c.id for c in project.clips] == ["c", "a", "b"]
    assert from_b.ann_duration == 0.0
    assert from_b.is_visible_at(0.0)       # c was covered and now starts at 0


def test_reorder_leaves_time_outside_clips_where_it_was() -> None:
    project = ProjectState()
    first, second = _clip("a", 0.0, 0.0, 5.0), _clip("b", 5.0, 0.0, 5.0)
    project.clips = [first, second]
    redaction = _redact(8.0, 4.0)          # b's last 2 s, then 2 s past the end
    project.annotations = [redaction]
    old_spans = {c.id: (c.start_time, c.start_time + c.display_duration) for c in project.clips}

    second.start_time, first.start_time = 0.0, 5.0
    project.move_redactions_with_clips(old_spans)

    assert _covers(redaction, 3.0, 5.0)    # b's last 2 s at their new place
    assert _covers(redaction, 10.0, 12.0)  # the time past the end did not move


def test_timeline_positions_round_trip() -> None:
    project = _two_clip_project()
    before = _positions(project)
    saved = project.timeline_positions()

    project.clips[1].trim_start = 9.0
    project.ripple_after(14.0, -4.0, excluded_clip_id="second")
    project.ripple_after(0.0, 3.0)
    assert _positions(project) != before

    project.restore_timeline_positions(saved)
    _approx_equal(_positions(project), before)


# --- Review follow-ups: snapping and trash drop during a trim drag ----------


def _drag_snapped(handle_time: float, targets: list[float], *, trash: bool = False) -> ProjectState:
    project = _two_clip_project()
    canvas = TimelineCanvas(project)
    assert canvas.snap_enabled  # the default, and what users drag with
    y = canvas._track_y(0) + 20
    _press(canvas, _x(canvas, handle_time), y)
    for target in targets:
        _move(canvas, _x(canvas, target), y)
    canvas._over_trash = trash
    _release(canvas, _x(canvas, targets[-1]), y)
    return project


@pytest.mark.parametrize("handle, final", [(TAIL, 8.04), (HEAD, 12.04), (HEAD, 7.96)])
def test_trim_with_snapping_does_not_stick_to_the_previous_move(handle, final) -> None:
    """Snap targets come from the press-time timeline, so a handle that passed
    close by on an earlier move does not drag the result with it."""
    one = _drag_snapped(handle, [final])
    many = _drag_snapped(handle, [round(final) - 1.0, float(round(final)), final])

    _approx_equal(_positions(many), _positions(one))


@pytest.mark.parametrize("handle, path", [
    (TAIL, [9.0, 8.0, 9.97]),
    (HEAD, [12.0, 13.5, 10.03]),
    (HEAD, [8.0, 9.5, 10.03]),
])
def test_trim_with_snapping_snaps_back_to_where_it_started(handle, path) -> None:
    before = _positions(_two_clip_project())

    after = _drag_snapped(handle, path)

    _approx_equal(_positions(after), before)


def test_dropping_a_trim_drag_on_the_trash_deletes_the_untrimmed_clip() -> None:
    plain = _two_clip_project()
    canvas = TimelineCanvas(plain)
    canvas.selected_item = ("clip", "first")
    canvas._delete_selected_item()

    dumped = _drag_snapped(9.98, [6.0, 3.0], trash=True)

    assert [c.id for c in dumped.clips] == ["second"]
    _approx_equal(_positions(dumped), _positions(plain))
