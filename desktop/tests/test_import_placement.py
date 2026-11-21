"""Imported media goes in at the playhead (or the drop point), not at the end.

The point is the storyline edge nearest the time the import started at, so a
clip is never split by surprise; everything after it moves later by the total
imported length, and the whole import is one undo step.
"""
# ruff: noqa: F811  (pytest fixtures imported from test_main_window_headless)
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPointF, QUrl
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from neuroedit_desktop.models import (
    Annotation,
    AudioTrack,
    ProjectState,
    Slide,
    TimelineMarker,
    VideoClip,
)
from neuroedit_desktop.ui import main_window as main_window_module
from test_main_window_headless import _DropEvent, app, window  # noqa: F401


def _wait(win) -> None:
    for _ in range(500):
        QApplication.processEvents()
        if getattr(win, "_import_thread", None) is None:
            return
        QTest.qWait(10)
    pytest.fail("Import did not finish")


def _clip(clip_id: str, start: float, duration: float) -> VideoClip:
    return VideoClip(
        id=clip_id, path=f"/tmp/{clip_id}.mp4", name=clip_id, duration=duration,
        start_time=start, trim_start=0.0, trim_end=duration, width=1920, height=1080,
    )


def _populate(win) -> None:
    """A [0,10) B [10,20) C [20,30), with a slide, audio, marker, label and
    redaction all after the 10 s edge."""
    project = win.project
    project.clips = [_clip("A", 0, 10), _clip("B", 10, 10), _clip("C", 20, 10)]
    project.active_clip_id = "A"
    project.slides = [Slide(id="s", title="s", duration=3.0, start_time=30.0, insert=True)]
    project.audio_tracks = [AudioTrack(id="a", path="/tmp/a.wav", name="a", start_time=12.0, duration=4.0)]
    project.markers = [TimelineMarker(id="m", time=15.0, label="m")]
    project.annotations = [
        Annotation(id="early", frame_time=2.0, ann_duration=1.0, type="text", label="early", color="#fff"),
        Annotation(id="late", frame_time=25.0, ann_duration=1.0, type="text", label="late", color="#fff"),
        Annotation(id="red", frame_time=18.0, ann_duration=4.0, type="redact", label="red", color="#000"),
    ]
    project.zoom = 10.0
    win._invalidate_project_end_time()
    win._mark_dirty()


def _fixed_probe(monkeypatch, duration: float = 4.0) -> None:
    monkeypatch.setattr(main_window_module, "probe_video", lambda path: (duration, 1920, 1080))


def _starts(win) -> dict[str, float]:
    return {clip.id: round(clip.start_time, 6) for clip in win.project.clips}


def _paths(tmp_path: Path, *names: str) -> list[Path]:
    return [tmp_path / name for name in names]


def test_playhead_inside_a_clip_inserts_at_the_nearer_edge_without_splitting(window, tmp_path, monkeypatch):
    _populate(window)
    _fixed_probe(monkeypatch)
    window.project.current_time = 13.0  # inside B, nearer its start
    [video] = _paths(tmp_path, "new.mov")

    window._import_media_files([video])
    _wait(window)

    clips = window.project.clips
    assert len(clips) == 4  # nothing split
    assert [Path(c.path).name for c in clips] == ["A.mp4", "new.mov", "B.mp4", "C.mp4"]
    assert _starts(window) == {clips[0].id: 0.0, clips[1].id: 10.0, "B": 14.0, "C": 24.0}


def test_playhead_in_the_far_half_of_a_clip_goes_to_its_end(window, tmp_path, monkeypatch):
    _populate(window)
    _fixed_probe(monkeypatch)
    window.project.current_time = 17.0  # inside B, nearer its end
    window._import_media_files(_paths(tmp_path, "new.mov"))
    _wait(window)
    assert [Path(c.path).name for c in window.project.clips] == ["A.mp4", "B.mp4", "new.mov", "C.mp4"]
    assert window.project.clips[2].start_time == pytest.approx(20.0)
    assert window.project.clips[3].start_time == pytest.approx(24.0)


