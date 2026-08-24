from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import QFrame, QGraphicsObject, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QWidget

from neuroedit_desktop import diagnostics
from neuroedit_desktop.captions import CaptionCue, build_caption_cues, cue_at_time, paint_caption
from neuroedit_desktop.models import Annotation, ProjectState, new_id


def _distance_to_segment(
    px: float, py: float, x1: float, y1: float, x2: float, y2: float,
) -> float:
    dx, dy = x2 - x1, y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-6:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_sq))
    cx, cy = x1 + t * dx, y1 + t * dy
    return math.hypot(px - cx, py - cy)




class AnnotationGraphicsItem(QGraphicsObject):
    """Paints annotations and SAM prompt points in the same QGraphicsScene as
    the QGraphicsVideoItem. This avoids the macOS bug where a widget overlay
    on top of QVideoWidget is hidden by the native Metal surface."""

    # Tracked-mask playback loads one full-frame RGBA pixmap per propagated
    # frame (~8 MB each at 1080p); an unbounded cache pins gigabytes on long
    # propagations. 48 frames ≈ 24 s of lookback at the 2 Hz sample rate.
    _MASK_CACHE_LIMIT = 48

    def __init__(self, project: ProjectState, video_item: QGraphicsVideoItem) -> None:
        super().__init__()
        self.project = project
        self.video_item = video_item
        self._size = QSizeF(1920, 1080)
        self._mask_cache: dict[str, QPixmap] = {}
        self._slide_image_cache: dict[str, QPixmap] = {}
        self._preview_annotation: Annotation | None = None
        self._selected_slide_region: tuple[str, str] | None = None
        self._caption_cues: list[CaptionCue] = []
        self._caption_fingerprint: tuple | None = None
        self.setZValue(10)

    def set_size(self, size: QSizeF) -> None:
        if size.width() <= 0 or size.height() <= 0:
            return
        self.prepareGeometryChange()
        self._size = size
        self.update()

    def set_project(self, project: ProjectState) -> None:
        self.project = project
        if self._selected_slide_region is not None:
            slide_id, _kind = self._selected_slide_region
            if not any(slide.id == slide_id for slide in project.slides):
                self._selected_slide_region = None
        self.update()

    def invalidate_mask_cache(self, path: str | None = None) -> None:
        if path is None:
            self._mask_cache.clear()
        else:
            self._mask_cache.pop(path, None)
        self.update()

    def set_preview(self, annotation: Annotation | None) -> None:
        self._preview_annotation = annotation
        self.update()

    def set_selected_slide_region(self, slide_id: str | None, kind: str | None) -> None:
        self._selected_slide_region = (slide_id, kind) if slide_id and kind else None
        self.update()

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(0, 0, self._size.width(), self._size.height())

    def paint(self, painter, _option, _widget=None) -> None:
        paint_start = time.perf_counter()
        self._paint_impl(painter)
        diagnostics.record_paint(
            "canvas_paint", (time.perf_counter() - paint_start) * 1000.0
        )

    def _paint_impl(self, painter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self._size.width(), self._size.height()
        if w <= 0 or h <= 0:
            return

        active_slide = self._active_slide()
        if active_slide is not None:
            self._paint_slide(painter, active_slide, w, h)
            if not active_slide.overlay:
                # A full-frame slide covers the video, but captions (narration
                # continues across slides) and redactions still paint on top.
                self._paint_captions(painter, w, h)
                self._paint_redactions(painter, w, h)
                return

        for ann in self.project.annotations:
            if not ann.is_visible_at(self.project.current_time):
                continue

            mask_path = ann.mask_path_at(self.project.current_time)
            if ann.type in ("mask", "tracked-mask") and mask_path:
                pix = self._mask_cache.pop(mask_path, None)
                if pix is None:
                    pix = QPixmap(mask_path)
                if not pix.isNull():
                    # Re-insert on use → dict order doubles as LRU order.
                    self._mask_cache[mask_path] = pix
                    while len(self._mask_cache) > self._MASK_CACHE_LIMIT:
                        self._mask_cache.pop(next(iter(self._mask_cache)))
                if pix.isNull():
                    continue
                painter.setOpacity(max(0.05, min(1.0, ann.opacity)))
                painter.drawPixmap(QRectF(0, 0, w, h), pix, QRectF(pix.rect()))
                painter.setOpacity(1.0)
                continue

            self._paint_shape(painter, ann, w, h, preview=False)

        if self._preview_annotation is not None:
            self._paint_shape(painter, self._preview_annotation, w, h, preview=True)

        for point in self.project.sam_points:
            color = QColor("#10b981" if point.type == "positive" else "#ef4444")
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.setBrush(QBrush(color))
            painter.drawEllipse(
                QPointF(point.x * w, point.y * h), 9.0, 9.0,
            )

        self._paint_fade_overlay(painter, w, h)
        self._paint_captions(painter, w, h)
        self._paint_redactions(painter, w, h)

    def _paint_captions(self, painter: QPainter, w: float, h: float) -> None:
        if not self.project.captions_enabled or not self.project.transcript_segments:
            return
        fingerprint = tuple(
            (s.id, s.start_time, s.end_time, s.speaker, s.text)
            for s in self.project.transcript_segments
        )
        if fingerprint != self._caption_fingerprint:
            self._caption_cues = build_caption_cues(self.project.transcript_segments)
            self._caption_fingerprint = fingerprint
        cue = cue_at_time(self._caption_cues, self.project.current_time)
        if cue is None:
            return
        paint_caption(
            painter,
            cue,
            w,
            h,
            size=self.project.caption_size,
            position=self.project.caption_position,
            background=self.project.caption_background,
        )

    def _paint_redactions(self, painter: QPainter, w: float, h: float) -> None:
        """Burn opaque black over every visible redaction, last and on top, so no
        PHI (and no other annotation) can show through. Mirrors the exporter."""
        painter.setOpacity(1.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#000000")))
        selected_redaction = None
        for ann in self.project.annotations:
            if ann.type != "redact" or not ann.is_visible_at(self.project.current_time):
                continue
            painter.drawRect(self._rect_from_geometry(ann, w, h))
            if self.project.selected_annotation_id == ann.id:
                selected_redaction = ann
        # Draw selection handles for the selected redaction on top of the fill so
        # it stays adjustable.
        if selected_redaction is not None:
            self._paint_selection(painter, selected_redaction, w, h)

    def _paint_fade_overlay(self, painter: QPainter, w: float, h: float) -> None:
        # Find the clip the playhead is currently inside. Apply fade-in at its
        # start, fade-out near its end. Both fade to/from `fade_color`.
        t = self.project.current_time
        for clip in self.project.clips:
            start = clip.start_time
            end = clip.start_time + clip.display_duration
            if not (start <= t <= end):
                continue
            alpha = 0.0
            if clip.fade_in > 0 and t < start + clip.fade_in:
                alpha = max(alpha, 1.0 - (t - start) / clip.fade_in)
            if clip.fade_out > 0 and t > end - clip.fade_out:
                alpha = max(alpha, 1.0 - (end - t) / clip.fade_out)
            if alpha <= 0.0:
                return
            color = QColor(clip.fade_color or "#000000")
            color.setAlphaF(max(0.0, min(1.0, alpha)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawRect(QRectF(0, 0, w, h))
            return

    def _paint_shape(
        self,
        painter: QPainter,
        ann: Annotation,
        w: float,
        h: float,
        *,
        preview: bool,
    ) -> None:
        if ann.type == "redact":
            # Redaction boxes are burned opaque in the final pass of paint() so
            # nothing (other annotations, fades) can render on top. While the user
            # is dragging a new one, show a translucent guide instead.
            if preview:
                guide = QColor("#000000")
                guide.setAlphaF(0.55)
                painter.setPen(QPen(QColor("#ffffff"), 1, Qt.PenStyle.DashLine))
                painter.setBrush(QBrush(guide))
                painter.drawRect(self._rect_from_geometry(ann, w, h))
            return

        color = QColor(ann.color)
        color.setAlphaF(max(0.05, min(1.0, ann.opacity)))
        pen_width = max(1, int(float(ann.geometry.get("width_px", self.project.draw_width))))
        pen = QPen(color, pen_width)
        if preview:
            pen.setStyle(Qt.PenStyle.DashLine)
            color.setAlphaF(max(0.15, min(0.35, ann.opacity)))
            painter.setBrush(QBrush(color))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen)

        if ann.type == "rect":
            painter.drawRect(self._rect_from_geometry(ann, w, h))
        elif ann.type == "ellipse":
            painter.drawEllipse(self._rect_from_geometry(ann, w, h))
        elif ann.type == "arrow":
            self._paint_arrow(painter, ann, w, h, color)
        elif ann.type == "text":
            self._paint_text(painter, ann, w, h, color)

        if not preview and ann.type in {"rect", "ellipse", "arrow"}:
            self._paint_attached_label(painter, ann, w, h, color)

        if not preview and self.project.selected_annotation_id == ann.id:
            self._paint_selection(painter, ann, w, h)

    def _paint_text(
        self,
        painter: QPainter,
        ann: Annotation,
        w: float,
        h: float,
        color: QColor,
    ) -> None:
        label = ann.label or "Text"
        x = float(ann.geometry.get("x", 0.5)) * w
        y = float(ann.geometry.get("y", 0.5)) * h
        font = QFont(painter.font())
        font.setPointSize(max(8, int(ann.font_size or 15)))
        font.setBold(True)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        text_rect = metrics.boundingRect(label).adjusted(-10, -6, 10, 6)
        text_rect.moveTopLeft(QPointF(x, y))
        bg = QColor("#000000")
        bg.setAlpha(160)
        painter.setPen(QPen(color, 1))
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(text_rect, 6, 6)
        painter.setPen(color)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)

    def _paint_selection(self, painter: QPainter, ann: Annotation, w: float, h: float) -> None:
        bounds = self.selection_bounds(ann, w, h)
        if bounds is None:
            return
        painter.setBrush(Qt.BrushStyle.NoBrush)
        halo = QPen(QColor("#ffffff"), 1.5)
        halo.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(halo)
        painter.drawRect(bounds.adjusted(-4, -4, 4, 4))

        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.setBrush(QBrush(QColor("#22d3ee")))
        for point in self.handle_points(ann, w, h):
            painter.drawEllipse(point, 5.0, 5.0)
        label_rect = self.attached_label_rect(ann, w, h)
        if label_rect is not None:
            painter.setPen(QPen(QColor("#fbbf24"), 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(label_rect.adjusted(-3, -3, 3, 3), 5, 5)

    def selection_bounds(self, ann: Annotation, w: float, h: float) -> QRectF | None:
        if ann.type in ("rect", "ellipse", "redact"):
            return self._rect_from_geometry(ann, w, h)
        if ann.type == "arrow":
            x1 = float(ann.geometry.get("x1", 0.0)) * w
            y1 = float(ann.geometry.get("y1", 0.0)) * h
            x2 = float(ann.geometry.get("x2", 0.0)) * w
            y2 = float(ann.geometry.get("y2", 0.0)) * h
            return QRectF(QPointF(min(x1, x2), min(y1, y2)),
                          QPointF(max(x1, x2), max(y1, y2)))
        if ann.type == "text":
            label = ann.label or "Text"
            font = QFont()
            font.setPointSize(max(8, int(ann.font_size or 15)))
            font.setBold(True)
            metrics = QFontMetricsF(font)
            x = float(ann.geometry.get("x", 0.5)) * w
            y = float(ann.geometry.get("y", 0.5)) * h
            rect = metrics.boundingRect(label).adjusted(-10, -6, 10, 6)
            rect.moveTopLeft(QPointF(x, y))
            return rect
        return None

    def handle_points(self, ann: Annotation, w: float, h: float) -> list[QPointF]:
        if ann.type == "arrow":
            return [
                QPointF(float(ann.geometry.get("x1", 0.0)) * w,
                        float(ann.geometry.get("y1", 0.0)) * h),
                QPointF(float(ann.geometry.get("x2", 0.0)) * w,
                        float(ann.geometry.get("y2", 0.0)) * h),
            ]
        bounds = self.selection_bounds(ann, w, h)
        if bounds is None:
            return []
        return [
            bounds.topLeft(), bounds.topRight(),
            bounds.bottomRight(), bounds.bottomLeft(),
        ]

    def hit_test(self, norm_x: float, norm_y: float) -> Annotation | None:
        w, h = self._size.width(), self._size.height()
        if w <= 0 or h <= 0:
            return None
        px, py = norm_x * w, norm_y * h
        for ann in reversed(self.project.annotations):
            if not ann.is_visible_at(self.project.current_time):
                continue
            if ann.type == "arrow":
                label_rect = self.attached_label_rect(ann, w, h)
                if label_rect is not None and label_rect.contains(QPointF(px, py)):
                    return ann
                x1 = float(ann.geometry.get("x1", 0.0)) * w
                y1 = float(ann.geometry.get("y1", 0.0)) * h
                x2 = float(ann.geometry.get("x2", 0.0)) * w
                y2 = float(ann.geometry.get("y2", 0.0)) * h
                if _distance_to_segment(px, py, x1, y1, x2, y2) <= 10.0:
                    return ann
                continue
            label_rect = self.attached_label_rect(ann, w, h)
            if label_rect is not None and label_rect.contains(QPointF(px, py)):
                return ann
            bounds = self.selection_bounds(ann, w, h)
            if bounds is not None and bounds.contains(QPointF(px, py)):
                return ann
        return None

    def hit_test_attached_label(self, ann: Annotation, norm_x: float, norm_y: float) -> bool:
        w, h = self._size.width(), self._size.height()
        if w <= 0 or h <= 0:
            return False
        rect = self.attached_label_rect(ann, w, h)
        if rect is None:
            return False
        return rect.contains(QPointF(norm_x * w, norm_y * h))

    def hit_test_handle(
        self, ann: Annotation, norm_x: float, norm_y: float
    ) -> int | None:
        w, h = self._size.width(), self._size.height()
        if w <= 0 or h <= 0:
            return None
        px, py = norm_x * w, norm_y * h
        for idx, point in enumerate(self.handle_points(ann, w, h)):
            if math.hypot(point.x() - px, point.y() - py) <= 10.0:
                return idx
        return None

    def _rect_from_geometry(self, ann: Annotation, w: float, h: float) -> QRectF:
        return QRectF(
            float(ann.geometry.get("x", 0.0)) * w,
            float(ann.geometry.get("y", 0.0)) * h,
            float(ann.geometry.get("width", 0.0)) * w,
            float(ann.geometry.get("height", 0.0)) * h,
        )

    def _paint_arrow(
        self,
        painter: QPainter,
        ann: Annotation,
        w: float,
        h: float,
        color: QColor,
    ) -> None:
        start = QPointF(
            float(ann.geometry.get("x1", 0.0)) * w,
            float(ann.geometry.get("y1", 0.0)) * h,
        )
        end = QPointF(
            float(ann.geometry.get("x2", 0.0)) * w,
            float(ann.geometry.get("y2", 0.0)) * h,
        )
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = math.hypot(dx, dy)
        if length < 2:
            return

        painter.drawLine(start, end)
        angle = math.atan2(dy, dx)
        head_len = min(28.0, max(12.0, length * 0.18))
        spread = math.radians(28)
        left = QPointF(
            end.x() - head_len * math.cos(angle - spread),
            end.y() - head_len * math.sin(angle - spread),
        )
        right = QPointF(
            end.x() - head_len * math.cos(angle + spread),
            end.y() - head_len * math.sin(angle + spread),
        )
        painter.setBrush(QBrush(color))
        painter.drawPolygon(QPolygonF([end, left, right]))

    def _label_should_show(self, ann: Annotation) -> bool:
        if not getattr(ann, "show_label", True):
            return False
        label = ann.label.strip()
        if not label:
            return False
        return label.lower() != ann.type

    def attached_label_rect(self, ann: Annotation, w: float, h: float) -> QRectF | None:
        if ann.type not in {"rect", "ellipse", "arrow"} or not self._label_should_show(ann):
            return None
        label = ann.label.strip()
        font = QFont()
        font.setPointSize(max(8, int(ann.font_size or 15)))
        font.setBold(True)
        metrics = QFontMetricsF(font)
        text_rect = QRectF(metrics.boundingRect(label).adjusted(-8, -5, 8, 5))

        if ann.type == "arrow":
            anchor = QPointF(
                float(ann.geometry.get("x1", 0.0)) * w + 10,
                float(ann.geometry.get("y1", 0.0)) * h - text_rect.height() - 8,
            )
            if anchor.y() < 0:
                anchor.setY(float(ann.geometry.get("y1", 0.0)) * h + 8)
        else:
            bounds = self._rect_from_geometry(ann, w, h)
            anchor = bounds.topLeft() + QPointF(0, -text_rect.height() - 8)
            if anchor.y() < 0:
                anchor = bounds.bottomLeft() + QPointF(0, 8)

        anchor += QPointF(
            float(ann.geometry.get("label_dx", 0.0)) * w,
            float(ann.geometry.get("label_dy", 0.0)) * h,
        )
        text_rect.moveTopLeft(anchor)
        return text_rect

    def _paint_attached_label(
        self,
        painter: QPainter,
        ann: Annotation,
        w: float,
        h: float,
        color: QColor,
    ) -> None:
        label = ann.label.strip()
        text_rect = self.attached_label_rect(ann, w, h)
        if text_rect is None:
            return
        font = QFont(painter.font())
        font.setPointSize(max(8, int(ann.font_size or 15)))
        font.setBold(True)
        painter.setFont(font)
        bg = QColor("#000000")
        bg.setAlpha(170)
        painter.setPen(QPen(color, 1))
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(text_rect, 6, 6)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)

    def _active_slide(self):
        # Half-open end (`<`) to match exporter._slide_at_time so preview and export
        # agree on which frames are slide frames.
        for slide in reversed(self.project.slides):
            if slide.start_time <= self.project.current_time < slide.start_time + max(0.1, slide.duration):
                return slide
        return None

    def time_state(self, time_s: float) -> tuple:
        """Return the overlay state that can change as the playhead advances."""
        slide = next(
            (
                item
                for item in reversed(self.project.slides)
                if item.start_time <= time_s < item.start_time + max(0.1, item.duration)
            ),
            None,
        )
        annotations = tuple(
            (ann.id, ann.mask_path_at(time_s))
            for ann in self.project.annotations
            if ann.is_visible_at(time_s)
        )

        caption = None
        if self.project.captions_enabled and self.project.transcript_segments:
            fingerprint = tuple(
                (s.id, s.start_time, s.end_time, s.speaker, s.text)
                for s in self.project.transcript_segments
            )
            if fingerprint != self._caption_fingerprint:
                self._caption_cues = build_caption_cues(self.project.transcript_segments)
                self._caption_fingerprint = fingerprint
            caption = cue_at_time(self._caption_cues, time_s)

        fade = 0.0
        for clip in self.project.clips:
            start = clip.start_time
            end = clip.start_time + clip.display_duration
            if not (start <= time_s <= end):
                continue
            if clip.fade_in > 0 and time_s < start + clip.fade_in:
                fade = max(fade, 1.0 - (time_s - start) / clip.fade_in)
            if clip.fade_out > 0 and time_s > end - clip.fade_out:
                fade = max(fade, 1.0 - (end - time_s) / clip.fade_out)
            break

        return slide.id if slide else None, annotations, caption, fade

    def _paint_slide(self, painter: QPainter, slide, w: float, h: float) -> None:
        rect = QRectF(0, 0, w, h)
        if not getattr(slide, "overlay", False):
            painter.fillRect(rect, QColor(slide.background))

        image_path = getattr(slide, "image_path", None)
        if image_path:
            pix = self._slide_image_cache.get(image_path)
            if pix is None:
                pix = QPixmap(image_path)
                if not pix.isNull():
                    self._slide_image_cache[image_path] = pix
            if pix is not None and not pix.isNull():
                painter.drawPixmap(rect, pix, QRectF(pix.rect()))

        family = getattr(slide, "font_family", "") or painter.font().family()
        bold = getattr(slide, "bold", True)
        italic = getattr(slide, "italic", False)

        title_rect = self._slide_title_rect(slide, w, h)
        body_rect = self._slide_body_rect(slide, w, h)

        selected_kind = None
        if self._selected_slide_region and self._selected_slide_region[0] == slide.id:
            selected_kind = self._selected_slide_region[1]
            selected_rect = title_rect if selected_kind == "title" else body_rect
            fill = QColor("#000000")
            fill.setAlpha(105)
            painter.setBrush(QBrush(fill))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(selected_rect.adjusted(-10, -8, 10, 8), 12, 12)

        title_font = QFont(family)
        title_font.setBold(bold)
        title_font.setItalic(italic)
        title_font.setPointSize(
            self._fit_slide_font_size(
                slide.title, title_rect, slide.font_size + 10,
                bold=bold, italic=italic, family=family, min_size=12, max_size=72,
            )
        )
        painter.setFont(title_font)
        painter.setPen(QColor(slide.text_color))
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom | Qt.TextFlag.TextWordWrap,
            slide.title,
        )

        body_font = QFont(family)
        body_font.setBold(False)
        body_font.setItalic(italic)
        body_font.setPointSize(
            self._fit_slide_font_size(
                slide.content, body_rect, slide.font_size,
                bold=False, italic=italic, family=family, min_size=10, max_size=54,
            )
        )
        painter.setFont(body_font)
        painter.drawText(
            body_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            slide.content,
        )

        if selected_kind is not None:
            self._paint_slide_region_selection(
                painter,
                title_rect if selected_kind == "title" else body_rect,
            )

    def _fit_slide_font_size(
        self,
        text: str,
        rect: QRectF,
        desired: int,
        *,
        bold: bool,
        italic: bool,
        family: str,
        min_size: int,
        max_size: int,
    ) -> int:
        if not text or rect.width() <= 0 or rect.height() <= 0:
            return max(min_size, min(desired, max_size))
        size = max(min_size, min(desired, max_size))
        while size > min_size:
            font = QFont(family)
            font.setBold(bold)
            font.setItalic(italic)
            font.setPointSize(size)
            metrics = QFontMetricsF(font)
            bounds = metrics.boundingRect(
                rect,
                int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignHCenter),
                text,
            )
            if bounds.width() <= rect.width() and bounds.height() <= rect.height():
                return size
            size -= 1
        return min_size

    def _paint_slide_region_selection(self, painter: QPainter, rect: QRectF) -> None:
        guide = QPen(QColor("#22d3ee"), 2)
        guide.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(guide)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)
        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.setBrush(QBrush(QColor("#22d3ee")))
        for point in self._slide_region_handle_points(rect):
            painter.drawRect(QRectF(point.x() - 5, point.y() - 5, 10, 10))

    def _slide_title_rect(self, slide, w: float, h: float) -> QRectF:
        return QRectF(
            getattr(slide, "title_x", 0.05) * w,
            getattr(slide, "title_y", 0.07) * h,
            getattr(slide, "title_w", 0.90) * w,
            getattr(slide, "title_h", 0.40) * h,
        )

    def _slide_body_rect(self, slide, w: float, h: float) -> QRectF:
        return QRectF(
            getattr(slide, "body_x", 0.07) * w,
            getattr(slide, "body_y", 0.50) * h,
            getattr(slide, "body_w", 0.86) * w,
            getattr(slide, "body_h", 0.43) * h,
        )

    def slide_text_hit_test(self, norm_x: float, norm_y: float):
        """Return ('title' | 'body', slide) when the click hits a slide text
        region of the currently-active slide; otherwise None."""
        slide = self._active_slide()
        if slide is None:
            return None
        w = self._size.width()
        h = self._size.height()
        px, py = norm_x * w, norm_y * h
        title = self._slide_title_rect(slide, w, h)
        body = self._slide_body_rect(slide, w, h)
        if title.contains(QPointF(px, py)):
            return ("title", slide)
        if body.contains(QPointF(px, py)):
            return ("body", slide)
        return None

    def slide_text_handle_hit_test(self, norm_x: float, norm_y: float):
        if self._selected_slide_region is None:
            return None
        slide_id, kind = self._selected_slide_region
        slide = self._active_slide()
        if slide is None or slide.id != slide_id:
            return None
        w = self._size.width()
        h = self._size.height()
        px, py = norm_x * w, norm_y * h
        rect = self._slide_title_rect(slide, w, h) if kind == "title" else self._slide_body_rect(slide, w, h)
        for idx, point in enumerate(self._slide_region_handle_points(rect)):
            if math.hypot(point.x() - px, point.y() - py) <= 12.0:
                return (kind, slide, idx)
        return None

    @staticmethod
    def _slide_region_handle_points(rect: QRectF) -> list[QPointF]:
        return [
            rect.topLeft(),
            rect.topRight(),
            rect.bottomRight(),
            rect.bottomLeft(),
        ]


