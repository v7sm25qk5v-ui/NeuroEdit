"""NE-028: timeline polish items that need the main window or the theme."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QStyle, QStyleOptionSlider, QWidget  # noqa: E402

from neuroedit_desktop.models import Annotation, ProjectState, VideoClip  # noqa: E402
from neuroedit_desktop.ui import editor_panels, styles  # noqa: E402
from neuroedit_desktop.ui.editor_panels import RichTimelineWidget, TimelineCanvas  # noqa: E402
from neuroedit_desktop.ui.labels_panel import LabelsPanel  # noqa: E402
from neuroedit_desktop.ui.tutorial import TutorialCard  # noqa: E402
from test_main_window_headless import _review_state, app, reviewed, window  # noqa: E402, F401


def test_pending_timeline_layout_update_is_cancelled_on_delete(app, monkeypatch):  # noqa: F811
    import sys

    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: errors.append(error))
    timeline = RichTimelineWidget(ProjectState())
    # A final scrollbar change can queue a resize just before the editor closes.
    timeline.toolbar_scroll.horizontalScrollBar().setRange(0, 100)
    timeline.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()

    assert errors == []


def test_timeline_delete_of_a_label_is_one_undoable_edit_that_resets_review(reviewed):  # noqa: F811
    reviewed.project.annotations.append(
        Annotation(id="note", frame_time=2.0, ann_duration=3.0, type="text", label="Note", color="#fff")
    )
    reviewed.project.selected_annotation_id = "note"
    reviewed._push_history()
    undo_depth = len(reviewed._undo_stack)
    canvas = reviewed.timeline.canvas
    canvas._set_selection(("annotation", "note"))

    canvas._delete_selected_item()

    assert reviewed.project.annotations == []
    assert reviewed.project.selected_annotation_id is None
    assert _review_state(reviewed) == (False, False, False, False, undo_depth + 1, 0)
    reviewed.undo()
    assert [a.id for a in reviewed.project.annotations] == ["note"]


def test_annotation_hit_test_does_not_rescan_per_annotation(monkeypatch):
    project = ProjectState()
    project.zoom = 100.0
    project.clips.append(VideoClip(
        id="c", path="/x.mp4", name="x", duration=300, start_time=0, trim_start=0, trim_end=300,
    ))
    project.annotations = [
        Annotation(id=f"a{i}", frame_time=i * 0.5, ann_duration=2.0, type="text", label="n", color="#fff")
        for i in range(200)
    ]
    canvas = TimelineCanvas(project)
    calls = []
    real = editor_panels.project_end_time
    monkeypatch.setattr(editor_panels, "project_end_time", lambda p: calls.append(1) or real(p))

    assert canvas._hit_block(canvas.LABEL_W + 5000.5, 5) is None

    assert len(calls) <= 5, "lane/end-time work must not repeat per annotation"


@pytest.fixture()
def dark_then_light(app):  # noqa: F811
    styles.apply_app_style(app, "light")
    yield
    styles.apply_app_style(app, "light")


def test_tutorial_card_uses_the_current_theme(app, dark_then_light):  # noqa: F811
    parent = QWidget()
    light = TutorialCard(parent).styleSheet()
    styles.apply_app_style(app, "dark")
    dark = TutorialCard(parent).styleSheet()

    assert styles.DARK_THEME.bg_tertiary in dark
    assert styles.LIGHT_THEME.bg_tertiary in light
    assert dark != light


def test_label_presets_follow_a_theme_switch(app, dark_then_light):  # noqa: F811
    panel = LabelsPanel(ProjectState())
    button = panel._builtin_buttons[0][0]
    assert styles.LIGHT_THEME.bg_card in button.styleSheet()

    styles.apply_app_style(app, "dark")
    panel.restyle_presets()

    assert styles.DARK_THEME.bg_card in button.styleSheet()
    assert styles.LIGHT_THEME.bg_card not in button.styleSheet()
    assert styles.DARK_THEME.text_muted in panel._presets_toggle.styleSheet()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_arrowless_timeline_scrollbar_can_drag_and_hides_when_content_fits(app, dark_then_light, theme):  # noqa: F811
    styles.apply_app_style(app, theme)
    project = ProjectState(
        zoom=100,
        clips=[VideoClip(id="clip", path="/tmp/clip.mp4", name="Clip", duration=40, trim_end=40)],
    )
    timeline = RichTimelineWidget(project)
    timeline.setMinimumHeight(340)
    timeline.resize(520, 340)
    timeline.show()
    app.processEvents()
    try:
        bar = timeline.scroll.horizontalScrollBar()
        assert bar.isVisible() and bar.maximum() > 0
        assert timeline.rect().contains(QRect(bar.mapTo(timeline, QPoint()), bar.size()))
        opts = QStyleOptionSlider()
        bar.initStyleOption(opts)
        style = bar.style()
        control = QStyle.ComplexControl.CC_ScrollBar
        assert style.subControlRect(control, opts, QStyle.SubControl.SC_ScrollBarAddLine, bar).isEmpty()
        assert style.subControlRect(control, opts, QStyle.SubControl.SC_ScrollBarSubLine, bar).isEmpty()
        thumb = style.subControlRect(control, opts, QStyle.SubControl.SC_ScrollBarSlider, bar)
        # The thin visible pill leaves a small margin for the pointer.
        assert thumb.height() >= 12
        QTest.mousePress(bar, Qt.MouseButton.LeftButton, pos=thumb.center())
        QTest.mouseMove(bar, thumb.center() + QPoint(46, 0))
        QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, pos=thumb.center() + QPoint(46, 0))
        assert bar.value() > 0

        project.zoom = 1
        timeline.refresh()
        app.processEvents()
        assert bar.maximum() == 0 and not bar.isVisible()
    finally:
        timeline.close()
