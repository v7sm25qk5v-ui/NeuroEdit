import json, os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QEvent, QPointF, QPoint, Qt, QSettings
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from test_main_window_headless import app, window  # noqa: F401
from neuroedit_desktop.models import Annotation, AudioTrack, TranscriptSegment, new_id
from neuroedit_desktop.sam_backend import SamBackend, SamBackendInfo
from neuroedit_desktop.ui import styles as ui_styles
from neuroedit_desktop.ui.main_window import MainWindow


# NE-014 repro moved to tests/test_main_window_headless.py when fixed.


def test_ne016_slider_does_not_flood_undo(window, tmp_path, monkeypatch):
    monkeypatch.setattr(window, "_sync_player_to_timeline", lambda **k: None)
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    window.project.audio_tracks.append(AudioTrack(id="t1", path=str(tmp_path / "v.wav"), name="V", duration=5))
    window.audio_panel.refresh()
    window.audio_panel.select_track("t1")
    window._seed_history()
    assert window.audio_panel._selected_track() is not None
    n = len(window._undo_stack)
    for v in range(99, 49, -1):
        window.audio_panel.volume_slider.setValue(v)
    print("NE016 growth", len(window._undo_stack) - n)
    assert len(window._undo_stack) - n <= 1


def test_ne020_gap_shifts_captions_and_mask_frames(window, tmp_path, monkeypatch):
    monkeypatch.setattr(window, "_sync_player_to_timeline", lambda **k: None)
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    window.project.add_clip(tmp_path / "m.mov", duration=20, width=100, height=100)
    seg = TranscriptSegment(id="s", audio_track_id=None, start_time=10, end_time=12, text="hi")
    window.project.transcript_segments.append(seg)
    ann = Annotation(id="a", frame_time=10.0, ann_duration=5.0, type="tracked-mask", label="m", color="#f00",
                     mask_frames=[{"time": 10.0, "mask_path": "a"}, {"time": 11.0, "mask_path": "b"}])
    window.project.annotations.append(ann)
    window._insert_timeline_gap(5.0, 5.0)
    times = [f["time"] for f in ann.mask_frames]
    print("NE020 seg", seg.start_time, seg.end_time, "ann", ann.frame_time, "mask times", times)
    assert seg.start_time == 15.0 and times == [15.0, 16.0]


def test_ne019_duration_event_does_not_dirty(window, tmp_path, monkeypatch):
    monkeypatch.setattr(window, "_sync_player_to_timeline", lambda **k: None)
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    c = window.project.add_clip(tmp_path / "m.mov", duration=20, width=100, height=100)
    window.project.active_clip_id = c.id
    window._seed_history()
    window.dirty = False
    window._duration_changed(20000)
    print("NE019 dirty", window.dirty)
    assert window.dirty is False


# NE-017, NE-018 and NE-022 repros were replaced by tests under tests/ when fixed.
