"""Coalesce a slider drag or text edit into one undo step.

A panel mutates the project live while the user drags or types, calling
`EditGesture.tick()` after each change. The main window answers `changed` with a
history-less dirty mark (live preview, autosave) and `committed` with exactly
one undo snapshot. Mirrors the canvas's `annotation_mutated` / `edit_committed`.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QTextEdit


class EditGesture(QObject):
    begun = Signal()      # first change of a gesture
    changed = Signal()    # every change: the model was just mutated
    committed = Signal()  # the gesture ended: push one undo snapshot

    def __init__(self, parent: QObject | None = None, idle_ms: int = 600) -> None:
        super().__init__(parent)
        self.pending = False
        self._source: QObject | None = None
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(idle_ms)
        self._idle.timeout.connect(self.commit)

    def begin(self, source: QObject | None = None) -> None:
        if self.pending and source is not None and source is not self._source:
            self.commit()
        if not self.pending:
            self.pending = True
            self._source = source
            self.begun.emit()

    def tick(self) -> None:
        self.begin()
        self.changed.emit()

    def touch_idle(self) -> None:
        """A change with no definite end (arrow key, wheel): commit once the
        user pauses, or earlier on any flush."""
        self._idle.start()

    def commit(self) -> None:
        self._idle.stop()
        if self.pending:
            self.pending = False
            self._source = None
            self.committed.emit()

    def reset(self) -> None:
        """Drop a pending gesture without a snapshot (the caller records the
        state itself, or the project it belonged to is gone)."""
        self._idle.stop()
        self.pending = False
        self._source = None


class CommitTextEdit(QTextEdit):
    """QTextEdit that reports focus loss, its only natural end of an edit."""

    editingFinished = Signal()  # noqa: N815 - mirrors QLineEdit

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        super().focusOutEvent(event)
        if event.reason() != Qt.FocusReason.PopupFocusReason:
            self.editingFinished.emit()


__all__ = ["CommitTextEdit", "EditGesture"]
