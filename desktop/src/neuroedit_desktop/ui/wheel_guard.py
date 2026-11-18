"""Keep the scroll wheel from changing values the user did not pick (NE-040).

Spin boxes, combo boxes and sliders react to the wheel whenever the pointer is
over them, so scrolling a panel past one silently edits it. The guard lets
them take the wheel only once they already have keyboard focus (clicked or
tabbed into); otherwise the event goes to the surrounding widget, which
scrolls as if the control were not there.
"""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QScrollBar,
)

_GUARDED = (QAbstractSpinBox, QComboBox, QAbstractSlider)


def _is_guarded(obj: QObject) -> bool:
    return isinstance(obj, _GUARDED) and not isinstance(obj, QScrollBar)


class WheelGuard(QObject):
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        kind = event.type()
        if kind == QEvent.Type.Polish and _is_guarded(obj):
            # WheelFocus would hand focus to the control under the pointer
            # before this filter runs, defeating the focus check below.
            if obj.focusPolicy() == Qt.FocusPolicy.WheelFocus:
                obj.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        elif kind == QEvent.Type.Wheel and _is_guarded(obj) and not obj.hasFocus():
            # Qt 6 does not propagate a re-sent (non-spontaneous) wheel event,
            # so offer it to each ancestor until one handles it.
            parent = obj.parentWidget()
            while parent is not None:
                event.accept()
                QCoreApplication.sendEvent(parent, event)
                if event.isAccepted() or parent.isWindow():
                    break
                parent = parent.parentWidget()
            return True
        return False


_guard: WheelGuard | None = None


def install_wheel_guard(app: QApplication) -> WheelGuard:
    global _guard
    if _guard is None:
        _guard = WheelGuard(app)
        app.installEventFilter(_guard)
    return _guard
