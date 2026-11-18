"""Lay out and paint annotation labels in the source picture's pixel space."""
from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPen

from neuroedit_desktop.models import Annotation

_CENTER = int(Qt.AlignmentFlag.AlignCenter)
_WORD_WRAP = int(Qt.TextFlag.TextWordWrap)
_WRAP_ANYWHERE = int(Qt.TextFlag.TextWrapAnywhere)


@dataclass(frozen=True)
class LabelLayout:
    text: str
    font: QFont
    flags: int
    box: QRectF
    text_box: QRectF
    frame_shift: QPointF


def annotation_label_layout(ann: Annotation, width: float, height: float) -> LabelLayout | None:
    standalone = ann.type == "text"
    if standalone:
        text = ann.label or "Text"
    else:
        text = ann.label.strip()
        if ann.type not in {"rect", "ellipse", "arrow"} or not ann.show_label or not text or text.lower() == ann.type:
            return None

    # Leave one pixel for the border and reduce padding on very small sources.
    pad_x = min(10 if standalone else 8, width / 8)
    pad_y = min(6 if standalone else 5, height / 8)
    max_w = width - 2 * pad_x - 2
    max_h = height - 2 * pad_y - 2
    if max_w <= 0 or max_h <= 0:
        return None

    # Resolve the font once in source pixels. Measuring the same font we draw
    # avoids variation from the painter's inherited family or device DPI.
    font = QFont()
    font.setBold(True)
    font.setPointSize(max(8, int(ann.font_size or 15)))
    # Some font backends retain a point-sized resolved font and report a
    # pixel size of -1. Convert explicitly so shrinking works there too.
    desired_px = max(1, round(font.pointSizeF() * QFontMetricsF(font).fontDpi() / 72))
    limit = QRectF(0, 0, max_w, max_h)

    def measure(size: int) -> tuple[float, float, int]:
        font.setPixelSize(size)
        metrics = QFontMetricsF(font)
        bounds = metrics.boundingRect(limit, _CENTER, text)
        if math.ceil(bounds.width()) <= max_w:
            return math.ceil(bounds.width()), math.ceil(bounds.height()), _CENTER
        flags = _CENTER | _WORD_WRAP
        bounds = metrics.boundingRect(limit, flags, text)
        if bounds.width() > max_w:
            flags = _CENTER | _WRAP_ANYWHERE
            bounds = metrics.boundingRect(limit, flags, text)
        # Keep the measured wrap width. Narrowing it afterwards could add
        # another line when drawn.
        return max(max_w, bounds.width()), math.ceil(bounds.height()), flags

    text_w, text_h, flags = measure(desired_px)
    if text_w > max_w or text_h > max_h:
        # Most labels fit above. For oversized text, find the largest font that
        # fits both dimensions after wrapping instead of dropping characters.
        low, high = 1, desired_px - 1
        size = 0
        while low <= high:
            middle = (low + high) // 2
            measured = measure(middle)
            if measured[0] <= max_w and measured[1] <= max_h:
                size = middle
                low = middle + 1
            else:
                high = middle - 1
        if size == 0:
            return None
        text_w, text_h, flags = measure(size)

    box = QRectF(0, 0, text_w + 2 * pad_x, text_h + 2 * pad_y)
    geometry = ann.geometry
    if standalone:
        x, y = float(geometry.get("x", 0.5)) * width, float(geometry.get("y", 0.5)) * height
    elif ann.type == "arrow":
        x = float(geometry.get("x1", 0.0)) * width + 10
        y = float(geometry.get("y1", 0.0)) * height - box.height() - 8
        if y < 0:
            y = float(geometry.get("y1", 0.0)) * height + 8
    else:
        x = float(geometry.get("x", 0.0)) * width
        top = float(geometry.get("y", 0.0)) * height
        y = top - box.height() - 8
        if y < 0:
            y = top + float(geometry.get("height", 0.0)) * height + 8
    if not standalone:
        x += float(geometry.get("label_dx", 0.0)) * width
        y += float(geometry.get("label_dy", 0.0)) * height

    box.moveTo(max(1.0, min(x, width - box.width() - 1)),
               max(1.0, min(y, height - box.height() - 1)))
    return LabelLayout(text, font, flags, box, box.adjusted(pad_x, pad_y, -pad_x, -pad_y),
                       box.topLeft() - QPointF(x, y))


def paint_annotation_label(painter: QPainter, ann: Annotation, width: float, height: float,
                           color: QColor) -> None:
    layout = annotation_label_layout(ann, width, height)
    if layout is None:
        return
    standalone = ann.type == "text"
    painter.save()
    painter.setFont(layout.font)
    bg = QColor(0, 0, 0, 160 if standalone else 170)
    painter.setPen(QPen(color, 1))
    painter.setBrush(QBrush(bg))
    painter.drawRoundedRect(layout.box, 6, 6)
    painter.setPen(color if standalone else QColor("#ffffff"))
    painter.drawText(layout.text_box, layout.flags | int(Qt.TextFlag.TextDontClip), layout.text)
    painter.restore()