class VideoGraphicsView(QGraphicsView):
    """Holds the QGraphicsVideoItem plus the AnnotationGraphicsItem in a single
    scene so macOS paints annotations over the video's Metal surface correctly."""

    sam_point_added = Signal(float, float)
    annotation_added = Signal(Annotation)
    selection_changed = Signal(object)  # annotation id or None
    annotation_mutated = Signal()
    edit_committed = Signal()  # a move/resize drag finished — push one undo snapshot
    delete_selected_requested = Signal()
    edit_label_requested = Signal(str)

    def __init__(self, project: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        scene = QGraphicsScene(self)
        self.setScene(scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setBackgroundBrush(QBrush(QColor("#000000")))
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.video_item = QGraphicsVideoItem()
        self.video_item.setSize(QSizeF(1920, 1080))
        scene.addItem(self.video_item)

        self.image_item = QGraphicsPixmapItem()
        self.image_item.setZValue(5)
        self.image_item.setVisible(False)
        scene.addItem(self.image_item)

        self.annotation_item = AnnotationGraphicsItem(project, self.video_item)
        self.annotation_item.set_size(self.video_item.size())
        scene.addItem(self.annotation_item)

        self.video_item.nativeSizeChanged.connect(self._native_size_changed)

        self._drag_start: tuple[float, float] | None = None
        self._drag_current: tuple[float, float] | None = None
        self._select_mode: str | None = None  # "move" | "resize"
        self._select_target_id: str | None = None
        self._select_handle: int | None = None
        self._select_start_geometry: dict | None = None
        self._select_did_mutate = False  # True once a select drag actually moved/resized
        self._slide_drag = None  # (mode, "title" | "body", slide_id, start_norm, start_rect, handle)
        self._slide_did_mutate = False  # True once a slide-text drag actually moved/resized
        self._fit()

    def _native_size_changed(self, size: QSizeF) -> None:
        if size.width() > 0 and size.height() > 0:
            self.video_item.setSize(size)
            self.annotation_item.set_size(size)
            self.scene().setSceneRect(QRectF(QPointF(0, 0), size))
            self._rescale_image_item()
            self._fit()

    def set_image(self, path: str | None) -> None:
        if not path:
            self.image_item.setPixmap(QPixmap())
            self.image_item.setVisible(False)
            self.video_item.setVisible(True)
            return
        pix = QPixmap(path)
        if pix.isNull():
            self.image_item.setVisible(False)
            self.video_item.setVisible(True)
            return
        self._raw_image_pixmap = pix
        # Use the image's intrinsic size as the scene size so it fills the view.
        size = QSizeF(pix.width(), pix.height())
        self.video_item.setSize(size)
        self.annotation_item.set_size(size)
        self.scene().setSceneRect(QRectF(QPointF(0, 0), size))
        self.image_item.setPixmap(pix)
        self.image_item.setOffset(0, 0)
        self.image_item.setVisible(True)
        self.video_item.setVisible(False)
        self._fit()

    def show_black(self) -> None:
        """Clear the preview to the black background — used when no clip or image
        sits under the playhead (e.g. after deleting the clip there) so a stale
        last decoded frame can't linger."""
        if not self.video_item.isVisible() and not self.image_item.isVisible():
            return
        self.image_item.setPixmap(QPixmap())
        self.image_item.setVisible(False)
        self.video_item.setVisible(False)
        self._raw_image_pixmap = None
        self.update_annotations()

    def _rescale_image_item(self) -> None:
        # Pixmap is stored at native size; image_item just needs to stay at (0,0).
        pix = getattr(self, "_raw_image_pixmap", None)
        if pix is not None and self.image_item.isVisible():
            self.image_item.setPixmap(pix)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        rect = self.video_item.boundingRect()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def set_project(self, project: ProjectState) -> None:
        self.annotation_item.set_project(project)
        self.annotation_item.set_preview(None)

    def update_annotations(self) -> None:
        self.annotation_item.update()

    def update_annotations_for_time(self, previous_time: float, current_time: float) -> None:
        if self.annotation_item.time_state(previous_time) != self.annotation_item.time_state(
            current_time
        ):
            self.annotation_item.update()

    def _scene_to_norm(self, event_pos) -> tuple[float, float] | None:
        scene_pos = self.mapToScene(event_pos)
        rect = self.video_item.boundingRect()
        if rect.width() <= 0 or rect.height() <= 0:
            return None
        x = scene_pos.x() / rect.width()
        y = scene_pos.y() / rect.height()
        if x < 0 or x > 1 or y < 0 or y > 1:
            return None
        return max(0.0, min(1.0, x)), max(0.0, min(1.0, y))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            norm = self._scene_to_norm(event.position().toPoint())
            if norm is not None:
                project = self.annotation_item.project
                # Drag slide text only when the Slides panel is open.
                if project.active_panel == "slides":
                    self._slide_did_mutate = False
                    handle_hit = self.annotation_item.slide_text_handle_hit_test(*norm)
                    if handle_hit is not None:
                        kind, slide, handle = handle_hit
                        self.annotation_item.set_selected_slide_region(slide.id, kind)
                        self._slide_drag = (
                            "resize",
                            kind,
                            slide.id,
                            norm,
                            self._slide_rect_tuple(slide, kind),
                            handle,
                        )
                        self.setCursor(self._slide_resize_cursor(handle))
                        return
                    hit = self.annotation_item.slide_text_hit_test(*norm)
                    if hit is not None:
                        kind, slide = hit
                        self.annotation_item.set_selected_slide_region(slide.id, kind)
                        self._slide_drag = (
                            "move",
                            kind,
                            slide.id,
                            norm,
                            self._slide_rect_tuple(slide, kind),
                            None,
                        )
                        self.setCursor(Qt.CursorShape.ClosedHandCursor)
                        return
                    self.annotation_item.set_selected_slide_region(None, None)
                if project.active_tool == "sam":
                    self.sam_point_added.emit(*norm)
                    return
                if project.active_tool in {"rect", "ellipse", "arrow", "redact"}:
                    self._drag_start = norm
                    self._drag_current = norm
                    self.annotation_item.set_preview(
                        self._build_drag_annotation(project, norm, norm),
                    )
                    return
                if project.active_tool == "text":
                    self._place_text_annotation(norm)
                    return
                if project.active_tool == "select":
                    self._select_did_mutate = False
                    self._select_press(norm)
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        project = self.annotation_item.project
        if self._slide_drag is not None:
            norm = self._scene_to_norm(event.position().toPoint())
            if norm is not None:
                mode, kind, slide_id, start_norm, start_rect, handle = self._slide_drag
                slide = next((s for s in project.slides if s.id == slide_id), None)
                if slide is not None:
                    dx = norm[0] - start_norm[0]
                    dy = norm[1] - start_norm[1]
                    if mode == "move":
                        self._apply_slide_rect(
                            slide,
                            kind,
                            self._clamped_slide_rect(
                                start_rect[0] + dx,
                                start_rect[1] + dy,
                                start_rect[2],
                                start_rect[3],
                            ),
                        )
                    else:
                        self._resize_slide_rect(slide, kind, start_rect, dx, dy, int(handle or 0))
                    self._slide_did_mutate = True
                    self.annotation_mutated.emit()
                    self.annotation_item.update()
                return
        if project.active_panel == "slides":
            norm = self._scene_to_norm(event.position().toPoint())
            if norm is not None:
                handle_hit = self.annotation_item.slide_text_handle_hit_test(*norm)
                if handle_hit is not None:
                    self.setCursor(self._slide_resize_cursor(int(handle_hit[2])))
                    return
                if self.annotation_item.slide_text_hit_test(*norm) is not None:
                    self.setCursor(Qt.CursorShape.OpenHandCursor)
                    return
            self.setCursor(Qt.CursorShape.ArrowCursor)
        if self._drag_start and project.active_tool in {"rect", "ellipse", "arrow", "redact"}:
            norm = self._scene_to_norm(event.position().toPoint())
            if norm is not None:
                self._drag_current = norm
                preview = self._build_drag_annotation(project, self._drag_start, norm)
                self.annotation_item.set_preview(preview)
                return
        if self._select_mode and project.active_tool == "select":
            norm = self._scene_to_norm(event.position().toPoint())
            if norm is not None:
                self._select_drag(norm)
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        project = self.annotation_item.project
        if self._slide_drag is not None:
            self._slide_drag = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.annotation_item.update()
            if self._slide_did_mutate:
                self._slide_did_mutate = False
                self.edit_committed.emit()
            return
        if self._drag_start and project.active_tool in {"rect", "ellipse", "arrow", "redact"}:
            end_norm = self._scene_to_norm(event.position().toPoint())
            start_norm = self._drag_start
            self._drag_start = None
            self._drag_current = None
            self.annotation_item.set_preview(None)
            if end_norm is None:
                super().mouseReleaseEvent(event)
                return
            if not self._drag_is_large_enough(project.active_tool, start_norm, end_norm):
                return
            annotation = self._build_drag_annotation(project, start_norm, end_norm)
            self.annotation_added.emit(annotation)
            return
        if self._select_mode and project.active_tool == "select":
            self._select_mode = None
            self._select_target_id = None
            self._select_handle = None
            self._select_start_geometry = None
            self._drag_start = None
            self._drag_current = None
            if self._select_did_mutate:
                self._select_did_mutate = False
                self.edit_committed.emit()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        project = self.annotation_item.project
        if event.button() == Qt.MouseButton.LeftButton and project.active_tool == "select":
            norm = self._scene_to_norm(event.position().toPoint())
            if norm is not None:
                hit = self.annotation_item.hit_test(*norm)
                if hit is not None:
                    project.selected_annotation_id = hit.id
                    self.selection_changed.emit(hit.id)
                    self.edit_label_requested.emit(hit.id)
                    return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            project = self.annotation_item.project
            if project.selected_annotation_id:
                self.delete_selected_requested.emit()
                return
        super().keyPressEvent(event)

    def _place_text_annotation(self, norm: tuple[float, float]) -> None:
        project = self.annotation_item.project
        label = project.draw_label.strip() or "Label"
        annotation = Annotation(
            id=new_id(),
            frame_time=project.current_time,
            ann_duration=5.0,
            type="text",
            label=label,
            color=project.draw_color,
            visible=True,
            opacity=project.draw_opacity,
            geometry={"x": norm[0], "y": norm[1]},
        )
        self.annotation_added.emit(annotation)

    def _slide_rect_tuple(self, slide, kind: str) -> tuple[float, float, float, float]:
        if kind == "title":
            return (slide.title_x, slide.title_y, slide.title_w, slide.title_h)
        return (slide.body_x, slide.body_y, slide.body_w, slide.body_h)

    def _apply_slide_rect(
        self,
        slide,
        kind: str,
        rect: tuple[float, float, float, float],
    ) -> None:
        x, y, w, h = rect
        if kind == "title":
            slide.title_x, slide.title_y, slide.title_w, slide.title_h = x, y, w, h
        else:
            slide.body_x, slide.body_y, slide.body_w, slide.body_h = x, y, w, h

    def _clamped_slide_rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
    ) -> tuple[float, float, float, float]:
        w = max(0.05, min(1.0, w))
        h = max(0.05, min(1.0, h))
        x = max(0.0, min(1.0 - w, x))
        y = max(0.0, min(1.0 - h, y))
        return (x, y, w, h)

    def _resize_slide_rect(
        self,
        slide,
        kind: str,
        start_rect: tuple[float, float, float, float],
        dx: float,
        dy: float,
        handle: int,
    ) -> None:
        x0, y0, w, h = start_rect
        x1 = x0 + w
        y1 = y0 + h
        if handle == 0:
            x0 += dx
            y0 += dy
        elif handle == 1:
            x1 += dx
            y0 += dy
        elif handle == 2:
            x1 += dx
            y1 += dy
        else:
            x0 += dx
            y1 += dy

        x0 = max(0.0, min(1.0, x0))
        y0 = max(0.0, min(1.0, y0))
        x1 = max(0.0, min(1.0, x1))
        y1 = max(0.0, min(1.0, y1))
        min_w = 0.08
        min_h = 0.08
        if abs(x1 - x0) < min_w:
            if handle in (0, 3):
                x0 = min(1.0 - min_w, x1 - min_w)
            else:
                x1 = max(min_w, x0 + min_w)
        if abs(y1 - y0) < min_h:
            if handle in (0, 1):
                y0 = min(1.0 - min_h, y1 - min_h)
            else:
                y1 = max(min_h, y0 + min_h)
        self._apply_slide_rect(
            slide,
            kind,
            self._clamped_slide_rect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)),
        )

    def _slide_resize_cursor(self, handle: int):
        if handle in (0, 2):
            return Qt.CursorShape.SizeFDiagCursor
        return Qt.CursorShape.SizeBDiagCursor

    def _select_press(self, norm: tuple[float, float]) -> None:
        project = self.annotation_item.project
        current_id = project.selected_annotation_id
        current = next(
            (a for a in project.annotations if a.id == current_id), None
        ) if current_id else None

        if current is not None:
            if (
                current.type in {"rect", "ellipse", "arrow"}
                and self.annotation_item.hit_test_attached_label(current, *norm)
            ):
                self._select_mode = "label"
                self._select_target_id = current.id
                self._select_start_geometry = dict(current.geometry)
                self._drag_start = norm
                return
            handle = self.annotation_item.hit_test_handle(current, *norm)
            if handle is not None:
                self._select_mode = "resize"
                self._select_target_id = current.id
                self._select_handle = handle
                self._select_start_geometry = dict(current.geometry)
                self._drag_start = norm
                return

        hit = self.annotation_item.hit_test(*norm)
        if hit is None:
            if project.selected_annotation_id is not None:
                project.selected_annotation_id = None
                self.selection_changed.emit(None)
                self.annotation_item.update()
            return

        project.selected_annotation_id = hit.id
        self.selection_changed.emit(hit.id)
        self._select_mode = "move"
        self._select_target_id = hit.id
        self._select_start_geometry = dict(hit.geometry)
        self._drag_start = norm
        self.annotation_item.update()

    def _select_drag(self, norm: tuple[float, float]) -> None:
        if self._drag_start is None or self._select_target_id is None:
            return
        project = self.annotation_item.project
        ann = next((a for a in project.annotations if a.id == self._select_target_id), None)
        if ann is None or self._select_start_geometry is None:
            return
        dx = norm[0] - self._drag_start[0]
        dy = norm[1] - self._drag_start[1]
        start = self._select_start_geometry

        if self._select_mode == "move":
            if ann.type == "arrow":
                ann.geometry["x1"] = float(start.get("x1", 0.0)) + dx
                ann.geometry["y1"] = float(start.get("y1", 0.0)) + dy
                ann.geometry["x2"] = float(start.get("x2", 0.0)) + dx
                ann.geometry["y2"] = float(start.get("y2", 0.0)) + dy
            else:
                ann.geometry["x"] = float(start.get("x", 0.0)) + dx
                ann.geometry["y"] = float(start.get("y", 0.0)) + dy
        elif self._select_mode == "label":
            ann.geometry["label_dx"] = float(start.get("label_dx", 0.0)) + dx
            ann.geometry["label_dy"] = float(start.get("label_dy", 0.0)) + dy
        elif self._select_mode == "resize":
            if ann.type == "arrow":
                if self._select_handle == 0:
                    ann.geometry["x1"] = norm[0]
                    ann.geometry["y1"] = norm[1]
                else:
                    ann.geometry["x2"] = norm[0]
                    ann.geometry["y2"] = norm[1]
            elif ann.type in ("rect", "ellipse", "redact"):
                x0 = float(start.get("x", 0.0))
                y0 = float(start.get("y", 0.0))
                x1 = x0 + float(start.get("width", 0.0))
                y1 = y0 + float(start.get("height", 0.0))
                idx = self._select_handle or 0
                if idx == 0:   # top-left
                    x0, y0 = norm
                elif idx == 1: # top-right
                    x1, y0 = norm[0], norm[1]
                elif idx == 2: # bottom-right
                    x1, y1 = norm
                elif idx == 3: # bottom-left
                    x0, y1 = norm[0], norm[1]
                ann.geometry["x"] = min(x0, x1)
                ann.geometry["y"] = min(y0, y1)
                ann.geometry["width"] = abs(x1 - x0)
                ann.geometry["height"] = abs(y1 - y0)
            elif ann.type == "text":
                ann.geometry["x"] = norm[0]
                ann.geometry["y"] = norm[1]
        self._select_did_mutate = True
        self.annotation_mutated.emit()
        self.annotation_item.update()

    def _drag_is_large_enough(
        self,
        tool: str,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> bool:
        sx, sy = start
        ex, ey = end
        if tool == "arrow":
            return math.hypot(ex - sx, ey - sy) >= 0.01
        return abs(ex - sx) >= 0.005 and abs(ey - sy) >= 0.005

    def _build_drag_annotation(
        self,
        project: ProjectState,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> Annotation:
        sx, sy = start
        ex, ey = end
        geometry: dict[str, float | list[float] | str]
        if project.active_tool == "arrow":
            geometry = {
                "x1": sx,
                "y1": sy,
                "x2": ex,
                "y2": ey,
                "width_px": float(project.draw_width),
            }
        else:
            x0, y0 = min(sx, ex), min(sy, ey)
            x1, y1 = max(sx, ex), max(sy, ey)
            geometry = {
                "x": x0,
                "y": y0,
                "width": x1 - x0,
                "height": y1 - y0,
                "width_px": float(project.draw_width),
            }

        if project.active_tool == "redact":
            # PHI redaction: opaque black box that covers the WHOLE timeline by
            # default (frame_time 0 + ann_duration 0). Over-redacting is the safe
            # default — the user can shorten the window later in the Labels panel.
            return Annotation(
                id=new_id(),
                frame_time=0.0,
                ann_duration=0.0,
                type="redact",
                label="Redacted",
                color="#000000",
                visible=True,
                opacity=1.0,
                geometry=geometry,
                show_label=False,
            )

        label = project.draw_label.strip() or project.active_tool.title()
        return Annotation(
            id=new_id(),
            frame_time=project.current_time,
            ann_duration=5.0,
            type=project.active_tool,
            label=label,
            color=project.draw_color,
            visible=True,
            opacity=project.draw_opacity,
            geometry=geometry,
            show_label=bool(project.draw_label.strip()),
        )
