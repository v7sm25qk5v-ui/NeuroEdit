from __future__ import annotations

import copy
import datetime
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, QSizeF, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QDesktopServices, QFont, QFontMetricsF, QIcon, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QInputDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGraphicsObject,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtCore import QSettings

from neuroedit_desktop.exporter import ExportCancelled, ExportSettings, ProjectExporter
from neuroedit_desktop.models import Annotation, PanelType, ProjectState, SamPoint, Slide, VideoClip, new_id
from neuroedit_desktop.project_store import ProjectStore
from neuroedit_desktop.sam_backend import SamBackend, SamCancelled
from neuroedit_desktop.ui.editor_panels import (
    AudioPanel,
    MediaExplorerPanel,
    RichTimelineWidget,
    SlideEditorPanel,
    TipsPanel,
    project_preflight_warnings,
    project_end_time,
)
from neuroedit_desktop.ui.tutorial import TutorialOverlay, build_default_steps
from neuroedit_desktop.video_probe import probe_video

_RESOURCES = Path(__file__).parent.parent / "resources"
from neuroedit_desktop.ui.styles import (
    ACCENT_AMBER, ACCENT_CYAN, ACCENT_RED,
    BG_CARD, BG_HOVER,
    BORDER, BORDER_BRIGHT, PRIMARY, TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY,
)

VIDEO_TYPES = [
    ("educational", "Educational"),
    ("case-study", "Case Study"),
    ("surgical-report", "Surgical Report"),
    ("conference", "Conference"),
    ("training", "Training"),
    ("research", "Research"),
]

TOOLS = [
    ("select",  "↖",  "Select (V)"),
    ("sam",     "⊕",  "SAM Segment (S)"),
    ("rect",    "▭",  "Rectangle (R)"),
    ("ellipse", "○",  "Ellipse (E)"),
    ("arrow",   "↗",  "Arrow (A)"),
    ("text",    "T",  "Text (T)"),
    ("brush",   "✏",  "Brush (B)"),
    ("redact",  "█",  "Redact PHI (X) — burns an opaque box over patient identifiers"),
]

PANELS: list[tuple[PanelType, str, str]] = [
    ("sam",    "SAM",    ACCENT_CYAN),
    ("labels", "Labels", PRIMARY),
    ("tips",   "Tips",   ACCENT_AMBER),
    ("slides", "Slides", "#8b5cf6"),
    ("audio",  "Audio",  ACCENT_RED),
]

SWATCH_COLORS = ["#00e5ff", "#ef4444", "#f59e0b", "#10b981", "#8b5cf6", "#f43f5e", "#ffffff", "#fb923c"]

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".webm"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".heic", ".bmp", ".webp"}

ANATOMY_PRESETS = [
    ("Tumor margin", "#ef4444"),
    ("Eloquent cortex", "#f59e0b"),
    ("Cortical vein", "#3b82f6"),
    ("Cranial nerve", "#facc15"),
    ("Dura", "#a78bfa"),
    ("Falx cerebri", "#6366f1"),
    ("Sylvian fissure", "#22d3ee"),
    ("MCA branch", "#f43f5e"),
    ("Perforator", "#fb923c"),
    ("Resection cavity", "#4ade80"),
    ("Tentorium", "#818cf8"),
    ("Bridging vein", "#60a5fa"),
    ("Nerve root", "#fbbf24"),
    ("Disc space", "#34d399"),
    ("Vertebral body", "#94a3b8"),
]

_BUILTIN_PRESET_LABELS = {label.lower() for label, _ in ANATOMY_PRESETS}
CUSTOM_PRESETS_PATH = Path.home() / ".neuroedit" / "custom_label_presets.json"


def _load_custom_presets() -> list[str]:
    try:
        data = json.loads(CUSTOM_PRESETS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(s) for s in data if s]
    except Exception:  # noqa: BLE001
        pass
    return []


