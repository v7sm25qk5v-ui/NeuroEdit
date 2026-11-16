"""NE-025: the guided tutorial must not change a project that already has work.

On a project with content the tour is "show, don't do": steps point at the
controls but input to the highlighted area is blocked and the on_enter actions
only change view state. On an empty project the hands-on tour is unchanged.

View-only keys ignored when comparing ``ProjectState.to_dict()`` before/after:
active_panel, active_tool, current_time, zoom, scroll_left,
selected_annotation_id (the tour legitimately switches panel/tool and seeks).
"""
# ruff: noqa: F811
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from neuroedit_desktop.models import Annotation, Slide, TimelineMarker, new_id
from neuroedit_desktop.ui.tutorial import TutorialOverlay, build_default_steps

from test_main_window_headless import app, reviewed, window  # noqa: F401

@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A modal QMessageBox would block forever offscreen; record instead."""
    from PySide6.QtWidgets import QDialog, QMessageBox

    shown = []
    monkeypatch.setattr(QDialog, "exec", lambda self: shown.append(("dialog", type(self).__name__)) or 0)
    for name in ("warning", "question", "information", "critical"):
        monkeypatch.setattr(
            QMessageBox, name,
            lambda *a, _n=name, **k: shown.append((_n, a[1:])) or QMessageBox.StandardButton.No,
        )
    return shown


VIEW_KEYS = {
    "active_panel", "active_tool", "current_time", "zoom", "scroll_left",
    "selected_annotation_id",
}


def _doc(window):
    return {k: v for k, v in window.project.to_dict().items() if k not in VIEW_KEYS}


def _state(window):
    p = window.project
    return (
        _doc(window),
        (p.phi_review_confirmed, p.deidentified_confirmed,
         p.audio_reviewed_for_phi, dict(p.phi_review_progress)),
        len(window._undo_stack), len(window._redo_stack), window.dirty,
    )


@pytest.fixture()
def worked(reviewed, monkeypatch):
    """`reviewed` plus an annotation, a marker and a slide; still not dirty."""
    monkeypatch.setattr(reviewed, "_seek_global", lambda *_a, **_k: None, raising=False)
    p = reviewed.project
    p.annotations.append(Annotation(
        id=new_id(), frame_time=1.0, ann_duration=2.0, type="rect",
        label="mine", color="#ff0000", geometry={"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
    ))
    p.markers.append(TimelineMarker(id=new_id(), time=2.0, label="m"))
    p.slides.append(Slide(id=new_id(), title="s", start_time=5.0))
    reviewed._seed_history()
    reviewed.dirty = False
    reviewed.show()
    return reviewed


def _click(overlay, pos: QPoint):
    for kind, fn in ((QEvent.Type.MouseButtonPress, overlay.mousePressEvent),
                     (QEvent.Type.MouseButtonRelease, overlay.mouseReleaseEvent)):
        fn(QMouseEvent(kind, QPointF(pos), QPointF(overlay.mapToGlobal(pos)),
                       Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier))


def _run_all_steps(overlay, app):
    for _ in range(len(overlay.steps)):
        # Try to "practice" inside the highlighted area on every step.
        if not overlay._target_rect.isEmpty():
            _click(overlay, overlay._target_rect.center())
        app.processEvents()
        overlay.advance()
        app.processEvents()


def test_full_tour_on_project_with_work_changes_nothing(worked, app):
    before = _state(worked)
    overlay = TutorialOverlay(worked, build_default_steps(worked))
    _run_all_steps(overlay, app)
    assert overlay.isHidden()
    assert _state(worked) == before


def test_dismissing_midway_changes_nothing(worked, app):
    before = _state(worked)
    overlay = TutorialOverlay(worked, build_default_steps(worked))
    for _ in range(6):
        _click(overlay, overlay._target_rect.center())
        overlay.advance()
    overlay.card.skip_btn.click()
    app.processEvents()
    assert overlay.isHidden()
    assert _state(worked) == before


def test_tour_on_project_with_work_is_view_only(worked, app):
    overlay = TutorialOverlay(worked, build_default_steps(worked))
    assert overlay._input_cutout_rect().isEmpty()
    for step in overlay.steps:
        assert not step.practice_mode
    assert "tour only" in overlay.steps[0].body.lower()
    overlay.close()


def test_empty_project_first_run_still_hands_on(window, app):
    window.show()
    assert not window.project.clips
    steps = build_default_steps(window)
    assert sum(s.practice_mode for s in steps) >= 10
    assert "sample clip" in steps[0].body.lower()
    forwarded = []
    overlay = TutorialOverlay(window, steps)
    overlay._forward_mouse = lambda target, event: forwarded.append(target)
    overlay.index = 4  # Choose the Rectangle Tool
    overlay._apply_step()
    assert window.label_input.currentText() == "practice target"
    assert not overlay._input_cutout_rect().isEmpty()
    _click(overlay, overlay._target_rect.center())
    assert forwarded  # clicks inside the highlight still reach the real control
    overlay.index = 9  # Try SAM Points
    overlay._apply_step()
    assert window.project.active_tool == "sam" and window.project.sam_points_enabled
    overlay.close()


def test_read_only_tour_can_be_driven_and_left_from_the_keyboard(worked, app):
    from PySide6.QtGui import QKeyEvent

    before = _state(worked)
    overlay = TutorialOverlay(worked, build_default_steps(worked))
    overlay.show()
    assert overlay.read_only
    closed = []
    overlay.finished.connect(lambda: closed.append(True))
    start = overlay.index

    def press(key):
        overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))

    press(Qt.Key.Key_Delete)          # an editing key: swallowed, nothing happens
    assert not closed and _state(worked) == before
    press(Qt.Key.Key_Return)          # next step
    assert overlay.index == start + 1
    press(Qt.Key.Key_Escape)          # leave the tour
    app.processEvents()
    assert closed
    assert _state(worked) == before


def test_starting_the_tutorial_does_not_add_the_sample_clip_to_a_project_with_work(window, monkeypatch):
    """A project with slides or labels but no clips is still the user's work."""
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    window.project.slides.append(Slide(id=new_id(), title="mine", start_time=0.0))
    window._seed_history()
    window.dirty = False
    before = (_doc(window), len(window._undo_stack), window.dirty)

    window._load_tutorial_video()

    assert (_doc(window), len(window._undo_stack), window.dirty) == before
    assert not window.project.clips