def test_playhead_past_the_end_appends(window, tmp_path, monkeypatch):
    _populate(window)
    _fixed_probe(monkeypatch)
    window.project.current_time = 500.0
    window._import_media_files(_paths(tmp_path, "new.mov"))
    _wait(window)
    last = window.project.clips[-1]
    assert Path(last.path).name == "new.mov"
    assert last.start_time == pytest.approx(33.0)  # after the inserted slide too
    assert "at the end" in window.statusBar().currentMessage()
    assert window.project.slides[0].start_time == pytest.approx(30.0)


def test_empty_timeline_imports_at_the_start(window, tmp_path, monkeypatch):
    _fixed_probe(monkeypatch)
    window._import_media_files(_paths(tmp_path, "a.mov", "b.mov"))
    _wait(window)
    assert [(Path(c.path).name, c.start_time) for c in window.project.clips] == [
        ("a.mov", 0.0), ("b.mov", 4.0),
    ]
    assert "Added 2 clips at the start" == window.statusBar().currentMessage()


def test_several_files_keep_their_order_and_sit_back_to_back(window, tmp_path, monkeypatch):
    _populate(window)
    _fixed_probe(monkeypatch)
    window.project.current_time = 10.0
    window._import_media_files(_paths(tmp_path, "z.mov", "a.mov", "m.mov"))
    _wait(window)
    clips = window.project.clips
    assert [Path(c.path).name for c in clips] == [
        "A.mp4", "z.mov", "a.mov", "m.mov", "B.mp4", "C.mp4",
    ]
    assert [c.start_time for c in clips] == pytest.approx([0, 10, 14, 18, 22, 32])


def test_later_items_shift_by_the_imported_length_and_earlier_ones_stay(window, tmp_path, monkeypatch):
    _populate(window)
    _fixed_probe(monkeypatch, 5.0)
    window.project.current_time = 10.0
    window._import_media_files(_paths(tmp_path, "x.mov", "y.mov"))  # 10 s in total
    _wait(window)
    project = window.project
    assert _starts(window)["A"] == 0.0
    assert _starts(window)["B"] == pytest.approx(20.0)
    assert _starts(window)["C"] == pytest.approx(30.0)
    assert project.slides[0].start_time == pytest.approx(40.0)
    assert project.audio_tracks[0].start_time == pytest.approx(22.0)
    assert project.markers[0].time == pytest.approx(25.0)
    by_id = {ann.id: ann for ann in project.annotations}
    assert by_id["early"].frame_time == pytest.approx(2.0)
    assert by_id["late"].frame_time == pytest.approx(35.0)
    assert by_id["red"].frame_time == pytest.approx(28.0)


def test_playhead_moves_to_the_first_new_clip_and_it_is_active(window, tmp_path, monkeypatch):
    _populate(window)
    _fixed_probe(monkeypatch)
    window.project.current_time = 20.0
    window._import_media_files(_paths(tmp_path, "x.mov", "y.mov"))
    _wait(window)
    first = window.project.clips[2]
    assert Path(first.path).name == "x.mov"
    assert window.project.current_time == pytest.approx(20.0)
    assert window.project.active_clip_id == first.id
    assert window.statusBar().currentMessage() == "Added 2 clips at 0:20.0"


def test_playhead_follows_the_new_clip_when_it_was_elsewhere(window, tmp_path, monkeypatch):
    _populate(window)
    _fixed_probe(monkeypatch)
    window.project.current_time = 28.0  # nearer C's end (30)
    window._import_media_files(_paths(tmp_path, "x.mov"))
    _wait(window)
    assert window.project.current_time == pytest.approx(30.0)
    assert window.project.active_clip_id == window.project.clips[3].id


def test_whole_import_is_one_undo_step(window, tmp_path, monkeypatch):
    _populate(window)
    _fixed_probe(monkeypatch)
    window.project.current_time = 10.0
    before = window.project.to_dict()
    history = len(window._undo_stack)
    window._import_media_files(_paths(tmp_path, "x.mov", "y.mov", "z.mov"))
    _wait(window)
    assert len(window._undo_stack) == history + 1
    window.undo()
    after = window.project.to_dict()
    for key in ("clips", "slides", "audio_tracks", "markers", "annotations"):
        assert after[key] == before[key], key


