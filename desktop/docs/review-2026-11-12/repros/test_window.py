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


def test_ne014_zoom_does_not_reset_review(window, tmp_path, monkeypatch):
    window.project.add_clip(tmp_path / "m.mov", duration=10, width=100, height=100)
    monkeypatch.setattr(window, "_sync_player_to_timeline", lambda **k: None)
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    window.project.phi_review_confirmed = True
    window.project.deidentified_confirmed = True
    window._seed_history()
    n = len(window._undo_stack)
    window.timeline._set_zoom(120.0)
    print("NE014 flags", window.project.phi_review_confirmed, window.project.deidentified_confirmed,
          "stack", n, "->", len(window._undo_stack))
    assert window.project.phi_review_confirmed and window.project.deidentified_confirmed
    assert len(window._undo_stack) == n


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


def test_ne018_new_project_does_not_reuse_scratch(window, tmp_path, monkeypatch):
    window.project.add_clip(tmp_path / "m.mov", duration=10, width=100, height=100)
    window._mark_dirty()
    window._autosave()
    assert not window.dirty
    old = window.store.project_path
    assert "m.mov" in old.read_text()
    calls = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: calls.append(a) or QMessageBox.StandardButton.Cancel)
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    window._new_project()
    print("NE018 prompts", len(calls), "same path", window.store.project_path == old, old)
    assert calls or window.store.project_path != old


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


def test_ne022_release_outside_frame_emits_clamped(window, monkeypatch):
    view = window.video_view
    try:
        view.annotation_added.disconnect()
    except Exception:
        pass
    got = []
    view.annotation_added.connect(got.append)
    window.project.active_tool = "redact"
    view.annotation_item.project.active_tool = "redact"
    w = view.video_item.boundingRect().width()
    h = view.video_item.boundingRect().height()
    monkeypatch.setattr(view, "mapToScene", lambda p: QPointF(w + 10, h * 0.5))
    view._drag_start = (0.8, 0.5)
    ev = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(5, 5), QPointF(5, 5),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    view.mouseReleaseEvent(ev)
    print("NE022 emitted", len(got), "scene_to_norm", view._scene_to_norm(QPoint(5, 5)))
    assert len(got) == 1


@pytest.fixture()
def window_bad_autosave(app, tmp_path, monkeypatch):
    monkeypatch.setattr(SamBackend, "probe", lambda self: SamBackendInfo("missing", "none", "stubbed"))
    monkeypatch.setattr(MainWindow, "_maybe_show_first_run_tutorial", lambda self: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    settings = QSettings("NeuroEdit", "Desktop")
    orig = {k: settings.value(k) for k in ("storage/projectRoot", "storage/promptShown", "tutorial/seen")}
    settings.setValue("storage/projectRoot", str(tmp_path / "Autosave"))
    settings.setValue("storage/promptShown", True)
    settings.setValue("tutorial/seen", True)
    settings.setValue(ui_styles.THEME_SETTING_KEY, "light")
    ui_styles.apply_app_style(app, "light")
    bad = tmp_path / "Autosave" / "project.json"
    bad.parent.mkdir(parents=True)
    bad.write_text('{"clips": "not-a-list"')
    win = MainWindow()
    try:
        yield win
    finally:
        QApplication.processEvents()
        t = getattr(win, "_sam_probe_thread", None)
        if t is not None:
            t.quit(); t.wait(5000)
        win.close()
        for k, v in orig.items():
            settings.setValue(k, v if v is not None else "")


def test_ne017_unreadable_autosave_preserved(window_bad_autosave, tmp_path):
    win = window_bad_autosave
    win._mark_dirty()
    win._autosave()
    root = tmp_path / "Autosave"
    files = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    print("NE017 files", files, "store path", win.store.project_path)
    assert any(p.read_bytes() == b'{"clips": "not-a-list"' for p in root.rglob("*") if p.is_file())