def test_read_only_tour_restores_the_users_panel_and_tool(worked, app):
    worked.project.active_panel = "labels"
    worked.project.active_tool = "select"
    before = _state(worked)

    overlay = TutorialOverlay(worked, build_default_steps(worked))
    overlay.show()
    while overlay.isVisible() and overlay.index < len(overlay.steps) - 1:
        overlay.advance()
    assert (worked.project.active_panel, worked.project.active_tool) != ("labels", "select")
    overlay.close()
    app.processEvents()

    assert (worked.project.active_panel, worked.project.active_tool) == ("labels", "select")
    assert _state(worked) == before


def test_read_only_tour_refuses_dropped_files_and_frees_the_keyboard_when_hidden(worked, app, tmp_path):
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QDragEnterEvent
    from PySide6.QtWidgets import QWidget

    before = _state(worked)
    overlay = TutorialOverlay(worked, build_default_steps(worked))
    overlay.show()

    # The overlay, not the window behind it, is the drop target, and it declines.
    assert overlay.acceptDrops()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path / "clip.mov"))])
    event = QDragEnterEvent(
        QPoint(50, 50), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    event.ignore()
    overlay.dragEnterEvent(event)
    assert not event.isAccepted()

    assert QWidget.keyboardGrabber() is overlay
    overlay.hide()
    assert QWidget.keyboardGrabber() is None
    overlay.close()
    app.processEvents()
    assert _state(worked) == before


def test_pristine_sample_after_restart_is_hands_on_but_edited_sample_is_not(window):
    from pathlib import Path
    from neuroedit_desktop.ui.tutorial import project_has_user_content
    import neuroedit_desktop.ui.tutorial as tutorial

    sample = Path(tutorial.__file__).parent.parent / "resources" / "tutorial_clip.mp4"
    clip = window.project.add_clip(sample, 10.0, 1920, 1080)
    assert not hasattr(window, "_tutorial_clip_id")
    assert not project_has_user_content(window)
    clip.trim_start = 1.0
    assert project_has_user_content(window)
