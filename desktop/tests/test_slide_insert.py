"""Inserted slides: a full slide that gets its own time in the video storyline.

The clips after it play later instead of being hidden behind it. Near a clip
edge the slide goes to the edge, so a slide meant to sit between two clips
never splits one a second from its end. Dragging one on the timeline moves it
between clips only.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from neuroedit_desktop.models import (
    Annotation,
    AudioTrack,
    ProjectState,
    Slide,
    TimelineMarker,
    VideoClip,
)
from neuroedit_desktop.ui.editor_panels import SlideEditorPanel, TimelineCanvas
from test_main_window_headless import window  # noqa: F401


@pytest.fixture(scope="module", autouse=True)
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _clip(clip_id: str, start: float, duration: float, path: str = "/tmp/clip.mp4") -> VideoClip:
    return VideoClip(
        id=clip_id, path=path, name=clip_id, duration=duration,
        start_time=start, trim_start=0.0, trim_end=duration,
    )


def _project(*lengths: float) -> ProjectState:
    """Back-to-back clips "A", "B", ... with the given lengths."""
    project = ProjectState(zoom=80.0)
    cursor = 0.0
    for index, length in enumerate(lengths):
        project.clips.append(_clip(chr(ord("A") + index), cursor, length))
        cursor += length
    return project


def _slide(slide_id: str = "s", duration: float = 5.0, start: float = 0.0, **kwargs) -> Slide:
    return Slide(id=slide_id, title=slide_id, duration=duration, start_time=start, **kwargs)


def _starts(project: ProjectState) -> dict[str, float]:
    return {clip.id: round(clip.start_time, 6) for clip in project.clips}


def _insert(project: ProjectState, slide: Slide, time_s: float) -> None:
    project.slides.append(slide)
    project.insert_slide(slide, project.slide_insert_point(time_s))


# --- where an inserted slide goes ---------------------------------------------

@pytest.mark.parametrize("aim, expected", [
    (0.0, 0.0),     # timeline start
    (0.7, 0.0),     # a second into A: to A's start, not a 0.7 s sliver
    (19.0, 20.0),   # a second before A ends: between A and B
    (21.5, 20.0),   # a second and a half into B: between A and B
    (10.0, 10.0),   # well inside A: a deliberate split
    (55.0, 40.0),   # past the end: right after the last clip
])
def test_insert_point_snaps_to_clip_edges_but_allows_a_deliberate_split(aim, expected):
    project = _project(20, 20)
    assert project.slide_insert_point(aim) == pytest.approx(expected)


def test_insert_point_snap_widens_when_zoomed_out():
    project = _project(20, 20)
    project.zoom = 2.0  # 16 px is 8 s: a click this far out cannot be precise
    assert project.slide_insert_point(13.0) == pytest.approx(20.0)
    project.zoom = 80.0
    assert project.slide_insert_point(13.0) == pytest.approx(13.0)


def test_insert_point_never_lands_inside_another_inserted_slide():
    project = _project(20, 20)
    _insert(project, _slide("first", 6), 20.0)  # [20, 26)
    assert project.slide_insert_point(21.0) == pytest.approx(20.0)
    assert project.slide_insert_point(25.0) == pytest.approx(26.0)
    # Past the end of everything, including a closing slide.
    _insert(project, _slide("closing", 4), 99.0)
    assert project.slides[-1].start_time == pytest.approx(46.0)
    assert project.slide_insert_point(80.0) == pytest.approx(50.0)


def test_drag_points_only_use_edges():
    project = _project(20, 20)
    assert project.slide_insert_point(10.5, boundaries_only=True) == pytest.approx(20.0)
    assert project.slide_insert_point(9.5, boundaries_only=True) == pytest.approx(0.0)


# --- inserting, moving, resizing, removing -------------------------------------

def test_title_slide_at_start_pushes_everything_later_and_hides_nothing():
    project = _project(20, 20)
    project.audio_tracks.append(AudioTrack(id="voice", path="v.wav", name="v", start_time=3, duration=4))
    project.markers.append(TimelineMarker(id="m", time=25.0, label="m"))
    title = _slide("title", 5)
    _insert(project, title, 0.4)

    assert (title.start_time, title.insert, title.overlay) == (0.0, True, False)
    assert _starts(project) == {"A": 5.0, "B": 25.0}
    assert project.audio_tracks[0].start_time == pytest.approx(8.0)
    assert project.markers[0].time == pytest.approx(30.0)
    # No clip overlaps the slide: nothing is hidden behind it.
    assert all(c.start_time >= title.start_time + title.duration - 1e-9 for c in project.clips)


def test_insert_well_inside_a_clip_splits_it_around_the_slide():
    project = _project(20)
    _insert(project, _slide("mid", 5), 10.0)
    assert [(c.start_time, c.trim_start, c.trim_end) for c in project.clips] == [
        (0.0, 0.0, 10.0), (15.0, 10.0, 20.0),
    ]
    assert project.clips[1].name.endswith("(after slide)")


def test_reordering_clips_keeps_the_title_slide_first():
    """Before this change a gap before the first clip collapsed on any clip
    move, sliding the first clip under the title slide."""
    project = _project(20, 20)
    _insert(project, _slide("title", 5), 0.0)
    project.arrange_clips_without_overlap()
    assert _starts(project) == {"A": 5.0, "B": 25.0}
    # Drag B in front of A on the timeline: both stay after the title slide.
    canvas = TimelineCanvas(project)
    canvas._preview_clip_move("B", 0.0)
    canvas._commit_clip_move()
    assert _starts(project) == {"B": 5.0, "A": 25.0}


def test_removing_an_inserted_slide_closes_its_time():
    project = _project(20, 20)
    project.markers.append(TimelineMarker(id="m", time=30.0, label="m"))
    title = _slide("title", 5)
    _insert(project, title, 20.0)
    assert _starts(project) == {"A": 0.0, "B": 25.0}
    assert project.remove_slide_gap(title)
    assert _starts(project) == {"A": 0.0, "B": 20.0}
    assert project.markers[0].time == pytest.approx(30.0)
    assert not title.insert


def test_move_between_clips_and_back_restores_everything():
    project = _project(20, 20)
    project.audio_tracks.append(AudioTrack(id="in", path="a.wav", name="a", start_time=2, duration=1))
    title = _slide("title", 5)
    _insert(project, title, 0.0)  # title [0,5), A [5,25), B [25,45), audio at 7
    before = project.to_dict()

    # Aim near the end of A, read with the slide taken out (A is then 0-20).
    project.move_inserted_slide(title, 18.5)
    assert title.start_time == pytest.approx(20.0)
    assert _starts(project) == {"A": 0.0, "B": 25.0}

    project.move_inserted_slide(title, 0.5)
    assert project.to_dict() == before


def test_a_drag_that_ends_in_the_same_slot_moves_nothing():
    """Items that start inside the slide's own time would move if the slide
    were closed and opened again in place."""
    project = _project(20, 20)
    title = _slide("title", 5)
    _insert(project, title, 20.0)
    project.audio_tracks.append(AudioTrack(id="inside", path="a.wav", name="a", start_time=22, duration=1))
    before = project.to_dict()
    project.move_inserted_slide(title, 19.0)
    assert project.to_dict() == before


def test_changing_an_inserted_slides_duration_pushes_or_pulls_what_follows():
    project = _project(20, 20)
    slide = _slide("s", 5)
    _insert(project, slide, 20.0)
    project.resize_inserted_slide(slide, 8.0)
    assert _starts(project)["B"] == pytest.approx(28.0)
    project.resize_inserted_slide(slide, 3.0)
    assert _starts(project)["B"] == pytest.approx(23.0)
    # A cover slide's duration moves nothing.
    cover = _slide("cover", 2, start=1.0)
    project.slides.append(cover)
    project.resize_inserted_slide(cover, 6.0)
    assert _starts(project) == {"A": 0.0, "B": 23.0}


def test_place_at_playhead_reads_the_playhead_in_the_current_layout():
    project = _project(20, 20)
    title = _slide("title", 5)
    _insert(project, title, 0.0)  # title [0,5), A [5,25), B [25,45)
    # Playhead 5 s into B: a deliberate split of B, 5 s in.
    project.place_inserted_slide(title, 30.0)
    assert [(c.id, c.start_time, c.trim_start) for c in project.clips] == [
        ("A", 0.0, 0.0), ("B", 20.0, 0.0), (project.clips[2].id, 30.0, 5.0),
    ]
    assert title.start_time == pytest.approx(25.0)


def test_redaction_on_the_next_clip_stays_with_its_footage():
    project = _project(20, 20)
    privacy = Annotation("privacy", 20.0, 4.0, "redact", "", "#000")
    project.annotations.append(privacy)
    slide = _slide("s", 5)
    _insert(project, slide, 20.0)
    assert (privacy.frame_time, privacy.ann_duration) == (25.0, 4.0)  # still on B's first 4 s
    project.resize_inserted_slide(slide, 7.0)
    assert privacy.frame_time == pytest.approx(27.0)
    project.remove_slide_gap(slide)
    assert (privacy.frame_time, privacy.ann_duration) == (pytest.approx(20.0), pytest.approx(4.0))


def test_old_projects_load_with_cover_slides():
    project = ProjectState.from_dict({"slides": [{"id": "s", "title": "t"}]})
    assert project.slides[0].insert is False
    assert ProjectState.from_dict(project.to_dict()).slides[0].insert is False


# --- timeline: dragging, deleting, painting ------------------------------------

def _mouse(canvas, kind, x, y, buttons=Qt.MouseButton.LeftButton):
    event = QMouseEvent(
        kind, QPointF(x, y), QPointF(x, y), Qt.MouseButton.LeftButton, buttons,
        Qt.KeyboardModifier.NoModifier,
    )
    {QEvent.Type.MouseButtonPress: canvas.mousePressEvent,
     QEvent.Type.MouseMove: canvas.mouseMoveEvent,
     QEvent.Type.MouseButtonRelease: canvas.mouseReleaseEvent}[kind](event)


def _slide_center(canvas, slide):
    rect = canvas._slide_block_rect(slide, max(1.0, canvas.project.zoom))
    return rect.center().x(), rect.center().y()


def _x(canvas, time_s):
    return canvas.LABEL_W + time_s * canvas.project.zoom


@pytest.fixture()
def titled():
    project = _project(20, 20)
    project.zoom = 20.0
    title = _slide("title", 5)
    _insert(project, title, 0.0)  # title [0,5), A [5,25), B [25,45)
    project.duration = 45.0  # as the app keeps it; the canvas recomputes it on drags
    canvas = TimelineCanvas(project)
    edits = []
    canvas.project_changed.connect(lambda: edits.append(True))
    return project, title, canvas, edits


def test_dragging_an_inserted_slide_parts_the_clips_live_and_is_one_edit(titled):
    project, title, canvas, edits = titled
    x, y = _slide_center(canvas, title)  # 2.5 s into the slide
    _mouse(canvas, QEvent.Type.MouseButtonPress, x, y)
    # Its start aimed 1.5 s before A's end (A is 0-20 with the slide out).
    _mouse(canvas, QEvent.Type.MouseMove, _x(canvas, 18.5 + 2.5), y)
    assert title.start_time == pytest.approx(20.0)
    assert _starts(project) == {"A": 0.0, "B": 25.0}
    assert canvas._snap_indicator_time == pytest.approx(20.0)
    # Back over the start, then out again: every move starts from the press.
    _mouse(canvas, QEvent.Type.MouseMove, _x(canvas, 1.0 + 2.5), y)
    assert _starts(project) == {"A": 5.0, "B": 25.0}
    _mouse(canvas, QEvent.Type.MouseMove, _x(canvas, 30.0 + 2.5), y)
    _mouse(canvas, QEvent.Type.MouseButtonRelease, _x(canvas, 30.0 + 2.5), y, Qt.MouseButton.NoButton)
    assert title.start_time == pytest.approx(20.0)
    assert len(project.clips) == 2, "a drag never splits a clip"
    assert edits == [True]


def test_escape_cancels_an_inserted_slide_drag(titled):
    project, title, canvas, edits = titled
    before = project.to_dict()
    x, y = _slide_center(canvas, title)
    _mouse(canvas, QEvent.Type.MouseButtonPress, x, y)
    _mouse(canvas, QEvent.Type.MouseMove, _x(canvas, 40.0), y)
    assert project.to_dict() != before
    canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert project.to_dict() == before
    _mouse(canvas, QEvent.Type.MouseButtonRelease, _x(canvas, 40.0), y, Qt.MouseButton.NoButton)
    assert project.to_dict() == before and edits == []


def test_deleting_an_inserted_slide_on_the_timeline_closes_its_time(titled):
    project, title, canvas, edits = titled
    canvas._set_selection(("slide", title.id))
    canvas._delete_selected_item()
    assert not project.slides
    assert _starts(project) == {"A": 0.0, "B": 20.0}
    assert edits == [True]


def test_cover_slide_drag_still_moves_freely(titled):
    project, _title, canvas, _edits = titled
    cover = _slide("cover", 2, start=10.0)
    project.slides.append(cover)
    canvas.snap_enabled = False
    x, y = _slide_center(canvas, cover)
    _mouse(canvas, QEvent.Type.MouseButtonPress, x, y)
    _mouse(canvas, QEvent.Type.MouseMove, x + 3 * project.zoom, y)
    _mouse(canvas, QEvent.Type.MouseButtonRelease, x + 3 * project.zoom, y, Qt.MouseButton.NoButton)
    assert cover.start_time == pytest.approx(13.0)
    assert _starts(project) == {"A": 5.0, "B": 25.0}


def test_inserted_cover_and_overlay_slides_paint(titled):
    project, title, canvas, _edits = titled
    project.slides.append(_slide("cover", 3, start=8.0))
    project.slides.append(_slide("overlay", 3, start=12.0, overlay=True))
    canvas.refresh_geometry()
    image = canvas.grab().toImage()
    assert not image.isNull()
    # The icon's centre bar is drawn in the middle of the inserted slide.
    cx, cy = _slide_center(canvas, title)
    ratio = image.devicePixelRatio()
    centre = image.pixelColor(int(cx * ratio), int(cy * ratio))
    edge = image.pixelColor(int((cx + 8) * ratio), int((cy - 9) * ratio))
    assert centre != edge


def test_cache_key_changes_with_placement(titled):
    _project_, title, canvas, _edits = titled
    key = canvas._static_fingerprint(20.0)
    title.insert = False
    assert canvas._static_fingerprint(20.0) != key


# --- Slides panel ---------------------------------------------------------------

@pytest.fixture()
def panel():
    project = _project(20, 20)
    widget = SlideEditorPanel(project)
    yield project, widget
    widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_new_slide_is_inserted_at_the_nearest_clip_edge(panel):
    project, widget = panel
    project.current_time = 21.0  # a second into B
    widget._create_slide()
    slide = project.slides[0]
    assert (slide.start_time, slide.insert) == (20.0, True)
    assert _starts(project) == {"A": 0.0, "B": 25.0}
    assert widget.placement_combo.currentData() == "insert"
    assert "inserted" in widget.list_widget.item(0).text()


def test_switching_placement_opens_and_closes_the_slides_time(panel):
    project, widget = panel
    project.current_time = 20.0
    widget._create_slide()
    slide = project.slides[0]
    widget.placement_combo.setCurrentIndex(widget.placement_combo.findData("cover"))
    assert (slide.insert, slide.overlay) == (False, False)
    assert _starts(project) == {"A": 0.0, "B": 20.0}
    widget.placement_combo.setCurrentIndex(widget.placement_combo.findData("overlay"))
    assert (slide.insert, slide.overlay) == (False, True)
    widget.placement_combo.setCurrentIndex(widget.placement_combo.findData("insert"))
    assert (slide.insert, slide.overlay, slide.start_time) == (True, False, 20.0)
    assert _starts(project) == {"A": 0.0, "B": 25.0}


def test_duration_edit_and_delete_in_the_panel_move_the_video(panel):
    project, widget = panel
    project.current_time = 20.0
    widget._create_slide()
    widget.duration_input.setValue(8.0)
    assert _starts(project)["B"] == pytest.approx(28.0)
    widget._delete_selected()
    assert not project.slides and _starts(project)["B"] == pytest.approx(20.0)


# --- export ---------------------------------------------------------------------

def test_export_shows_the_title_slide_then_the_whole_clip(tmp_path):
    from neuroedit_desktop.exporter import ExportSettings, ProjectExporter

    sample = Path(__file__).resolve().parents[1] / "src/neuroedit_desktop/resources/tutorial_clip.mp4"
    plain = ProjectState()
    plain.clips.append(_clip("A", 0.0, 4.0, str(sample)))
    titled_project = ProjectState.from_dict(plain.to_dict())
    title = _slide("title", 2, background="#ff0000")
    _insert(titled_project, title, 0.0)

    def frame(project, time_s):
        exporter = ProjectExporter(project, ExportSettings(tmp_path / "o.mp4", 160, 90, 30, 20, "t"))
        try:
            return exporter._render_frame(time_s)
        finally:
            exporter._release_captures()

    slide_frame = frame(titled_project, 1.0)
    assert np.all(slide_frame[45, 5] == [0, 0, 255]) or np.all(slide_frame[45, 5] == [255, 0, 0])
    # The clip's first frames are not lost behind the slide: they play after it.
    assert np.array_equal(frame(titled_project, 2.0 + 0.5), frame(plain, 0.5))


# --- review follow-ups ------------------------------------------------------------

def test_dragging_right_lands_where_the_pointer_is_drawn():
    """The pointer is read against the timeline as drawn; the clips after the
    slide are drawn a slide-length later than they are with it taken out."""
    project = _project(10, 10, 10)
    project.zoom = 20.0
    slide = _slide("s", 5)
    _insert(project, slide, 10.0)  # A 0-10, s 10-15, B 15-25, C 25-35
    canvas = TimelineCanvas(project)
    x, y = _slide_center(canvas, slide)  # 2.5 s into the slide
    _mouse(canvas, QEvent.Type.MouseButtonPress, x, y)
    _mouse(canvas, QEvent.Type.MouseMove, _x(canvas, 25.5 + 2.5), y)  # start aimed at B's drawn end
    assert slide.start_time == pytest.approx(20.0)  # after B, not after C
    assert _starts(project) == {"A": 0.0, "B": 10.0, "C": 25.0}
    # Holding the pointer there keeps it there.
    _mouse(canvas, QEvent.Type.MouseMove, _x(canvas, 20.5 + 2.5), y)
    assert slide.start_time == pytest.approx(20.0)
    _mouse(canvas, QEvent.Type.MouseButtonRelease, _x(canvas, 23.0), y, Qt.MouseButton.NoButton)


def test_take_still_room_never_lands_inside_an_inserted_slide():
    project = _project(10, 10)
    slide = _slide("s", 5)
    _insert(project, slide, 10.0)  # A 0-10, s 10-15, B 15-25
    point = project.insert_gap(project.outside_inserted_slides(12.0), 5.0)
    assert point == pytest.approx(10.0)
    assert slide.start_time == pytest.approx(15.0) and _starts(project)["B"] == pytest.approx(20.0)


@pytest.mark.parametrize("aim, expected", [(0.03, 0.0), (9.97, 10.0)])
def test_room_this_close_to_a_clip_edge_goes_to_the_edge(aim, expected):
    project = _project(10)
    privacy = Annotation("privacy", 0.01, 0.01, "redact", "", "#000")
    project.annotations.append(privacy)
    assert project.insert_gap(aim, 5.0) == pytest.approx(expected)
    assert len(project.clips) == 1
    clip = project.clips[0]
    assert clip.start_time == pytest.approx(5.0 if expected == 0.0 else 0.0)
    # The redacted footage moved with the clip and is still covered.
    assert privacy.frame_time == pytest.approx(clip.start_time + 0.01)


def test_redaction_moved_off_the_insertion_point_keeps_its_mask_frames_aligned():
    project = _project(10, 10)
    privacy = Annotation(
        "privacy", 10.0, 3.0, "redact", "", "#000",
        mask_frames=[{"time": 10.0, "mask_path": "a"}, {"time": 11.0, "mask_path": "b"}],
    )
    project.annotations.append(privacy)
    _insert(project, _slide("s", 5), 10.0)
    assert privacy.frame_time == pytest.approx(15.0)
    assert [frame["time"] for frame in privacy.mask_frames] == [15.0, 16.0]


def test_a_file_with_overlay_and_insert_both_set_is_an_overlay():
    project = _project(10, 10)
    project.slides.append(_slide("odd", 5, start=10.0, overlay=True, insert=True))
    assert not project.remove_slide_gap(project.slides[0])
    assert _starts(project) == {"A": 0.0, "B": 10.0}


def test_a_duration_the_spinner_cannot_show_survives_other_edits(panel):
    project, widget = panel
    project.slides.append(_slide("s", 0.3, start=20.0))
    project.slides[0].insert = True
    widget.refresh()
    widget.title_input.setText("renamed")
    assert project.slides[0].duration == pytest.approx(0.3)
    assert _starts(project) == {"A": 0.0, "B": 20.0}


def test_in_the_app_each_slide_edit_is_one_undo_step(window, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(window, "_sync_player_to_timeline", lambda **_k: None)
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    for name in ("first", "second"):
        window.project.add_clip(tmp_path / f"{name}.mov", duration=10, width=100, height=100)
    window._seed_history()
    panel = window.slides_panel
    window.project.current_time = 10.5

    depth = len(window._undo_stack)
    panel._create_slide()
    assert len(window._undo_stack) == depth + 1
    assert [c.start_time for c in window.project.clips] == [0.0, 15.0]

    panel.placement_combo.setCurrentIndex(panel.placement_combo.findData("cover"))
    assert len(window._undo_stack) == depth + 2
    assert [c.start_time for c in window.project.clips] == [0.0, 10.0]

    window.undo()
    assert [c.start_time for c in window.project.clips] == [0.0, 15.0]
    window.undo()
    assert [c.start_time for c in window.project.clips] == [0.0, 10.0]
    assert not window.project.slides


def test_redaction_ending_at_a_clip_edge_stops_at_an_inserted_slide():
    """The user's choice: a clip redacted to its last frame must not put the
    redaction box on the slide inserted after it."""
    project = _project(10, 10)
    privacy = Annotation("privacy", 0.0, 10.0, "redact", "", "#000")
    project.annotations.append(privacy)
    slide = _slide("s", 5)
    _insert(project, slide, 10.0)
    assert (privacy.frame_time, privacy.ann_duration) == (0.0, 10.0)
    assert not privacy.is_visible_at(12.0)
    # Growing the slide does not stretch it either; A's footage stays covered.
    project.resize_inserted_slide(slide, 7.0)
    assert (privacy.frame_time, privacy.ann_duration) == (0.0, 10.0)
    assert privacy.is_visible_at(9.99)


def test_redaction_ending_at_a_split_point_still_covers_the_resumed_footage():
    project = _project(20)
    privacy = Annotation("privacy", 0.0, 10.0, "redact", "", "#000")
    project.annotations.append(privacy)
    _insert(project, _slide("mid", 5), 10.0)  # splits the clip at 10
    assert privacy.is_visible_at(15.0), "source frame 10 resumes at 15 and stays covered"
