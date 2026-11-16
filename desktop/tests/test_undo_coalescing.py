"""NE-016: one undo step per slider drag or text edit (audio panel, slide
editor, labels inspector), with the live preview and PHI resets unchanged."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from neuroedit_desktop.models import Annotation, AudioTrack, Slide, TranscriptSegment
from neuroedit_desktop.ui.main_window import MainWindow
from test_main_window_headless import app, window  # noqa: F401


@pytest.fixture()
def invalidations(monkeypatch):
    """Count review resets. Patched before the window exists so the signal
    connections made in MainWindow.__init__ pick up the counting wrapper."""
    calls = []
    original = MainWindow._invalidate_review_attestations

    def counting(self):
        calls.append(1)
        original(self)

    monkeypatch.setattr(MainWindow, "_invalidate_review_attestations", counting)
    return calls


@pytest.fixture()
def win(invalidations, window, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(window, "_sync_player_to_timeline", lambda **k: None)
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    project = window.project
    project.audio_tracks += [
        AudioTrack(id="t1", path=str(tmp_path / "a.wav"), name="One", duration=5, volume=1.0),
        AudioTrack(id="t2", path=str(tmp_path / "b.wav"), name="Two", duration=5, volume=1.0),
    ]
    project.transcript_segments.append(
        TranscriptSegment(id="s1", audio_track_id=None, start_time=1, end_time=3, text="original")
    )
    project.slides.append(Slide(id="sl1", title="Old title", content="old body", duration=5,
                                start_time=0, background="#000", text_color="#fff", font_size=20))
    project.annotations.append(
        Annotation(id="an1", frame_time=0.0, ann_duration=4.0, type="rect", label="x", color="#fff"))
    window.audio_panel.refresh()
    window.slides_panel.refresh()
    window.labels_panel.refresh()
    window.audio_panel.select_track("t1")
    window._seed_history()
    invalidations.clear()
    return window


def _confirm_review(w):
    w.project.phi_review_confirmed = True
    w.project.deidentified_confirmed = True
    w.project.audio_reviewed_for_phi = True
    w.project.phi_review_progress = {"transcript": True}


def _steps(w):
    return len(w._undo_stack) - 1


def _track(w, track_id="t1"):
    return next(t for t in w.project.audio_tracks if t.id == track_id)


# ── audio panel ──────────────────────────────────────────────────────────────

def test_slider_drag_is_one_undo_step(win):
    panel = win.audio_panel
    slider = panel.volume_slider
    slider.setSliderDown(True)
    for value in range(99, 49, -1):
        slider.setValue(value)
        assert _track(win).volume == pytest.approx(value / 100)  # live model
        assert win.dirty and _steps(win) == 0  # no history during the drag
    slider.setSliderDown(False)  # emits sliderReleased
    assert _steps(win) == 1
    win.undo()
    assert _track(win).volume == pytest.approx(1.0)
    assert win.audio_panel.volume_slider.value() == 100


def test_slider_without_press_commits_when_idle(win):
    """Arrow keys / wheel: no sliderReleased, so an idle pause ends the edit."""
    for value in range(99, 49, -1):
        win.audio_panel.volume_slider.setValue(value)
    assert _steps(win) == 0
    QTest.qWait(900)
    assert _steps(win) == 1
    assert _track(win).volume == pytest.approx(0.5)


@pytest.mark.parametrize("control", ["volume", "opacity"])
def test_keyboard_step_then_held_slider_drag_stays_one_step_per_gesture(win, control):
    if control == "volume":
        slider = win.audio_panel.volume_slider
    else:
        win.labels_panel.set_selected_annotation("an1")
        slider = win.labels_panel.opacity_slider
    slider.setValue(70)  # keyboard or wheel starts an idle timer
    slider.setSliderDown(True)
    assert _steps(win) == 1
    slider.setValue(60)
    QTest.qWait(700)  # longer than the idle timer while the drag is held
    slider.setValue(50)
    assert _steps(win) == 1
    slider.setSliderDown(False)
    assert _steps(win) == 2


def test_spinbox_steps_commit_once_on_editing_finished(win):
    panel = win.audio_panel
    assert not panel.start_input.keyboardTracking()
    for value in (1.0, 1.5, 2.0, 2.5):
        panel.start_input.setValue(value)
    assert _steps(win) == 0
    panel.start_input.editingFinished.emit()
    assert _steps(win) == 1
    assert _track(win).start_time == pytest.approx(2.5)


def test_focus_out_without_change_creates_no_step(win):
    win.audio_panel.track_name.editingFinished.emit()
    win.audio_panel.start_input.editingFinished.emit()
    win.audio_panel.segment_text.editingFinished.emit()
    win.slides_panel.title_input.editingFinished.emit()
    assert _steps(win) == 0
    assert not win.dirty


def test_typed_track_name_is_one_step(win):
    for i in range(1, 9):
        win.audio_panel.track_name.setText("Renamed"[:i])
    win.audio_panel.track_name.editingFinished.emit()
    assert _steps(win) == 1
    win.undo()
    assert _track(win).name == "One"


def test_transcript_text_typing_one_step_and_phi_reset_immediately(win, invalidations):
    _confirm_review(win)
    edit = win.audio_panel.segment_text
    win.audio_panel.refresh_transcript()
    edit.setPlainText("original")
    win.audio_panel.gesture.reset()
    _confirm_review(win)
    win._seed_history()
    invalidations.clear()

    edit.moveCursor(edit.textCursor().MoveOperation.End)
    edit.insertPlainText("!")
    # Reset happens at the first keystroke, long before the edit is committed,
    # so no export can run on a stale caption confirmation.
    assert win.project.phi_review_progress == {}
    assert not win.project.phi_review_confirmed
    for ch in " more words typed here":
        edit.insertPlainText(ch)
    assert win.project.transcript_segments[0].text == "original! more words typed here"
    assert _steps(win) == 0
    edit.editingFinished.emit()
    assert _steps(win) == 1
    assert len(invalidations) == 1  # once per committed edit, not per keystroke

    win.undo()
    assert win.project.transcript_segments[0].text == "original"


def test_second_text_edit_resets_review_again_once(win, invalidations):
    edit = win.audio_panel.segment_text
    for text in ("first", "second"):
        _confirm_review(win)
        edit.insertPlainText(text)
        edit.insertPlainText("x")
        edit.editingFinished.emit()
    assert len(invalidations) == 2
    assert _steps(win) == 2


def test_switching_selection_commits_pending_edit_to_previous_item(win):
    win.audio_panel.volume_slider.setValue(40)
    assert _steps(win) == 0
    win.audio_panel.select_track("t2")
    assert _steps(win) == 1
    assert _track(win, "t1").volume == pytest.approx(0.4)
    assert _track(win, "t2").volume == pytest.approx(1.0)
    win.audio_panel.volume_slider.setValue(70)
    win.audio_panel.gesture.commit()
    assert _steps(win) == 2
    win.undo()
    assert _track(win, "t2").volume == pytest.approx(1.0)
    assert _track(win, "t1").volume == pytest.approx(0.4)
    win.undo()
    assert _track(win, "t1").volume == pytest.approx(1.0)


def test_undo_mid_edit_commits_then_undoes_it(win):
    win.audio_panel.volume_slider.setValue(30)
    win.audio_panel.volume_slider.setValue(20)
    win.undo()
    assert _track(win).volume == pytest.approx(1.0)
    assert not win.audio_panel.gesture.pending
    assert win.redo_action.isEnabled()
    win.redo()
    assert _track(win).volume == pytest.approx(0.2)


def test_pending_edit_is_committed_before_project_replacement(win, monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Discard),
    )
    win.audio_panel.volume_slider.setValue(10)
    assert _steps(win) == 0
    assert win._confirm_project_replacement() is True
    assert _steps(win) == 1  # recorded against the project it belongs to
    assert not win.audio_panel.gesture.pending


def test_discrete_audio_controls_still_one_step_each(win):
    win.audio_panel.captions_enabled_check.setChecked(True)
    assert _steps(win) == 1
    box = win.audio_panel.caption_background_check
    box.setChecked(not box.isChecked())
    assert _steps(win) == 2


def test_pending_volume_and_caption_toggle_undo_separately(win):
    win.audio_panel.volume_slider.setValue(40)
    win.audio_panel.captions_enabled_check.setChecked(True)
    assert _steps(win) == 2
    win.undo()
    assert not win.project.captions_enabled
    assert _track(win).volume == pytest.approx(0.4)
    win.undo()
    assert _track(win).volume == pytest.approx(1.0)


def test_pending_volume_and_track_start_undo_separately(win):
    panel = win.audio_panel
    panel.volume_slider.setValue(40)
    panel.start_input.setValue(2.0)
    panel.start_input.editingFinished.emit()
    assert _steps(win) == 2
    win.undo()
    assert _track(win).start_time == pytest.approx(0.0)
    assert _track(win).volume == pytest.approx(0.4)
    win.undo()
    assert _track(win).volume == pytest.approx(1.0)


# ── slide editor ─────────────────────────────────────────────────────────────

def test_slide_title_30_chars_is_one_step(win, invalidations):
    _confirm_review(win)
    panel = win.slides_panel
    panel.select_slide("sl1")
    title = "A thirty character slide title"[:30]
    assert len(title) == 30
    for i in range(1, 31):
        panel.title_input.setText(title[:i])
    assert win.project.slides[0].title == title
    assert win.project.phi_review_progress == {} and not win.project.phi_review_confirmed
    assert _steps(win) == 0
    panel.title_input.editingFinished.emit()
    assert _steps(win) == 1
    assert len(invalidations) == 1
    win.undo()
    assert win.project.slides[0].title == "Old title"


def test_slide_body_and_spinboxes_coalesce(win):
    panel = win.slides_panel
    panel.select_slide("sl1")
    for text in ("n", "ne", "new", "new body"):
        panel.content_input.setPlainText(text)
    assert _steps(win) == 0
    panel.content_input.editingFinished.emit()
    assert _steps(win) == 1
    assert not panel.duration_input.keyboardTracking()
    for value in (6.0, 7.0, 8.0):
        panel.duration_input.setValue(value)
    panel.duration_input.editingFinished.emit()
    assert _steps(win) == 2
    assert win.project.slides[0].duration == pytest.approx(8.0)


def test_slide_discrete_toggle_is_its_own_step(win):
    panel = win.slides_panel
    panel.select_slide("sl1")
    panel.bold_check.setChecked(not panel.bold_check.isChecked())
    assert _steps(win) == 1
    panel.italic_check.setChecked(True)
    assert _steps(win) == 2


def test_pending_slide_title_and_bold_toggle_undo_separately(win):
    panel = win.slides_panel
    panel.select_slide("sl1")
    original_bold = win.project.slides[0].bold
    panel.title_input.setText("New title")
    panel.bold_check.setChecked(not original_bold)
    assert _steps(win) == 2
    win.undo()
    assert win.project.slides[0].bold == original_bold
    assert win.project.slides[0].title == "New title"
    win.undo()
    assert win.project.slides[0].title == "Old title"


# ── labels inspector ─────────────────────────────────────────────────────────

def test_label_opacity_drag_is_one_step_with_live_model(win):
    panel = win.labels_panel
    panel.set_selected_annotation("an1")
    ann = win.project.annotations[0]
    slider = panel.opacity_slider
    slider.setSliderDown(True)
    for value in range(90, 40, -1):
        slider.setValue(value)
        assert ann.opacity == pytest.approx(value / 100)
    assert _steps(win) == 0 and win.dirty
    slider.setSliderDown(False)
    assert _steps(win) == 1
    win.undo()
    assert win.project.annotations[0].opacity != pytest.approx(0.41)


def test_label_spinboxes_commit_on_editing_finished(win):
    panel = win.labels_panel
    panel.set_selected_annotation("an1")
    assert not panel.duration_input.keyboardTracking()
    for value in (5.0, 5.5, 6.0):
        panel.duration_input.setValue(value)
    assert _steps(win) == 0
    panel.duration_input.editingFinished.emit()
    assert _steps(win) == 1
    assert win.project.annotations[0].ann_duration == pytest.approx(6.0)
    for value in (10, 11, 12):
        panel.font_size_input.setValue(value)
    panel.set_selected_annotation(None)  # selection change commits
    assert _steps(win) == 2
    assert win.project.annotations[0].font_size == 12


def test_direct_annotation_update_is_still_a_single_step(win):
    win._update_annotation_opacity("an1", 0.5)
    assert _steps(win) == 1


def test_pending_opacity_and_color_undo_separately(win):
    panel = win.labels_panel
    panel.set_selected_annotation("an1")
    original_opacity = win.project.annotations[0].opacity
    original_color = win.project.annotations[0].color
    panel.opacity_slider.setValue(40)
    panel._color_clicked("#ff0000")
    assert _steps(win) == 2
    win.undo()
    assert win.project.annotations[0].color == original_color
    assert win.project.annotations[0].opacity == pytest.approx(0.4)
    win.undo()
    assert win.project.annotations[0].opacity == pytest.approx(original_opacity)


def test_timeline_input_commits_pending_panel_edit_before_any_timeline_change(win):
    from PySide6.QtCore import QPoint, Qt

    win.audio_panel.volume_slider.setValue(70)
    assert win.audio_panel.gesture.pending
    QTest.mouseClick(win.timeline.canvas, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
    assert not win.audio_panel.gesture.pending
    assert _steps(win) == 1
    win.undo()
    assert _track(win).volume == pytest.approx(1.0)


def test_input_in_the_same_panel_keeps_text_gesture_pending(win):
    from PySide6.QtCore import Qt

    win.audio_panel.track_name.setText("New name")
    assert win.audio_panel.gesture.pending
    QTest.keyClick(win.audio_panel.track_name, Qt.Key.Key_End)
    assert win.audio_panel.gesture.pending
    assert _steps(win) == 0


# --- Typed spinbox values and re-confirmed review (independent review, 2026-11-16) ---


def _type_in_spinbox(spinbox, text):
    spinbox.setFocus()
    line_edit = spinbox.lineEdit()
    line_edit.selectAll()
    QTest.keyClicks(line_edit, text)


@pytest.mark.parametrize("target", ["label_duration", "slide_duration", "audio_start"])
def test_typed_spinbox_value_reaches_the_document_on_flush(win, target):
    """Digits typed into a spinbox are applied only on Enter or focus-out. Save,
    Export, Undo, and Quit shortcuts move neither, so the flush must take the
    value: a redaction must not be exported shorter than the field shows."""
    win.show()
    if target == "label_duration":
        win._set_panel("labels")
        win.labels_panel.set_selected_annotation("an1")
        spinbox, read = win.labels_panel.duration_input, lambda: win.project.annotations[0].ann_duration
    elif target == "slide_duration":
        win._set_panel("slides")
        win.slides_panel.select_slide("sl1")
        spinbox, read = win.slides_panel.duration_input, lambda: win.project.slides[0].duration
    else:
        win._set_panel("audio")
        spinbox, read = win.audio_panel.start_input, lambda: _track(win).start_time
    before, steps_before = read(), _steps(win)

    _type_in_spinbox(spinbox, "30")
    assert read() == before, "typing alone does not apply the value (keyboard tracking is off)"

    win._flush_pending_edits()

    assert read() == pytest.approx(30.0)
    assert _steps(win) == steps_before + 1
    win.undo()
    assert read() == pytest.approx(before)


def test_label_edit_after_review_was_reconfirmed_resets_it_again(win):
    win._set_panel("labels")
    win.labels_panel.set_selected_annotation("an1")
    spinbox = win.labels_panel.duration_input

    spinbox.setValue(3.0)          # gesture begins: review is reset
    _confirm_review(win)           # confirmed again while the field still has focus
    spinbox.setValue(1.0)          # a further change in the same gesture

    project = win.project
    assert not (
        project.phi_review_confirmed or project.deidentified_confirmed
        or project.audio_reviewed_for_phi or project.phi_review_progress
    )
