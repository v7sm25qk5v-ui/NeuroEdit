from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from neuroedit_desktop.models import Annotation, ProjectState  # noqa: E402
from neuroedit_desktop.ui.main_window import MainWindow  # noqa: E402


class _StubPanel:
    def __init__(self) -> None:
        self.selected_annotation_id: str | None = None

    def set_selected_annotation(self, annotation_id: str | None) -> None:
        self.selected_annotation_id = annotation_id


class _StubView:
    def update_annotations(self) -> None:
        pass


def _annotation(annotation_id: str = "ann-1", label: str = "Tumor") -> Annotation:
    return Annotation(
        id=annotation_id,
        frame_time=0.0,
        ann_duration=1.0,
        type="rect",
        label=label,
        color="#22d3ee",
        geometry={"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
    )


def _window(project: ProjectState | None = None) -> MainWindow:
    window = MainWindow.__new__(MainWindow)
    window.project = project or ProjectState()
    window.dirty = False
    window._undo_stack = [window._snapshot()]
    window._redo_stack = []
    window._history_limit = 50
    window._restoring = False
    window.labels_panel = _StubPanel()
    window.video_view = _StubView()
    window.refresh = lambda: None
    window._update_title = lambda: None
    window._update_history_actions = lambda: None
    return window


def test_tool_panel_and_selection_changes_do_not_create_undo_entries() -> None:
    project = ProjectState()
    project.annotations.append(_annotation())
    window = _window(project)

    window._set_tool("rect")
    window._set_panel("labels")
    window._on_view_selection_changed("ann-1")
    window._on_panel_selection_changed(None)

    assert len(window._undo_stack) == 1
    assert window.dirty is True


def test_editing_annotation_creates_undo_entry() -> None:
    project = ProjectState()
    project.annotations.append(_annotation())
    window = _window(project)

    window._update_annotation_label("ann-1", "Updated")

    assert len(window._undo_stack) == 2
    assert window._undo_stack[-1]["annotations"][0]["label"] == "Updated"
    assert window.dirty is True


def test_net_zero_document_mutation_clears_redo_stack() -> None:
    project = ProjectState()
    project.annotations.append(_annotation())
    window = _window(project)
    window._redo_stack = [{"annotations": [{"label": "future"}]}]

    window._push_history()

    assert len(window._undo_stack) == 1
    assert window._redo_stack == []
