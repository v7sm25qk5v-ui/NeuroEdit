"""NE-019: media duration events do not dirty an unchanged project, and a no-op
history push does not drop the redo stack."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from test_main_window_headless import app, reviewed, window  # noqa: F401


def test_unchanged_duration_event_keeps_project_clean(reviewed):  # noqa: F811
    win = reviewed
    refreshes = []
    win.refresh = lambda *a, **k: refreshes.append(1)
    before = (len(win._undo_stack), len(win._redo_stack))

    win._duration_changed(10000)

    assert win.dirty is False
    assert refreshes == []
    assert (len(win._undo_stack), len(win._redo_stack)) == before


def test_zero_or_negative_duration_event_is_ignored(reviewed):  # noqa: F811
    reviewed._duration_changed(0)
    reviewed._duration_changed(-5)
    assert reviewed.dirty is False


def test_corrected_duration_is_saved_without_history_or_redo_loss(reviewed):  # noqa: F811
    win = reviewed
    before = (len(win._undo_stack), len(win._redo_stack))

    win._duration_changed(12500)

    clip = win.project.clips[0]
    assert clip.duration == 12.5
    assert clip.trim_end == 12.5
    assert win.dirty is True
    assert (len(win._undo_stack), len(win._redo_stack)) == before


def test_noop_push_history_keeps_redo(reviewed):  # noqa: F811
    win = reviewed
    assert len(win._redo_stack) == 1
    win._push_history()  # nothing changed since the undo
    assert len(win._redo_stack) == 1
    assert win.redo_action.isEnabled()


def test_real_change_push_history_clears_redo(reviewed):  # noqa: F811
    win = reviewed
    win.project.project_name = "something new"
    win._push_history()
    assert win._redo_stack == []
    assert not win.redo_action.isEnabled()


def test_undo_redo_across_source_change_survives_duration_events(reviewed):  # noqa: F811
    win = reviewed
    win.redo()
    win._duration_changed(10000)  # Qt re-emits after the source reloads
    win.undo()
    win._duration_changed(10000)
    assert len(win._redo_stack) == 1
    win.redo()
    assert win.project.project_name == "renamed"
