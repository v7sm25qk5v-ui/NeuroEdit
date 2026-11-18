"""NE-040: the wheel only changes a value control that already has focus."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from neuroedit_desktop.ui.wheel_guard import install_wheel_guard


@pytest.fixture()
def panel():
    app = QApplication.instance() or QApplication([])
    install_wheel_guard(app)
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.addSpacing(600)
    spin = QDoubleSpinBox()
    spin.setRange(0, 100)
    spin.setValue(50)
    combo = QComboBox()
    combo.addItems(["Black", "White", "Gray"])
    combo.setCurrentIndex(1)
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(0, 100)
    slider.setValue(50)
    for widget in (spin, combo, slider):
        layout.addWidget(widget)
    layout.addSpacing(600)
    scroll = QScrollArea()
    scroll.setWidget(content)
    scroll.setWidgetResizable(True)
    scroll.resize(300, 300)
    scroll.show()
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum() // 2)
    QApplication.processEvents()
    # Showing the window focuses its first focusable child (the spin box).
    for widget in (spin, combo, slider):
        widget.clearFocus()
    QApplication.processEvents()
    yield scroll, spin, combo, slider
    scroll.close()


def _wheel(widget: QWidget, dy: int = -120) -> None:
    pos = QPointF(widget.width() / 2, widget.height() / 2)
    event = QWheelEvent(pos, widget.mapToGlobal(pos), QPoint(), QPoint(0, dy),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)
    QApplication.processEvents()


def test_unfocused_controls_ignore_wheel_and_panel_scrolls(panel):
    scroll, spin, combo, slider = panel
    bar = scroll.verticalScrollBar()
    for widget in (spin, combo, slider):
        before = bar.value()
        _wheel(widget)
        assert bar.value() > before, f"{type(widget).__name__} should pass the wheel on"
    assert spin.value() == 50
    assert combo.currentIndex() == 1
    assert slider.value() == 50


def test_focused_control_still_takes_wheel(panel):
    scroll, spin, _combo, _slider = panel
    scroll.activateWindow()
    spin.setFocus(Qt.FocusReason.MouseFocusReason)
    QApplication.processEvents()
    if not spin.hasFocus():
        pytest.skip("platform did not grant focus to the offscreen window")
    _wheel(spin, dy=120)
    assert spin.value() != 50


def test_guarded_controls_do_not_take_focus_from_the_wheel(panel):
    _scroll, spin, combo, _slider = panel
    assert spin.focusPolicy() != Qt.FocusPolicy.WheelFocus
    assert combo.focusPolicy() != Qt.FocusPolicy.WheelFocus
