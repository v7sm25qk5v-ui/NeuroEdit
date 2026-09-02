"""Interactive coach-mark tutorial.

The overlay covers the entire main window with a translucent dim, punches a
spotlight cutout around the current step's target widget, and shows a small
card with title/body and Next/Skip buttons. Clicks outside the spotlight are
swallowed; clicks inside are passed through so the user can actually try the
highlighted control.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from neuroedit_desktop.ui.styles import (
    ACCENT_CYAN, BG_TERTIARY, BORDER_BRIGHT, PRIMARY, TEXT_PRIMARY, TEXT_SECONDARY,
)


@dataclass
class TutorialStep:
    title: str
    body: str
    target_resolver: Callable[[], QWidget | None] | None = None
    on_enter: Callable[[], None] | None = None
    # Optional: override the side the card is placed on relative to target.
    # Values: "auto" | "below" | "above" | "right" | "left"
    placement: str = "auto"
    # When True, draws animated pulsing rings around the target to indicate
    # where the user should click.
    practice_mode: bool = False


class TutorialCard(QFrame):
    next_clicked = Signal()
    skip_clicked = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("tutorialCard")
        self.setStyleSheet(f"""
            QFrame#tutorialCard {{
                background: {BG_TERTIARY};
                border: 1px solid {ACCENT_CYAN};
                border-radius: 12px;
            }}
            QLabel#tutorialTitle {{
                color: {TEXT_PRIMARY};
                font-size: 14px;
                font-weight: 700;
            }}
            QLabel#tutorialBody {{
                color: {TEXT_SECONDARY};
                font-size: 12px;
            }}
            QLabel#tutorialProgress {{
                color: {TEXT_SECONDARY};
                font-size: 11px;
            }}
            QPushButton#tutorialNext {{
                background: {PRIMARY};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: 600;
            }}
            QPushButton#tutorialNext:hover {{ background: {ACCENT_CYAN}; }}
            QPushButton#tutorialSkip {{
                background: transparent;
                color: {TEXT_SECONDARY};
                border: 1px solid {BORDER_BRIGHT};
                border-radius: 6px;
                padding: 6px 12px;
            }}
            QPushButton#tutorialSkip:hover {{ color: {TEXT_PRIMARY}; }}
        """)
        self.setMinimumWidth(280)
        self.setMaximumWidth(360)

        self.title_label = QLabel()
        self.title_label.setObjectName("tutorialTitle")
        self.title_label.setWordWrap(True)
        self.body_label = QLabel()
        self.body_label.setObjectName("tutorialBody")
        self.body_label.setWordWrap(True)
        self.progress_label = QLabel()
        self.progress_label.setObjectName("tutorialProgress")
        self.next_btn = QPushButton("Next ›")
        self.next_btn.setObjectName("tutorialNext")
        self.next_btn.clicked.connect(self.next_clicked)
        self.skip_btn = QPushButton("Skip tour")
        self.skip_btn.setObjectName("tutorialSkip")
        self.skip_btn.clicked.connect(self.skip_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        layout.addWidget(self.title_label)
        layout.addWidget(self.body_label)
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        bottom.addWidget(self.progress_label)
        bottom.addStretch(1)
        bottom.addWidget(self.skip_btn)
        bottom.addWidget(self.next_btn)
        layout.addLayout(bottom)

    def set_step(self, title: str, body: str, index: int, total: int, last: bool) -> None:
        self.title_label.setText(title)
        self.body_label.setText(body)
        self.progress_label.setText(f"{index + 1} / {total}")
        self.next_btn.setText("Got it" if last else "Next ›")
        self.adjustSize()


class TutorialOverlay(QWidget):
    finished = Signal()

    def __init__(self, parent: QWidget, steps: list[TutorialStep]) -> None:
        super().__init__(parent)
        self.steps = steps
        self.index = 0
        self._target_rect = QRect()
        self._pulse_t = 0.0
        self._drag_target: QWidget | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setGeometry(parent.rect())
        parent.installEventFilter(self)

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(40)  # ~25 fps
        self._anim_timer.timeout.connect(self._tick_animation)

        self.card = TutorialCard(self)
        self.card.next_clicked.connect(self.advance)
        self.card.skip_clicked.connect(self.close)

        self._apply_step()
        self.show()
        self.raise_()

    def _tick_animation(self) -> None:
        self._pulse_t += 0.10
        if self._pulse_t > 2 * math.pi:
            self._pulse_t -= 2 * math.pi
        self.update()

    def _step_practice_mode(self) -> bool:
        if 0 <= self.index < len(self.steps):
            return self.steps[self.index].practice_mode
        return False

    def eventFilter(self, watched, event):  # noqa: N802
        # Keep the overlay sized to the parent.
        if watched is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
            self._refresh_target_rect()
            self._position_card()
            self._update_input_mask()
        return False

    def _resolve_target(self) -> QWidget | None:
        step = self.steps[self.index]
        if step.target_resolver is None:
            return None
        try:
            return step.target_resolver()
        except Exception:
            return None

    def _refresh_target_rect(self) -> None:
        widget = self._resolve_target()
        if widget is None or not widget.isVisible():
            self._target_rect = QRect()
            return
        size = widget.size()
        top_left_global = widget.mapToGlobal(QPoint(0, 0))
        top_left_local = self.mapFromGlobal(top_left_global)
        self._target_rect = QRect(top_left_local, size)

    def _input_cutout_rect(self) -> QRect:
        if self._target_rect.isEmpty():
            return QRect()
        return self._target_rect.adjusted(-8, -8, 8, 8).intersected(self.rect())

    def _update_input_mask(self) -> None:
        region = QRegion(self.rect())
        cutout = self._input_cutout_rect()
        if not cutout.isEmpty():
            region = region.subtracted(QRegion(cutout))
        if hasattr(self, "card") and self.card.isVisible():
            region = region.united(QRegion(self.card.geometry().adjusted(-4, -4, 4, 4)))
        self.setMask(region)

    def _apply_step(self) -> None:
        if self.index >= len(self.steps):
            self.close()
            return
        step = self.steps[self.index]
        if step.on_enter is not None:
            try:
                step.on_enter()
            except Exception:
                pass
        self._refresh_target_rect()
        self.card.set_step(
            step.title, step.body, self.index, len(self.steps),
            last=self.index == len(self.steps) - 1,
        )
        self._position_card()
        self._update_input_mask()
        if step.practice_mode and not self._target_rect.isEmpty():
            self._anim_timer.start()
        else:
            self._anim_timer.stop()
        self.update()

    def _position_card(self) -> None:
        self.card.adjustSize()
        margin = 16
        if self._target_rect.isEmpty():
            # Center it in the overlay.
            r = self.rect()
            x = r.center().x() - self.card.width() // 2
            y = r.center().y() - self.card.height() // 2
            self.card.move(max(margin, x), max(margin, y))
            return
        target = self._target_rect
        candidates = []
        # Below
        candidates.append(("below", target.center().x() - self.card.width() // 2,
                           target.bottom() + margin))
        # Above
        candidates.append(("above", target.center().x() - self.card.width() // 2,
                           target.top() - self.card.height() - margin))
        # Right
        candidates.append(("right", target.right() + margin,
                           target.center().y() - self.card.height() // 2))
        # Left
        candidates.append(("left", target.left() - self.card.width() - margin,
                           target.center().y() - self.card.height() // 2))
        placement = self.steps[self.index].placement if 0 <= self.index < len(self.steps) else "auto"
        if placement != "auto":
            candidates.sort(key=lambda candidate: 0 if candidate[0] == placement else 1)
        chosen = None
        view = self.rect()
        for _name, x, y in candidates:
            if (x >= margin and y >= margin
                    and x + self.card.width() <= view.right() - margin
                    and y + self.card.height() <= view.bottom() - margin):
                chosen = (x, y)
                break
        if chosen is None:
            chosen = (max(margin, min(candidates[0][1], view.width() - self.card.width() - margin)),
                      max(margin, target.bottom() + margin))
        self.card.move(*chosen)

    def advance(self) -> None:
        self.index += 1
        if self.index >= len(self.steps):
            self.close()
            return
        self._apply_step()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        full = QPainterPath()
        full.addRect(QRectF(self.rect()))
        if not self._target_rect.isEmpty():
            cutout = QPainterPath()
            cutout.addRoundedRect(QRectF(self._target_rect.adjusted(-6, -6, 6, 6)), 10, 10)
            full = full.subtracted(cutout)
        painter.fillPath(full, QColor(0, 0, 0, 170))
        if not self._target_rect.isEmpty():
            pen = QPen(QColor(ACCENT_CYAN), 3)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(self._target_rect.adjusted(-6, -6, 6, 6), 10, 10)

        if self._step_practice_mode() and not self._target_rect.isEmpty():
            self._paint_practice_marker(painter)

    def _paint_practice_marker(self, painter: QPainter) -> None:
        """Draw animated pulsing rings + 'Click here' label around the target."""
        t = self._pulse_t
        center = QPointF(self._target_rect.center())
        half_diag = math.hypot(self._target_rect.width(), self._target_rect.height()) / 2.0
        base_r = half_diag + 10

        # Three concentric amber rings, each offset in phase
        for i, (extra_r, base_alpha) in enumerate([(0, 200), (16, 130), (32, 65)]):
            phase = t + i * 0.9
            r = base_r + extra_r + 6 * math.sin(phase)
            alpha = int(base_alpha * (0.55 + 0.45 * math.sin(phase)))
            painter.setPen(QPen(QColor(251, 191, 36, alpha), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, r, r)

        # "Click here" label — placed above target when there's room, else below
        bounce = int(4 * abs(math.sin(t * 0.8)))
        label_text = "▼  Click here"
        if self._target_rect.top() > 50:
            label_y = self._target_rect.top() - 30 - bounce
        else:
            label_y = self._target_rect.bottom() + 8 + bounce
            label_text = "▲  Click here"
        label_rect = QRect(
            center.x() - 70,
            label_y,
            140, 22,
        )
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(251, 191, 36))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, label_text)

    # ── Event forwarding ─────────────────────────────────────────────────────

    def _real_widget_at(self, overlay_pos: QPoint) -> QWidget | None:
        """Return the widget under overlay_pos, bypassing this overlay.

        Briefly hides the overlay so QApplication.widgetAt() sees through it.
        The hide/show is synchronous (no event-loop iteration between them),
        so no visible flicker occurs.
        """
        global_pt = self.mapToGlobal(overlay_pos)
        self.setVisible(False)
        w = QApplication.widgetAt(global_pt)
        self.setVisible(True)
        # Ignore the overlay itself and the tutorial card.
        if w is None or w is self:
            return None
        ancestor = w
        while ancestor is not None:
            if ancestor is self.card:
                return None
            ancestor = ancestor.parent()
        return w

    def _forward_mouse(self, target: QWidget, event: QMouseEvent) -> None:
        """Re-send a mouse event to *target* with corrected local coordinates."""
        global_pt = self.mapToGlobal(event.position().toPoint())
        local_pt = target.mapFromGlobal(global_pt)
        forwarded = QMouseEvent(
            event.type(),
            QPointF(local_pt),
            QPointF(global_pt),
            event.button(),
            event.buttons(),
            event.modifiers(),
        )
        QApplication.sendEvent(target, forwarded)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._target_rect.contains(event.pos()):
            w = self._real_widget_at(event.pos())
            if w is not None:
                self._drag_target = w
                self._forward_mouse(w, event)
                w.setFocus()
            return
        self._drag_target = None
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_target is not None:
            self._forward_mouse(self._drag_target, event)
            return
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_target is not None:
            self._forward_mouse(self._drag_target, event)
            self._drag_target = None
            return
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self._target_rect.contains(event.pos()):
            w = self._real_widget_at(event.pos())
            if w is not None:
                self._forward_mouse(w, event)
                w.setFocus()
        else:
            event.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        focused = QApplication.focusWidget()
        if focused is not None and focused is not self:
            QApplication.sendEvent(focused, event)
        else:
            event.ignore()

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        focused = QApplication.focusWidget()
        if focused is not None and focused is not self:
            QApplication.sendEvent(focused, event)
        else:
            event.ignore()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._anim_timer.stop()
        if self.parent() is not None:
            self.parent().removeEventFilter(self)
        self.finished.emit()
        super().closeEvent(event)


def build_default_steps(window) -> list[TutorialStep]:
    """Construct a hands-on sample-clip walkthrough for NeuroEdit."""
    def _tool(name):
        return getattr(window, "tool_buttons", {}).get(name)

    def _panel_btn(name):
        return getattr(window, "panel_buttons", {}).get(name)

    def _refresh_window() -> None:
        if hasattr(window, "refresh"):
            window.refresh()

    def _set_tool(name: str):
        def _action() -> None:
            project = getattr(window, "project", None)
            if project is not None:
                project.active_tool = name
                _refresh_window()
        return _action

    def _set_panel(name: str):
        def _action() -> None:
            project = getattr(window, "project", None)
            if project is not None:
                project.active_panel = name
                _refresh_window()
        return _action

    def _prepare_label() -> None:
        label_input = getattr(window, "label_input", None)
        if label_input is not None and not label_input.currentText().strip():
            label_input.setEditText("practice target")

    def _prepare_sam_point() -> None:
        project = getattr(window, "project", None)
        if project is not None:
            project.active_panel = "sam"
            project.active_tool = "sam"
            project.sam_points_enabled = True
            project.sam_mode = "positive"
            _refresh_window()
        sam_panel = getattr(window, "sam_panel", None)
        if sam_panel is not None:
            sam_panel.refresh()

    def _pause_at_start() -> None:
        player = getattr(window, "player", None)
        if player is not None:
            player.pause()
        if hasattr(window, "_seek_global"):
            window._seek_global(0.0)

    return [
        TutorialStep(
            title="Start With the Sample Clip",
            body=(
                "This walkthrough uses the loaded sample clip and follows a normal edit "
                "from scratch: scrub, label, draw, review the timeline, make a still, "
                "add a slide, and export. Complete the action in each highlighted area, "
                "then press Next."
            ),
            target_resolver=lambda: getattr(window, "video_view", None),
            on_enter=_pause_at_start,
        ),
        TutorialStep(
            title="Play and Pause the Clip",
            body=(
                "Click Play to start the sample clip, then click it again to pause. "
                "This is the basic review loop before placing annotations."
            ),
            target_resolver=lambda: getattr(window, "play_button", None),
            practice_mode=True,
        ),
        TutorialStep(
            title="Scrub to a Useful Frame",
            body=(
                "Use the timeline to click near the beginning of the clip or drag the "
                "red playhead. Pick a frame you want to annotate, then press Next."
            ),
            target_resolver=lambda: getattr(window, "timeline", None),
            placement="above",
            practice_mode=True,
        ),
        TutorialStep(
            title="Name the Annotation",
            body=(
                "Click the label field and type a short name, such as 'tumor' or "
                "'practice target'. New shapes will use this label."
            ),
            target_resolver=lambda: getattr(window, "label_input", None),
            practice_mode=True,
        ),
        TutorialStep(
            title="Choose the Rectangle Tool",
            body=(
                "Click the Rectangle tool. The next step will draw directly on the video."
            ),
            target_resolver=lambda: _tool("rect"),
            on_enter=_prepare_label,
            practice_mode=True,
        ),
        TutorialStep(
            title="Draw the First Label",
            body=(
                "Click and drag on the video to draw a rectangle around a region. "
                "You should see the shape while dragging and the label after release."
            ),
            target_resolver=lambda: getattr(window, "video_view", None),
            on_enter=_set_tool("rect"),
            practice_mode=True,
        ),
        TutorialStep(
            title="Use an Arrow Callout",
            body=(
                "Now draw an arrow. The tail starts where you click; drag toward the "
                "object so the arrowhead ends at what you want to highlight."
            ),
            target_resolver=lambda: getattr(window, "video_view", None),
            on_enter=_set_tool("arrow"),
            practice_mode=True,
        ),
        TutorialStep(
            title="Add a Freehand Highlight",
            body=(
                "The Brush follows your pointer as a continuous freeform stroke. "
                "Click and drag over the video to highlight a path; color, width, "
                "and opacity remain editable in the Labels panel."
            ),
            target_resolver=lambda: getattr(window, "video_view", None),
            on_enter=_set_tool("brush"),
            practice_mode=True,
        ),
        TutorialStep(
            title="Review and Edit Labels",
            body=(
                "The Labels panel lists your annotations. Select a label to change its "
                "text, color, opacity, stroke width, or duration."
            ),
            target_resolver=lambda: getattr(window, "labels_panel", None),
            on_enter=_set_panel("labels"),
            practice_mode=True,
        ),
        TutorialStep(
            title="Try SAM Points",
            body=(
                "Open SAM, keep point placement enabled, and click one point on the "
                "video. This teaches the prompt workflow without requiring you to run "
                "the full model during the tutorial."
            ),
            target_resolver=lambda: getattr(window, "video_view", None),
            on_enter=_prepare_sam_point,
            practice_mode=True,
        ),
        TutorialStep(
            title="Take a Still",
            body=(
                "Click Take Still. The app captures the current preview, including "
                "visible labels, inserts it as a slide, and creates space in the timeline."
            ),
            target_resolver=lambda: getattr(window, "take_still_btn", None),
            practice_mode=True,
        ),
        TutorialStep(
            title="Inspect the Slide",
            body=(
                "The Slides panel shows stills and title slides. Select the still or "
                "create a new slide, then adjust its duration and text."
            ),
            target_resolver=lambda: getattr(window, "slides_panel", None),
            on_enter=_set_panel("slides"),
            practice_mode=True,
        ),
        TutorialStep(
            title="Read the Timeline",
            body=(
                "The timeline shows video, audio, slides, and markers in separate rows. "
                "Use the vertical splitter above the timeline to give this area more room."
            ),
            target_resolver=lambda: getattr(window, "timeline", None),
            placement="above",
            practice_mode=True,
        ),
        TutorialStep(
            title="Add a Marker",
            body=(
                "Click Mark to add a timeline marker at the playhead. Markers are useful "
                "for cuts, narration points, and storyboard beats."
            ),
            target_resolver=lambda: getattr(getattr(window, "timeline", None), "marker_btn", None),
            placement="above",
            practice_mode=True,
        ),
        TutorialStep(
            title="Export When Ready",
            body=(
                "Use Export when the sample edit looks right. The final MP4 includes "
                "the clip, labels, masks, slides, stills, markers-driven edits, and audio."
            ),
            target_resolver=lambda: getattr(window, "export_btn", None),
            practice_mode=True,
        ),
    ]


def build_practice_steps(window) -> list[TutorialStep]:
    return build_default_steps(window)