def _save_custom_presets(presets: list[str]) -> None:
    try:
        CUSTOM_PRESETS_PATH.parent.mkdir(parents=True, exist_ok=True)
        CUSTOM_PRESETS_PATH.write_text(
            json.dumps(presets, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001
        pass


def default_project_root() -> Path:
    return Path.home() / "Documents" / "NeuroEdit" / "Autosave"


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


def format_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes = int(seconds // 60)
    remainder = seconds % 60
    return f"{minutes}:{remainder:04.1f}"


class AnnotationGraphicsItem(QGraphicsObject):
    """Paints annotations and SAM prompt points in the same QGraphicsScene as
    the QGraphicsVideoItem. This avoids the macOS bug where a widget overlay
    on top of QVideoWidget is hidden by the native Metal surface."""

    def __init__(self, project: ProjectState, video_item: QGraphicsVideoItem) -> None:
        super().__init__()
        self.project = project
        self.video_item = video_item
        self._size = QSizeF(1920, 1080)
        self._mask_cache: dict[str, QPixmap] = {}
        self._slide_image_cache: dict[str, QPixmap] = {}
        self._preview_annotation: Annotation | None = None
        self._selected_slide_region: tuple[str, str] | None = None
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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self._size.width(), self._size.height()
        if w <= 0 or h <= 0:
            return

        active_slide = self._active_slide()
        if active_slide is not None:
            self._paint_slide(painter, active_slide, w, h)
            if not active_slide.overlay:
                # A full-frame slide covers the video, but redactions still burn on
                # top so a redaction placed over slide/still content can't vanish.
                self._paint_redactions(painter, w, h)
                return

        for ann in self.project.annotations:
            if not ann.is_visible_at(self.project.current_time):
                continue

            mask_path = ann.mask_path_at(self.project.current_time)
            if ann.type in ("mask", "tracked-mask") and mask_path:
                pix = self._mask_cache.get(mask_path)
                if pix is None:
                    pix = QPixmap(mask_path)
                    if not pix.isNull():
                        self._mask_cache[mask_path] = pix
                if pix is None or pix.isNull():
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
        self._paint_redactions(painter, w, h)

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
            if slide.start_time <= self.project.current_time < slide.start_time + slide.duration:
                return slide
        return None

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


class TimelineWidget(QWidget):
    seek_requested = Signal(float)

    def __init__(self, project: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("timeline")
        self.project = project
        self.time_label = QLabel("0:00.0")
        self.time_label.setProperty("role", "muted")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1)
        self.slider.sliderMoved.connect(self._slider_moved)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        timeline_label = QLabel("Timeline")
        timeline_label.setProperty("role", "title")
        layout.addWidget(timeline_label)
        layout.addWidget(self.time_label)
        layout.addWidget(self.slider, 1)

    def set_project(self, project: ProjectState) -> None:
        self.project = project
        self.refresh()

    def refresh(self) -> None:
        max_ms = max(1, int(self.project.duration * 1000))
        self.slider.blockSignals(True)
        self.slider.setRange(0, max_ms)
        self.slider.setValue(min(max_ms, int(self.project.current_time * 1000)))
        self.slider.blockSignals(False)
        self.time_label.setText(
            f"{format_time(self.project.current_time)} / {format_time(self.project.duration)}"
        )

    def _slider_moved(self, value: int) -> None:
        self.seek_requested.emit(value / 1000)


class SamPanel(QWidget):
    segment_requested = Signal()
    propagate_requested = Signal()
    clear_points_requested = Signal()
    undo_point_requested = Signal()
    points_enabled_changed = Signal(bool)
    mode_changed = Signal(str)  # "positive" | "negative"
    delete_weights_requested = Signal()

    def __init__(self, project: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.status = QLabel("Preparing SAM backend…")
        self.status.setProperty("role", "muted")
        self.status.setWordWrap(True)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate marquee
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.hide()

        self.include_btn = QPushButton("＋ Include")
        self.exclude_btn = QPushButton("− Exclude")
        self.include_btn.setCheckable(True)
        self.exclude_btn.setCheckable(True)
        self.include_btn.setChecked(project.sam_mode == "positive")
        self.exclude_btn.setChecked(project.sam_mode == "negative")
        self._apply_mode_styles()
        self.include_btn.clicked.connect(lambda: self._set_mode("positive"))
        self.exclude_btn.clicked.connect(lambda: self._set_mode("negative"))

        mode_row = QVBoxLayout()
        mode_row.setSpacing(6)
        mode_row.addWidget(self.include_btn)
        mode_row.addWidget(self.exclude_btn)

        self.point_toggle = QPushButton()
        self.point_toggle.setCheckable(True)
        self.point_toggle.setToolTip("When on, clicks in the video add SAM prompt points.")
        self.point_toggle.setChecked(project.sam_points_enabled)
        self.point_toggle.toggled.connect(self._points_enabled_changed)
        self._apply_point_toggle_style()

        self.undo_button = QPushButton("Undo Last Point")
        self.undo_button.clicked.connect(self.undo_point_requested)

        self.points = QListWidget()
        self.segment_button = QPushButton("Run Segmentation")
        self.propagate_button = QPushButton("Video Propagation")
        self.clear_button = QPushButton("Clear Points")
        self.segment_button.setProperty("variant", "cyan")
        self.propagate_button.setProperty("variant", "emerald")
        self.clear_button.setProperty("variant", "danger")

        self.segment_button.clicked.connect(self.segment_requested)
        self.propagate_button.clicked.connect(self.propagate_requested)
        self.clear_button.clicked.connect(self.clear_points_requested)

        self.delete_weights_button = QPushButton("Delete Cached Weights (3.2 GB)")
        self.delete_weights_button.setProperty("variant", "danger")
        self.delete_weights_button.setToolTip(
            "Removes the SAM3 model weights from your cache (~/.cache/huggingface).\n"
            "Useful before uninstalling the app. You can re-download them later."
        )
        self.delete_weights_button.clicked.connect(self.delete_weights_requested)
        self.delete_weights_button.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        title = QLabel("SAM Segmentation")
        title.setProperty("role", "title")
        layout.addWidget(title)
        layout.addWidget(self.status)
        layout.addWidget(self.progress)
        mode_label = QLabel("Prompt mode")
        mode_label.setProperty("role", "muted")
        layout.addWidget(mode_label)
        layout.addLayout(mode_row)
        layout.addWidget(self.point_toggle)
        points_label = QLabel("Prompt points")
        points_label.setProperty("role", "muted")
        layout.addWidget(points_label)
        layout.addWidget(self.points, 1)
        layout.addWidget(self.undo_button)
        layout.addWidget(self.segment_button)
        layout.addWidget(self.propagate_button)
        layout.addWidget(self.clear_button)
        layout.addWidget(self.delete_weights_button)

    def set_project(self, project: ProjectState) -> None:
        self.project = project
        self.include_btn.setChecked(project.sam_mode == "positive")
        self.exclude_btn.setChecked(project.sam_mode == "negative")
        self.point_toggle.blockSignals(True)
        self.point_toggle.setChecked(project.sam_points_enabled)
        self.point_toggle.blockSignals(False)
        self._apply_mode_styles()
        self._apply_point_toggle_style()
        self.refresh()

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def set_weights_cached(self, cached: bool) -> None:
        self.delete_weights_button.setVisible(cached)

    def set_busy(self, busy: bool) -> None:
        self.progress.setVisible(busy)
        self.segment_button.setEnabled(not busy)
        self.propagate_button.setEnabled(not busy)
        self.point_toggle.setEnabled(not busy)
        self.undo_button.setEnabled(not busy and bool(self.project.sam_points))

    def refresh(self) -> None:
        self.points.clear()
        for idx, point in enumerate(self.project.sam_points, start=1):
            marker = "＋" if point.type == "positive" else "−"
            self.points.addItem(
                f"{marker}  {idx}. {point.type} ({point.x * 100:.0f}%, {point.y * 100:.0f}%)"
            )
        self.undo_button.setEnabled(bool(self.project.sam_points))
        self._apply_point_toggle_style()

    def _set_mode(self, mode: str) -> None:
        self.include_btn.setChecked(mode == "positive")
        self.exclude_btn.setChecked(mode == "negative")
        self._apply_mode_styles()
        self.mode_changed.emit(mode)

    def _points_enabled_changed(self, enabled: bool) -> None:
        self._apply_point_toggle_style()
        self.points_enabled_changed.emit(enabled)

    def _apply_mode_styles(self) -> None:
        inc_on = self.include_btn.isChecked()
        exc_on = self.exclude_btn.isChecked()
        self.include_btn.setStyleSheet(self._mode_css("#10b981", inc_on))
        self.exclude_btn.setStyleSheet(self._mode_css("#ef4444", exc_on))

    def _apply_point_toggle_style(self) -> None:
        enabled = self.point_toggle.isChecked()
        self.point_toggle.setText(
            "Point Placement On"
            if enabled
            else "Point Placement Off"
        )
        color = "#22d3ee" if enabled else "#64748b"
        bg = "rgba(34, 211, 238, 0.16)" if enabled else "rgba(100, 116, 139, 0.10)"
        self.point_toggle.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: {color};"
            f" border: 1px solid {color}; border-radius: 8px;"
            f" padding: 7px 10px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: rgba(255,255,255,0.06); }}"
        )

    @staticmethod
    def _mode_css(color: str, active: bool) -> str:
        if active:
            return (
                f"QPushButton {{ background: {color}; color: white; border: 1px solid {color};"
                f"  border-radius: 8px; padding: 6px 10px; font-weight: 700; }}"
            )
        return (
            f"QPushButton {{ background: transparent; color: {color}; border: 1px solid {color};"
            f"  border-radius: 8px; padding: 6px 10px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: rgba(255,255,255,0.05); }}"
        )


class LabelsPanel(QWidget):
    delete_requested = Signal(str)
    duplicate_requested = Signal(str)
    set_start_to_playhead = Signal(str)
    set_end_to_playhead = Signal(str)
    seek_requested = Signal(float)
    preset_selected = Signal(str, str)
    duration_changed = Signal(str, float)
    label_text_changed = Signal(str, str)
    color_changed = Signal(str, str)
    font_size_changed = Signal(str, int)
    stroke_width_changed = Signal(str, int)
    opacity_changed = Signal(str, float)
    show_label_changed = Signal(str, bool)
    selection_changed = Signal(object)  # annotation id or None

    def __init__(self, project: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self._refreshing = False
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._seek_item)
        self.list_widget.currentItemChanged.connect(self._load_selected)
        self.list_widget.currentItemChanged.connect(self._emit_selection)

        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("Label text")
        self.label_edit.editingFinished.connect(self._label_text_edited)

        self.show_label_check = QCheckBox("Show label on shape")
        self.show_label_check.toggled.connect(self._show_label_changed)

        self.duration_input = QDoubleSpinBox()
        self.duration_input.setRange(0.0, 3600.0)
        self.duration_input.setSingleStep(0.5)
        self.duration_input.setSuffix(" s")
        self.duration_input.setToolTip("0 seconds keeps the label visible for the rest of the timeline.")
        self.duration_input.valueChanged.connect(self._duration_changed)

        self.font_size_input = QDoubleSpinBox()
        self.font_size_input.setDecimals(0)
        self.font_size_input.setRange(8, 96)
        self.font_size_input.setSingleStep(1)
        self.font_size_input.setSuffix(" pt")
        self.font_size_input.valueChanged.connect(self._font_size_changed)

        self.stroke_input = QDoubleSpinBox()
        self.stroke_input.setDecimals(0)
        self.stroke_input.setRange(1, 30)
        self.stroke_input.setSingleStep(1)
        self.stroke_input.setSuffix(" px")
        self.stroke_input.valueChanged.connect(self._stroke_changed)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(10, 100)
        self.opacity_slider.valueChanged.connect(self._opacity_slider_changed)

        self._color_row = QHBoxLayout()
        self._color_row.setSpacing(4)
        self._color_buttons: dict[str, QPushButton] = {}
        for color in SWATCH_COLORS:
            btn = QPushButton()
            btn.setFixedSize(18, 18)
            btn.setToolTip(color)
            btn.setStyleSheet(
                f"QPushButton {{ border-radius: 9px; border: 2px solid transparent; background: {color}; }}"
                f"QPushButton:hover {{ border-color: white; }}"
            )
            btn.clicked.connect(lambda _=False, c=color: self._color_clicked(c))
            self._color_buttons[color] = btn
            self._color_row.addWidget(btn)
        self._color_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        title = QLabel("Labels")
        title.setProperty("role", "title")
        layout.addWidget(title)

        self._presets_toggle = QPushButton("▸  Quick Label Presets")
        self._presets_toggle.setCheckable(True)
        self._presets_toggle.setStyleSheet(
            f"QPushButton {{ text-align: left; border: none; background: transparent;"
            f"  color: {TEXT_MUTED}; padding: 2px 0; font-size: 11px; }}"
            f"QPushButton:hover {{ color: {TEXT_PRIMARY}; }}"
        )
        self._presets_toggle.clicked.connect(self._toggle_presets)
        layout.addWidget(self._presets_toggle)

        self._presets_container = QWidget()
        presets_layout = QVBoxLayout(self._presets_container)
        presets_layout.setContentsMargins(0, 0, 0, 4)
        presets_layout.setSpacing(4)

        builtin_label = QLabel("Built-in")
        builtin_label.setProperty("role", "muted")
        presets_layout.addWidget(builtin_label)

        builtin_grid_widget = QWidget()
        self._builtin_grid = QGridLayout(builtin_grid_widget)
        self._builtin_grid.setContentsMargins(0, 0, 0, 0)
        self._builtin_grid.setHorizontalSpacing(6)
        self._builtin_grid.setVerticalSpacing(6)
        for idx, (label, color) in enumerate(ANATOMY_PRESETS):
            btn = QPushButton(label)
            btn.setToolTip(f"Use label: {label}")
            btn.clicked.connect(
                lambda _=False, preset_label=label, c=color: (
                    self.preset_selected.emit(preset_label, c)
                )
            )
            btn.setStyleSheet(
                f"QPushButton {{ color: {color}; border: 1px solid {BORDER};"
                f" background: {BG_CARD}; border-radius: 10px;"
                f" padding: 5px 7px; font-size: 10px; text-align: left; }}"
                f"QPushButton:hover {{ border-color: {color}; background: {BG_HOVER}; }}"
            )
            self._builtin_grid.addWidget(btn, idx // 2, idx % 2)
        presets_layout.addWidget(builtin_grid_widget)

        custom_label = QLabel("Custom")
        custom_label.setProperty("role", "muted")
        presets_layout.addWidget(custom_label)

        self._custom_grid_widget = QWidget()
        self._custom_grid = QGridLayout(self._custom_grid_widget)
        self._custom_grid.setContentsMargins(0, 0, 0, 0)
        self._custom_grid.setHorizontalSpacing(6)
        self._custom_grid.setVerticalSpacing(4)
        presets_layout.addWidget(self._custom_grid_widget)

        add_row = QHBoxLayout()
        add_row.setSpacing(4)
        self._new_preset_edit = QLineEdit()
        self._new_preset_edit.setPlaceholderText("New preset label…")
        self._new_preset_edit.setFixedHeight(26)
        add_preset_btn = QPushButton("Add")
        add_preset_btn.setFixedHeight(26)
        add_preset_btn.setFixedWidth(44)
        add_preset_btn.clicked.connect(self._add_custom_preset)
        self._new_preset_edit.returnPressed.connect(self._add_custom_preset)
        add_row.addWidget(self._new_preset_edit, 1)
        add_row.addWidget(add_preset_btn)
        presets_layout.addLayout(add_row)

        self._custom_presets: list[str] = _load_custom_presets()
        self._refresh_custom_grid()

        self._presets_container.setVisible(False)
        layout.addWidget(self._presets_container)

        layout.addWidget(self.list_widget, 1)

        self._inspector = QWidget()
        inspector_layout = QVBoxLayout(self._inspector)
        inspector_layout.setContentsMargins(0, 8, 0, 0)
        inspector_layout.setSpacing(6)
        inspector_title = QLabel("Edit Selected")
        inspector_title.setProperty("role", "muted")
        inspector_layout.addWidget(inspector_title)
        inspector_layout.addWidget(self.label_edit)
        inspector_layout.addWidget(self.show_label_check)
        inspector_layout.addLayout(self._color_row)

        def _row(label_text: str, widget: QWidget) -> QHBoxLayout:
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setProperty("role", "muted")
            lbl.setFixedWidth(72)
            row.addWidget(lbl)
            row.addWidget(widget, 1)
            return row

        self.start_time_label = QLabel("")
        self.start_time_label.setProperty("role", "muted")

        set_start_btn = QPushButton("◀ Set start")
        set_start_btn.setToolTip("Set annotation start to current playhead position")
        set_start_btn.clicked.connect(self._set_start_to_playhead)
        set_end_btn = QPushButton("Set end ▶")
        set_end_btn.setToolTip("Set annotation end to current playhead position")
        set_end_btn.clicked.connect(self._set_end_to_playhead)
        playhead_row = QHBoxLayout()
        playhead_row.setSpacing(4)
        playhead_row.addWidget(set_start_btn, 1)
        playhead_row.addWidget(set_end_btn, 1)

        inspector_layout.addWidget(self.start_time_label)
        inspector_layout.addLayout(_row("Duration", self.duration_input))
        inspector_layout.addLayout(playhead_row)
        inspector_layout.addLayout(_row("Font size", self.font_size_input))
        inspector_layout.addLayout(_row("Stroke", self.stroke_input))
        inspector_layout.addLayout(_row("Opacity", self.opacity_slider))

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        self._duplicate_btn = QPushButton("Duplicate")
        self._duplicate_btn.setToolTip("Duplicate annotation at playhead (Cmd+D)")
        self._duplicate_btn.clicked.connect(self._duplicate_selected)
        self._delete_inspector_btn = QPushButton("Delete")
        self._delete_inspector_btn.setToolTip("Delete selected annotation")
        self._delete_inspector_btn.setStyleSheet(
            "QPushButton { color: #F44336; border-color: rgba(244, 67, 54, 0.35);"
            " background: rgba(244, 67, 54, 0.10); }"
            "QPushButton:hover { background: rgba(244, 67, 54, 0.22); }"
        )
        self._delete_inspector_btn.clicked.connect(self._delete_selected)
        action_row.addWidget(self._duplicate_btn, 1)
        action_row.addWidget(self._delete_inspector_btn, 1)
        inspector_layout.addLayout(action_row)

        layout.addWidget(self._inspector)

    def set_project(self, project: ProjectState) -> None:
        self.project = project
        self.refresh()

    def refresh(self) -> None:
        self._refreshing = True
        selected_id = self.project.selected_annotation_id or self._selected_id()
        self.list_widget.clear()
        for ann in self.project.annotations:
            item = QListWidgetItem(
                f"{ann.label or '(unlabeled)'}  |  {ann.type}  |  "
                f"{format_time(ann.frame_time)}  |  {ann.ann_duration:g}s"
            )
            item.setData(Qt.ItemDataRole.UserRole, ann.id)
            self.list_widget.addItem(item)
            if ann.id == selected_id:
                self.list_widget.setCurrentItem(item)
        self._refreshing = False
        self._load_selected()

    def set_selected_annotation(self, ann_id: str | None) -> None:
        self._refreshing = True
        if ann_id is None:
            self.list_widget.setCurrentItem(None)
        else:
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                if str(item.data(Qt.ItemDataRole.UserRole)) == ann_id:
                    self.list_widget.setCurrentItem(item)
                    break
        self._refreshing = False
        self._load_selected()

    def _selected_id(self) -> str | None:
        item = self.list_widget.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _selected_annotation(self) -> Annotation | None:
        ann_id = self._selected_id()
        if ann_id is None:
            return None
        return next((ann for ann in self.project.annotations if ann.id == ann_id), None)

    def _toggle_presets(self) -> None:
        visible = self._presets_toggle.isChecked()
        self._presets_container.setVisible(visible)
        self._presets_toggle.setText(("▾" if visible else "▸") + "  Quick Label Presets")

    def _refresh_custom_grid(self) -> None:
        while self._custom_grid.count():
            item = self._custom_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for idx, preset_label in enumerate(self._custom_presets):
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(2)
            btn = QPushButton(preset_label)
            btn.setToolTip(f"Use label: {preset_label}")
            btn.clicked.connect(
                lambda _=False, pl=preset_label: self.preset_selected.emit(pl, self.project.draw_color)
            )
            btn.setStyleSheet(
                f"QPushButton {{ color: {TEXT_SECONDARY}; border: 1px solid {BORDER};"
                f" background: {BG_CARD}; border-radius: 10px;"
                f" padding: 5px 7px; font-size: 10px; text-align: left; }}"
                f"QPushButton:hover {{ border-color: {BORDER_BRIGHT}; background: {BG_HOVER}; }}"
            )
            remove_btn = QPushButton("×")
            remove_btn.setFixedSize(18, 18)
            remove_btn.setToolTip(f"Remove preset: {preset_label}")
            remove_btn.setStyleSheet(
                f"QPushButton {{ color: {TEXT_MUTED}; border: none; background: transparent;"
                f" font-size: 12px; padding: 0; }}"
                f"QPushButton:hover {{ color: #F44336; }}"
            )
            remove_btn.clicked.connect(lambda _=False, pl=preset_label: self._remove_custom_preset(pl))
            row_layout.addWidget(btn, 1)
            row_layout.addWidget(remove_btn)
            self._custom_grid.addWidget(row_widget, idx, 0)
        self._custom_grid_widget.setVisible(bool(self._custom_presets))

    def _add_custom_preset(self) -> None:
        text = self._new_preset_edit.text().strip()
        if not text:
            return
        if text.lower() in _BUILTIN_PRESET_LABELS:
            return
        if text.lower() in {p.lower() for p in self._custom_presets}:
            return
        self._custom_presets.append(text)
        _save_custom_presets(self._custom_presets)
        self._new_preset_edit.clear()
        self._refresh_custom_grid()

    def _remove_custom_preset(self, label: str) -> None:
        self._custom_presets = [p for p in self._custom_presets if p != label]
        _save_custom_presets(self._custom_presets)
        self._refresh_custom_grid()

    def _load_selected(self) -> None:
        ann = self._selected_annotation()
        has = ann is not None
        self._inspector.setVisible(has)
        blockers = [self.duration_input, self.label_edit, self.show_label_check, self.font_size_input,
                    self.stroke_input, self.opacity_slider]
        for w in blockers:
            w.blockSignals(True)
        self.label_edit.setText(ann.label if ann else "")
        is_shape = ann is not None and ann.type in {"rect", "ellipse", "arrow"}
        self.show_label_check.setEnabled(is_shape)
        self.show_label_check.setChecked(bool(getattr(ann, "show_label", True)) if is_shape else ann is not None)
        self.duration_input.setValue(float(ann.ann_duration if ann else 0.0))
        self.font_size_input.setValue(float(ann.font_size if ann else 15))
        stroke_px = 6
        if ann is not None:
            stroke_px = int(float(ann.geometry.get("width_px", self.project.draw_width)))
        self.stroke_input.setValue(float(stroke_px))
        self.opacity_slider.setValue(int(round((ann.opacity if ann else 0.85) * 100)))
        for w in blockers:
            w.blockSignals(False)

        if ann is not None:
            self.start_time_label.setText(f"Start: {format_time(ann.frame_time)}")
        else:
            self.start_time_label.setText("")

        for color, btn in self._color_buttons.items():
            active = ann is not None and color.lower() == ann.color.lower()
            border = "white" if active else "transparent"
            btn.setStyleSheet(
                f"QPushButton {{ border-radius: 9px; border: 2px solid {border}; background: {color}; }}"
                f"QPushButton:hover {{ border-color: white; }}"
            )

    def _duration_changed(self, value: float) -> None:
        if self._refreshing:
            return
        ann_id = self._selected_id()
        if ann_id:
            self.duration_changed.emit(ann_id, float(value))

    def _label_text_edited(self) -> None:
        if self._refreshing:
            return
        ann_id = self._selected_id()
        if ann_id:
            self.label_text_changed.emit(ann_id, self.label_edit.text())

    def _color_clicked(self, color: str) -> None:
        ann_id = self._selected_id()
        if ann_id:
            self.color_changed.emit(ann_id, color)

    def _font_size_changed(self, value: float) -> None:
        if self._refreshing:
            return
        ann_id = self._selected_id()
        if ann_id:
            self.font_size_changed.emit(ann_id, int(value))

    def _show_label_changed(self, checked: bool) -> None:
        if self._refreshing:
            return
        ann_id = self._selected_id()
        if ann_id:
            self.show_label_changed.emit(ann_id, checked)

    def _stroke_changed(self, value: float) -> None:
        if self._refreshing:
            return
        ann_id = self._selected_id()
        if ann_id:
            self.stroke_width_changed.emit(ann_id, int(value))

    def _opacity_slider_changed(self, value: int) -> None:
        if self._refreshing:
            return
        ann_id = self._selected_id()
        if ann_id:
            self.opacity_changed.emit(ann_id, float(value) / 100.0)

    def _emit_selection(self) -> None:
        if self._refreshing:
            return
        ann_id = self._selected_id()
        self.selection_changed.emit(ann_id)
        ann = self._selected_annotation()
        if ann is not None:
            self.seek_requested.emit(ann.frame_time)

    def _delete_selected(self) -> None:
        item = self.list_widget.currentItem()
        if item:
            self.delete_requested.emit(str(item.data(Qt.ItemDataRole.UserRole)))

    def _duplicate_selected(self) -> None:
        ann_id = self._selected_id()
        if ann_id:
            self.duplicate_requested.emit(ann_id)

    def _set_start_to_playhead(self) -> None:
        ann_id = self._selected_id()
        if ann_id:
            self.set_start_to_playhead.emit(ann_id)

    def _set_end_to_playhead(self) -> None:
        ann_id = self._selected_id()
        if ann_id:
            self.set_end_to_playhead.emit(ann_id)

    def _seek_item(self, item: QListWidgetItem) -> None:
        ann_id = str(item.data(Qt.ItemDataRole.UserRole))
        for ann in self.project.annotations:
            if ann.id == ann_id:
                self.seek_requested.emit(ann.frame_time)
                return


class SamProbeWorker(QObject):
    """Probes the SAM backend and warms the model weights in the background.
    PyTorch import (5-15s) + first model download (~375 MB) + MPS compile
    all happen here so segmentation clicks later are instant."""
    finished = Signal(object)   # emits SamBackendInfo
    progress = Signal(str)

    def __init__(self, backend: SamBackend) -> None:
        super().__init__()
        self.backend = backend
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        from neuroedit_desktop.sam_backend import SamBackendInfo
        try:
            self.progress.emit("Importing PyTorch…")
            info = self.backend.probe()
            if info.status == "ready":
                self.progress.emit(info.message)
        except Exception as exc:  # noqa: BLE001
            info = SamBackendInfo(status="missing", device="none", message=str(exc))
        self.finished.emit(info)


class SamSegmentWorker(QObject):
    """Runs SamBackend.segment_frame on a background thread. Model load + MPS
    inference on a 1080p frame takes several seconds — must not block UI."""
    finished = Signal(object, object)  # (result_or_none, error_msg_or_none)
    progress = Signal(str)

    def __init__(
        self,
        backend: SamBackend,
        video_path: Path,
        time_s: float,
        points: list[SamPoint],
        mask_dir: Path,
    ) -> None:
        super().__init__()
        self.backend = backend
        self.video_path = video_path
        self.time_s = time_s
        self.points = points
        self.mask_dir = mask_dir
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            result = self.backend.segment_frame(
                self.video_path, self.time_s, self.points, self.mask_dir,
                progress=self.progress.emit,
            )
            self.finished.emit(result, None)
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(None, str(exc))


class SamPropagationWorker(QObject):
    finished = Signal(object, object)  # (result_or_none, error_msg_or_none)
    progress = Signal(str)

    def __init__(
        self,
        backend: SamBackend,
        video_path: Path,
        start_time_s: float,
        duration_s: float,
        points: list[SamPoint],
        mask_dir: Path,
        sample_rate: float = 2.0,
    ) -> None:
        super().__init__()
        self.backend = backend
        self.video_path = video_path
        self.start_time_s = start_time_s
        self.duration_s = duration_s
        self.points = points
        self.mask_dir = mask_dir
        self.sample_rate = sample_rate
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            result = self.backend.propagate_video(
                self.video_path,
                self.start_time_s,
                self.duration_s,
                self.points,
                self.mask_dir,
                progress=self.progress.emit,
                sample_rate=self.sample_rate,
                cancelled=lambda: self._cancelled,
            )
            self.finished.emit(result, None)
        except SamCancelled:
            self.finished.emit(None, None)
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(None, str(exc))


class SamDownloadWorker(QObject):
    """Authenticates with HuggingFace and downloads SAM3 weights via warmup()."""
    finished = Signal(object)  # SamBackendInfo
    progress = Signal(str)

    def __init__(self, backend: SamBackend, token: str) -> None:
        super().__init__()
        self.backend = backend
        self.token = token

    def run(self) -> None:
        from neuroedit_desktop.sam_backend import SamBackendInfo
        try:
            if self.token:
                self.progress.emit("Authenticating with HuggingFace…")
                self.backend.login(self.token)
            self.progress.emit("Downloading SAM3 weights (~3.2 GB, this may take several minutes)…")
            info = self.backend.warmup(self.progress.emit)
            self.finished.emit(info)
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(SamBackendInfo(status="missing", device="none", message=str(exc)))


class SamSetupDialog(QDialog):
    """Shown when SAM3 stack is installed but weights are not yet downloaded."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set Up SAM3")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        intro = QLabel(
            "SAM3 requires a one-time download of <b>~3.2 GB</b> from Meta / HuggingFace.<br><br>"
            "1. <a href='https://huggingface.co/facebook/sam3'>Accept the SAM3 license</a> "
            "&nbsp;(free HuggingFace account required).<br>"
            "2. <a href='https://huggingface.co/settings/tokens'>Create a read token</a> "
            "and paste it below."
        )
        intro.setOpenExternalLinks(True)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        token_label = QLabel("HuggingFace token:")
        self._token_edit = QLineEdit()
        self._token_edit.setPlaceholderText("hf_…")
        try:
            from huggingface_hub import get_token
            saved = get_token()
            if saved:
                self._token_edit.setText(saved)
        except Exception:  # noqa: BLE001
            pass
        layout.addWidget(token_label)
        layout.addWidget(self._token_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Download")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def token(self) -> str:
        return self._token_edit.text().strip()


class ExportDialog(QDialog):
    PRESETS = [
        (
            "1080p",
            "Recommended: 1080p MP4",
            "Best default for teaching videos, conference screens, and general sharing.",
            1920,
            1080,
            30,
            20,
        ),
        (
            "720p",
            "Small screen: 720p MP4",
            "Smaller files for quick review, email, or mobile-first viewing.",
            1280,
            720,
            30,
            23,
        ),
        (
            "4k",
            "Big screen / high quality: 4K MP4",
            "Use for large displays or when you want the cleanest export.",
            3840,
            2160,
            30,
            18,
        ),
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export Video")
        self.setMinimumWidth(440)

        title = QLabel("Where will this video be watched?")
        title.setProperty("role", "title")
        title.setWordWrap(True)
        intro = QLabel(
            "Choose the viewing target. NeuroEdit will keep the format simple: "
            "MP4 for the best Mac and Windows compatibility."
        )
        intro.setProperty("role", "muted")
        intro.setWordWrap(True)

        self.preset_combo = QComboBox()
        for key, label, help_text, width, height, fps, crf in self.PRESETS:
            self.preset_combo.addItem(label, (key, width, height, fps, crf, help_text))
        self.preset_combo.currentIndexChanged.connect(self._preset_changed)

        self.help_label = QLabel()
        self.help_label.setProperty("role", "muted")
        self.help_label.setWordWrap(True)

        self.file_type = QComboBox()
        self.file_type.addItem("MP4 video (.mp4) - highest compatibility", "mp4")
        self.file_type.setEnabled(False)

        self.mute_source_audio_check = QCheckBox(
            "Remove original clip audio (may contain spoken PHI)"
        )
        # Safe default for a clinical tool: drop the original operating-room audio,
        # which can contain spoken identifiers. Narration added on the Audio panel
        # is always kept. The user must deliberately opt in to retaining it.
        self.mute_source_audio_check.setChecked(True)
        self.mute_source_audio_check.setToolTip(
            "Drops the audio recorded with your video clips from the export. "
            "Narration or music you added on the Audio panel is kept."
        )

        form = QFormLayout()
        form.addRow("Viewing target", self.preset_combo)
        form.addRow("File type", self.file_type)
        form.addRow("Privacy", self.mute_source_audio_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Choose Save Location")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(self.help_label)
        layout.addWidget(buttons)
        self._preset_changed()

    def export_settings(self, output_path: Path) -> ExportSettings:
        _key, width, height, fps, crf, _help_text = self.preset_combo.currentData()
        return ExportSettings(
            output_path=output_path,
            width=int(width),
            height=int(height),
            fps=int(fps),
            crf=int(crf),
            label=self.preset_combo.currentText(),
            mute_source_audio=self.mute_source_audio_check.isChecked(),
        )

    def _preset_changed(self) -> None:
        _key, width, height, fps, _crf, help_text = self.preset_combo.currentData()
        self.help_label.setText(f"{help_text} Output: {width} x {height}, {fps} fps.")


class ExportWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(object, object, object)  # output_path_or_none, error_or_none, warnings

    def __init__(self, project: ProjectState, settings: ExportSettings) -> None:
        super().__init__()
        self.project = project
        self.settings = settings
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            exporter = ProjectExporter(
                self.project,
                self.settings,
                progress=self.progress.emit,
                cancelled=lambda: self._cancelled,
            )
            warnings = exporter.export()
            self.finished.emit(str(self.settings.output_path), None, warnings)
        except ExportCancelled:
            self.finished.emit(None, "Export canceled.", [])
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(None, str(exc), [])


def _relative_time(ts: float) -> str:
    now = datetime.datetime.now()
    dt = datetime.datetime.fromtimestamp(ts)
    delta = now - dt
    days = delta.days
    if days < 1:
        return "Opened today"
    if days == 1:
        return "Opened yesterday"
    if days < 7:
        return f"Opened {days} days ago"
    if days < 14:
        return "Opened last week"
    if days < 28:
        weeks = days // 7
        return f"Opened {weeks} weeks ago"
    return dt.strftime("%b %-d, %Y")


def _read_project_meta(path: Path) -> dict:
    result = {
        "project_name": None,
        "total_duration": 0.0,
        "media_count": 0,
        "missing_count": 0,
        "first_source_path": None,
        "first_clip_duration": 0.0,
        "ok": False,
    }
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        result["project_name"] = data.get("project_name")
        clips = data.get("clips") or []
        audio = data.get("audio_tracks") or data.get("audio") or []
        slides = data.get("slides") or []
        for clip in clips:
            dur = clip.get("duration") or 0.0
            result["total_duration"] += float(dur)
            src = clip.get("path") or clip.get("source_path")
            if src and result["first_source_path"] is None:
                result["first_source_path"] = src
                result["first_clip_duration"] = float(dur)
        result["media_count"] = len(clips) + len(audio) + len(slides)
        for clip in clips:
            src = clip.get("path") or clip.get("source_path")
            if src and not Path(src).exists():
                result["missing_count"] += 1
        for track in audio:
            src = track.get("path") or track.get("source_path")
            if src and not Path(src).exists():
                result["missing_count"] += 1
        for slide in slides:
            src = slide.get("image_path") or slide.get("source_path")
            if src and not Path(src).exists():
                result["missing_count"] += 1
        result["ok"] = True
    except Exception:  # noqa: BLE001
        pass
    return result


def _make_gray_placeholder(width: int = 160, height: int = 90) -> QPixmap:
    img = QImage(width, height, QImage.Format.Format_RGB32)
    img.fill(QColor("#2c3340"))
    return QPixmap.fromImage(img)


class ThumbnailWorker(QObject):
    thumbnail_ready = Signal(str, str)  # project_path, thumb_path

    def __init__(self, tasks: list[tuple[str, str, float]]) -> None:
        super().__init__()
        self._tasks = tasks
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    def run(self) -> None:
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # noqa: BLE001
            return
        for project_path, source_path, clip_dur in self._tasks:
            if self._stopped:
                break
            thumb = Path(project_path).with_suffix(".thumb.jpg")
            try:
                proj_mtime = Path(project_path).stat().st_mtime
                if thumb.exists() and thumb.stat().st_mtime >= proj_mtime:
                    self.thumbnail_ready.emit(project_path, str(thumb))
                    continue
                offset = clip_dur * 0.15 if clip_dur > 0 else 5.0
                src = f'"{source_path}"' if sys.platform in ("win32",) and " " in source_path else source_path
                cmd = [
                    ffmpeg, "-y", "-ss", str(offset),
                    "-i", src,
                    "-frames:v", "1", "-q:v", "2",
                    str(thumb),
                ]
                subprocess.run(cmd, capture_output=True, timeout=15)
                if thumb.exists():
                    self.thumbnail_ready.emit(project_path, str(thumb))
            except Exception:  # noqa: BLE001
                pass


class ProjectLibraryDialog(QDialog):
    project_selected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Project Library")
        self.setMinimumSize(640, 420)
        self._thumb_thread = None
        self._thumb_worker = None
        self._build_ui()
        self._populate()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Recent Projects")
        title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(False)
        self.list_widget.setSpacing(2)
        self.list_widget.setIconSize(QSize(160, 90))
        self.list_widget.itemDoubleClicked.connect(self._open_selected)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.remove_btn = QPushButton("Remove from List")
        self.remove_btn.clicked.connect(self._remove_selected)
        open_btn = QPushButton("Open")
        open_btn.setDefault(True)
        open_btn.clicked.connect(self._open_selected)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.remove_btn)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(open_btn)
        layout.addLayout(btn_row)

    def _populate(self) -> None:
        self._stop_thumb_thread()
        self.list_widget.clear()
        settings = QSettings("NeuroEdit", "Desktop")
        recents: list[str] = settings.value("recentProjects", []) or []

        thumb_tasks: list[tuple[str, str, float]] = []
        placeholder_icon = QPixmap(_make_gray_placeholder())

        for path_str in recents:
            p = Path(path_str)
            folder_name = p.parent.name if p.name == "project.json" else p.name
            meta = _read_project_meta(p)
            project_name = meta["project_name"] or folder_name

            modified = ""
            try:
                ts = p.stat().st_mtime
                modified = _relative_time(ts)
            except Exception:  # noqa: BLE001
                pass

            dur = meta["total_duration"]
            if dur > 0:
                mins = int(dur) // 60
                secs = int(dur) % 60
                dur_str = f"{mins}:{secs:02d}"
            else:
                dur_str = ""

            clips_data = []
            try:
                with p.open(encoding="utf-8") as f:
                    _d = json.load(f)
                clips_data = _d.get("clips") or []
                audio_data = _d.get("audio_tracks") or _d.get("audio") or []
                slides_data = _d.get("slides") or []
            except Exception:  # noqa: BLE001
                clips_data = []
                audio_data = []
                slides_data = []

            parts = []
            if clips_data:
                parts.append(f"{len(clips_data)} clip{'s' if len(clips_data) != 1 else ''}")
            if audio_data:
                parts.append(f"{len(audio_data)} audio")
            if slides_data:
                parts.append(f"{len(slides_data)} slide{'s' if len(slides_data) != 1 else ''}")
            media_str = ", ".join(parts) if parts else ""

            detail_line = ""
            if dur_str and media_str:
                detail_line = f"{dur_str}  •  {media_str}"
            elif dur_str:
                detail_line = dur_str
            elif media_str:
                detail_line = media_str

            missing = meta["missing_count"]
            if meta["ok"] and missing > 0:
                status_suffix = f"  ⚠ {missing} source file{'s' if missing != 1 else ''} missing"
            elif not meta["ok"] and not p.exists():
                status_suffix = "  (not found)"
            else:
                status_suffix = ""

            lines = [project_name]
            if modified:
                lines.append(modified)
            if detail_line:
                lines.append(detail_line)
            display = "\n".join(lines)
            if status_suffix:
                display += status_suffix

            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, path_str)
            item.setIcon(QPixmap(placeholder_icon))

            if meta["ok"] and missing == 0:
                item.setForeground(QColor("#4CAF50"))
            elif meta["ok"] and missing > 0:
                item.setForeground(QColor("#F44336"))
            elif not p.exists():
                item.setForeground(QColor("#6b7280"))

            self.list_widget.addItem(item)

            if meta["first_source_path"]:
                thumb_tasks.append((path_str, meta["first_source_path"], meta["first_clip_duration"]))

        if not recents:
            placeholder = QListWidgetItem("No recent projects")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_widget.addItem(placeholder)

        if thumb_tasks:
            self._start_thumb_thread(thumb_tasks)

    def _start_thumb_thread(self, tasks: list[tuple[str, str, float]]) -> None:
        self._thumb_thread = QThread()
        self._thumb_worker = ThumbnailWorker(tasks)
        self._thumb_worker.moveToThread(self._thumb_thread)
        self._thumb_thread.started.connect(self._thumb_worker.run)
        self._thumb_worker.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._thumb_thread.start()

    def _stop_thumb_thread(self) -> None:
        if self._thumb_worker is not None:
            self._thumb_worker.stop()
        if self._thumb_thread is not None:
            self._thumb_thread.quit()
            self._thumb_thread.wait(500)
        self._thumb_thread = None
        self._thumb_worker = None

    def _on_thumbnail_ready(self, project_path: str, thumb_path: str) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == project_path:
                pix = QPixmap(thumb_path)
                if not pix.isNull():
                    item.setIcon(pix)
                break

    def _show_context_menu(self, pos) -> None:
        item = self.list_widget.itemAt(pos)
        if item is None:
            return
        path_str = item.data(Qt.ItemDataRole.UserRole)
        if not path_str:
            return
        if sys.platform == "darwin":
            reveal_label = "Reveal in Finder"
        elif sys.platform == "win32":
            reveal_label = "Reveal in Explorer"
        else:
            reveal_label = "Open folder"
        menu = QMenu(self)
        open_act = menu.addAction("Open")
        reveal_act = menu.addAction(reveal_label)
        remove_act = menu.addAction("Remove from List")
        chosen = menu.exec(self.list_widget.mapToGlobal(pos))
        if chosen == open_act:
            self.list_widget.setCurrentItem(item)
            self._open_selected()
        elif chosen == reveal_act:
            folder = str(Path(path_str).parent)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        elif chosen == remove_act:
            self.list_widget.setCurrentItem(item)
            self._remove_selected()

    def _open_selected(self, *_) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        path_str = item.data(Qt.ItemDataRole.UserRole)
        if not path_str:
            return
        self.project_selected.emit(path_str)
        self.accept()

    def _remove_selected(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        path_str = item.data(Qt.ItemDataRole.UserRole)
        if not path_str:
            return
        settings = QSettings("NeuroEdit", "Desktop")
        recents: list[str] = settings.value("recentProjects", []) or []
        if path_str in recents:
            recents.remove(path_str)
        settings.setValue("recentProjects", recents)
        self._populate()

    def closeEvent(self, event) -> None:
        self._stop_thumb_thread()
        super().closeEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.project = ProjectState()
        self.store = ProjectStore.create(default_project_root())
        self.sam_backend = SamBackend()
        self.dirty = False

        # Undo/redo: snapshots of document state before each mutation.
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._history_limit = 50
        self._restoring = False  # True while applying a history snapshot
        self._media_warnings_shown: set[str] = set()
        self._media_problem_cache: dict[tuple[str, str, int, int], str | None] = {}

        if self.store.project_path.exists():
            try:
                self.store, self.project = ProjectStore.open(self.store.project_path)
            except Exception as exc:
                QMessageBox.warning(self, "Autosave restore failed", str(exc))

        self.setWindowTitle(f"NeuroEdit — {self.project.project_name}")
        self.setObjectName("mainWindow")
        # Minimum window size is computed from the real pane widths once the
        # central UI is built (see the end of _build_central_ui).
        self._build_media()
        self._build_actions()
        self._build_menubar()
        self._build_header()
        self._build_central_ui()
        self._build_statusbar()
        self._build_autosave()
        self._validate_loaded_project_media("Autosave restore")
        self._load_active_clip()
        self.refresh()
        # Seed history with initial project state.
        self._undo_stack.append(self._snapshot())
        self._update_history_actions()
        QTimer.singleShot(0, self._load_sam_backend)
        # Defer the first-run prompt until the window has actually painted.
        QTimer.singleShot(400, self._maybe_show_first_run_tutorial)

    # ── Media ──────────────────────────────────────────────────────────────

    def _build_media(self) -> None:
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.audio.setVolume(self.project.volume)
        self._timeline_playing = False
        self._last_timeline_tick = time.monotonic()
        self.timeline_clock = QTimer(self)
        self.timeline_clock.setInterval(33)
        self.timeline_clock.timeout.connect(self._tick_timeline_playback)

    # ── Actions ────────────────────────────────────────────────────────────

    def _build_actions(self) -> None:
        self.new_action = QAction("New Project", self)
        self.new_action.setShortcut("Ctrl+N")
        self.open_action = QAction("Open Project…", self)
        self.open_action.setShortcut("Ctrl+O")
        self.open_library_action = QAction("Project Library…", self)
        self.open_library_action.setShortcut("Ctrl+Shift+O")
        self.save_action = QAction("Save", self)
        self.save_action.setShortcut("Ctrl+S")
        self.save_as_action = QAction("Save Project As…", self)
        self.save_as_action.setShortcut("Ctrl+Shift+S")
        self.import_video_action = QAction("Import Video…", self)
        self.import_video_action.setShortcut("Ctrl+I")
        self.import_image_action = QAction("Import Image…", self)
        self.import_image_action.setShortcut("Ctrl+Shift+I")

        self.tutorial_action = QAction("Tutorial", self)
        self.tutorial_action.setShortcut("F1")
        self.tutorial_action.triggered.connect(self.start_tutorial)

        self.about_action = QAction("About NeuroEdit", self)
        self.about_action.triggered.connect(self._show_about)

        self.undo_action = QAction("Undo", self)
        self.undo_action.setShortcut("Ctrl+Z")
        self.undo_action.setEnabled(False)

        self.redo_action = QAction("Redo", self)
        self.redo_action.setShortcuts(["Ctrl+Shift+Z", "Ctrl+Y"])
        self.redo_action.setEnabled(False)

        self.duplicate_annotation_action = QAction("Duplicate Annotation at Playhead", self)
        self.duplicate_annotation_action.setShortcut("Ctrl+D")
        self.duplicate_annotation_action.triggered.connect(self._duplicate_selected_annotation)

        self.delete_annotation_action = QAction("Delete Annotation", self)
        self.delete_annotation_action.triggered.connect(self._delete_selected_annotation)

        self.new_action.triggered.connect(self._new_project)
        self.open_action.triggered.connect(self._open_project)
        self.open_library_action.triggered.connect(self._open_project_library)
        self.save_action.triggered.connect(self._save_project)
        self.save_as_action.triggered.connect(self._save_project_as)
        self.import_video_action.triggered.connect(self._import_video)
        self.import_image_action.triggered.connect(self._import_image)
        self.undo_action.triggered.connect(self.undo)
        self.redo_action.triggered.connect(self.redo)

    # ── Menu bar ──────────────────────────────────────────────────────────

    def _build_menubar(self) -> None:
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        file_menu.addAction(self.new_action)
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.open_library_action)
        self.recent_menu = file_menu.addMenu("Open Recent")
        file_menu.addSeparator()
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.save_as_action)
        file_menu.addSeparator()
        file_menu.addAction(self.import_video_action)
        file_menu.addAction(self.import_image_action)
        self._rebuild_recent_menu()

        edit_menu = menubar.addMenu("Edit")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.duplicate_annotation_action)
        edit_menu.addAction(self.delete_annotation_action)

        help_menu = menubar.addMenu("Help")
        help_menu.addAction(self.tutorial_action)
        help_menu.addSeparator()
        help_menu.addAction(self.about_action)

    # ── Header bar (matches web app design) ──────────────────────────────

    def _build_header(self) -> None:
        header = QWidget()
        header.setObjectName("appHeader")
        header.setFixedHeight(92)

        # Two rows so the toolbar never overflows / overlaps at higher display
        # scaling: row 1 = identity, history, project, panels, export;
        # row 2 = the annotation drawing tools.
        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(8)
        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(8)
        outer = QVBoxLayout(header)
        outer.setContentsMargins(14, 7, 14, 7)
        outer.setSpacing(7)
        outer.addLayout(row1)
        outer.addLayout(row2)
        layout = row1

        # Logo icon
        logo = QLabel()
        logo.setFixedSize(32, 32)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _icon_path = _RESOURCES / "icon_64.png"
        if _icon_path.exists():
            _pix = QPixmap(str(_icon_path)).scaled(
                32, 32,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            logo.setPixmap(_pix)
        else:
            logo.setText("⬡")
            logo.setStyleSheet(f"""
                QLabel {{
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                        stop:0 {PRIMARY}, stop:1 {ACCENT_CYAN});
                    border-radius: 8px;
                    color: white;
                    font-size: 16px;
                    font-weight: 900;
                }}
            """)
        layout.addWidget(logo)

        name_label = QLabel("NeuroEdit")
        name_label.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: 750;")
        layout.addWidget(name_label)

        layout.addWidget(self._vdivider())

        # Undo / redo
        for action, glyph, tip in [
            (self.undo_action, "↶", "Undo (Ctrl+Z)"),
            (self.redo_action, "↷", "Redo (Ctrl+Shift+Z)"),
        ]:
            btn = QPushButton(glyph)
            btn.setToolTip(tip)
            btn.setFixedSize(32, 32)
            btn.setStyleSheet(self._tool_btn_css())
            btn.clicked.connect(action.trigger)
            action.changed.connect(lambda b=btn, a=action: b.setEnabled(a.isEnabled()))
            btn.setEnabled(action.isEnabled())
            layout.addWidget(btn)

        layout.addWidget(self._vdivider())

        # Project name
        self.project_name = QLineEdit(self.project.project_name)
        self.project_name.setFixedWidth(176)
        self.project_name.setPlaceholderText("Project name")
        self.project_name.editingFinished.connect(self._project_name_changed)
        layout.addWidget(self.project_name)

        layout.addWidget(self._vdivider())

        # Video type
        self.video_type = QComboBox()
        self.video_type.setFixedWidth(140)
        for value, label in VIDEO_TYPES:
            self.video_type.addItem(label, value)
        self.video_type.currentIndexChanged.connect(self._video_type_changed)
        layout.addWidget(self.video_type)

        # Right side of row 1: panel tabs + export
        row1.addStretch(1)

        self.panel_buttons: dict[str, QPushButton] = {}
        self.panel_group = QButtonGroup(self)
        self.panel_group.setExclusive(True)
        for panel, label, color in PANELS:
            btn = QPushButton(label)
            btn.setProperty("role", "panelTab")
            btn.setCheckable(True)
            btn.setFixedHeight(32)
            btn.clicked.connect(lambda _=False, p=panel: self._set_panel(p))
            self.panel_group.addButton(btn)
            self.panel_buttons[panel] = btn
            row1.addWidget(btn)
            if panel == self.project.active_panel:
                btn.setChecked(True)

        row1.addWidget(self._vdivider())

        self.export_btn = QPushButton("Export")
        self.export_btn.setProperty("variant", "emerald")
        self.export_btn.setFixedHeight(32)
        self.export_btn.clicked.connect(self._export_project)
        row1.addWidget(self.export_btn)

        # ── Row 2: annotation drawing tools ──────────────────────────────
        layout = row2

        # Tool buttons
        self.tool_buttons: dict[str, QPushButton] = {}
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)
        for tool, char, tip in TOOLS:
            btn = QPushButton(char)
            btn.setToolTip(tip)
            btn.setFixedSize(30, 30)
            btn.setCheckable(True)
            btn.setStyleSheet(self._tool_btn_css())
            btn.clicked.connect(lambda _=False, t=tool: self._set_tool(t))
            self.tool_group.addButton(btn)
            self.tool_buttons[tool] = btn
            layout.addWidget(btn)
            if tool == self.project.active_tool:
                btn.setChecked(True)

        layout.addWidget(self._vdivider())

        # Color swatches
        self.swatch_group = QButtonGroup(self)
        self.swatch_group.setExclusive(True)
        self._swatch_buttons: dict[str, QPushButton] = {}
        for color in SWATCH_COLORS:
            btn = QPushButton()
            btn.setFixedSize(18, 18)
            btn.setToolTip(color)
            btn.setCheckable(True)
            btn.setStyleSheet(self._swatch_css(color, checked=color == self.project.draw_color))
            btn.clicked.connect(lambda _=False, c=color: self._set_color_from_swatch(c))
            self.swatch_group.addButton(btn)
            self._swatch_buttons[color] = btn
            layout.addWidget(btn)
            if color == self.project.draw_color:
                btn.setChecked(True)

        # Custom color picker
        self.color_picker_btn = QPushButton()
        self.color_picker_btn.setFixedSize(18, 18)
        self.color_picker_btn.setToolTip("Custom color…")
        self.color_picker_btn.setStyleSheet(
            f"QPushButton {{ border-radius: 9px; border: 1px solid {BORDER_BRIGHT}; background: {BG_CARD}; }}"
            f"QPushButton:hover {{ border-color: white; }}"
        )
        self.color_picker_btn.clicked.connect(self._choose_color)
        layout.addWidget(self.color_picker_btn)

        layout.addWidget(self._vdivider())

        # Stroke width slider
        self.width_slider = QSlider(Qt.Orientation.Horizontal)
        self.width_slider.setRange(1, 20)
        self.width_slider.setValue(self.project.draw_width)
        self.width_slider.setFixedWidth(80)
        self.width_slider.valueChanged.connect(self._width_changed)
        layout.addWidget(self.width_slider)

        self.width_label = QLabel(f"{self.project.draw_width}px")
        self.width_label.setFixedWidth(28)
        self.width_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.width_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        layout.addWidget(self.width_label)

        layout.addWidget(self._vdivider())

        # Label selector
        self.label_input = QComboBox()
        self.label_input.setEditable(True)
        self.label_input.setFixedWidth(176)
        self.label_input.addItem("")
        for label, _color in ANATOMY_PRESETS:
            self.label_input.addItem(label)
        for label in _load_custom_presets():
            self.label_input.addItem(label)
        self.label_input.setEditText(self.project.draw_label)
        if self.label_input.lineEdit() is not None:
            self.label_input.lineEdit().setPlaceholderText("Label…")
        self.label_input.currentTextChanged.connect(self._label_changed)
        layout.addWidget(self.label_input)

        row2.addStretch(1)

        # Install as top widget (no native toolbar). Wrap the two-row header in a
        # horizontal scroll area so a narrow window scrolls the toolbar instead of
        # clipping its right-hand controls (panel tabs / Export). The 8px scrollbar
        # (global QSS) only appears below the header's natural width and overlays
        # the header's bottom margin, so the visible height is unchanged.
        container = QWidget()
        container.setObjectName("appRoot")
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        header.setMinimumWidth(header.sizeHint().width())
        header_scroll = QScrollArea()
        header_scroll.setObjectName("headerScroll")
        header_scroll.setWidget(header)
        header_scroll.setWidgetResizable(True)
        header_scroll.setFrameShape(QFrame.Shape.NoFrame)
        header_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        header_scroll.setFixedHeight(header.maximumHeight())
        vbox.addWidget(header_scroll)
        self._header_widget = header
        self._main_container = container
        self._main_vbox = vbox
        self.setCentralWidget(container)

    def _vdivider(self) -> QWidget:
        d = QFrame()
        d.setFrameShape(QFrame.Shape.VLine)
        d.setFixedHeight(24)
        d.setStyleSheet(f"color: {BORDER}; background: {BORDER};")
        return d

    def _tool_btn_css(self) -> str:
        return (
            f"QPushButton {{ border-radius: 8px; border: none; background: transparent;"
            f"  color: {TEXT_MUTED}; font-size: 15px; }}"
            f"QPushButton:hover {{ background: {BG_HOVER}; color: {TEXT_PRIMARY}; }}"
            f"QPushButton:checked {{ background: {PRIMARY}; color: white; }}"
        )

    def _swatch_css(self, color: str, checked: bool = False) -> str:
        border = "white" if checked else "transparent"
        return (
            f"QPushButton {{ border-radius: 10px; border: 2px solid {border}; background: {color}; }}"
            f"QPushButton:checked {{ border-color: white; }}"
        )

    # ── Central UI (video + panels + timeline) ────────────────────────────

    def _build_central_ui(self) -> None:
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_splitter.setChildrenCollapsible(False)
        body_layout.addWidget(main_splitter, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Video column
        video_column = QWidget()
        video_column.setObjectName("videoColumn")
        # Keep the video preview + playback controls usable; stops the splitter or
        # a narrow window from squeezing the video pane to nothing.
        video_column.setMinimumWidth(360)
        video_column_layout = QVBoxLayout(video_column)
        video_column_layout.setContentsMargins(0, 0, 0, 0)
        video_column_layout.setSpacing(0)

        self.video_view = VideoGraphicsView(self.project)
        self.video_view.setStyleSheet("background: #000000;")
        self.player.setVideoOutput(self.video_view.video_item)
        self.video_view.sam_point_added.connect(self._add_sam_point)
        self.video_view.annotation_added.connect(self._add_annotation)
        self.video_view.selection_changed.connect(self._on_view_selection_changed)
        self.video_view.annotation_mutated.connect(self._on_annotation_mutated)
        self.video_view.edit_committed.connect(self._commit_canvas_edit)
        self.video_view.delete_selected_requested.connect(self._delete_selected_annotation)
        self.video_view.edit_label_requested.connect(self._start_inline_label_edit)
        video_column_layout.addWidget(self.video_view, 1)

        # Playback controls bar
        controls_frame = QFrame()
        controls_frame.setObjectName("controlsBar")
        controls = QHBoxLayout(controls_frame)
        controls.setContentsMargins(12, 8, 12, 8)
        controls.setSpacing(8)

        skip_back_btn = QPushButton("⏮")
        skip_back_btn.setFixedSize(32, 32)
        skip_back_btn.setToolTip("Skip to start")
        skip_back_btn.clicked.connect(lambda: self._seek_global(0))

        back_btn = QPushButton("⟨")
        back_btn.setFixedSize(32, 32)
        back_btn.setToolTip("Previous frame")
        back_btn.clicked.connect(lambda: self._step_frame(-1))

        self.play_button = QPushButton("▶")
        self.play_button.setFixedSize(38, 38)
        self.play_button.setProperty("variant", "primary")
        self.play_button.clicked.connect(self._toggle_play)

        fwd_btn = QPushButton("⟩")
        fwd_btn.setFixedSize(32, 32)
        fwd_btn.setToolTip("Next frame")
        fwd_btn.clicked.connect(lambda: self._step_frame(1))

        for b in (skip_back_btn, back_btn, fwd_btn):
            b.setStyleSheet(
                f"QPushButton {{ border-radius: 8px; border: none; background: transparent;"
                f"  color: {TEXT_MUTED}; font-size: 14px; }}"
                f"QPushButton:hover {{ background: {BG_HOVER}; color: {TEXT_PRIMARY}; }}"
            )

        controls.addWidget(skip_back_btn)
        controls.addWidget(back_btn)
        controls.addWidget(self.play_button)
        controls.addWidget(fwd_btn)

        self.time_label = QLabel("0:00.0")
        self.time_label.setProperty("role", "muted")
        controls.addWidget(self.time_label)

        self.take_still_btn = QPushButton("Take Still")
        self.take_still_btn.setProperty("variant", "cyan")
        self.take_still_btn.setToolTip("Capture the current preview and insert it as a slide.")
        self.take_still_btn.clicked.connect(self._take_still)
        controls.addWidget(self.take_still_btn)
        controls.addStretch(1)

        # Speed button
        self.speed_btn = QPushButton("1×")
        self.speed_btn.setFixedSize(42, 28)
        self.speed_btn.setToolTip("Cycle playback speed")
        self.speed_btn.setStyleSheet(
            f"QPushButton {{ border-radius: 6px; border: 1px solid {BORDER}; background: {BG_HOVER};"
            f"  color: {TEXT_SECONDARY}; font-size: 11px; font-family: monospace; }}"
            f"QPushButton:hover {{ border-color: {BORDER_BRIGHT}; color: {TEXT_PRIMARY}; }}"
        )
        self.speed_btn.clicked.connect(self._cycle_speed)
        controls.addWidget(self.speed_btn)

        video_column_layout.addWidget(controls_frame)

        # Timeline
        self.timeline = RichTimelineWidget(self.project)
        self.timeline.seek_requested.connect(self._seek_global)
        self.timeline.project_changed.connect(self._mark_project_dirty)
        self.timeline.item_activated.connect(self._timeline_item_activated)
        self.timeline.setMinimumHeight(340)

        self.media_panel = MediaExplorerPanel(self.project)
        self.media_panel.import_videos_requested.connect(self._import_video)
        self.media_panel.import_images_requested.connect(self._import_image)
        self.media_panel.file_import_requested.connect(self._import_media_file)
        self.media_panel.clip_selected.connect(self._select_media_clip)
        self.media_scroll = QScrollArea()
        self.media_scroll.setObjectName("mediaExplorerScroll")
        self.media_scroll.setWidget(self.media_panel)
        self.media_scroll.setWidgetResizable(True)
        self.media_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.media_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.media_scroll.setMinimumWidth(250)
        self.media_scroll.setMinimumHeight(0)
        splitter.addWidget(self.media_scroll)
        splitter.addWidget(video_column)

        # Right panel
        self.panels = QStackedWidget()
        self.panels.setObjectName("rightPanel")
        self.panels.setMinimumHeight(0)
        self.sam_panel = SamPanel(self.project)
        self.labels_panel = LabelsPanel(self.project)
        self.tips_panel = TipsPanel(self.project)
        self.slides_panel = SlideEditorPanel(self.project)
        self.audio_panel = AudioPanel(
            self.project,
            self.store.project_path.parent / "audio",
        )

        self.sam_panel.segment_requested.connect(self._run_segmentation)
        self.sam_panel.propagate_requested.connect(self._run_propagation)
        self.sam_panel.clear_points_requested.connect(self._clear_sam_points)
        self.sam_panel.undo_point_requested.connect(self._undo_sam_point)
        self.sam_panel.points_enabled_changed.connect(self._set_sam_points_enabled)
        self.sam_panel.mode_changed.connect(self._set_sam_mode)
        self.sam_panel.delete_weights_requested.connect(self._delete_sam_weights)
        self.labels_panel.delete_requested.connect(self._delete_annotation)
        self.labels_panel.duplicate_requested.connect(self._duplicate_annotation)
        self.labels_panel.set_start_to_playhead.connect(self._set_annotation_start_to_playhead)
        self.labels_panel.set_end_to_playhead.connect(self._set_annotation_end_to_playhead)
        self.labels_panel.seek_requested.connect(self._seek_global)
        self.labels_panel.preset_selected.connect(self._apply_label_preset)
        self.labels_panel.duration_changed.connect(self._update_annotation_duration)
        self.labels_panel.label_text_changed.connect(self._update_annotation_label)
        self.labels_panel.color_changed.connect(self._update_annotation_color)
        self.labels_panel.font_size_changed.connect(self._update_annotation_font_size)
        self.labels_panel.stroke_width_changed.connect(self._update_annotation_stroke)
        self.labels_panel.opacity_changed.connect(self._update_annotation_opacity)
        self.labels_panel.show_label_changed.connect(self._update_annotation_show_label)
        self.labels_panel.selection_changed.connect(self._on_panel_selection_changed)
        self.tips_panel.project_changed.connect(self._mark_project_metadata_dirty)
        self.slides_panel.project_changed.connect(self._mark_project_dirty)
        self.audio_panel.project_changed.connect(self._mark_project_dirty)
        self.audio_panel.seek_requested.connect(self._seek_global)

        for panel_widget in (
            self.sam_panel, self.labels_panel, self.tips_panel,
            self.slides_panel, self.audio_panel,
        ):
            self.panels.addWidget(panel_widget)

        self.panel_scroll = QScrollArea()
        self.panel_scroll.setObjectName("rightPanelScroll")
        self.panel_scroll.setWidget(self.panels)
        self.panel_scroll.setWidgetResizable(True)
        self.panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.panel_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # Never let the right pane be narrower than its widest panel's content,
        # so panels don't clip / horizontally scroll when the window is resized.
        panel_min = self.panels.minimumSizeHint().width()
        self.panel_scroll.setMinimumWidth(panel_min)
        self.panel_scroll.setMinimumHeight(0)
        splitter.addWidget(self.panel_scroll)
        # Stretch factors: media list and side panel hold their size; the
        # video column absorbs window-resize deltas. The user can drag the
        # splitter handles to repartition any of the three.
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setCollapsible(2, False)
        splitter.setSizes([260, 900, panel_min])
        splitter.setMinimumHeight(0)

        main_splitter.addWidget(splitter)
        main_splitter.addWidget(self.timeline)
        main_splitter.setSizes([500, 380])

        self._main_vbox.addWidget(body, 1)

        # Window floor that fits media + video + the side panel at their content
        # widths, so narrowing the window can never clip the panels. The header
        # scrolls above this width, so it is never the binding constraint.
        self.setMinimumSize(
            self.media_scroll.minimumWidth() + video_column.minimumWidth() + panel_min + 30,
            600,
        )

    # ── Status bar ────────────────────────────────────────────────────────

    def _build_statusbar(self) -> None:
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")

    # ── Autosave ──────────────────────────────────────────────────────────

    def _build_autosave(self) -> None:
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(2000)
        self.autosave_timer.timeout.connect(self._autosave)
        self.autosave_timer.start()

    # ── Refresh ───────────────────────────────────────────────────────────

    def refresh(self) -> None:
        self.project_name.blockSignals(True)
        self.project_name.setText(self.project.project_name)
        self.project_name.blockSignals(False)

        idx = self.video_type.findData(self.project.video_type)
        if idx >= 0:
            self.video_type.blockSignals(True)
            self.video_type.setCurrentIndex(idx)
            self.video_type.blockSignals(False)

        self.label_input.blockSignals(True)
        self.label_input.setEditText(self.project.draw_label)
        self.label_input.blockSignals(False)

        self.width_slider.blockSignals(True)
        self.width_slider.setValue(self.project.draw_width)
        self.width_slider.blockSignals(False)
        self.width_label.setText(f"{self.project.draw_width}px")

        # Tool buttons
        for btn in self.tool_group.buttons():
            tool_char = btn.text()
            tool_id = next((t for t, c, _ in TOOLS if c == tool_char), None)
            btn.setChecked(tool_id == self.project.active_tool)

        # Color swatches
        for color, btn in self._swatch_buttons.items():
            checked = color.lower() == self.project.draw_color.lower()
            btn.setChecked(checked)
            btn.setStyleSheet(self._swatch_css(color, checked=checked))

        # Panel tabs — active tab gets its accent color
        for panel, label, accent in PANELS:
            btn = self.panel_buttons[panel]
            active = panel == self.project.active_panel
            btn.setChecked(active)
            border = accent if active else "transparent"
            bg = f"rgba({QColor(accent).red()}, {QColor(accent).green()}, {QColor(accent).blue()}, 0.18)" if active else "transparent"
            weight = "700" if active else "600"
            btn.setStyleSheet(
                f"QPushButton {{ background: {bg}; border: 1px solid {border};"
                f"  color: {TEXT_PRIMARY if active else TEXT_SECONDARY};"
                f"  border-radius: 7px; font-weight: {weight}; padding: 5px 9px; }}"
                f"QPushButton:hover {{ background: {BG_HOVER}; color: {TEXT_PRIMARY};"
                f" border-color: {BORDER_BRIGHT}; }}"
            )

        # Panel stack
        for i, (panel, *_) in enumerate(PANELS):
            if panel == self.project.active_panel:
                self.panels.setCurrentIndex(i)
                break

        self.video_view.set_project(self.project)
        self.timeline.set_project(self.project)
        self.media_panel.set_project(self.project)
        self.sam_panel.set_project(self.project)
        self.labels_panel.set_project(self.project)
        self.tips_panel.set_project(self.project)
        self.slides_panel.set_project(self.project)
        self.audio_panel.set_project(
            self.project,
            self.store.project_path.parent / "audio",
        )
        self.timeline.refresh()
        self.video_view.update_annotations()
        self.time_label.setText(format_time(self.project.current_time))
        self.speed_btn.setText(f"{self.project.playback_rate:g}×")

    # ── Helpers ───────────────────────────────────────────────────────────

    def _mark_dirty(self, *, history: bool = True) -> None:
        if history and not self._restoring:
            self._push_history()
        self.dirty = True
        self.refresh()
        self._update_title()

    def _mark_project_dirty(self) -> None:
        if not self._restoring:
            self._push_history()
        self.dirty = True
        self._update_title()
        self.video_view.set_project(self.project)
        self.video_view.update_annotations()
        self.timeline.refresh()
        self.media_panel.refresh()

    def _mark_project_metadata_dirty(self) -> None:
        self.dirty = True
        self._update_title()

    # ── Undo/redo ─────────────────────────────────────────────────────────

    def _snapshot(self) -> dict:
        snapshot = self.project.to_dict()
        for key in (
            "active_panel",
            "active_tool",
            "current_time",
            "scroll_left",
            "selected_annotation_id",
            "zoom",
        ):
            snapshot.pop(key, None)
        return snapshot

    def _push_history(self) -> None:
        snapshot = self._snapshot()
        self._redo_stack.clear()
        if self._undo_stack and self._undo_stack[-1] == snapshot:
            self._update_history_actions()
            return
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > self._history_limit:
            self._undo_stack.pop(0)
        self._update_history_actions()

    def _update_history_actions(self) -> None:
        self.undo_action.setEnabled(len(self._undo_stack) > 1)
        self.redo_action.setEnabled(bool(self._redo_stack))

    def undo(self) -> None:
        if len(self._undo_stack) <= 1:
            return
        current = self._undo_stack.pop()
        self._redo_stack.append(current)
        previous = self._undo_stack[-1]
        self._apply_snapshot(previous)
        self._update_history_actions()

    def redo(self) -> None:
        if not self._redo_stack:
            return
        snapshot = self._redo_stack.pop()
        self._undo_stack.append(snapshot)
        self._apply_snapshot(snapshot)
        self._update_history_actions()

    def _apply_snapshot(self, snapshot: dict) -> None:
        self._restoring = True
        try:
            active_panel = self.project.active_panel
            active_tool = self.project.active_tool
            current_time = self.project.current_time
            scroll_left = self.project.scroll_left
            selected_annotation_id = self.project.selected_annotation_id
            zoom = self.project.zoom
            old_clip = self.project.active_clip
            old_path = old_clip.path if old_clip else None
            self.project = ProjectState.from_dict(snapshot)
            self.project.active_panel = active_panel
            self.project.active_tool = active_tool
            self.project.current_time = current_time
            self.project.scroll_left = scroll_left
            if any(ann.id == selected_annotation_id for ann in self.project.annotations):
                self.project.selected_annotation_id = selected_annotation_id
            self.project.zoom = zoom
            self.dirty = True
            new_clip = self.project.active_clip
            new_path = new_clip.path if new_clip else None
            if old_path != new_path:
                self._load_active_clip()
            self.refresh()
        finally:
            self._restoring = False

    # ── Tutorial ──────────────────────────────────────────────────────────

    def _load_tutorial_video(self) -> None:
        """Load the bundled tutorial clip when no clips are present yet."""
        if self.project.clips:
            return
        video_path = Path(__file__).parent.parent / "resources" / "tutorial_clip.mp4"
        if not video_path.exists():
            return
        clip = self._add_video_clip(video_path)
        if clip is not None:
            self._tutorial_clip_id = clip.id
            self.project.active_clip_id = clip.id
            self._load_active_clip()
            self._mark_dirty()

    def _show_about(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("About NeuroEdit")
        dlg.setFixedWidth(420)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(32, 32, 32, 24)
        layout.setSpacing(16)

        # Logo wordmark
        _wm_path = _RESOURCES / "logo_wordmark.png"
        if _wm_path.exists():
            wm_label = QLabel()
            pix = QPixmap(str(_wm_path)).scaledToWidth(
                280, Qt.TransformationMode.SmoothTransformation
            )
            wm_label.setPixmap(pix)
            wm_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(wm_label)
        else:
            title = QLabel("NeuroEdit")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {TEXT_PRIMARY};")
            layout.addWidget(title)

        version_label = QLabel("v0.2.1-alpha")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_label.setStyleSheet(f"font-size: 12px; color: {ACCENT_CYAN};")
        layout.addWidget(version_label)

        desc = QLabel(
            "Standalone desktop video editor for preparing operative video\n"
            "for conference, research, and educational use."
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet(f"font-size: 12px; color: {TEXT_SECONDARY}; line-height: 1.5;")
        layout.addWidget(desc)

        disclaimer = QLabel(
            "Not a medical device. Not FDA-cleared. Not for clinical decision-making."
        )
        disclaimer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet(
            f"font-size: 10px; color: {TEXT_MUTED}; font-style: italic;"
        )
        layout.addWidget(disclaimer)

        layout.addSpacing(8)
        btn = QPushButton("Close")
        btn.setProperty("variant", "primary")
        btn.setFixedWidth(100)
        btn.clicked.connect(dlg.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        dlg.exec()

    def start_tutorial(self) -> None:
        existing = getattr(self, "_tutorial_overlay", None)
        if existing is not None and not existing.isHidden():
            existing.close()
        self._load_tutorial_video()
        steps = build_default_steps(self)
        overlay = TutorialOverlay(self, steps)
        overlay.finished.connect(lambda: setattr(self, "_tutorial_overlay", None))
        self._tutorial_overlay = overlay

    def _maybe_show_first_run_tutorial(self) -> None:
        settings = QSettings("NeuroEdit", "Desktop")
        if settings.value("tutorial/seen", False, type=bool):
            return
        settings.setValue("tutorial/seen", True)
        reply = QMessageBox.question(
            self,
            "Welcome to NeuroEdit",
            "Would you like a quick tour of the main features? "
            "(You can also start it any time from Help → Tutorial.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.start_tutorial()

    def _autosave(self) -> None:
        if not self.dirty:
            return
        try:
            self.store.save(self.project)
            self.statusBar().showMessage(f"Autosaved {self.store.project_path}", 2500)
            self.dirty = False
            self._update_title()
        except Exception as exc:
            self.statusBar().showMessage(f"Autosave failed: {exc}", 5000)

    # ── Project actions ───────────────────────────────────────────────────

    def _new_project(self) -> None:
        if self.dirty:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "Save changes to the current project before creating a new one?",
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            if reply == QMessageBox.StandardButton.Save:
                self._save_project()
                if self.dirty:  # save was cancelled
                    return
        self.player.stop()
        self.project = ProjectState()
        self.store = ProjectStore.create(default_project_root())
        self.dirty = False
        self._load_active_clip()
        self.refresh()
        self._update_title()

    def _open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open NeuroEdit Project",
            str(Path.home() / "Documents"),
            "NeuroEdit Project (project.json)",
        )
        if not path:
            return
        try:
            self.store, self.project = ProjectStore.open(Path(path))
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return
        self._add_to_recent(Path(path))
        self._validate_loaded_project_media("Open project")
        self._load_active_clip()
        self._mark_dirty()

    def _save_project(self) -> None:
        if self.store.project_path.parent == default_project_root():
            # Still in autosave location — prompt for a real save destination
            self._save_project_as()
            return
        try:
            self.store.save(self.project)
            self.dirty = False
            self._update_title()
            self.statusBar().showMessage(f"Saved {self.store.project_path}", 3000)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))

    def _save_project_as(self) -> None:
        # Step 1: project name
        name, ok = QInputDialog.getText(
            self, "Save Project As", "Project name:",
            text=self.project.project_name,
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        # Step 2: parent folder to save into
        parent = QFileDialog.getExistingDirectory(
            self, "Choose Save Location",
            str(Path.home() / "Documents" / "NeuroEdit"),
        )
        if not parent:
            return

        # Create <parent>/<name>/ as the project folder
        project_folder = Path(parent) / name
        self.project.project_name = name
        self.store = ProjectStore.create(project_folder)
        try:
            self.store.save(self.project)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self.dirty = False
        self._update_title()
        self._add_to_recent(self.store.project_path)
        self.statusBar().showMessage(f"Saved {self.store.project_path}", 3000)
        self.project_name.blockSignals(True)
        self.project_name.setText(self.project.project_name)
        self.project_name.blockSignals(False)

    def _add_to_recent(self, project_path: Path) -> None:
        settings = QSettings("NeuroEdit", "Desktop")
        recents: list[str] = settings.value("recentProjects", []) or []
        path_str = str(project_path)
        if path_str in recents:
            recents.remove(path_str)
        recents.insert(0, path_str)
        settings.setValue("recentProjects", recents[:8])
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        self.recent_menu.clear()
        settings = QSettings("NeuroEdit", "Desktop")
        recents: list[str] = settings.value("recentProjects", []) or []
        if not recents:
            placeholder = QAction("No Recent Projects", self)
            placeholder.setEnabled(False)
            self.recent_menu.addAction(placeholder)
            return
        for path_str in recents:
            p = Path(path_str)
            label = f"{p.parent.name}" if p.name == "project.json" else p.name
            action = QAction(label, self)
            action.setToolTip(path_str)
            action.triggered.connect(lambda _=False, ps=path_str: self._open_recent_project(ps))
            self.recent_menu.addAction(action)
        self.recent_menu.addSeparator()
        clear_action = QAction("Clear Recent Projects", self)
        clear_action.triggered.connect(self._clear_recent_projects)
        self.recent_menu.addAction(clear_action)

    def _open_recent_project(self, path_str: str) -> None:
        path = Path(path_str)
        if not path.exists():
            QMessageBox.warning(self, "Not Found", f"Project not found:\n{path_str}")
            settings = QSettings("NeuroEdit", "Desktop")
            recents: list[str] = settings.value("recentProjects", []) or []
            if path_str in recents:
                recents.remove(path_str)
            settings.setValue("recentProjects", recents)
            self._rebuild_recent_menu()
            return
        try:
            self.store, self.project = ProjectStore.open(path)
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return
        self._add_to_recent(path)
        self._validate_loaded_project_media("Open recent project")
        self._load_active_clip()
        self._mark_dirty()

    def _clear_recent_projects(self) -> None:
        QSettings("NeuroEdit", "Desktop").setValue("recentProjects", [])
        self._rebuild_recent_menu()

    def _open_project_library(self) -> None:
        dialog = ProjectLibraryDialog(self)
        dialog.project_selected.connect(self._open_recent_project)
        dialog.exec()

    def _update_title(self) -> None:
        prefix = "• " if self.dirty else ""
        self.setWindowTitle(f"{prefix}NeuroEdit — {self.project.project_name}")

    def _import_video(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import Video",
            str(Path.home() / "Movies"),
            "Video Files (*.mp4 *.mov *.m4v *.avi *.webm);;All Files (*)",
        )
        if not paths:
            return
        clip = None
        for path in paths:
            clip = self._add_video_clip(Path(path))
        if clip is not None:
            self.project.active_clip_id = clip.id
        self._load_active_clip()
        self._mark_dirty()

    def _import_image(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import Image",
            str(Path.home() / "Pictures"),
            "Image Files (*.png *.jpg *.jpeg *.heic *.bmp *.webp);;All Files (*)",
        )
        if not paths:
            return
        clip = None
        for path in paths:
            clip = self._add_image_clip(Path(path))
        if clip is not None:
            self.project.active_clip_id = clip.id
        self._load_active_clip()
        self._mark_dirty()

    def _add_video_clip(self, video_path: Path):
        duration, width, height = probe_video(video_path)
        if duration <= 0:
            duration = 5.0
            self.statusBar().showMessage(
                f"Could not read duration for {video_path.name}; using a temporary 5s clip.",
                5000,
            )
        return self.project.add_clip(video_path, duration=duration, width=width, height=height)

    def _add_image_clip(self, image_path: Path):
        pix = QPixmap(str(image_path))
        if pix.isNull():
            QMessageBox.warning(self, "Import Image", f"Could not read image: {image_path.name}")
            return None
        return self.project.add_image_clip(
            image_path,
            width=pix.width() or 1920,
            height=pix.height() or 1080,
            display_duration=5.0,
        )

    def _import_media_file(self, path: str) -> None:
        media_path = Path(path)
        suffix = media_path.suffix.lower()
        if suffix in VIDEO_EXTENSIONS:
            clip = self._add_video_clip(media_path)
        elif suffix in IMAGE_EXTENSIONS:
            clip = self._add_image_clip(media_path)
        else:
            QMessageBox.information(self, "Import Media", f"Unsupported media file: {media_path.name}")
            return
        if clip is None:
            return
        self.project.active_clip_id = clip.id
        self._load_active_clip()
        self._mark_dirty()

    def _select_media_clip(self, clip_id: str) -> None:
        clip = next((candidate for candidate in self.project.clips if candidate.id == clip_id), None)
        if clip is None:
            return
        self._seek_global(clip.start_time)
        scroll_x = max(0, int(clip.start_time * self.project.zoom) - 150)
        self.timeline.scroll.horizontalScrollBar().setValue(scroll_x)

    def _timeline_item_activated(self, kind: str, item_id: str) -> None:
        if kind == "clip":
            clip = next((c for c in self.project.clips if c.id == item_id), None)
            if clip:
                self._seek_global(clip.start_time)
                scroll_x = max(0, int(clip.start_time * self.project.zoom) - 150)
                self.timeline.scroll.horizontalScrollBar().setValue(scroll_x)
        elif kind == "slide":
            slide = next((s for s in self.project.slides if s.id == item_id), None)
            if slide:
                self.project.active_panel = "slides"
                self._seek_global(slide.start_time)
                self.slides_panel.select_slide(item_id)
        elif kind == "audio":
            track = next((t for t in self.project.audio_tracks if t.id == item_id), None)
            if track:
                self.project.active_panel = "audio"
                self._seek_global(track.start_time)
                self.audio_panel.select_track(item_id)
        elif kind == "marker":
            marker = next((m for m in self.project.markers if m.id == item_id), None)
            if marker:
                self._seek_global(marker.time)

    def _take_still(self) -> None:
        duration = 5.0
        time_s = self.project.current_time
        still_path = self._render_current_still(time_s)
        if still_path is None:
            return

        self._insert_timeline_gap(time_s, duration)
        slide = Slide(
            id=new_id(),
            title=f"Still {format_time(time_s)}",
            image_path=str(still_path),
            duration=duration,
            start_time=time_s,
            background="#000000",
            text_color="#ffffff",
            font_size=20,
        )
        self.project.slides.append(slide)
        self.project.duration = project_end_time(self.project)
        self.project.active_panel = "slides"
        self._seek_global(time_s)
        self._mark_dirty()
        self.statusBar().showMessage(f"Inserted still slide at {format_time(time_s)}", 3000)

    def _render_current_still(self, time_s: float) -> Path | None:
        width, height = self._current_frame_size()
        still_dir = self.store.project_path.parent / "stills"
        still_dir.mkdir(parents=True, exist_ok=True)
        still_path = still_dir / f"still_{int(time.time() * 1000)}.png"
        snapshot = ProjectState.from_dict(self.project.to_dict())
        renderer = ProjectExporter(
            snapshot,
            ExportSettings(still_path.with_suffix(".mp4"), width, height, 1, 20, "Still"),
        )
        try:
            frame = renderer._render_frame(time_s)
            image = QImage(
                frame.data,
                width,
                height,
                int(frame.strides[0]),
                QImage.Format.Format_RGB888,
            ).copy()
            if not image.save(str(still_path)):
                QMessageBox.warning(self, "Take Still", "Could not save the still image.")
                return None
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Take Still", f"Could not capture still: {exc}")
            return None
        finally:
            renderer._release_captures()
        return still_path

    def _current_frame_size(self) -> tuple[int, int]:
        clip = self._clip_at_time(self.project.current_time) or self.project.active_clip
        if clip is not None:
            return max(1, clip.width or 1920), max(1, clip.height or 1080)
        return 1920, 1080

    def _insert_timeline_gap(self, time_s: float, duration: float) -> None:
        clips = list(self.project.clips)
        for clip in clips:
            start = clip.start_time
            end = start + clip.display_duration
            if start < time_s < end:
                self._split_clip_for_gap(clip, time_s, duration)
            elif start >= time_s:
                clip.start_time += duration

        for slide in self.project.slides:
            if slide.start_time >= time_s:
                slide.start_time += duration
        for track in self.project.audio_tracks:
            if track.start_time >= time_s:
                track.start_time += duration
        for marker in self.project.markers:
            if marker.time >= time_s:
                marker.time += duration
        for ann in self.project.annotations:
            if ann.frame_time >= time_s:
                ann.frame_time += duration
            elif ann.is_visible_at(time_s):
                # Cap annotation so it doesn't bleed through the inserted gap
                ann.ann_duration = time_s - ann.frame_time
        self.project.arrange_clips_without_overlap()

    def _split_clip_for_gap(self, clip: VideoClip, time_s: float, gap_duration: float) -> None:
        left_duration = time_s - clip.start_time
        split_trim = clip.trim_start + left_duration
        right_duration = clip.trim_end - split_trim
        if left_duration < 0.05:
            clip.start_time += gap_duration
            return
        if right_duration < 0.05:
            return

        original_trim_end = clip.trim_end
        clip.trim_end = split_trim
        right = VideoClip(
            id=new_id(),
            path=clip.path,
            name=f"{clip.name} (after still)",
            duration=clip.duration,
            start_time=time_s + gap_duration,
            trim_start=split_trim,
            trim_end=original_trim_end,
            width=clip.width,
            height=clip.height,
            thumbnail_path=clip.thumbnail_path,
            media_type=clip.media_type,
            fade_in=clip.fade_in,
            fade_out=clip.fade_out,
            fade_color=clip.fade_color,
        )
        idx = self.project.clips.index(clip)
        self.project.clips.insert(idx + 1, right)

    def _export_project(self) -> None:
        self.project.duration = project_end_time(self.project)
        if self.project.duration <= 0 or (not self.project.clips and not self.project.slides):
            QMessageBox.information(self, "Export", "Add at least one clip or slide before exporting.")
            return

        preflight_warnings = project_preflight_warnings(self.project)
        if preflight_warnings:
            message = (
                "NeuroEdit found operative-video preflight issues:\n\n"
                + "\n".join(f"- {warning}" for warning in preflight_warnings[:10])
            )
            if len(preflight_warnings) > 10:
                message += f"\n- ...and {len(preflight_warnings) - 10} more"
            message += "\n\nContinue export anyway?"
            reply = QMessageBox.question(
                self,
                "Export Preflight",
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                self.project.active_panel = "tips"
                self.refresh()
                return

        dialog = ExportDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        default_name = self._safe_export_name(self.project.project_name)
        default_path = Path.home() / "Movies" / f"{default_name}.mp4"
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save MP4 Export",
            str(default_path),
            "MP4 Video (*.mp4)",
        )
        if not path_str:
            return
        output_path = Path(path_str)
        if output_path.suffix.lower() != ".mp4":
            output_path = output_path.with_suffix(".mp4")
        settings = dialog.export_settings(output_path)
        if not settings.mute_source_audio and any(
            clip.media_type == "video" for clip in self.project.clips
        ):
            reply = QMessageBox.warning(
                self,
                "Keep original audio?",
                "You chose to keep the original clip audio. Operating-room audio can "
                "contain spoken patient identifiers (name, MRN, date of birth).\n\n"
                "The Redact tool only covers on-screen PHI — it does not remove audio.\n\n"
                "Export with the original audio anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._start_export(settings)

    def _safe_export_name(self, value: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_", " ") else "_" for ch in value)
        safe = "_".join(safe.strip().split())
        return safe or "NeuroEdit_Export"

    def _start_export(self, settings: ExportSettings) -> None:
        if getattr(self, "_export_thread", None) is not None:
            QMessageBox.information(self, "Export", "An export is already running.")
            return
        project_snapshot = ProjectState.from_dict(self.project.to_dict())
        self._export_report_project = project_snapshot
        progress = QProgressDialog("Preparing export...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Exporting MP4")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        thread = QThread(self)
        worker = ExportWorker(project_snapshot, settings)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._export_progress)
        worker.finished.connect(self._export_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: setattr(self, "_export_thread", None))
        progress.canceled.connect(worker.cancel)

        self._export_progress_dialog = progress
        self._export_thread = thread
        self._export_worker = worker
        self.statusBar().showMessage("Export started...")
        thread.start()

    def _export_progress(self, value: int, message: str) -> None:
        progress = getattr(self, "_export_progress_dialog", None)
        if progress is not None:
            progress.setLabelText(message)
            progress.setValue(max(0, min(100, int(value))))
        self.statusBar().showMessage(message)

    def _export_finished(self, output_path, error, warnings) -> None:
        progress = getattr(self, "_export_progress_dialog", None)
        if progress is not None:
            progress.close()
        self._export_progress_dialog = None
        self._export_worker = None

        if error:
            if str(error) == "Export canceled.":
                self.statusBar().showMessage("Export canceled.", 3000)
                return
            QMessageBox.critical(self, "Export failed", str(error))
            self.statusBar().showMessage("Export failed.", 5000)
            return

        warning_text = ""
        if warnings:
            warning_text = "\n\nNotes:\n" + "\n".join(f"- {warning}" for warning in warnings)
        report_path = self._write_export_report(Path(output_path), warnings)
        if report_path is not None:
            warning_text += f"\n\nExport report:\n{report_path}"
        QMessageBox.information(
            self,
            "Export complete",
            f"Saved MP4 export:\n{output_path}{warning_text}",
        )
        self.statusBar().showMessage(f"Exported {output_path}", 5000)

    def _write_export_report(self, output_path: Path, export_warnings: list[str]) -> Path | None:
        project = getattr(self, "_export_report_project", None)
        if project is None:
            return None
        report_path = output_path.with_suffix(".export-report.txt")
        preflight = project_preflight_warnings(project)
        lines = [
            f"NeuroEdit Export Report: {project.project_name}",
            f"Video goal: {project.video_goal}",
            f"Audience: {project.intended_audience or 'Not specified'}",
            f"Timeline duration: {format_time(project.duration)}",
            "",
            "Storyboard",
            f"Objective: {project.storyboard_objective or 'Not specified'}",
            f"Case context: {project.storyboard_case_context or 'Not specified'}",
            f"Key anatomy: {project.storyboard_key_anatomy or 'Not specified'}",
            f"Operative steps: {project.storyboard_steps or 'Not specified'}",
            f"Decision points: {project.storyboard_decision_points or 'Not specified'}",
            f"Pearl/pitfall: {project.storyboard_teaching_pearl or 'Not specified'}",
            f"Final point: {project.storyboard_final_point or 'Not specified'}",
            "",
            "Privacy / distribution",
            f"Consent/authorization confirmed: {project.consent_confirmed}",
            f"Staff notice/consent addressed: {project.staff_notice_confirmed}",
            f"De-identified: {project.deidentified_confirmed}",
            f"PHI review completed: {project.phi_review_confirmed}",
            f"Edit disclosure: {project.edit_disclosure or 'Not specified'}",
            "",
            "Timeline counts",
            f"Video/image clips: {len(project.clips)}",
            f"Audio tracks: {len(project.audio_tracks)}",
            f"Slides/stills: {len(project.slides)}",
            f"Markers: {len(project.markers)}",
            f"Annotations: {len(project.annotations)}",
            "",
            "Preflight issues at export",
        ]
        lines.extend(f"- {warning}" for warning in preflight or ["None"])
        if export_warnings:
            lines.append("")
            lines.append("Renderer warnings")
            lines.extend(f"- {warning}" for warning in export_warnings)
        try:
            report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            return None
        return report_path

    def _clip_media_problem(self, clip: VideoClip) -> str | None:
        path = Path(clip.path)
        if not path.exists():
            return "file is missing"
        if clip.media_type == "image":
            if QPixmap(str(path)).isNull():
                return "image could not be read"
            return None
        duration, width, height = probe_video(path)
        if duration <= 0 or width <= 0 or height <= 0:
            return "video could not be read"
        return None

    def _cached_clip_media_problem(self, clip: VideoClip) -> str | None:
        path = Path(clip.path)
        try:
            stat = path.stat()
            key = (clip.id, clip.path, stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            key = (clip.id, clip.path, -1, -1)
        if key not in self._media_problem_cache:
            self._media_problem_cache[key] = self._clip_media_problem(clip)
        return self._media_problem_cache[key]

    def _validate_loaded_project_media(self, context: str) -> None:
        problems: list[tuple[VideoClip, str]] = []
        for clip in self.project.clips:
            problem = self._cached_clip_media_problem(clip)
            if problem is not None:
                problems.append((clip, problem))

        bad_ids = {clip.id for clip, _problem in problems}
        if self.project.active_clip_id in bad_ids:
            replacement = next((clip for clip in self.project.clips if clip.id not in bad_ids), None)
            self.project.active_clip_id = replacement.id if replacement else None

        if not problems:
            return

        key = f"{self.store.project_path}:{','.join(sorted(bad_ids))}"
        if key in self._media_warnings_shown:
            return
        self._media_warnings_shown.add(key)

        lines = [f"{clip.name}: {problem}" for clip, problem in problems[:8]]
        extra = len(problems) - len(lines)
        if extra > 0:
            lines.append(f"...and {extra} more")
        QMessageBox.warning(
            self,
            "Media unavailable",
            f"{context} found media that cannot be loaded.\n\n"
            + "\n".join(lines)
            + "\n\nThose clips remain in the project, but NeuroEdit will skip loading them until the files are restored or re-imported.",
        )
        self.statusBar().showMessage(f"{len(problems)} media item(s) unavailable", 6000)

    def _load_active_clip(self) -> None:
        clip = self.project.active_clip
        if not clip:
            self.player.stop()
            self.video_view.set_image(None)
            return
        problem = self._cached_clip_media_problem(clip)
        if problem is not None:
            self.player.stop()
            self.player.setSource(QUrl())
            self.video_view.set_image(None)
            self.statusBar().showMessage(f"Cannot load {clip.name}: {problem}", 6000)
            return
        if clip.media_type == "image":
            # Image clips bypass the media player entirely.
            self.player.stop()
            self.player.setSource(QUrl())
            self.video_view.set_image(clip.path)
        else:
            self.video_view.set_image(None)
            self.player.setSource(QUrl.fromLocalFile(clip.path))
            self.player.setPlaybackRate(self.project.playback_rate)
            self.audio.setMuted(self.project.is_muted)
            self.audio.setVolume(self.project.volume)
        self._seek_global(self.project.current_time)

    def _clip_at_time(self, time_s: float):
        for clip in self.project.clips:
            start = clip.start_time
            end = clip.start_time + clip.display_duration
            if start <= time_s <= end:
                return clip
        return None

    def _slide_at_time(self, time_s: float):
        for slide in reversed(self.project.slides):
            if slide.start_time <= time_s <= slide.start_time + slide.duration:
                return slide
        return None

    # ── Settings changes ──────────────────────────────────────────────────

    def _project_name_changed(self) -> None:
        self.project.project_name = self.project_name.text().strip() or "Untitled Case"
        self._mark_dirty()

    def _video_type_changed(self) -> None:
        self.project.video_type = self.video_type.currentData()
        self._mark_dirty()

    def _set_tool(self, tool: str) -> None:
        self.project.active_tool = tool
        self._mark_dirty(history=False)

    def _set_panel(self, panel: PanelType) -> None:
        self.project.active_panel = panel
        self._mark_dirty(history=False)

    def _set_color_from_swatch(self, color: str) -> None:
        self.project.draw_color = color
        self._mark_dirty()

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.project.draw_color), self, "Annotation Color")
        if color.isValid():
            self.project.draw_color = color.name()
            self._mark_dirty()

    def _label_changed(self, value: str) -> None:
        self.project.draw_label = value
        preset_color = next((color for label, color in ANATOMY_PRESETS if label == value), None)
        if preset_color is not None:
            self.project.draw_color = preset_color
            self.project.active_tool = "arrow"
        self._mark_dirty()

    def _apply_label_preset(self, label: str, color: str) -> None:
        self.project.draw_label = label
        self.project.draw_color = color
        self.project.active_tool = "arrow"
        self.project.active_panel = "labels"
        self._mark_dirty()

    def _width_changed(self, value: int) -> None:
        self.project.draw_width = value
        self.width_label.setText(f"{value}px")
        self._mark_dirty()

    # ── Playback ──────────────────────────────────────────────────────────

    _SPEEDS = [0.25, 0.5, 1.0, 1.5, 2.0, 4.0]

    def _toggle_play(self) -> None:
        if self._timeline_playing or self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._timeline_playing = False
            self.timeline_clock.stop()
            self.player.pause()
            self.play_button.setText("▶")
        else:
            self._timeline_playing = True
            self._last_timeline_tick = time.monotonic()
            self.timeline_clock.start()
            self._sync_player_to_timeline(play=True)
            self.play_button.setText("⏸")

    def _cycle_speed(self) -> None:
        current = self.project.playback_rate
        speeds = self._SPEEDS
        try:
            idx = speeds.index(current)
        except ValueError:
            idx = 2
        self.project.playback_rate = speeds[(idx + 1) % len(speeds)]
        self.player.setPlaybackRate(self.project.playback_rate)
        self._mark_dirty()

    def _step_frame(self, direction: int) -> None:
        self._seek_global(self.project.current_time + direction / 30)

    def _seek_global(self, time_s: float) -> None:
        self.project.duration = project_end_time(self.project)
        time_s = max(0.0, min(time_s, self.project.duration))
        self.project.current_time = time_s
        self._sync_player_to_timeline(play=self._timeline_playing)
        self.timeline.refresh()
        self.video_view.update_annotations()
        self.time_label.setText(format_time(self.project.current_time))

    def _position_changed(self, position_ms: int) -> None:
        clip = self.project.active_clip
        if not clip:
            return
        self.project.current_time = clip.start_time + position_ms / 1000 - clip.trim_start
        if self._slide_at_time(self.project.current_time) is not None:
            self.player.pause()
            self._last_timeline_tick = time.monotonic()
        if self.project.current_time > clip.start_time + clip.display_duration:
            self.player.pause()
            self._last_timeline_tick = time.monotonic()
        self.timeline.refresh()
        self.video_view.update_annotations()
        self.time_label.setText(format_time(self.project.current_time))

    def _tick_timeline_playback(self) -> None:
        if not self._timeline_playing:
            return
        now = time.monotonic()
        elapsed = now - self._last_timeline_tick
        self._last_timeline_tick = now

        active = self._clip_at_time(self.project.current_time)
        on_image = active is not None and active.media_type == "image"

        if (
            self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            and self._slide_at_time(self.project.current_time) is None
            and not on_image
        ):
            return

        self.project.duration = project_end_time(self.project)
        next_time = self.project.current_time + elapsed * self.project.playback_rate
        if next_time >= self.project.duration:
            self.project.current_time = self.project.duration
            self._timeline_playing = False
            self.timeline_clock.stop()
            self.player.pause()
            self.play_button.setText("▶")
        else:
            self.project.current_time = next_time
            self._sync_player_to_timeline(play=True)
        self.timeline.refresh()
        self.video_view.update_annotations()
        self.time_label.setText(format_time(self.project.current_time))

    def _sync_player_to_timeline(self, *, play: bool) -> None:
        slide = self._slide_at_time(self.project.current_time)
        clip = self._clip_at_time(self.project.current_time)
        if slide is not None or clip is None:
            self.player.pause()
            self.video_view.update_annotations()
            return

        problem = self._cached_clip_media_problem(clip)
        if problem is not None:
            self.player.pause()
            self.player.setSource(QUrl())
            self.video_view.set_image(None)
            self.video_view.update_annotations()
            self.statusBar().showMessage(f"Cannot load {clip.name}: {problem}", 6000)
            return

        clip_changed = self.project.active_clip_id != clip.id
        if clip_changed:
            self.project.active_clip_id = clip.id

        if clip.media_type == "image":
            # Switch the view to the image; never feed it to QMediaPlayer.
            if clip_changed or not self.video_view.image_item.isVisible():
                self.player.stop()
                self.player.setSource(QUrl())
                self.video_view.set_image(clip.path)
            self.video_view.update_annotations()
            return

        if clip_changed or not self.video_view.video_item.isVisible():
            self.video_view.set_image(None)
            self.player.setSource(QUrl.fromLocalFile(clip.path))
            self.player.setPlaybackRate(self.project.playback_rate)

        local_s = clip.trim_start + max(0.0, self.project.current_time - clip.start_time)
        target_ms = int(local_s * 1000)
        if abs(self.player.position() - target_ms) > 80:
            self.player.setPosition(target_ms)
        if play:
            self.player.play()

    def _duration_changed(self, duration_ms: int) -> None:
        clip = self.project.active_clip
        if not clip:
            return
        duration_s = duration_ms / 1000
        if duration_s > 0:
            old_duration = clip.duration
            clip.duration = duration_s
            if clip.trim_end <= 0 or abs(clip.trim_end - old_duration) < 0.05 or clip.trim_end > duration_s:
                clip.trim_end = duration_s
                self.project.arrange_clips_without_overlap(clip.id)
            self.project.duration = max(self.project.duration, clip.start_time + clip.display_duration)
            self._mark_dirty()

    # ── SAM / annotations ─────────────────────────────────────────────────

    def _add_sam_point(self, x: float, y: float) -> None:
        if not self.project.sam_points_enabled:
            self.sam_panel.set_status("Point placement is off. Enable it before adding SAM points.")
            return
        self.project.sam_points.append(SamPoint(x=x, y=y, type=self.project.sam_mode))
        self._mark_dirty()

    def _add_annotation(self, annotation: Annotation) -> None:
        self.project.annotations.append(annotation)
        self.project.selected_annotation_id = annotation.id
        self.project.active_panel = "labels"
        self._set_panel("labels")
        self._mark_dirty()

    def _delete_annotation(self, annotation_id: str) -> None:
        self.project.annotations = [
            ann for ann in self.project.annotations if ann.id != annotation_id
        ]
        if self.project.selected_annotation_id == annotation_id:
            self.project.selected_annotation_id = None
        self._mark_dirty()

    def _update_annotation_duration(self, annotation_id: str, duration: float) -> None:
        for ann in self.project.annotations:
            if ann.id == annotation_id:
                ann.ann_duration = max(0.0, duration)
                break
        self._mark_dirty()

    def _find_annotation(self, annotation_id: str) -> Annotation | None:
        return next((a for a in self.project.annotations if a.id == annotation_id), None)

    def _update_annotation_label(self, annotation_id: str, text: str) -> None:
        ann = self._find_annotation(annotation_id)
        if ann is not None:
            ann.label = text
            self._mark_dirty()

    def _update_annotation_color(self, annotation_id: str, color: str) -> None:
        ann = self._find_annotation(annotation_id)
        if ann is not None:
            ann.color = color
            self._mark_dirty()

    def _update_annotation_font_size(self, annotation_id: str, size: int) -> None:
        ann = self._find_annotation(annotation_id)
        if ann is not None:
            ann.font_size = max(8, int(size))
            self._mark_dirty()

    def _update_annotation_stroke(self, annotation_id: str, width: int) -> None:
        ann = self._find_annotation(annotation_id)
        if ann is not None:
            ann.geometry["width_px"] = float(max(1, int(width)))
            self._mark_dirty()

    def _update_annotation_opacity(self, annotation_id: str, opacity: float) -> None:
        ann = self._find_annotation(annotation_id)
        if ann is not None:
            ann.opacity = max(0.05, min(1.0, float(opacity)))
            self._mark_dirty()

    def _update_annotation_show_label(self, annotation_id: str, show: bool) -> None:
        ann = self._find_annotation(annotation_id)
        if ann is not None and ann.type in {"rect", "ellipse", "arrow"}:
            ann.show_label = bool(show)
            self._mark_dirty()

    def _delete_selected_annotation(self) -> None:
        ann_id = self.project.selected_annotation_id
        if ann_id:
            self.project.selected_annotation_id = None
            self._delete_annotation(ann_id)

    def _duplicate_annotation(self, annotation_id: str) -> None:
        ann = self._find_annotation(annotation_id)
        if ann is None:
            return
        new_ann = copy.deepcopy(ann)
        new_ann.id = new_id()
        new_ann.frame_time = self.project.current_time
        self.project.annotations.append(new_ann)
        self.project.selected_annotation_id = new_ann.id
        self._mark_dirty()

    def _duplicate_selected_annotation(self) -> None:
        fw = QApplication.focusWidget()
        if isinstance(fw, (QLineEdit, QTextEdit)):
            return
        ann_id = self.project.selected_annotation_id
        if ann_id:
            self._duplicate_annotation(ann_id)

    def _set_annotation_start_to_playhead(self, annotation_id: str) -> None:
        ann = self._find_annotation(annotation_id)
        if ann is None:
            return
        ann.frame_time = self.project.current_time
        self._mark_dirty()

    def _set_annotation_end_to_playhead(self, annotation_id: str) -> None:
        ann = self._find_annotation(annotation_id)
        if ann is None:
            return
        new_duration = self.project.current_time - ann.frame_time
        ann.ann_duration = max(0.1, new_duration)
        self._mark_dirty()

    def _on_view_selection_changed(self, ann_id) -> None:
        self.project.selected_annotation_id = ann_id if isinstance(ann_id, str) else None
        self.labels_panel.set_selected_annotation(self.project.selected_annotation_id)
        self._mark_dirty(history=False)
        self.video_view.update_annotations()

    def _on_panel_selection_changed(self, ann_id) -> None:
        new_id = ann_id if isinstance(ann_id, str) else None
        if new_id == self.project.selected_annotation_id:
            return
        self.project.selected_annotation_id = new_id
        self._mark_dirty(history=False)
        self.video_view.update_annotations()

    def _on_annotation_mutated(self) -> None:
        self.dirty = True
        self.labels_panel.refresh()
        self.timeline.refresh()

    def _commit_canvas_edit(self) -> None:
        # A move/resize drag on the canvas just finished. The in-progress drag
        # only marked the project dirty; push a single undo snapshot now so the
        # whole gesture is one undoable step.
        self._mark_dirty()

    def _start_inline_label_edit(self, annotation_id: str) -> None:
        ann = self._find_annotation(annotation_id)
        if ann is None:
            return
        self.project.active_panel = "labels"
        self._mark_dirty(history=False)
        self.labels_panel.set_selected_annotation(annotation_id)
        self.labels_panel.label_edit.setFocus()
        self.labels_panel.label_edit.selectAll()

    def _clear_sam_points(self) -> None:
        self.project.sam_points.clear()
        self._mark_dirty()

    def _undo_sam_point(self) -> None:
        if self.project.sam_points:
            self.project.sam_points.pop()
            self._mark_dirty()

    def _set_sam_points_enabled(self, enabled: bool) -> None:
        self.project.sam_points_enabled = enabled
        self._mark_dirty()

    def _start_sam_heartbeat(self, stage: str) -> None:
        import time
        self._sam_stage = stage
        self._sam_stage_start = time.monotonic()
        self.sam_panel.set_status(f"{stage} (0s)")
        if not hasattr(self, "_sam_heartbeat_timer"):
            self._sam_heartbeat_timer = QTimer(self)
            self._sam_heartbeat_timer.setInterval(500)
            self._sam_heartbeat_timer.timeout.connect(self._tick_sam_heartbeat)
        self._sam_heartbeat_timer.start()

    def _tick_sam_heartbeat(self) -> None:
        import time
        elapsed = int(time.monotonic() - self._sam_stage_start)
        self.sam_panel.set_status(f"{self._sam_stage} ({elapsed}s)")

    def _stop_sam_heartbeat(self) -> None:
        if hasattr(self, "_sam_heartbeat_timer"):
            self._sam_heartbeat_timer.stop()

    def _set_sam_mode(self, mode: str) -> None:
        if mode not in ("positive", "negative"):
            return
        self.project.sam_mode = mode  # type: ignore[assignment]
        self._mark_dirty()

    def _load_sam_backend(self) -> None:
        # Guard against double-calls while a probe is already in flight
        if getattr(self, "_sam_probe_thread", None) is not None:
            return
        self.sam_panel.set_status("Loading SAM backend… (importing PyTorch)")
        self.sam_panel.set_busy(True)
        self.statusBar().showMessage("Loading SAM backend…")

        self._sam_probe_thread = QThread(self)
        self._sam_probe_worker = SamProbeWorker(self.sam_backend)
        self._sam_probe_worker.moveToThread(self._sam_probe_thread)
        self._sam_probe_thread.started.connect(self._sam_probe_worker.run)
        self._sam_probe_worker.progress.connect(self._on_sam_probe_progress)
        self._sam_probe_worker.finished.connect(self._on_sam_probe_finished)
        self._sam_probe_worker.finished.connect(self._sam_probe_thread.quit)
        self._sam_probe_thread.finished.connect(self._sam_probe_worker.deleteLater)
        self._sam_probe_thread.finished.connect(self._sam_probe_thread.deleteLater)
        self._sam_probe_thread.start()

    def _on_sam_probe_progress(self, message: str) -> None:
        self._start_sam_heartbeat(message)
        self.statusBar().showMessage(f"SAM: {message}")

    def _on_sam_probe_finished(self, info) -> None:  # type: ignore[no-untyped-def]
        self._stop_sam_heartbeat()
        self._sam_probe_thread = None
        self._sam_probe_worker = None
        cached = self.sam_backend.is_weights_cached()
        self.sam_panel.set_weights_cached(cached)
        if info.status == "ready" and not cached:
            self.sam_panel.set_status("SAM3 weights not downloaded yet.")
            self.sam_panel.set_busy(False)
            self.statusBar().showMessage("SAM3 weights not downloaded", 4000)
            self._show_sam_setup()
            return
        label = {
            "ready": info.message or f"SAM ready ({info.device})",
            "unsupported": f"SAM on CPU — {info.message}",
            "missing": f"SAM unavailable — {info.message}",
        }.get(info.status, info.message)
        self.sam_panel.set_status(label)
        self.sam_panel.set_busy(False)
        self.statusBar().showMessage(f"SAM backend: {info.status}", 4000)

    def _show_sam_setup(self) -> None:
        dlg = SamSetupDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.sam_panel.set_status("SAM3 setup cancelled. Reopen the SAM panel to try again.")
            return
        self._start_sam_download(dlg.token())

    def _start_sam_download(self, token: str) -> None:
        self.sam_panel.set_status("Downloading SAM3 weights…")
        self.sam_panel.set_busy(True)
        self.statusBar().showMessage("SAM3: downloading weights…")
        self._sam_download_thread = QThread(self)
        self._sam_download_worker = SamDownloadWorker(self.sam_backend, token)
        self._sam_download_worker.moveToThread(self._sam_download_thread)
        self._sam_download_thread.started.connect(self._sam_download_worker.run)
        self._sam_download_worker.progress.connect(self._on_sam_probe_progress)
        self._sam_download_worker.finished.connect(self._on_sam_download_finished)
        self._sam_download_worker.finished.connect(self._sam_download_thread.quit)
        self._sam_download_thread.finished.connect(self._sam_download_worker.deleteLater)
        self._sam_download_thread.finished.connect(self._sam_download_thread.deleteLater)
        self._sam_download_thread.start()

    def _on_sam_download_finished(self, info) -> None:  # type: ignore[no-untyped-def]
        self._stop_sam_heartbeat()
        self._sam_download_thread = None
        self._sam_download_worker = None
        cached = self.sam_backend.is_weights_cached()
        self.sam_panel.set_weights_cached(cached)
        if info.status == "ready":
            self.sam_panel.set_status(info.message or f"SAM3 ready ({info.device})")
            self.statusBar().showMessage("SAM3 ready", 4000)
        else:
            self.sam_panel.set_status(f"Download failed: {info.message}")
            self.statusBar().showMessage("SAM3 download failed", 5000)
        self.sam_panel.set_busy(False)

    def _delete_sam_weights(self) -> None:
        import shutil
        cache = Path.home() / ".cache" / "huggingface" / "hub" / "models--facebook--sam3"
        reply = QMessageBox.question(
            self,
            "Delete SAM3 weights?",
            "This will permanently delete ~3.2 GB of cached SAM3 model weights.\n\n"
            "SAM3 features will stop working until you re-download them.\n\n"
            "Delete the weights?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            shutil.rmtree(cache, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Delete failed", str(exc))
            return
        self.sam_panel.set_weights_cached(False)
        self.sam_panel.set_status("SAM3 weights deleted. Re-open the SAM panel to set up again.")
        self.statusBar().showMessage("SAM3 weights deleted", 4000)

    def _run_segmentation(self) -> None:
        clip = self.project.active_clip
        if not clip:
            QMessageBox.information(self, "No video", "Import a video before running SAM.")
            return
        if not self.project.sam_points:
            QMessageBox.information(
                self, "No prompt points",
                "Place at least one SAM point on the video before running segmentation.",
            )
            return
        if getattr(self, "_sam_segment_thread", None) is not None:
            return

        self.sam_panel.set_status("Running SAM segmentation…")
        self.sam_panel.set_busy(True)
        self.statusBar().showMessage("SAM: running segmentation…")

        mask_dir = self.store.project_path.parent / "masks"
        self._sam_segment_thread = QThread(self)
        self._sam_segment_worker = SamSegmentWorker(
            self.sam_backend,
            Path(clip.path),
            self.project.current_time,
            list(self.project.sam_points),
            mask_dir,
        )
        self._sam_segment_worker.moveToThread(self._sam_segment_thread)
        self._sam_segment_thread.started.connect(self._sam_segment_worker.run)
        self._sam_segment_worker.progress.connect(self._on_segment_progress)
        self._sam_segment_worker.finished.connect(self._on_segment_finished)
        self._sam_segment_worker.finished.connect(self._sam_segment_thread.quit)
        self._sam_segment_thread.finished.connect(self._sam_segment_worker.deleteLater)
        self._sam_segment_thread.finished.connect(self._sam_segment_thread.deleteLater)
        self._sam_segment_thread.start()

    def _on_segment_progress(self, message: str) -> None:
        self._start_sam_heartbeat(message)
        self.statusBar().showMessage(f"SAM: {message}")

    def _on_segment_finished(self, result, error) -> None:  # type: ignore[no-untyped-def]
        self._stop_sam_heartbeat()
        self._sam_segment_thread = None
        self._sam_segment_worker = None
        self.sam_panel.set_busy(False)
        if error:
            self.sam_panel.set_status(f"Segmentation failed: {error}")
            self.statusBar().showMessage("SAM: segmentation failed", 5000)
            QMessageBox.critical(self, "SAM segmentation failed", str(error))
            return
        if result is None:
            return
        annotation = Annotation(
            id=new_id(),
            frame_time=self.project.current_time,
            ann_duration=0.0,
            type="mask",
            label=self.project.draw_label or "SAM mask",
            color=self.project.draw_color,
            visible=True,
            opacity=0.55,
            geometry={},
            mask_path=str(result.mask_path),
            score=float(result.score),
        )
        self.project.annotations.append(annotation)
        self.video_view.annotation_item.invalidate_mask_cache()
        self.sam_panel.set_status(f"{result.backend} mask saved (score {result.score:.2f})")
        self.statusBar().showMessage(
            f"SAM: {result.backend} mask saved (score {result.score:.2f})",
            4000,
        )
        self._mark_dirty()

    def _run_propagation(self) -> None:
        clip = self.project.active_clip
        if not clip:
            QMessageBox.information(self, "No video", "Import a video before running propagation.")
            return
        if not self.project.sam_points:
            QMessageBox.information(
                self, "No prompt points",
                "Place at least one SAM point on the video before running propagation.",
            )
            return
        if getattr(self, "_sam_propagation_thread", None) is not None:
            return

        self.sam_panel.set_status("Running video propagation…")
        self.sam_panel.set_busy(True)
        self.statusBar().showMessage("SAM: running video propagation…")

        mask_dir = self.store.project_path.parent / "masks"
        self._sam_propagation_thread = QThread(self)
        self._sam_propagation_worker = SamPropagationWorker(
            self.sam_backend,
            Path(clip.path),
            self.project.current_time,
            duration_s=5.0,
            points=list(self.project.sam_points),
            mask_dir=mask_dir,
            sample_rate=2.0,
        )
        self._sam_propagation_worker.moveToThread(self._sam_propagation_thread)
        self._sam_propagation_thread.started.connect(self._sam_propagation_worker.run)
        self._sam_propagation_worker.progress.connect(self._on_propagation_progress)
        self._sam_propagation_worker.finished.connect(self._on_propagation_finished)
        self._sam_propagation_worker.finished.connect(self._sam_propagation_thread.quit)
        self._sam_propagation_thread.finished.connect(self._sam_propagation_worker.deleteLater)
        self._sam_propagation_thread.finished.connect(self._sam_propagation_thread.deleteLater)
        self._sam_propagation_thread.start()

    def _on_propagation_progress(self, message: str) -> None:
        self._start_sam_heartbeat(message)
        self.statusBar().showMessage(f"SAM: {message}")

    def _on_propagation_finished(self, result, error) -> None:  # type: ignore[no-untyped-def]
        self._stop_sam_heartbeat()
        self._sam_propagation_thread = None
        self._sam_propagation_worker = None
        self.sam_panel.set_busy(False)

        if error:
            self.sam_panel.set_status(f"Propagation failed: {error}")
            self.statusBar().showMessage("SAM: propagation failed", 5000)
            QMessageBox.critical(self, "SAM propagation failed", str(error))
            return
        if result is None or not result.mask_frames:
            return

        first_time = float(result.mask_frames[0]["time"])
        last_time = float(result.mask_frames[-1]["time"])
        frame_step = 1.0 / result.sample_rate
        ann_duration = max(frame_step, last_time - first_time + frame_step)
        annotation = Annotation(
            id=new_id(),
            frame_time=first_time,
            ann_duration=ann_duration,
            type="tracked-mask",
            label=self.project.draw_label or "SAM propagation",
            color=self.project.draw_color,
            visible=True,
            opacity=0.55,
            geometry={},
            mask_path=str(result.mask_frames[0]["mask_path"]),
            mask_frames=result.mask_frames,
            score=float(result.score),
            sample_rate=float(result.sample_rate),
        )
        self.project.annotations.append(annotation)
        self.project.sam_points.clear()
        self.project.active_panel = "labels"
        self.video_view.annotation_item.invalidate_mask_cache()
        self.sam_panel.set_status(
            f"{result.backend} propagation saved {len(result.mask_frames)} frames "
            f"(score {result.score:.2f})"
        )
        self.statusBar().showMessage(
            f"SAM: {result.backend} propagation saved {len(result.mask_frames)} frames",
            4000,
        )
        self._mark_dirty()

    def _shutdown_threads(self) -> bool:
        """Stop background workers so Qt does not abort with 'QThread: Destroyed
        while thread is still running' when the window closes mid-export or
        mid-SAM-run. Cooperative workers (export, SAM propagation) stop promptly;
        a worker stuck in an uninterruptible torch/ffmpeg C call is force-terminated
        after a grace period. Returns True if any thread had to be force-terminated
        (heap may be inconsistent — the caller should exit immediately)."""
        pairs = [
            ("_export_thread", "_export_worker"),
            ("_sam_probe_thread", "_sam_probe_worker"),
            ("_sam_segment_thread", "_sam_segment_worker"),
            ("_sam_propagation_thread", "_sam_propagation_worker"),
        ]
        force_terminated = False
        for thread_attr, worker_attr in pairs:
            worker = getattr(self, worker_attr, None)
            if worker is not None:
                try:
                    worker.cancel()
                except Exception:  # noqa: BLE001
                    pass
            thread = getattr(self, thread_attr, None)
            if thread is None:
                continue
            try:
                if thread.isRunning():
                    thread.quit()
                    if not thread.wait(5000):
                        # A blocking torch/ffmpeg call can't be interrupted
                        # cooperatively; force it down so the process can exit.
                        thread.terminate()
                        thread.wait(2000)
                        force_terminated = True
            except RuntimeError:
                # Underlying C++ thread object already deleted (deleteLater fired).
                pass
        return force_terminated

    def closeEvent(self, event) -> None:  # noqa: N802
        for timer_attr in ("autosave_timer", "_sam_heartbeat_timer"):
            timer = getattr(self, timer_attr, None)
            if timer is not None:
                timer.stop()
        # Save BEFORE touching threads, while the heap is known-good — if a worker
        # later has to be force-terminated mid-allocation, the project is already
        # safely on disk.
        try:
            self.store.save(self.project)
        except Exception:  # noqa: BLE001
            pass
        force_terminated = self._shutdown_threads()
        if force_terminated:
            # A thread was killed at an arbitrary instruction (possibly inside the
            # torch/Metal or ffmpeg allocator). Skip graceful Qt teardown, which
            # could deadlock or segfault on the corrupted state, and exit now.
            os._exit(0)
        super().closeEvent(event)
