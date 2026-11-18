# ruff: noqa: F811  (tests take the imported `window` fixture as an argument)
"""Instant cuts: a second player decodes the next clip before playback gets there.

Clips split from one long recording often jump far apart in the source. Seeking
the playing player at such a cut froze the picture for most of a second on
footage with an 8 s keyframe interval. Before a cut, the cue player now loads
the next clip paused on its own hidden surface, and at the cut the two players
trade places.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QImage
from PySide6.QtMultimedia import QMediaPlayer, QVideoFrame
from PySide6.QtWidgets import QApplication

from neuroedit_desktop.models import Slide, VideoClip
from neuroedit_desktop.ui.main_window import _PlaybackCue
from test_main_window_headless import window  # noqa: F401


@pytest.fixture(scope="module", autouse=True)
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _clip(clip_id, start, trim_start, length, path="/tmp/source.mp4", media_type="video"):
    return VideoClip(id=clip_id, path=path, name=clip_id, duration=300, start_time=start,
                     trim_start=trim_start, trim_end=trim_start + length, media_type=media_type)


def _layout(window, monkeypatch, clips, now):
    window.project.clips = clips
    window.project.current_time = now
    window.project.playback_rate = 1.0
    window._invalidate_project_end_time()
    monkeypatch.setattr(window, "_cached_clip_media_problem", lambda clip: None)


# ── When to cue ───────────────────────────────────────────────────────────


def test_far_jump_in_the_same_file_is_cued(window, monkeypatch):
    _layout(window, monkeypatch, [_clip("a", 0, 151.669, 4.9), _clip("b", 4.9, 235.4, 3.5)], 3.0)
    assert window._next_cut_clip().id == "b"


def test_cut_to_another_file_is_cued(window, monkeypatch):
    _layout(window, monkeypatch, [_clip("a", 0, 0, 4), _clip("b", 4, 0, 4, path="/tmp/other.mp4")], 2.0)
    assert window._next_cut_clip().id == "b"


@pytest.mark.parametrize("case", ["contiguous", "far", "image", "slide", "end", "problem"])
def test_cuts_that_need_no_cue(window, monkeypatch, case):
    clips = [_clip("a", 0, 10, 5), _clip("b", 5, 40, 5)]
    now = 3.0
    if case == "contiguous":
        clips[1] = _clip("b", 5, 15.0, 5)  # the playing player simply runs on
    elif case == "far":
        now = 1.0  # 4 s before the cut, outside the lead
    elif case == "image":
        clips[1] = _clip("b", 5, 0, 5, path="/tmp/still.png", media_type="image")
    elif case == "end":
        clips = clips[:1]
    _layout(window, monkeypatch, clips, now)
    if case == "slide":
        window.project.slides = [Slide(id="s", title="Title", start_time=5, duration=2)]
    if case == "problem":
        monkeypatch.setattr(window, "_cached_clip_media_problem", lambda clip: "missing")
    try:
        assert window._next_cut_clip() is None
    finally:
        window.project.slides = []


def test_lead_time_scales_with_playback_speed(window, monkeypatch):
    _layout(window, monkeypatch, [_clip("a", 0, 0, 20), _clip("b", 20, 100, 5)], 12.0)
    assert window._next_cut_clip() is None
    window.project.playback_rate = 4.0  # 8 s of timeline is 2 s of wall clock
    assert window._next_cut_clip().id == "b"


# ── Cue player state ──────────────────────────────────────────────────────


def _frame(start_ms):
    image = QImage(16, 9, QImage.Format.Format_RGB32)
    image.fill(QColor("blue"))
    frame = QVideoFrame(image)
    frame.setStartTime(start_ms * 1000)
    frame.setEndTime(start_ms * 1000 + 33_333)
    return frame


def test_cue_seeks_once_loaded_and_is_ready_only_at_its_frame(window, monkeypatch):
    seeks = []
    monkeypatch.setattr(window._cue_player, "setPosition", seeks.append)
    window._cue = _PlaybackCue("b", "/tmp/source.mp4", 235_400)
    window._cue_status_changed(QMediaPlayer.MediaStatus.LoadingMedia)
    assert seeks == []
    window._cue_status_changed(QMediaPlayer.MediaStatus.LoadedMedia)
    window._cue_status_changed(QMediaPlayer.MediaStatus.BufferedMedia)
    assert seeks == [235_400]
    window._cue_frame_arrived(_frame(156_000))  # the player's previous clip
    window._cue_frame_arrived(_frame(240_000))  # nowhere near the cue
    assert not window._cue.ready
    window._cue_frame_arrived(_frame(235_368))  # frame spanning the target
    assert window._cue.ready


def test_invalid_media_drops_the_cue(window):
    window._cue = _PlaybackCue("b", "/tmp/source.mp4", 1000)
    window._cue_status_changed(QMediaPlayer.MediaStatus.InvalidMedia)
    assert window._cue is None


class _StubPlayer:
    def __init__(self, path, duration=0):
        self._source = QUrl.fromLocalFile(path)
        self._duration = duration
        self.calls = []

    def source(self):
        return self._source

    def duration(self):
        return self._duration

    def pause(self):
        self.calls.append("pause")

    def play(self):
        self.calls.append("play")

    def setPlaybackRate(self, rate):  # noqa: N802
        self.calls.append(("rate", rate))

    def setPosition(self, ms):  # noqa: N802
        self.calls.append(("seek", ms))

    def position(self):
        return 156_500

    def stop(self):
        pass

    def setSource(self, source):  # noqa: N802
        self._source = source

    def mediaStatus(self):  # noqa: N802
        return QMediaPlayer.MediaStatus.LoadedMedia

    def playbackState(self):  # noqa: N802
        return QMediaPlayer.PlaybackState.PausedState


def _arm_cut(window, monkeypatch, *, ready=True, now=4.92):
    _layout(window, monkeypatch, [_clip("a", 0, 151.669, 4.9), _clip("b", 4.9, 235.4, 3.5)], now)
    window.project.active_clip_id = "a"
    playing, cued = _StubPlayer("/tmp/source.mp4"), _StubPlayer("/tmp/source.mp4")
    monkeypatch.setattr(window, "player", playing)
    monkeypatch.setattr(window, "_cue_player", cued)
    window._cue = _PlaybackCue("b", "/tmp/source.mp4", 235_400, seek_issued=True, ready=ready)
    window.video_view.set_image(None)
    return playing, cued


def test_cut_swaps_in_the_cued_player_without_seeking(window, monkeypatch):
    playing, cued = _arm_cut(window, monkeypatch)
    surface, standby = window.video_view.video_item, window.video_view.cue_video_item
    audio, cue_audio = window.audio, window._cue_audio
    audio.setVolume(0.6)
    audio.setMuted(False)
    window._timeline_playing = True
    try:
        window._sync_player_to_timeline(play=True)
    finally:
        window._timeline_playing = False
    assert window.player is cued and window._cue_player is playing
    assert playing.calls == ["pause"]
    assert "play" in cued.calls and not any(isinstance(c, tuple) and c[0] == "seek" for c in cued.calls)
    assert window.video_view.video_item is standby and window.video_view.cue_video_item is surface
    assert standby.isVisible() and not surface.isVisible()
    assert window.audio is cue_audio and window._cue_audio is audio
    assert window.audio.volume() == pytest.approx(0.6) and not window.audio.isMuted()
    assert window._cue_audio.isMuted()
    assert window._cue is None
    assert window.project.active_clip_id == "b"


@pytest.mark.parametrize("problem", ["not_ready", "late", "edited", "other_clip"])
def test_cut_falls_back_to_a_seek_when_the_cue_does_not_fit(window, monkeypatch, problem):
    playing, cued = _arm_cut(window, monkeypatch, ready=problem != "not_ready",
                             now=5.4 if problem == "late" else 4.92)
    if problem == "edited":
        window.project.clips[1].trim_start = 236.0  # trimmed after it was cued
        window.project.clips[1].trim_end = 239.5
    if problem == "other_clip":
        window._cue.clip_id = "c"
    surface = window.video_view.video_item
    window._sync_player_to_timeline(play=True)
    assert window.player is playing and window.video_view.video_item is surface
    assert cued.calls == []
    assert any(isinstance(c, tuple) and c[0] == "seek" for c in playing.calls)


def test_swapped_surface_shows_and_reports_frames(window):
    view = window.video_view
    view.set_image(None)
    old = view.video_item
    view.cue_video_item.videoSink().setVideoFrame(_frame(5000))
    view.swap_video_items()
    assert view.video_item is not old and view.video_item.isVisible() and not old.isVisible()
    assert view.annotation_item.video_item is view.video_item
    assert view._last_video_frame.isValid()
    # Frames from the now-hidden surface no longer feed the transition hold.
    old.videoSink().setVideoFrame(QVideoFrame())
    assert not view.transition_item.isVisible()
    view.swap_video_items()


# ── Real decoder ──────────────────────────────────────────────────────────


def test_real_far_jump_in_one_file_is_taken_from_the_cue(window, tmp_path, monkeypatch):
    """A long-GOP file played as two clips far apart: the cut uses the cue
    player, and the picture changes colour within a few frames of the cut."""
    import subprocess
    import time

    from PySide6.QtTest import QTest

    from neuroedit_desktop.exporter import resolve_ffmpeg

    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        pytest.skip("Real decoder test requires ffmpeg")
    path = tmp_path / "long_gop.mp4"
    # Red for 6 s then blue, with a single keyframe: a seek to 39 s must
    # decode from the start, like the 8 s GOPs of imported recordings.
    subprocess.run([
        ffmpeg, "-v", "error",
        "-f", "lavfi", "-i", "color=c=red:s=160x90:r=30:d=6",
        "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=30:d=36",
        "-filter_complex", "[0][1]concat=n=2:v=1[v]", "-map", "[v]",
        "-c:v", "libx264", "-g", "1000", "-pix_fmt", "yuv420p", str(path),
    ], check=True, timeout=30)
    window.project.clips = [
        VideoClip(id="a", path=str(path), name="A", duration=42, start_time=0, trim_start=1, trim_end=2.5),
        VideoClip(id="b", path=str(path), name="B", duration=42, start_time=1.5, trim_start=39, trim_end=40),
    ]
    window._invalidate_project_end_time()
    window.project.current_time = 0
    window.project.active_clip_id = "a"
    window._load_active_clip()
    window.video_view.set_project(window.project)
    taken = []
    original = window._take_cue
    monkeypatch.setattr(window, "_take_cue", lambda clip, ms: taken.append(original(clip, ms)) or taken[-1])
    window._toggle_play()
    samples = []
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and window._timeline_playing:
        QTest.qWait(10)
        image = window.video_view.viewport().grab().toImage()
        color = image.pixelColor(image.width() // 2, image.height() // 2)
        samples.append((window.project.current_time, color.red(), color.blue()))
    assert not window._timeline_playing, "Playback stalled"
    assert True in taken, "the cut did not use the cue player"
    first_blue = next(t for t, r, b in samples if b > 180 and r < 40)
    assert first_blue - 1.5 < 0.1, f"picture changed {first_blue - 1.5:.2f}s after the cut"
