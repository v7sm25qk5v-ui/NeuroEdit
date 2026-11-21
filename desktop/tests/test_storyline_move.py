"""Reordering the storyline moves what is connected to each item with it.

The storyline is the video clips plus inserted slides, laid back to back.
Markers, finite labels, cover/overlay slides, loose captions and audio lying
inside one item ride on it; whole-timeline labels and long narrations stay;
redactions keep their own never-expose-footage rule.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from neuroedit_desktop.models import (
    Annotation,
    AudioTrack,
    ProjectState,
    Slide,
    TimelineMarker,
    TranscriptSegment,
    VideoClip,
)
from neuroedit_desktop.ui.editor_panels import TimelineCanvas

ZOOM = 100.0
approx = pytest.approx


@pytest.fixture(scope="module", autouse=True)
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _clip(clip_id: str, start: float, length: float) -> VideoClip:
    return VideoClip(
        id=clip_id, path=f"/tmp/{clip_id}.mp4", name=clip_id, duration=60.0,
        start_time=start, trim_start=0.0, trim_end=length,
    )


def _label(ann_id: str, start: float, duration: float, kind: str = "rect") -> Annotation:
    return Annotation(
        id=ann_id, frame_time=start, ann_duration=duration, type=kind,
        label=ann_id, color="#fff",
        geometry={"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.5},
    )


def _abc() -> ProjectState:
    """A 0-10, B 10-20, C 20-30."""
    project = ProjectState(zoom=ZOOM)
    project.clips = [_clip("A", 0.0, 10.0), _clip("B", 10.0, 10.0), _clip("C", 20.0, 10.0)]
    return project


def _starts(project: ProjectState) -> dict[str, float]:
    return {c.id: c.start_time for c in project.clips}


def _snapshot(project: ProjectState):
    return (list(project.clips), project.timeline_positions(), project.current_time)


def _restore(project: ProjectState, snap) -> None:
    project.clips = list(snap[0])
    project.restore_timeline_positions(snap[1])
    project.current_time = snap[2]


def _full_project() -> ProjectState:
    project = _abc()
    project.annotations = [
        _label("label-c", 22.0, 3.0),
        _label("label-a", 3.0, 2.0),
        _label("label-b", 12.0, 2.0),
        _label("whole", 5.0, 0.0),
        Annotation(
            id="tracked", frame_time=21.0, ann_duration=4.0, type="tracked-mask",
            label="tracked", color="#fff",
            mask_frames=[{"time": 21.0, "mask_path": "a.png"}, {"time": 23.0, "mask_path": "b.png"}],
        ),
        _label("redact-c", 21.0, 3.0, "redact"),
    ]
    project.markers = [
        TimelineMarker(id="m-c", time=21.0, label="c"),
        TimelineMarker(id="m-b", time=12.0, label="b"),
    ]
    project.slides = [
        Slide(id="cover-c", title="c", start_time=24.0, duration=2.0),
        Slide(id="overlay-a", title="a", start_time=1.0, duration=2.0, overlay=True),
    ]
    project.audio_tracks = [
        AudioTrack(id="narration", path="/tmp/n.m4a", name="n", start_time=8.0, duration=6.0),
        AudioTrack(id="sfx-c", path="/tmp/s.m4a", name="s", start_time=22.0, duration=3.0),
    ]
    project.transcript_segments = [
        TranscriptSegment("nar-1", "narration", 8.0, 10.0, "n1"),
        TranscriptSegment("sfx-1", "sfx-c", 22.0, 23.0, "s1"),
        TranscriptSegment("free-c", None, 26.0, 27.0, "free"),
        TranscriptSegment("free-a", None, 2.0, 3.0, "free a"),
    ]
    return project


def _by_id(items) -> dict:
    return {item.id: item for item in items}


def test_last_clip_to_front_carries_everything_connected() -> None:
    project = _full_project()
    project.reorder_storyline("C", 0)   # C 0-10, A 10-20, B 20-30
    ann, slides = _by_id(project.annotations), _by_id(project.slides)
    seg, tracks = _by_id(project.transcript_segments), _by_id(project.audio_tracks)
    markers = _by_id(project.markers)

    assert [c.id for c in project.clips] == ["C", "A", "B"]
    assert _starts(project) == {"C": 0.0, "A": 10.0, "B": 20.0}
    # Connected to C (-20)
    assert ann["label-c"].frame_time == approx(2.0)
    assert ann["label-c"].ann_duration == approx(3.0)
    assert markers["m-c"].time == approx(1.0)
    assert slides["cover-c"].start_time == approx(4.0)
    assert seg["free-c"].start_time == approx(6.0) and seg["free-c"].end_time == approx(7.0)
    assert tracks["sfx-c"].start_time == approx(2.0)
    assert seg["sfx-1"].start_time == approx(2.0) and seg["sfx-1"].end_time == approx(3.0)
    # Mask frame times shift with the label
    assert ann["tracked"].frame_time == approx(1.0)
    assert [f["time"] for f in ann["tracked"].mask_frames] == approx([1.0, 3.0])
    # Connected to A (+10) and B (+10)
    assert ann["label-a"].frame_time == approx(13.0)
    assert slides["overlay-a"].start_time == approx(11.0)
    assert seg["free-a"].start_time == approx(12.0)
    assert ann["label-b"].frame_time == approx(22.0)
    assert markers["m-b"].time == approx(22.0)
    # Stays put: whole-timeline label, narration spanning A and B
    assert (ann["whole"].frame_time, ann["whole"].ann_duration) == (5.0, 0.0)
    assert tracks["narration"].start_time == 8.0
    assert (seg["nar-1"].start_time, seg["nar-1"].end_time) == (8.0, 10.0)


def test_redactions_follow_footage_without_being_moved_twice() -> None:
    project = _full_project()
    project.reorder_storyline("C", 0)
    redact = _by_id(project.annotations)["redact-c"]
    assert (redact.frame_time, redact.ann_duration) == approx((1.0, 3.0))


def test_redaction_spanning_clips_that_become_apart_widens() -> None:
    project = _abc()
    spanning = _label("r", 8.0, 4.0, "redact")   # last 2 s of A, first 2 s of B
    project.annotations = [spanning]
    project.reorder_storyline("B", 2)            # A 0-10, C 10-20, B 20-30
    assert spanning.is_visible_at(8.0) and spanning.is_visible_at(9.9)
    assert spanning.is_visible_at(20.0) and spanning.is_visible_at(21.9)
    assert spanning.frame_time == approx(8.0) and spanning.ann_duration == approx(14.0)


def test_inserted_slide_keeps_its_place_between_neighbours() -> None:
    project = _abc()
    slide = Slide(id="S", title="S", start_time=20.0, duration=5.0, insert=True)
    project.clips[2].start_time = 25.0               # A 0-10, B 10-20, S 20-25, C 25-35
    project.slides = [slide]
    project.annotations = [_label("over-s", 21.0, 2.0)]
    project.markers = [TimelineMarker(id="m-s", time=22.0, label="s")]

    project.reorder_storyline("A", 3)                # B 0-10, S 10-15, C 15-25, A 25-35

    assert _starts(project) == {"B": 0.0, "C": 15.0, "A": 25.0}
    assert slide.start_time == approx(10.0)
    assert project.annotations[0].frame_time == approx(11.0)
    assert project.markers[0].time == approx(12.0)

    project.reorder_storyline("C", 0)                # C 0-10, B 10-20, S 20-25, A 25-35
    assert slide.start_time == approx(20.0)
    assert _starts(project) == {"C": 0.0, "B": 10.0, "A": 25.0}


def test_playhead_stays_on_the_same_frame_of_the_moved_clip() -> None:
    project = _abc()
    project.current_time = 23.5
    project.reorder_storyline("C", 0)
    assert project.current_time == approx(3.5)
    other = _abc()
    other.current_time = 5.0                         # inside A, not the moved clip
    other.reorder_storyline("C", 0)
    assert other.current_time == approx(5.0)


def test_undo_restores_everything() -> None:
    project = _full_project()
    project.current_time = 23.0
    before = _snapshot(project)
    values = [(obj, dict(vals)) for obj, vals in before[1]]
    project.reorder_storyline("C", 0)
    assert project.timeline_positions() != values
    _restore(project, before)
    assert [c.id for c in project.clips] == ["A", "B", "C"]
    after = project.timeline_positions()
    assert [(id(o), v) for o, v in after] == [(id(o), v) for o, v in values]
    assert project.current_time == 23.0


# --- through the real timeline drag -------------------------------------------


def _mouse(kind, x: float, y: float, button, buttons) -> QMouseEvent:
    return QMouseEvent(
        kind, QPointF(x, y), QPointF(x, y), button, buttons, Qt.KeyboardModifier.NoModifier,
    )


def _drag_clip(canvas: TimelineCanvas, from_time: float, to_time: float) -> None:
    y = canvas._track_y(0) + 20
    x = lambda t: canvas.LABEL_W + t * ZOOM  # noqa: E731
    canvas.mousePressEvent(_mouse(
        QEvent.Type.MouseButtonPress, x(from_time), y,
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton))
    canvas.mouseMoveEvent(_mouse(
        QEvent.Type.MouseMove, x(to_time), y,
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton))
    canvas.mouseReleaseEvent(_mouse(
        QEvent.Type.MouseButtonRelease, x(to_time), y,
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton))


def test_dragging_the_last_clip_to_the_front_moves_its_labels_with_it() -> None:
    project = _full_project()
    project.current_time = 23.0
    canvas = TimelineCanvas(project)
    changed = []
    canvas.project_changed.connect(lambda: changed.append(1))

    _drag_clip(canvas, 25.0, 1.0)

    ann = _by_id(project.annotations)
    assert [c.id for c in project.clips] == ["C", "A", "B"]
    assert ann["label-c"].frame_time == approx(2.0)
    assert ann["label-a"].frame_time == approx(13.0)
    assert ann["whole"].frame_time == 5.0
    assert _by_id(project.markers)["m-c"].time == approx(1.0)
    assert _by_id(project.slides)["cover-c"].start_time == approx(4.0)
    assert project.current_time == approx(3.0)
    assert project.duration == approx(30.0)
    assert len(changed) == 1                         # one drag, one edit


def test_drag_preview_shows_slides_in_the_new_order_and_matches_the_commit() -> None:
    project = _abc()
    project.clips[2].start_time = 25.0
    slide = Slide(id="S", title="S", start_time=20.0, duration=5.0, insert=True)
    cover = Slide(id="cover", title="c", start_time=27.0, duration=1.0)
    project.slides = [slide, cover]
    canvas = TimelineCanvas(project)

    canvas._preview_clip_move("C", 1.0)              # C first: C 0-10, A 10-20, B 20-30, S 30-35

    assert canvas._clip_preview_positions == approx({"C": 0.0, "A": 10.0, "B": 20.0})
    assert canvas._slide_preview_positions == approx({"S": 30.0, "cover": 2.0})
    assert slide.start_time == 20.0                  # nothing mutated while dragging
    canvas._commit_clip_move()
    assert (slide.start_time, cover.start_time) == approx((30.0, 2.0))
    assert _starts(project) == approx({"C": 0.0, "A": 10.0, "B": 20.0})


# --- moving an inserted slide --------------------------------------------------


def _slide_project() -> tuple[ProjectState, Slide]:
    """A 0-10, S 10-15, B 15-25, C 25-35."""
    project = ProjectState(zoom=ZOOM)
    project.clips = [_clip("A", 0.0, 10.0), _clip("B", 15.0, 10.0), _clip("C", 25.0, 10.0)]
    slide = Slide(id="S", title="S", start_time=10.0, duration=5.0, insert=True)
    project.slides = [slide, Slide(id="cover-a", title="c", start_time=2.0, duration=1.0)]
    project.annotations = [
        _label("over-s", 11.0, 2.0), _label("on-b", 18.0, 2.0), _label("whole", 0.0, 0.0),
    ]
    project.markers = [
        TimelineMarker(id="m-s", time=12.0, label="s"),
        TimelineMarker(id="m-c", time=30.0, label="c"),
    ]
    project.audio_tracks = [AudioTrack(id="sfx-s", path="/tmp/s.m4a", name="s",
                                       start_time=11.0, duration=2.0)]
    project.transcript_segments = [TranscriptSegment("cap-s", "sfx-s", 11.0, 12.0, "x")]
    return project, slide


def test_moving_an_inserted_slide_carries_what_sits_over_it() -> None:
    project, slide = _slide_project()
    project.move_inserted_slide(slide, 35.0)         # A 0-10, B 10-20, C 20-30, S 30-35
    ann = _by_id(project.annotations)

    assert _starts(project) == approx({"A": 0.0, "B": 10.0, "C": 20.0})
    assert slide.start_time == approx(30.0)
    assert ann["over-s"].frame_time == approx(31.0)
    assert _by_id(project.markers)["m-s"].time == approx(32.0)
    assert project.audio_tracks[0].start_time == approx(31.0)
    assert project.transcript_segments[0].start_time == approx(31.0)
    # Connected to their clips: B and C moved up 5, A did not move
    assert ann["on-b"].frame_time == approx(13.0)
    assert _by_id(project.markers)["m-c"].time == approx(25.0)
    assert _by_id(project.slides)["cover-a"].start_time == approx(2.0)
    assert ann["whole"].frame_time == 0.0


def test_moving_an_inserted_slide_to_the_front_pushes_clips_and_their_items() -> None:
    project, slide = _slide_project()
    project.move_inserted_slide(slide, 0.0)          # S 0-5, A 5-15, B 15-25, C 25-35
    ann = _by_id(project.annotations)

    assert slide.start_time == approx(0.0)
    assert _starts(project) == approx({"A": 5.0, "B": 15.0, "C": 25.0})
    assert ann["over-s"].frame_time == approx(1.0)
    assert _by_id(project.markers)["m-s"].time == approx(2.0)
    assert ann["on-b"].frame_time == approx(18.0)    # B did not move
    assert _by_id(project.slides)["cover-a"].start_time == approx(7.0)   # A moved +5


def test_placing_an_inserted_slide_at_the_playhead_carries_what_sits_over_it() -> None:
    project, slide = _slide_project()
    project.place_inserted_slide(slide, 35.0)
    assert slide.start_time == approx(30.0)
    assert _by_id(project.annotations)["over-s"].frame_time == approx(31.0)
    assert _by_id(project.markers)["m-s"].time == approx(32.0)


def test_dropping_an_inserted_slide_where_it_was_changes_nothing() -> None:
    project, slide = _slide_project()
    before = [(id(o), dict(v)) for o, v in project.timeline_positions()]
    project.move_inserted_slide(slide, 11.0)
    assert [(id(o), v) for o, v in project.timeline_positions()] == before