def test_images_follow_the_same_rule(window, tmp_path, monkeypatch):
    _populate(window)
    image = tmp_path / "still.png"
    assert QImage(10, 10, QImage.Format.Format_RGB32).save(str(image))
    window.project.current_time = 11.0
    window._import_media_files([image])
    _wait(window)
    clips = window.project.clips
    assert [Path(c.path).name for c in clips] == ["A.mp4", "still.png", "B.mp4", "C.mp4"]
    assert clips[1].start_time == pytest.approx(10.0)
    assert clips[2].start_time == pytest.approx(15.0)  # 5 s still


def test_drop_on_the_timeline_uses_the_drop_point_not_the_playhead(window, app, tmp_path, monkeypatch):
    _populate(window)
    _fixed_probe(monkeypatch)
    window.resize(1400, 900)
    window.show()
    app.processEvents()
    window.project.current_time = 0.0
    canvas = window.timeline.canvas
    # 19 s on the timeline: nearest edge is 20 (between B and C).
    canvas_pos = QPointF(canvas.LABEL_W + 19.0 * window.project.zoom, canvas.RULER_H + 5)
    window_pos = canvas.mapTo(window, canvas_pos.toPoint())
    video = tmp_path / "dropped.mov"
    video.touch()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(video))])

    class Event(_DropEvent):
        def position(self) -> QPointF:
            return QPointF(window_pos)

    event = Event(mime)
    window.dropEvent(event)
    _wait(window)

    assert event.accepted
    assert [Path(c.path).name for c in window.project.clips] == [
        "A.mp4", "B.mp4", "dropped.mov", "C.mp4",
    ]
    assert window.project.clips[2].start_time == pytest.approx(20.0)


def test_drop_outside_the_timeline_uses_the_playhead(window, app, tmp_path, monkeypatch):
    _populate(window)
    _fixed_probe(monkeypatch)
    window.project.current_time = 10.0
    video = tmp_path / "dropped.mov"
    video.touch()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(video))])
    window.dropEvent(_DropEvent(mime))  # position (0, 0): not over the timeline
    _wait(window)
    assert [Path(c.path).name for c in window.project.clips] == ["A.mp4", "dropped.mov", "B.mp4", "C.mp4"]


def test_project_changed_during_import_still_aborts(window, tmp_path, monkeypatch):
    _populate(window)
    import time

    def slow_probe(_path):
        time.sleep(0.1)
        return (4.0, 1920, 1080)

    monkeypatch.setattr(main_window_module, "probe_video", slow_probe)
    before = _starts(window)
    window.project.current_time = 10.0
    window._import_media_files(_paths(tmp_path, "x.mov"))
    window.project.project_name = "Changed while importing"
    _wait(window)
    assert _starts(window) == before
    assert len(window.project.clips) == 3


def test_insert_clips_at_model_and_default_append_unchanged():
    project = ProjectState()
    project.clips = [_clip("A", 0, 10), _clip("B", 10, 10)]
    appended = project.add_clip(Path("/tmp/n.mp4"), 3.0, 10, 10)
    assert appended.start_time == pytest.approx(20.0)
    new = [project.make_clip(Path("/tmp/x.mp4"), 2.0, 10, 10)]
    assert project.insert_clips_at(10.0, new) == pytest.approx(10.0)
    assert [c.id for c in project.clips][:1] == ["A"]
    assert project.clips[1] is new[0]
    assert project.clips[2].start_time == pytest.approx(12.0)
    assert project.clips[3].start_time == pytest.approx(22.0)


def test_import_at_the_start_keeps_an_opening_title_first():
    from neuroedit_desktop.models import ProjectState, Slide

    project = ProjectState()
    project.add_clip(Path("a.mp4"), duration=10, width=1920, height=1080)
    title = Slide(id="title", title="Title", duration=4.0)
    project.slides.append(title)
    project.insert_slide(title, 0.0)
    new = project.make_clip(Path("b.mp4"), duration=6, width=1920, height=1080)
    point = project.insert_clips_at(0.0, [new])
    assert point == 4.0 and title.start_time == 0.0
    assert new.start_time == 4.0
    assert project.clips[1].start_time == 10.0
