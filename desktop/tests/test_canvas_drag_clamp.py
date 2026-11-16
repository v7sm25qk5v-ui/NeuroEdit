"""NE-022: shape drags that leave the frame clamp to the edge instead of vanishing."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, QSizeF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from neuroedit_desktop.models import ProjectState
from neuroedit_desktop.ui.canvas import VideoGraphicsView

W, H = 1000.0, 500.0


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _view(tool, monkeypatch):
    project = ProjectState(current_time=1.0, active_tool=tool)
    view = VideoGraphicsView(project)
    view.video_item.setSize(QSizeF(W, H))
    pos = {"p": QPointF(0, 0)}
    monkeypatch.setattr(view, "mapToScene", lambda _p: pos["p"])
    added = []
    view.annotation_added.connect(added.append)
    return view, pos, added


def _ev(kind, buttons=Qt.MouseButton.LeftButton):
    return QMouseEvent(kind, QPointF(1, 1), QPointF(1, 1), Qt.MouseButton.LeftButton,
                       buttons, Qt.KeyboardModifier.NoModifier)


def _drag(view, pos, start, moves, end):
    pos["p"] = QPointF(*start)
    view.mousePressEvent(_ev(QEvent.Type.MouseButtonPress))
    for m in moves:
        pos["p"] = QPointF(*m)
        view.mouseMoveEvent(_ev(QEvent.Type.MouseMove))
    pos["p"] = QPointF(*end)
    view.mouseReleaseEvent(_ev(QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton))


@pytest.mark.parametrize("tool", ["rect", "ellipse", "arrow", "redact"])
def test_release_outside_frame_clamps_to_edge(app, monkeypatch, tool):
    view, pos, added = _view(tool, monkeypatch)
    _drag(view, pos, (800, 250), [(950, 250), (1040, 250)], (1060, 700))
    assert len(added) == 1
    g = added[0].geometry
    if tool == "arrow":
        assert (g["x2"], g["y2"]) == (1.0, 1.0)
    else:
        assert g["x"] + g["width"] == pytest.approx(1.0)
        assert g["y"] + g["height"] == pytest.approx(1.0)


def test_preview_follows_pointer_along_edge(app, monkeypatch):
    view, pos, added = _view("redact", monkeypatch)
    pos["p"] = QPointF(800, 100)
    view.mousePressEvent(_ev(QEvent.Type.MouseButtonPress))
    pos["p"] = QPointF(1200, 300)
    view.mouseMoveEvent(_ev(QEvent.Type.MouseMove))
    assert view._drag_current == (1.0, 0.6)
    pos["p"] = QPointF(1300, -50)
    view.mouseMoveEvent(_ev(QEvent.Type.MouseMove))
    assert view._drag_current == (1.0, 0.0)


def test_press_outside_frame_does_not_start_shape(app, monkeypatch):
    view, pos, added = _view("redact", monkeypatch)
    _drag(view, pos, (-20, 100), [(300, 300)], (400, 400))
    assert view._drag_start is None
    assert added == []


def test_accidental_click_still_rejected(app, monkeypatch):
    view, pos, added = _view("redact", monkeypatch)
    _drag(view, pos, (999, 250), [], (1005, 252))
    assert added == []
