"""NE-020: inserting a Take Still gap shifts captions and tracked-mask frames."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from neuroedit_desktop.models import Annotation, AudioTrack, TranscriptSegment
from test_main_window_headless import app, window  # noqa: F401


@pytest.fixture()
def gap_window(window, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(window, "_sync_player_to_timeline", lambda **k: None)
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    window.project.add_clip(tmp_path / "m.mov", duration=20, width=100, height=100)
    window._seed_history()
    return window


def test_gap_shifts_captions_and_mask_frames(gap_window):
    project = gap_window.project
    seg = TranscriptSegment(id="s", audio_track_id=None, start_time=10, end_time=12, text="hi")
    early = TranscriptSegment(id="e", audio_track_id=None, start_time=1, end_time=2, text="x")
    project.transcript_segments += [seg, early]
    ann = Annotation(id="a", frame_time=10.0, ann_duration=5.0, type="tracked-mask", label="m",
                     color="#f00",
                     mask_frames=[{"time": 10.0, "mask_path": "a"}, {"time": 11.0, "mask_path": "b"}])
    project.annotations.append(ann)

    gap_window._insert_timeline_gap(5.0, 5.0)

    assert (seg.start_time, seg.end_time) == (15.0, 17.0)
    assert (early.start_time, early.end_time) == (1.0, 2.0)
    assert ann.frame_time == 15.0
    assert [f["time"] for f in ann.mask_frames] == [15.0, 16.0]
    assert ann.mask_path_at(15.5) == "a"


def test_gap_does_not_shift_anything_twice(gap_window):
    project = gap_window.project
    track = AudioTrack(id="t", path="/tmp/a.wav", name="a", duration=4, start_time=8.0)
    project.audio_tracks.append(track)
    seg = TranscriptSegment(id="s", audio_track_id="t", start_time=8.0, end_time=9.0, text="hi")
    project.transcript_segments.append(seg)

    gap_window._insert_timeline_gap(5.0, 5.0)

    assert track.start_time == 13.0
    assert (seg.start_time, seg.end_time) == (13.0, 14.0)
    # The clip was split: the right half starts after the gap, once.
    assert [round(c.start_time, 6) for c in project.clips] == [0.0, 10.0]


def test_gap_redactions_grow_or_stay_unlimited(gap_window):
    project = gap_window.project
    spanning = Annotation(id="r1", frame_time=2.0, ann_duration=6.0, type="redact", label="",
                          color="#000")
    unlimited = Annotation(id="r2", frame_time=2.0, ann_duration=0, type="redact", label="",
                           color="#000")
    later = Annotation(id="r3", frame_time=7.0, ann_duration=2.0, type="redact", label="",
                       color="#000")
    label = Annotation(id="l", frame_time=1.0, ann_duration=8.0, type="rect", label="", color="#fff")
    project.annotations += [spanning, unlimited, later, label]

    gap_window._insert_timeline_gap(5.0, 5.0)

    assert (spanning.frame_time, spanning.ann_duration) == (2.0, 11.0)
    assert (unlimited.frame_time, unlimited.ann_duration) == (2.0, 0)
    assert (later.frame_time, later.ann_duration) == (12.0, 2.0)
    assert label.ann_duration == 4.0


def test_take_still_undo_restores_captions_and_mask_frames(gap_window, monkeypatch, tmp_path):
    project = gap_window.project
    project.transcript_segments.append(
        TranscriptSegment(id="s", audio_track_id=None, start_time=10, end_time=12, text="hi"))
    project.annotations.append(
        Annotation(id="a", frame_time=10.0, ann_duration=5.0, type="tracked-mask", label="m",
                   color="#f00", mask_frames=[{"time": 10.0, "mask_path": "a"}]))
    gap_window._seed_history()
    project.current_time = 5.0
    still = tmp_path / "still.png"
    still.write_bytes(b"x")
    monkeypatch.setattr(gap_window, "_render_current_still", lambda t: still)

    gap_window._take_still()
    assert project.transcript_segments[0].start_time == 15.0
    assert project.annotations[0].mask_frames[0]["time"] == 15.0

    gap_window.undo()
    assert gap_window.project.transcript_segments[0].start_time == 10.0
    assert gap_window.project.annotations[0].mask_frames[0]["time"] == 10.0
