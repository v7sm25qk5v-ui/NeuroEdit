from __future__ import annotations

import copy
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, QMimeData, QObject, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QFontDatabase,
    QIcon,
    QImage,
    QPainter,
    QPixmap,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QInputDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
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

from neuroedit_desktop import __version__, diagnostics
from neuroedit_desktop.models import Annotation, PanelType, ProjectState, SamPoint, Slide, VideoClip, new_id
from neuroedit_desktop.project_store import ProjectStore
from neuroedit_desktop.sam_backend import SamBackend
from neuroedit_desktop.ui import styles as ui_styles
from neuroedit_desktop.ui.dialogs import (
    ExportChecklistDialog,
    ExportDialog,
    ExportHistoryDialog,
    PhiReviewDialog,
    SamSetupDialog,
    StorageLocationDialog,
    default_project_root,
    legacy_project_root,
    migrate_storage_root,
    recommended_preset_key,
    recommended_project_root,
    record_export_history,
)
from neuroedit_desktop.ui.project_library import ProjectLibraryDialog
from neuroedit_desktop.ui.canvas import AnnotationGraphicsItem, VideoGraphicsView
from neuroedit_desktop.ui.sam_workers import (
    SamDownloadWorker,
    SamProbeWorker,
    SamPropagationWorker,
    SamSegmentWorker,
)
from neuroedit_desktop.ui.editor_panels import (
    AudioPanel,
    MediaExplorerPanel,
    RichTimelineWidget,
    SlideEditorPanel,
    TipsPanel,
    project_preflight_warnings,
    project_end_time,
)
from neuroedit_desktop.ui.styles import (
    ACCENT_AMBER, ACCENT_CYAN, ACCENT_RED, ACCENT_SLIDES,
    BG_CARD, BG_HOVER,
    BORDER, BORDER_BRIGHT, DANGER, PRIMARY,
    TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY, VIDEO_CANVAS,
)
from neuroedit_desktop.ui.tutorial import TutorialOverlay, build_default_steps
from neuroedit_desktop.video_probe import probe_video

if TYPE_CHECKING:
    from neuroedit_desktop.exporter import ExportSettings

__all__ = [
    "AnnotationGraphicsItem",
    "SamDownloadWorker",
    "SamProbeWorker",
    "SamPropagationWorker",
    "SamSegmentWorker",
    "VideoGraphicsView",
    "ExportChecklistDialog",
    "ExportDialog",
    "ExportHistoryDialog",
    "PhiReviewDialog",
    "SamSetupDialog",
    "StorageLocationDialog",
    "default_project_root",
    "legacy_project_root",
    "migrate_storage_root",
    "recommended_preset_key",
    "recommended_project_root",
]

_RESOURCES = Path(__file__).parent.parent / "resources"

# Brand wordmark face (see design_handoff): Space Grotesk 600 at -0.02em tracking.
_WORDMARK_FAMILY = "Space Grotesk"
_WORDMARK_FONT_PATHS = (
    _RESOURCES / "fonts" / "SpaceGrotesk-Medium.ttf",
    _RESOURCES / "fonts" / "SpaceGrotesk-Bold.ttf",
)
_wordmark_font_family: str | None = None
_wordmark_fonts_loaded = False


def _identity_mark_path(theme: str) -> Path:
    """The transparent aperture+scalpel mark SVG matched to the resolved theme
    ('light' or 'dark'). Used in the header and About lockups."""
    name = "neuroedit-mark-dark.svg" if theme == "dark" else "neuroedit-mark-light.svg"
    return _RESOURCES / name


def _render_svg_pixmap(svg_path: Path, size: int) -> QPixmap | None:
    """Rasterize an SVG to a square QPixmap at the device pixel ratio so the
    mark stays crisp on HiDPI displays. Returns None if the SVG can't load."""
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        return None
    app = QApplication.instance()
    dpr = app.devicePixelRatio() if app is not None else 1.0
    image = QImage(int(size * dpr), int(size * dpr), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def _load_wordmark_font_family() -> str | None:
    global _wordmark_font_family, _wordmark_fonts_loaded
    if _wordmark_fonts_loaded:
        return _wordmark_font_family
    _wordmark_fonts_loaded = True
    for path in _WORDMARK_FONT_PATHS:
        try:
            font_data = QByteArray(path.read_bytes())
        except OSError:
            continue
        font_id = QFontDatabase.addApplicationFontFromData(font_data)
        if font_id < 0:
            continue
        families = QFontDatabase.applicationFontFamilies(font_id)
        if _WORDMARK_FAMILY in families:
            _wordmark_font_family = _WORDMARK_FAMILY
    return _wordmark_font_family


def _wordmark_font(point_size: int) -> QFont:
    app = QApplication.instance()
    fallback = app.font().family() if app is not None else "Sans Serif"
    family = _load_wordmark_font_family() or fallback
    font = QFont(family, point_size)
    font.setWeight(QFont.Weight.DemiBold)  # 600
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    # -0.02em tracking: QFont spacing is a percentage of the natural spacing.
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 98.0)
    return font


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
    ("slides", "Slides", ACCENT_SLIDES),
    ("audio",  "Audio",  ACCENT_RED),
]

SWATCH_COLORS = ["#00e5ff", "#ef4444", "#f59e0b", "#10b981", "#8b5cf6", "#f43f5e", "#ffffff", "#fb923c"]

# Auto-assigned SAM mask colors: cyan, magenta, yellow, green, orange, blue,
# pink, lime. Colorblind-aware and deliberately without red — red reads as
# blood/danger on surgical video.
MASK_PALETTE = [
    "#22d3ee", "#e879f9", "#facc15", "#4ade80",
    "#fb923c", "#60a5fa", "#f472b6", "#a3e635",
]

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



def format_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes = int(seconds // 60)
    remainder = seconds % 60
    return f"{minutes}:{remainder:04.1f}"


def hex_to_rgb(color_hex: str) -> tuple[int, int, int]:
    value = color_hex.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def propagation_window_s(remaining_s: float, to_clip_end: bool, window_s: float) -> float:
    """Effective SAM propagation window: to the end of the clip, or the
    user-chosen window clamped to the remaining clip length (never below 1 s)."""
    if to_clip_end:
        return max(1.0, remaining_s)
    return max(1.0, min(window_s, remaining_s))


def referenced_mask_paths(project_dicts: list[dict]) -> set[str]:
    """Every mask PNG referenced by the given project dicts (current project
    plus undo/redo snapshots), as resolved path strings."""
    referenced: set[str] = set()
    for data in project_dicts:
        for ann in data.get("annotations") or []:
            mask_path = ann.get("mask_path")
            if mask_path:
                referenced.add(str(Path(str(mask_path)).resolve()))
            for frame in ann.get("mask_frames") or []:
                frame_path = frame.get("mask_path")
                if frame_path:
                    referenced.add(str(Path(str(frame_path)).resolve()))
    return referenced


def delete_orphan_masks(masks_dir: Path, referenced: set[str]) -> int:
    """Delete unreferenced files directly inside masks_dir. Never touches
    anything outside that directory. Returns the number of files removed."""
    if not masks_dir.is_dir():
        return 0
    masks_dir = masks_dir.resolve()
    removed = 0
    for path in masks_dir.iterdir():
        resolved = path.resolve()
        if not resolved.is_file() or resolved.parent != masks_dir:
            continue
        if str(resolved) in referenced:
            continue
        try:
            resolved.unlink()
            removed += 1
        except OSError:
            pass
    return removed


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
    mask_visibility_changed = Signal(str, bool)   # annotation id, visible
    mask_renamed = Signal(str, str)               # annotation id, new label
    mask_deleted = Signal(str)                    # annotation id
    mask_selected = Signal(str)                   # annotation id
    mask_retrack_requested = Signal(str)          # annotation id
    install_deps_requested = Signal()
    download_weights_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, project: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self._refreshing_masks = False
        self.status = QLabel("Preparing SAM backend…")
        self.status.setProperty("role", "muted")
        self.status.setWordWrap(True)

        self.last_run_label = QLabel()
        self.last_run_label.setProperty("role", "muted")
        self.last_run_label.setWordWrap(True)
        self.last_run_label.hide()

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate marquee
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.hide()

        # Visible only while a job runs; cooperative cancel for long SAM work.
        self.cancel_button = QPushButton("Cancel SAM Job")
        self.cancel_button.setProperty("variant", "danger")
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.cancel_button.hide()

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

        # Propagation window: track to clip end by default (least confusing for
        # novices), or a fixed number of seconds from the playhead. Both prefs
        # persist app-wide so the choice survives restarts.
        prefs = QSettings("NeuroEdit", "Desktop")
        self.track_window_spin = QDoubleSpinBox()
        self.track_window_spin.setRange(1.0, 120.0)
        self.track_window_spin.setDecimals(1)
        self.track_window_spin.setSingleStep(1.0)
        self.track_window_spin.setValue(float(prefs.value("sam/trackWindowS", 5.0)))
        self.track_window_spin.setSuffix(" s")
        self.track_to_end_check = QCheckBox("To clip end")
        self.track_to_end_check.setToolTip(
            "Track from the playhead to the end of the active clip."
        )
        track_to_end = prefs.value("sam/trackToEnd", True, type=bool)
        self.track_to_end_check.setChecked(track_to_end)
        self.track_window_spin.setEnabled(not track_to_end)
        self.track_to_end_check.toggled.connect(self._track_prefs_changed)
        self.track_window_spin.valueChanged.connect(self._track_prefs_changed)

        # Mask list (3D Slicer "Segment Editor" pattern): one row per
        # mask/tracked-mask annotation with visibility checkbox + inline rename.
        self.masks_list = QListWidget()
        self.masks_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.masks_list.customContextMenuRequested.connect(self._show_mask_menu)
        self.masks_list.itemChanged.connect(self._mask_item_changed)
        self.masks_list.currentItemChanged.connect(self._mask_selection_changed)

        # Shown instead of the working controls when the SAM backend is missing.
        self._explainer = QWidget()
        explainer_layout = QVBoxLayout(self._explainer)
        explainer_layout.setContentsMargins(0, 0, 0, 0)
        explainer_layout.setSpacing(8)
        explainer_text = QLabel(
            "SAM (Segment Anything) outlines an anatomical structure from a few "
            "clicks and can track it through the video. It runs entirely on this "
            "computer — no video ever leaves the machine. Using it needs a "
            "one-time setup: installing the AI components and downloading the "
            "model weights (~3.2 GB)."
        )
        explainer_text.setWordWrap(True)
        self.install_deps_button = QPushButton("Install Dependencies")
        self.install_deps_button.clicked.connect(self.install_deps_requested)
        self.download_weights_button = QPushButton("Download Weights")
        self.download_weights_button.setProperty("variant", "cyan")
        self.download_weights_button.clicked.connect(self.download_weights_requested)
        explainer_layout.addWidget(explainer_text)
        explainer_layout.addWidget(self.install_deps_button)
        explainer_layout.addWidget(self.download_weights_button)
        self._explainer.hide()

        self.delete_weights_button = QPushButton("Delete Cached Weights (3.2 GB)")
        self.delete_weights_button.setProperty("variant", "danger")
        self.delete_weights_button.setToolTip(
            "Removes the SAM3 model weights from your cache (~/.cache/huggingface).\n"
            "Useful before uninstalling the app. You can re-download them later."
        )
        self.delete_weights_button.clicked.connect(self.delete_weights_requested)
        self.delete_weights_button.hide()

        # Working controls live in one container so the missing-backend
        # explainer can swap them out with a single show/hide.
        self._controls = QWidget()
        controls_layout = QVBoxLayout(self._controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(10)
        mode_label = QLabel("Prompt mode")
        mode_label.setProperty("role", "muted")
        controls_layout.addWidget(mode_label)
        controls_layout.addLayout(mode_row)
        controls_layout.addWidget(self.point_toggle)
        points_label = QLabel("Prompt points")
        points_label.setProperty("role", "muted")
        controls_layout.addWidget(points_label)
        controls_layout.addWidget(self.points, 1)
        controls_layout.addWidget(self.undo_button)
        controls_layout.addWidget(self.segment_button)
        track_row = QHBoxLayout()
        track_row.setSpacing(6)
        track_label = QLabel("Track window")
        track_label.setProperty("role", "muted")
        track_row.addWidget(track_label)
        track_row.addWidget(self.track_window_spin, 1)
        track_row.addWidget(self.track_to_end_check)
        controls_layout.addLayout(track_row)
        controls_layout.addWidget(self.propagate_button)
        controls_layout.addWidget(self.clear_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        title = QLabel("SAM Segmentation")
        title.setProperty("role", "title")
        layout.addWidget(title)
        layout.addWidget(self.status)
        layout.addWidget(self.progress)
        layout.addWidget(self.cancel_button)
        layout.addWidget(self.last_run_label)
        layout.addWidget(self._explainer)
        layout.addWidget(self._controls, 2)
        masks_label = QLabel("Masks")
        masks_label.setProperty("role", "muted")
        layout.addWidget(masks_label)
        layout.addWidget(self.masks_list, 1)
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
        self.cancel_button.setVisible(busy)
        self.segment_button.setEnabled(not busy)
        self.propagate_button.setEnabled(not busy)
        self.point_toggle.setEnabled(not busy)
        self.undo_button.setEnabled(not busy and bool(self.project.sam_points))
        # Mask rows can't safely be renamed/deleted/re-tracked while a job may
        # rewrite their frames; gray the list until the job ends.
        self.masks_list.setEnabled(not busy)

    def _track_prefs_changed(self, *_args) -> None:
        to_end = self.track_to_end_check.isChecked()
        self.track_window_spin.setEnabled(not to_end)
        prefs = QSettings("NeuroEdit", "Desktop")
        prefs.setValue("sam/trackToEnd", to_end)
        prefs.setValue("sam/trackWindowS", float(self.track_window_spin.value()))

    def refresh(self) -> None:
        self.points.clear()
        for idx, point in enumerate(self.project.sam_points, start=1):
            marker = "＋" if point.type == "positive" else "−"
            self.points.addItem(
                f"{marker}  {idx}. {point.type} ({point.x * 100:.0f}%, {point.y * 100:.0f}%)"
            )
        self.undo_button.setEnabled(bool(self.project.sam_points))
        self._apply_point_toggle_style()
        self._refresh_masks()
        self._refresh_last_run()

    def show_backend_explainer(self, deps_missing: bool) -> None:
        """Backend probe failed: replace the working controls with a plain
        explanation and the relevant setup action(s)."""
        self._controls.hide()
        self.install_deps_button.setVisible(deps_missing)
        self._explainer.show()

    def show_backend_ready(self) -> None:
        self._explainer.hide()
        self._controls.show()

    # ── Mask list ─────────────────────────────────────────────────────────

    def _mask_annotations(self) -> list[Annotation]:
        return [a for a in self.project.annotations if a.type in ("mask", "tracked-mask")]

    @staticmethod
    def _mask_item_text(ann: Annotation) -> str:
        text = ann.label or "(unlabeled)"
        if ann.type == "tracked-mask" and ann.mask_frames:
            text += f" · {len(ann.mask_frames)} frames"
        return text

    def _selected_mask_id(self) -> str | None:
        item = self.masks_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _refresh_masks(self) -> None:
        self._refreshing_masks = True
        self.masks_list.blockSignals(True)
        selected_id = self.project.selected_annotation_id or self._selected_mask_id()
        self.masks_list.clear()
        for ann in self._mask_annotations():
            item = QListWidgetItem(self._mask_item_text(ann))
            item.setData(Qt.ItemDataRole.UserRole, ann.id)
            item.setFlags(
                item.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable
            )
            item.setCheckState(
                Qt.CheckState.Checked if ann.visible else Qt.CheckState.Unchecked
            )
            swatch = QPixmap(12, 12)
            swatch.fill(QColor(ann.color))
            item.setIcon(QIcon(swatch))
            self.masks_list.addItem(item)
            if ann.id == selected_id:
                self.masks_list.setCurrentItem(item)
        self.masks_list.blockSignals(False)
        self._refreshing_masks = False

    def _mask_item_changed(self, item: QListWidgetItem) -> None:
        if self._refreshing_masks:
            return
        # Read everything off the item before emitting: a connected handler may
        # trigger a refresh that rebuilds the list and deletes this item.
        ann_id = str(item.data(Qt.ItemDataRole.UserRole))
        visible = item.checkState() == Qt.CheckState.Checked
        label = re.sub(r"\s*·\s*\d+ frames$", "", item.text()).strip()
        ann = next((a for a in self._mask_annotations() if a.id == ann_id), None)
        if ann is None:
            return
        if visible != ann.visible:
            ann.visible = visible
            self.mask_visibility_changed.emit(ann_id, visible)
        elif label != (ann.label or "(unlabeled)"):
            ann.label = label
            self.mask_renamed.emit(ann_id, label)

    def _mask_selection_changed(self) -> None:
        if self._refreshing_masks:
            return
        ann_id = self._selected_mask_id()
        if ann_id:
            self.mask_selected.emit(ann_id)

    def _show_mask_menu(self, pos) -> None:  # type: ignore[no-untyped-def]
        item = self.masks_list.itemAt(pos)
        if item is None:
            return
        ann_id = str(item.data(Qt.ItemDataRole.UserRole))
        ann = next((a for a in self._mask_annotations() if a.id == ann_id), None)
        menu = QMenu(self)
        rename_action = menu.addAction("Rename")
        retrack_action = (
            menu.addAction("Re-track") if ann is not None and ann.type == "tracked-mask" else None
        )
        delete_action = menu.addAction("Delete Mask")
        chosen = menu.exec(self.masks_list.mapToGlobal(pos))
        if chosen is rename_action:
            self.masks_list.editItem(item)
        elif retrack_action is not None and chosen is retrack_action:
            self.mask_retrack_requested.emit(ann_id)
        elif chosen is delete_action:
            self.mask_deleted.emit(ann_id)

    def _refresh_last_run(self) -> None:
        data = getattr(self.project, "sam_last_run", {}) or {}
        if not data:
            self.last_run_label.hide()
            return
        started = str(data.get("started_iso", "")).replace("T", " ")[:16]
        duration = float(data.get("duration_s", 0.0) or 0.0)
        result = data.get("result", "")
        if result == "success":
            line = (
                f"✓ {int(data.get('frames', 0) or 0)} frames · {data.get('backend', '')}"
                f" · {started} · {duration:.0f}s"
            )
        elif result == "canceled":
            line = f"⚠ canceled · {started}"
        else:
            line = f"✗ failed: {data.get('message', '')}"
        self.last_run_label.setText(f"Last run\n{line}")
        self.last_run_label.show()

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
        self._delete_inspector_btn.setProperty("variant", "danger")
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
                f"QPushButton:hover {{ color: {DANGER}; }}"
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
        from neuroedit_desktop.exporter import ExportCancelled, ProjectExporter

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



class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.project = ProjectState()
        self.store = ProjectStore.create(default_project_root())
        self.sam_backend = SamBackend()
        self.dirty = False

        # Undo/redo: snapshots of document state before each mutation.
        self._undo_stack: list[bytes] = []
        self._redo_stack: list[bytes] = []
        self._undo_hashes: list[str] = []
        self._redo_hashes: list[str] = []
        self._undo_sizes: list[int] = []
        self._redo_sizes: list[int] = []
        self._autosave_snapshot: dict | None = None
        self._history_limit = 50
        self._history_bytes_limit = 64 * 1024 * 1024
        self._restoring = False  # True while applying a history snapshot
        self._media_warnings_shown: set[str] = set()
        self._media_problem_cache: dict[tuple[str, str, int, int], str | None] = {}
        self._project_end_time_cache: float | None = None

        if self.store.project_path.exists():
            try:
                self.store, self.project = ProjectStore.open(self.store.project_path)
            except Exception as exc:
                QMessageBox.warning(self, "Autosave restore failed", str(exc))

        self.setWindowTitle(f"NeuroEdit — {self.project.project_name}")
        self.setObjectName("mainWindow")
        self.setAcceptDrops(True)
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
        initial_snapshot = self._snapshot()
        initial_payload = self._snapshot_payload(initial_snapshot)
        self._undo_stack.append(initial_payload)
        self._undo_hashes.append(self._payload_hash(initial_payload))
        self._undo_sizes.append(len(initial_payload))
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
        self.player.mediaStatusChanged.connect(self._media_status_changed)
        # A seek issued right after setSource() is silently dropped because the
        # media isn't loaded yet, so a trimmed clip would play from 0 instead of
        # its trim_start. We stash the intended seek (and whether to play) here
        # and apply it from _media_status_changed once the media reports loaded.
        self._pending_seek_ms: int | None = None
        self._pending_play = False
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

        # Dev-only: timestamped paint/load/export/SAM timing log for manual QA.
        self.diagnostics_action = QAction("Performance Diagnostics (Developer)", self)
        self.diagnostics_action.setCheckable(True)
        settings_enabled = QSettings("NeuroEdit", "Desktop").value(
            "diagnostics/enabled", False, type=bool
        )
        if settings_enabled and not diagnostics.is_enabled():
            diagnostics.set_enabled(True)
        self.diagnostics_action.setChecked(diagnostics.is_enabled())
        self.diagnostics_action.toggled.connect(self._toggle_diagnostics)

        self.reveal_diagnostics_action = QAction("Reveal Diagnostics Log", self)
        self.reveal_diagnostics_action.setEnabled(diagnostics.is_enabled())
        self.reveal_diagnostics_action.triggered.connect(
            lambda: self._reveal_path(diagnostics.log_path())
        )

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

        self.phi_review_action = QAction("Guided PHI Review…", self)
        self.phi_review_action.triggered.connect(self._start_phi_review)

        self.export_captions_action = QAction("Export Captions (SRT/VTT)…", self)
        self.export_captions_action.triggered.connect(self._export_captions)

        self.export_history_action = QAction("Export History…", self)
        self.export_history_action.triggered.connect(self._show_export_history)

        self.storage_location_action = QAction("Project Storage Location…", self)
        self.storage_location_action.triggered.connect(self._change_storage_location)

        self.theme_action_group = QActionGroup(self)
        self.theme_action_group.setExclusive(True)
        self.theme_actions: dict[ui_styles.ThemeMode, QAction] = {}
        for mode, label in [
            ("light", "Light"),
            ("dark", "Dark"),
            ("system", "System"),
        ]:
            action = QAction(label, self)
            action.setCheckable(True)
            action.setData(mode)
            action.triggered.connect(
                lambda checked=False, m=mode: self._set_theme_mode(m, checked)
            )
            self.theme_action_group.addAction(action)
            self.theme_actions[mode] = action
        self.theme_actions[ui_styles.stored_theme_mode()].setChecked(True)

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
        file_menu.addSeparator()
        file_menu.addAction(self.export_captions_action)
        file_menu.addAction(self.export_history_action)
        file_menu.addSeparator()
        file_menu.addAction(self.storage_location_action)
        self._rebuild_recent_menu()

        edit_menu = menubar.addMenu("Edit")
        edit_menu.addAction(self.undo_action)
        edit_menu.addAction(self.redo_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.duplicate_annotation_action)
        edit_menu.addAction(self.delete_annotation_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.phi_review_action)

        view_menu = menubar.addMenu("View")
        appearance_menu = view_menu.addMenu("Appearance")
        for mode in ("light", "dark", "system"):
            appearance_menu.addAction(self.theme_actions[mode])

        help_menu = menubar.addMenu("Help")
        help_menu.addAction(self.tutorial_action)
        help_menu.addSeparator()
        help_menu.addAction(self.diagnostics_action)
        help_menu.addAction(self.reveal_diagnostics_action)
        help_menu.addSeparator()
        help_menu.addAction(self.about_action)

    def _set_theme_mode(self, mode: ui_styles.ThemeMode, checked: bool = True) -> None:
        if not checked:
            return
        ui_styles.save_theme_mode(mode)
        self._apply_theme_mode(mode)
        self.statusBar().showMessage(f"Appearance set to {mode.title()}", 3000)

    def _apply_theme_mode(self, mode: ui_styles.ThemeMode) -> None:
        app = QApplication.instance()
        if app is not None:
            ui_styles.apply_app_style(app, mode)
        self._sync_imported_theme_tokens()
        self._restyle_theme_widgets()
        self.refresh()

    def _sync_imported_theme_tokens(self) -> None:
        from neuroedit_desktop.ui import editor_panels

        for name in ui_styles.EXPORTED_COLOR_NAMES:
            value = getattr(ui_styles, name)
            if name in globals():
                globals()[name] = value
            if hasattr(editor_panels, name):
                setattr(editor_panels, name, value)
        global PANELS
        PANELS = [
            ("sam", "SAM", ui_styles.ACCENT_CYAN),
            ("labels", "Labels", ui_styles.PRIMARY),
            ("tips", "Tips", ui_styles.ACCENT_AMBER),
            ("slides", "Slides", ui_styles.ACCENT_SLIDES),
            ("audio", "Audio", ui_styles.ACCENT_RED),
        ]
        editor_panels.TimelineCanvas.TRACKS = [
            ("video", "Video", ui_styles.TIMELINE_VIDEO),
            ("audio", "Audio", ui_styles.TIMELINE_AUDIO),
            ("slides", "Slides", ui_styles.TIMELINE_SLIDES),
            ("markers", "Markers", ui_styles.TIMELINE_MARKERS),
        ]

    def _restyle_theme_widgets(self) -> None:
        for button in getattr(self, "tool_buttons", {}).values():
            button.setStyleSheet(self._tool_btn_css())
        if hasattr(self, "color_picker_btn"):
            self.color_picker_btn.setStyleSheet(
                f"QPushButton {{ border-radius: 9px; border: 1px solid {BORDER_BRIGHT}; background: {BG_CARD}; }}"
                f"QPushButton:hover {{ border-color: {TEXT_PRIMARY}; }}"
            )
        if hasattr(self, "width_label"):
            self.width_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        if hasattr(self, "video_view"):
            self.video_view.setStyleSheet(f"background: {VIDEO_CANVAS};")
        if hasattr(self, "speed_btn"):
            self.speed_btn.setStyleSheet(
                f"QPushButton {{ border-radius: 6px; border: 1px solid {BORDER}; background: {BG_HOVER};"
                f"  color: {TEXT_SECONDARY}; font-size: 11px; font-family: monospace; }}"
                f"QPushButton:hover {{ border-color: {BORDER_BRIGHT}; color: {TEXT_PRIMARY}; }}"
            )
        if hasattr(self, "timeline"):
            self.timeline.canvas._static_cache = None
            self.timeline.canvas._static_cache_key = None
            self.timeline.canvas.update()
        self._restyle_identity()

    def _restyle_identity(self) -> None:
        """Re-render the header mark and wordmark for the active theme. Called on
        build and whenever appearance/themeMode changes (light ↔ dark)."""
        logo = getattr(self, "_header_logo", None)
        if logo is not None:
            theme = ui_styles.resolve_theme_mode()
            pixmap = _render_svg_pixmap(_identity_mark_path(theme), 32)
            if pixmap is not None:
                logo.setPixmap(pixmap)
            else:  # SVG unavailable (e.g. QtSvg plugin missing): fall back to glyph
                logo.setText("⬡")
                logo.setStyleSheet(
                    f"QLabel {{ color: {TEXT_PRIMARY}; font-size: 18px; font-weight: 900; }}"
                )
        wordmark = getattr(self, "_header_wordmark", None)
        if wordmark is not None:
            wordmark.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent;")

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

        # Identity lockup: theme-matched aperture+scalpel mark + live wordmark.
        logo = QLabel()
        logo.setFixedSize(32, 32)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._header_logo = logo
        layout.addWidget(logo)

        name_label = QLabel("NeuroEdit")
        name_label.setFont(_wordmark_font(15))
        self._header_wordmark = name_label
        layout.addWidget(name_label)
        self._restyle_identity()

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
        self.video_view.setStyleSheet(f"background: {VIDEO_CANVAS};")
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
        self.sam_panel.mask_visibility_changed.connect(self._set_annotation_visibility)
        self.sam_panel.mask_renamed.connect(self._update_annotation_label)
        self.sam_panel.mask_deleted.connect(self._delete_annotation)
        self.sam_panel.mask_selected.connect(self._on_panel_selection_changed)
        self.sam_panel.mask_retrack_requested.connect(self._retrack_mask)
        self.sam_panel.install_deps_requested.connect(self._show_sam_install_help)
        self.sam_panel.download_weights_requested.connect(self._show_sam_setup)
        self.sam_panel.cancel_requested.connect(self._cancel_sam_jobs)
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
        self.audio_panel.export_captions_requested.connect(self._export_captions)

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
        # The vertical scrollbar (always present — panels are taller than the
        # viewport) eats into the viewport width on non-overlay styles, so it
        # must be part of the minimum or every panel scrolls sideways by
        # exactly its width.
        chrome_width = (
            self.panel_scroll.verticalScrollBar().sizeHint().width()
            + 2 * self.panel_scroll.frameWidth()
        )
        panel_min = self.panels.minimumSizeHint().width() + chrome_width
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
        self._invalidate_project_end_time()
        if history and not self._restoring:
            self._push_history()
        elif not history:
            self._autosave_snapshot = None
        self.dirty = True
        self.refresh()
        self._update_title()

    def _mark_project_dirty(self) -> None:
        self._invalidate_project_end_time()
        if not self._restoring:
            self._push_history()
        else:
            self._autosave_snapshot = None
        self.dirty = True
        self._update_title()
        self.video_view.set_project(self.project)
        # Re-point the player at whatever is under the playhead now. A timeline
        # edit can change (or remove) the clip there — without this, deleting the
        # clip under the playhead leaves its last frame frozen in the preview.
        self._sync_player_to_timeline(play=self._timeline_playing)
        self.video_view.update_annotations()
        self.timeline.refresh()
        self.media_panel.refresh()

    def _mark_project_metadata_dirty(self) -> None:
        self._autosave_snapshot = None
        self.dirty = True
        self._update_title()

    def _invalidate_project_end_time(self) -> None:
        self._project_end_time_cache = None

    def _project_end_time(self) -> float:
        cached = self._project_end_time_cache
        if cached is None:
            cached = project_end_time(self.project)
            self._project_end_time_cache = cached
        self.project.duration = cached
        return cached

    # ── Undo/redo ─────────────────────────────────────────────────────────

    # Transient UI state: excluded from undo snapshots and carried across
    # snapshot restores. draw_* are tool settings, not document content — the
    # width slider alone would otherwise push one snapshot per drag tick and
    # flush real edits out of the 50-entry history.
    _TRANSIENT_SNAPSHOT_KEYS = (
        "active_panel",
        "active_tool",
        "current_time",
        "scroll_left",
        "selected_annotation_id",
        "zoom",
        "draw_color",
        "draw_width",
        "draw_opacity",
        "draw_label",
    )

    def _snapshot(self, project_data: dict | None = None) -> dict:
        snapshot = dict(project_data if project_data is not None else self.project.to_dict())
        for key in self._TRANSIENT_SNAPSHOT_KEYS:
            snapshot.pop(key, None)
        return snapshot

    def _snapshot_payload(self, snapshot: dict) -> bytes:
        return json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _payload_hash(self, payload: bytes) -> str:
        return hashlib.blake2b(payload, digest_size=16).hexdigest()

    def _snapshot_hash(self, snapshot: dict) -> str:
        return self._payload_hash(self._snapshot_payload(snapshot))

    def _push_history(self) -> None:
        project_data = self.project.to_dict()
        snapshot = self._snapshot(project_data)
        snapshot_payload = self._snapshot_payload(snapshot)
        snapshot_hash = self._payload_hash(snapshot_payload)
        self._autosave_snapshot = project_data
        self._redo_stack.clear()
        self._redo_hashes.clear()
        self._redo_sizes.clear()
        if self._undo_hashes and self._undo_hashes[-1] == snapshot_hash:
            self._update_history_actions()
            return
        self._undo_stack.append(snapshot_payload)
        self._undo_hashes.append(snapshot_hash)
        self._undo_sizes.append(len(snapshot_payload))
        while len(self._undo_stack) > 1 and (
            len(self._undo_stack) > self._history_limit
            or sum(self._undo_sizes) > self._history_bytes_limit
        ):
            self._undo_stack.pop(0)
            self._undo_hashes.pop(0)
            self._undo_sizes.pop(0)
        self._update_history_actions()

    def _update_history_actions(self) -> None:
        self.undo_action.setEnabled(len(self._undo_stack) > 1)
        self.redo_action.setEnabled(bool(self._redo_stack))

    def undo(self) -> None:
        if len(self._undo_stack) <= 1:
            return
        current = self._undo_stack.pop()
        current_hash = self._undo_hashes.pop()
        current_size = self._undo_sizes.pop()
        self._redo_stack.append(current)
        self._redo_hashes.append(current_hash)
        self._redo_sizes.append(current_size)
        previous = self._undo_stack[-1]
        self._apply_snapshot(previous)
        self._update_history_actions()

    def redo(self) -> None:
        if not self._redo_stack:
            return
        snapshot = self._redo_stack.pop()
        snapshot_hash = (
            self._redo_hashes.pop()
            if self._redo_hashes
            else self._payload_hash(snapshot)
        )
        snapshot_size = (
            self._redo_sizes.pop()
            if self._redo_sizes
            else len(snapshot)
        )
        self._undo_stack.append(snapshot)
        self._undo_hashes.append(snapshot_hash)
        self._undo_sizes.append(snapshot_size)
        self._apply_snapshot(snapshot)
        self._update_history_actions()

    def _apply_snapshot(self, snapshot: bytes) -> None:
        self._restoring = True
        try:
            transient = {
                key: getattr(self.project, key) for key in self._TRANSIENT_SNAPSHOT_KEYS
            }
            old_clip = self.project.active_clip
            old_path = old_clip.path if old_clip else None
            self.project = ProjectState.from_dict(json.loads(snapshot))
            self._autosave_snapshot = None
            self._project_end_time_cache = None
            for key, value in transient.items():
                if key == "selected_annotation_id":
                    # Only carry the selection over if the annotation survived.
                    if any(ann.id == value for ann in self.project.annotations):
                        self.project.selected_annotation_id = value
                    continue
                setattr(self.project, key, value)
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

        # Identity lockup: theme-matched mark + live wordmark, centered.
        theme = ui_styles.resolve_theme_mode()
        lockup = QHBoxLayout()
        lockup.setSpacing(11)  # ≈ 0.33 × wordmark size
        lockup.addStretch()
        mark_pix = _render_svg_pixmap(_identity_mark_path(theme), 52)
        if mark_pix is not None:
            mark = QLabel()
            mark.setFixedSize(52, 52)
            mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
            mark.setPixmap(mark_pix)
            lockup.addWidget(mark)
        title = QLabel("NeuroEdit")
        title.setFont(_wordmark_font(26))
        title.setStyleSheet(f"color: {TEXT_PRIMARY}; background: transparent;")
        lockup.addWidget(title)
        lockup.addStretch()
        layout.addLayout(lockup)

        version_label = QLabel(f"v{__version__}")
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

    def _maybe_prompt_storage_location(self) -> None:
        settings = QSettings("NeuroEdit", "Desktop")
        if settings.value("storage/projectRoot", ""):
            return
        if settings.value("storage/promptShown", False, type=bool):
            return
        settings.setValue("storage/promptShown", True)
        self._change_storage_location()

    def _change_storage_location(self) -> None:
        old_root = default_project_root()
        dialog = StorageLocationDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        root = dialog.chosen_root()
        QSettings("NeuroEdit", "Desktop").setValue("storage/projectRoot", str(root))
        if root != old_root:
            self._offer_storage_migration(old_root, root)
        # Move the autosave target only when the open project is an untouched
        # scratch project still pointed at the old default location.
        is_scratch = (
            not self.project.clips
            and not self.project.audio_tracks
            and not self.project.slides
            and not self.project.annotations
        )
        if is_scratch and not self.dirty and self.store.project_path.parent != root:
            self.store = ProjectStore.create(root)
        self.statusBar().showMessage(f"New projects will be stored in {root}", 5000)

    def _offer_storage_migration(self, old_root: Path, new_root: Path) -> None:
        """Safe migration when the storage root changes: copy (never move) the
        previous autosave contents — project.json, masks, stills, audio may all
        hold PHI, so nothing is deleted until the user verifies the copy."""
        try:
            has_content = old_root.exists() and any(old_root.iterdir())
        except OSError:
            has_content = False
        if not has_content:
            return
        reply = QMessageBox.question(
            self,
            "Copy existing autosave data?",
            f"The previous storage location contains project data:\n{old_root}\n\n"
            f"Copy it to the new location?\n{new_root}\n\n"
            "Files are copied, not moved — the originals stay in place until "
            "you verify the new location and remove them yourself.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        error = migrate_storage_root(old_root, new_root)
        if error:
            QMessageBox.warning(
                self,
                "Migration incomplete",
                f"Some files could not be copied:\n{error}\n\n"
                "The previous location was left untouched.",
            )
            return
        # Re-point the open scratch store if it lived under the old root, so
        # future autosaves land in the migrated copy.
        try:
            rel = self.store.project_path.relative_to(old_root)
            self.store = ProjectStore(project_path=new_root / rel)
        except ValueError:
            pass
        self.statusBar().showMessage(
            "Autosave data copied to the new location (originals kept).", 6000
        )

    def _start_phi_review(self) -> None:
        dialog = PhiReviewDialog(self.project, self)
        dialog.seek_requested.connect(self._seek_global)
        dialog.review_completed.connect(self._phi_review_completed)
        result = dialog.exec()
        # Persist per-stop progress complete or not, so a paused review
        # resumes at the first unreviewed section — even after reopening.
        self.project.phi_review_progress = dialog.progress_dict()
        self._mark_dirty(history=False)
        if result != QDialog.DialogCode.Accepted and dialog.stops:
            done = len(dialog.progress_dict())
            self.statusBar().showMessage(
                f"PHI review paused — {done} of {len(dialog.stops)} sections "
                "reviewed. Resume any time from Edit → Guided PHI Review.",
                6000,
            )

    def _phi_review_completed(self) -> None:
        self.project.phi_review_confirmed = True
        self._mark_dirty(history=False)
        self.refresh()
        self.statusBar().showMessage(
            "PHI review complete — recorded in the project and export report.", 6000
        )

    def _maybe_show_first_run_tutorial(self) -> None:
        self._maybe_prompt_storage_location()
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
            if self._autosave_snapshot is not None:
                self.store.save_data(self._autosave_snapshot)
            else:
                self.store.save(self.project)
            self.statusBar().showMessage(f"Autosaved {self.store.project_path}", 2500)
            self.dirty = False
            self._autosave_snapshot = None
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
        self._autosave_snapshot = None
        self._invalidate_project_end_time()
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
        load_start = time.perf_counter()
        try:
            self.store, self.project = ProjectStore.open(Path(path))
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return
        self._invalidate_project_end_time()
        self._add_to_recent(Path(path))
        self._validate_loaded_project_media("Open project")
        self._load_active_clip()
        self._log_project_load(load_start, "dialog")
        self._mark_dirty()

    def _save_project(self) -> None:
        if self.store.project_path.parent == default_project_root():
            # Still in autosave location — prompt for a real save destination
            self._save_project_as()
            return
        try:
            self.store.save(self.project)
            self.dirty = False
            self._autosave_snapshot = None
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
        self._autosave_snapshot = None
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
        load_start = time.perf_counter()
        try:
            self.store, self.project = ProjectStore.open(path)
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return
        self._invalidate_project_end_time()
        self._add_to_recent(path)
        self._validate_loaded_project_media("Open recent project")
        self._load_active_clip()
        self._log_project_load(load_start, "recent")
        self._mark_dirty()

    def _log_project_load(self, start_perf: float, source: str) -> None:
        # PHI-safe by construction: counts and timing only, no names or paths.
        diagnostics.log(
            "project_load",
            duration_ms=(time.perf_counter() - start_perf) * 1000.0,
            source=source,
            clips=len(self.project.clips),
            audio=len(self.project.audio_tracks),
            slides=len(self.project.slides),
            annotations=len(self.project.annotations),
        )

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
        self._import_media_files([Path(path) for path in paths])

    def _import_image(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import Image",
            str(Path.home() / "Pictures"),
            "Image Files (*.png *.jpg *.jpeg *.heic *.bmp *.webp);;All Files (*)",
        )
        if not paths:
            return
        self._import_media_files([Path(path) for path in paths])

    def _add_video_clip(self, video_path: Path):
        with diagnostics.timed("media_probe"):
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
        self._import_media_files([Path(path)])

    def _import_media_files(self, paths: list[Path]) -> None:
        clip = None
        video_count = sum(path.suffix.lower() in VIDEO_EXTENSIONS for path in paths)
        progress = None
        probed_videos = 0
        if video_count > 1:
            progress = QProgressDialog("Reading video metadata...", "", 0, video_count, self)
            progress.setCancelButton(None)
            progress.setMinimumDuration(0)
            progress.setWindowModality(Qt.WindowModality.WindowModal)
            progress.setValue(0)
            QApplication.processEvents()
        for media_path in paths:
            imported_clip = None
            suffix = media_path.suffix.lower()
            if suffix in VIDEO_EXTENSIONS:
                if progress is not None:
                    progress.setLabelText(
                        f"Reading video metadata ({probed_videos + 1} of {video_count})..."
                    )
                    QApplication.processEvents()
                imported_clip = self._add_video_clip(media_path)
                probed_videos += 1
                if progress is not None:
                    progress.setValue(probed_videos)
                    QApplication.processEvents()
            elif suffix in IMAGE_EXTENSIONS:
                imported_clip = self._add_image_clip(media_path)
            else:
                QMessageBox.information(
                    self, "Import Media", f"Unsupported media file: {media_path.name}"
                )
            if imported_clip is not None:
                clip = imported_clip
        if progress is not None:
            progress.close()
        if clip is None:
            return
        self.project.active_clip_id = clip.id
        self._load_active_clip()
        self._mark_dirty()

    @staticmethod
    def _dropped_media_paths(mime_data: QMimeData) -> list[Path]:
        if not mime_data.hasUrls():
            return []
        supported = VIDEO_EXTENSIONS | IMAGE_EXTENSIONS
        return [
            path
            for url in mime_data.urls()
            if url.isLocalFile()
            and (path := Path(url.toLocalFile())).is_file()
            and path.suffix.lower() in supported
        ]

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._dropped_media_paths(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = self._dropped_media_paths(event.mimeData())
        if not paths:
            event.ignore()
            return
        self._import_media_files(paths)
        event.acceptProposedAction()

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
        self._invalidate_project_end_time()
        self.project.duration = self._project_end_time()
        self.project.active_panel = "slides"
        self._seek_global(time_s)
        self._mark_dirty()
        self.statusBar().showMessage(f"Inserted still slide at {format_time(time_s)}", 3000)

    def _render_current_still(self, time_s: float) -> Path | None:
        from neuroedit_desktop.exporter import ExportSettings, ProjectExporter

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
        self.project.duration = self._project_end_time()
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

        dialog = ExportDialog(self.project, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        keeps_source_audio = not dialog.mute_source_audio_check.isChecked() and any(
            clip.media_type == "video" for clip in self.project.clips
        )
        includes_audio = keeps_source_audio or bool(self.project.audio_tracks)
        checklist = ExportChecklistDialog(
            self.project,
            export_includes_audio=includes_audio,
            keeps_source_audio=keeps_source_audio,
            parent=self,
        )
        if checklist.exec() != QDialog.DialogCode.Accepted:
            if checklist.guided_review_requested:
                self._start_phi_review()
            return
        checklist.apply_to_project(self.project)
        self._mark_dirty(history=False)
        self.refresh()

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
        self._start_export(settings)

    def _show_export_history(self) -> None:
        ExportHistoryDialog(self._reveal_path, self).exec()

    def _export_captions(self) -> None:
        from neuroedit_desktop.captions import build_caption_cues, cues_to_srt, cues_to_vtt

        if not self.project.transcript_segments:
            QMessageBox.information(
                self,
                "Export Captions",
                "No transcript segments yet. Add or import a transcript on the "
                "Audio panel first.",
            )
            return
        default_name = self._safe_export_name(self.project.project_name)
        default_path = Path.home() / "Movies" / f"{default_name}.srt"
        path_str, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Captions",
            str(default_path),
            "SubRip captions (*.srt);;WebVTT captions (*.vtt)",
        )
        if not path_str:
            return
        output_path = Path(path_str)
        wants_vtt = "WebVTT" in selected_filter or output_path.suffix.lower() == ".vtt"
        if output_path.suffix.lower() not in (".srt", ".vtt"):
            output_path = output_path.with_suffix(".vtt" if wants_vtt else ".srt")
        cues = build_caption_cues(self.project.transcript_segments)
        content = cues_to_vtt(cues) if wants_vtt else cues_to_srt(cues)
        try:
            output_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Export Captions failed", str(exc))
            return
        self.statusBar().showMessage(f"Captions saved to {output_path}", 5000)

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
        self._export_worker_settings = settings
        self._export_started_perf = time.perf_counter()
        self._export_first_progress_logged = False
        diagnostics.log(
            "export_start",
            width=settings.width, height=settings.height,
            fps=settings.fps, crf=settings.crf,
            clips=len(project_snapshot.clips),
        )
        self.export_btn.setEnabled(False)
        self.statusBar().showMessage("Export started...")
        thread.start()

    def _export_progress(self, value: int, message: str) -> None:
        if value > 0 and not getattr(self, "_export_first_progress_logged", True):
            # Export *startup* latency: time until the pipeline first reports.
            self._export_first_progress_logged = True
            diagnostics.log(
                "export_first_progress",
                duration_ms=(time.perf_counter() - self._export_started_perf) * 1000.0,
            )
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
        self.export_btn.setEnabled(True)
        started_perf = getattr(self, "_export_started_perf", None)
        diagnostics.log(
            "export_finished",
            duration_ms=(
                (time.perf_counter() - started_perf) * 1000.0 if started_perf else 0.0
            ),
            ok=int(error is None),
        )

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
        record_export_history(
            {
                "path": str(output_path),
                "report": str(report_path) if report_path else "",
                "label": getattr(getattr(self, "_export_worker_settings", None), "label", "")
                or self.project.project_name,
                "time": time.time(),
            }
        )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Export complete")
        box.setText(f"Saved MP4 export:\n{output_path}{warning_text}")
        reveal_mp4_btn = box.addButton("Reveal MP4", QMessageBox.ButtonRole.ActionRole)
        reveal_report_btn = None
        if report_path is not None:
            reveal_report_btn = box.addButton(
                "Reveal Report", QMessageBox.ButtonRole.ActionRole
            )
        box.addButton(QMessageBox.StandardButton.Ok)
        box.setDefaultButton(QMessageBox.StandardButton.Ok)
        box.exec()
        clicked = box.clickedButton()
        if clicked is reveal_mp4_btn:
            self._reveal_path(Path(output_path))
        elif reveal_report_btn is not None and clicked is reveal_report_btn:
            self._reveal_path(report_path)
        self.statusBar().showMessage(f"Exported {output_path}", 5000)

    @staticmethod
    def _reveal_path(path: Path) -> None:
        """Show the file selected in Finder/Explorer; fall back to opening the
        enclosing folder where selection isn't supported."""
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", "-R", str(path)], check=False)
                return
            if sys.platform == "win32":
                subprocess.run(["explorer", f"/select,{path}"], check=False)
                return
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

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
            f"Audio reviewed for spoken PHI: {project.audio_reviewed_for_phi}",
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
        # Half-open interval to match the exporter, so preview and export agree
        # on which clip owns a boundary frame.
        for clip in self.project.clips:
            start = clip.start_time
            end = clip.start_time + clip.display_duration
            if start <= time_s < end:
                return clip
        return None

    def _slide_at_time(self, time_s: float):
        for slide in reversed(self.project.slides):
            if slide.start_time <= time_s < slide.start_time + slide.duration:
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
        diagnostics.log("panel_switch", panel=panel)
        self._mark_dirty(history=False)

    def _toggle_diagnostics(self, checked: bool) -> None:
        diagnostics.set_enabled(checked)
        QSettings("NeuroEdit", "Desktop").setValue("diagnostics/enabled", checked)
        self.reveal_diagnostics_action.setEnabled(checked)
        if checked:
            self.statusBar().showMessage(
                f"Performance diagnostics on — logging to {diagnostics.log_path()}", 8000
            )
        else:
            self.statusBar().showMessage("Performance diagnostics off", 4000)

    # Draw-tool settings are transient UI state (see _TRANSIENT_SNAPSHOT_KEYS):
    # mark dirty for autosave, but never create or clobber undo history.

    def _set_color_from_swatch(self, color: str) -> None:
        self.project.draw_color = color
        self._mark_dirty(history=False)

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(QColor(self.project.draw_color), self, "Annotation Color")
        if color.isValid():
            self.project.draw_color = color.name()
            self._mark_dirty(history=False)

    def _label_changed(self, value: str) -> None:
        self.project.draw_label = value
        preset_color = next((color for label, color in ANATOMY_PRESETS if label == value), None)
        if preset_color is not None:
            self.project.draw_color = preset_color
            self.project.active_tool = "arrow"
        self._mark_dirty(history=False)

    def _apply_label_preset(self, label: str, color: str) -> None:
        self.project.draw_label = label
        self.project.draw_color = color
        self.project.active_tool = "arrow"
        self.project.active_panel = "labels"
        self._mark_dirty(history=False)

    def _width_changed(self, value: int) -> None:
        self.project.draw_width = value
        self.width_label.setText(f"{value}px")
        self._mark_dirty(history=False)

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
        self.project.duration = self._project_end_time()
        time_s = max(0.0, min(time_s, self.project.duration))
        self.project.current_time = time_s
        self._sync_player_to_timeline(play=self._timeline_playing)
        self.timeline.refresh()
        self.video_view.update_annotations()
        self.time_label.setText(format_time(self.project.current_time))

    def _position_changed(self, position_ms: int) -> None:
        # The monotonic timeline clock drives playback so variable-frame-rate
        # media cannot make the playhead pause and jump between sparse frame
        # timestamps. Ignore position events while timeline playback is active,
        # and also ignore them when
        # the source is cleared (entering a still/gap), when a fresh source has
        # not yet been sought to its trim_start (_pending_seek_ms outstanding),
        # or when the player isn't actually playing. Otherwise the transient
        # reset QMediaPlayer emits around setSource/setPosition could snap the
        # playhead back to (start_time - trim_start) and loop the previous clip.
        if (
            self._timeline_playing
            or self._pending_seek_ms is not None
            or self.player.source().isEmpty()
            or self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
        ):
            return
        clip = self.project.active_clip
        if not clip:
            return
        self.project.current_time = clip.start_time + position_ms / 1000 - clip.trim_start
        slide = self._slide_at_time(self.project.current_time)
        if slide is not None and not slide.overlay:
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

        # A clip's source is still loading toward its deferred seek: hold the
        # playhead here for the few ms until _media_status_changed seeks+plays,
        # so we don't advance past it or re-issue a play() that starts at 0.
        if self._pending_seek_ms is not None:
            return

        previous_time = self.project.current_time
        active = self._clip_at_time(previous_time)
        active_slide = self._slide_at_time(previous_time)
        on_image = active is not None and active.media_type == "image"

        player_was_playing_video = (
            self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            and (active_slide is None or active_slide.overlay)
            and not on_image
        )

        self.project.duration = self._project_end_time()
        next_time = self.project.current_time + elapsed * self.project.playback_rate
        if next_time >= self.project.duration:
            self.project.current_time = self.project.duration
            self._timeline_playing = False
            self.timeline_clock.stop()
            self.player.pause()
            self.play_button.setText("▶")
        else:
            self.project.current_time = next_time
            next_active = self._clip_at_time(self.project.current_time)
            next_slide = self._slide_at_time(self.project.current_time)
            if (
                not player_was_playing_video
                or (next_slide is not None and not next_slide.overlay)
                or next_active is None
                or active is None
                or next_active.id != active.id
            ):
                self._sync_player_to_timeline(play=True)
        self.timeline.refresh()
        self.video_view.update_annotations_for_time(previous_time, self.project.current_time)
        self.time_label.setText(format_time(self.project.current_time))

    def _sync_player_to_timeline(self, *, play: bool) -> None:
        slide = self._slide_at_time(self.project.current_time)
        clip = self._clip_at_time(self.project.current_time)
        if clip is None:
            # Nothing under the playhead (e.g. the clip there was deleted): stop
            # the player, drop its source, and clear the preview to black so the
            # deleted clip's last frame can't linger. A full-frame slide, if any,
            # still paints on top via the annotation layer.
            self.player.pause()
            if not self.player.source().isEmpty():
                self.player.setSource(QUrl())
            self.video_view.show_black()
            return
        if slide is not None and not slide.overlay:
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

        new_source = clip_changed or not self.video_view.video_item.isVisible()
        if new_source:
            self.video_view.set_image(None)
            self.player.setSource(QUrl.fromLocalFile(clip.path))
            self.player.setPlaybackRate(self.project.playback_rate)

        local_s = clip.trim_start + max(0.0, self.project.current_time - clip.start_time)
        target_ms = int(local_s * 1000)
        if new_source:
            # The fresh source can't be sought until it reports loaded; seeking
            # or playing now makes a trimmed clip start at 0. Defer both to
            # _media_status_changed so the clip enters at its trim_start.
            self._pending_seek_ms = target_ms
            self._pending_play = play
            self.player.pause()
            return
        self._pending_seek_ms = None
        if abs(self.player.position() - target_ms) > 80:
            self.player.setPosition(target_ms)
        if play:
            self.player.play()

    def _media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if self._pending_seek_ms is None:
            return
        if status in (
            QMediaPlayer.MediaStatus.NoMedia,
            QMediaPlayer.MediaStatus.InvalidMedia,
        ):
            self._pending_seek_ms = None
            self._pending_play = False
            return
        if status not in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            return
        self.player.setPosition(self._pending_seek_ms)
        self._pending_seek_ms = None
        if self._pending_play and self._timeline_playing:
            self.player.play()
        self._pending_play = False

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

    def _set_annotation_visibility(self, annotation_id: str, visible: bool) -> None:
        ann = self._find_annotation(annotation_id)
        if ann is not None:
            ann.visible = bool(visible)
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
        # Fires on every mouse-move of a canvas drag — keep it cheap. The canvas
        # repaints itself, and neither the Labels list nor the timeline renders
        # annotation geometry, so rebuilding them per move only made drags
        # stutter. The full refresh happens once on edit_committed.
        self.dirty = True
        self._autosave_snapshot = None
        self._update_title()

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
        self._sam_stage = stage
        self._sam_stage_start = time.monotonic()
        self.sam_panel.set_status(f"{stage} (0s)")
        if not hasattr(self, "_sam_heartbeat_timer"):
            self._sam_heartbeat_timer = QTimer(self)
            self._sam_heartbeat_timer.setInterval(500)
            self._sam_heartbeat_timer.timeout.connect(self._tick_sam_heartbeat)
        self._sam_heartbeat_timer.start()

    def _tick_sam_heartbeat(self) -> None:
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

    def _cancel_sam_jobs(self) -> None:
        """Cooperative cancel of whichever SAM worker is running. The download
        worker has no cancel hook (HF transfer is not interruptible), hence the
        getattr guard."""
        for worker_attr in (
            "_sam_segment_worker",
            "_sam_propagation_worker",
            "_sam_probe_worker",
            "_sam_download_worker",
        ):
            worker = getattr(self, worker_attr, None)
            cancel = getattr(worker, "cancel", None)
            if worker is not None and callable(cancel):
                cancel()
                self.statusBar().showMessage("SAM: cancel requested…", 3000)

    def _load_sam_backend(self) -> None:
        # Guard against double-calls while a probe is already in flight
        if getattr(self, "_sam_probe_thread", None) is not None:
            return
        self.sam_panel.set_status("Loading SAM backend… (importing PyTorch)")
        self.sam_panel.set_busy(True)
        self.statusBar().showMessage("Loading SAM backend…")
        diagnostics.log("sam_job", job="probe", state="started")

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
        diagnostics.log("sam_job", job="probe", state="finished", status=info.status)
        cached = self.sam_backend.is_weights_cached()
        self.sam_panel.set_weights_cached(cached)
        if info.status == "missing":
            # Torch / transformers not importable: explain SAM instead of only
            # showing the raw import error.
            self.sam_panel.show_backend_explainer(deps_missing=True)
        elif info.status == "ready" and not cached:
            self.sam_panel.show_backend_explainer(deps_missing=False)
        else:
            self.sam_panel.show_backend_ready()
        if info.status == "ready" and not cached:
            # The inline explainer (with its Download Weights button) is the
            # single setup entry point; auto-opening SamSetupDialog on top of
            # it produced two competing prompts for the same action.
            self.sam_panel.set_status(
                "SAM3 weights not downloaded yet — use Download Weights below."
            )
            self.sam_panel.set_busy(False)
            self.statusBar().showMessage("SAM3 weights not downloaded", 4000)
            return
        label = {
            "ready": info.message or f"SAM ready ({info.device})",
            "unsupported": f"SAM on CPU — {info.message}",
            "missing": f"SAM unavailable — {info.message}",
        }.get(info.status, info.message)
        self.sam_panel.set_status(label)
        self.sam_panel.set_busy(False)
        self.statusBar().showMessage(f"SAM backend: {info.status}", 4000)

    def _show_sam_install_help(self) -> None:
        # There is no in-app installer for the optional SAM stack; point the
        # user at the documented one-line install instead.
        QMessageBox.information(
            self,
            "Install SAM dependencies",
            "The AI components SAM needs (PyTorch + Transformers) are not "
            "installed in this copy of NeuroEdit.\n\n"
            "From a terminal, run:\n\n"
            '    pip install -e ".[sam]"\n\n'
            "from the NeuroEdit desktop folder, then restart NeuroEdit and "
            "reopen the SAM panel.",
        )

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
        diagnostics.log("sam_job", job="download", state="started")
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
        diagnostics.log("sam_job", job="download", state="finished", status=info.status)
        cached = self.sam_backend.is_weights_cached()
        self.sam_panel.set_weights_cached(cached)
        if info.status == "ready":
            self.sam_panel.show_backend_ready()
            self.sam_panel.set_status(info.message or f"SAM3 ready ({info.device})")
            self.statusBar().showMessage("SAM3 ready", 4000)
        else:
            self.sam_panel.set_status(f"Download failed: {info.message}")
            self.statusBar().showMessage("SAM3 download failed", 5000)
        self.sam_panel.set_busy(False)

    def _delete_sam_weights(self) -> None:
        import shutil
        cache = self.sam_backend.weights_cache_dir()
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
        self._sam_run_started_iso = datetime.datetime.now().isoformat(timespec="seconds")
        self._sam_run_start_monotonic = time.monotonic()
        diagnostics.log(
            "sam_job", job="segment", state="started",
            points=len(self.project.sam_points),
        )

        mask_dir = self.store.project_path.parent / "masks"
        self._pending_mask_color = self._next_mask_color()
        self._pending_prompt_points = self._current_prompt_points()
        self._sam_segment_thread = QThread(self)
        self._sam_segment_worker = SamSegmentWorker(
            self.sam_backend,
            Path(clip.path),
            self.project.current_time,
            list(self.project.sam_points),
            mask_dir,
            mask_color=hex_to_rgb(self._pending_mask_color),
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
            # Single-frame runs stamp sam_last_run just like propagation, so
            # the SAM panel's "Last run" row reflects whichever ran last.
            self.project.sam_last_run = self._sam_run_record("error", 0, "", str(error))
            diagnostics.log("sam_job", job="segment", state="finished", ok=0)
            self.sam_panel.set_status(f"Segmentation failed: {error}")
            self.statusBar().showMessage("SAM: segmentation failed", 5000)
            self._mark_dirty(history=False)
            QMessageBox.critical(self, "SAM segmentation failed", str(error))
            return
        if result is None:
            diagnostics.log("sam_job", job="segment", state="finished", ok=0)
            return
        annotation = Annotation(
            id=new_id(),
            frame_time=self.project.current_time,
            ann_duration=0.0,
            type="mask",
            label=self.project.draw_label or f"Mask {self._mask_count() + 1}",
            color=getattr(self, "_pending_mask_color", self.project.draw_color),
            visible=True,
            opacity=0.55,
            geometry={},
            mask_path=str(result.mask_path),
            score=float(result.score),
            prompt_points=list(getattr(self, "_pending_prompt_points", [])),
        )
        self.project.annotations.append(annotation)
        self.project.sam_last_run = self._sam_run_record("success", 1, result.backend, "")
        diagnostics.log("sam_job", job="segment", state="finished", ok=1)
        self.video_view.annotation_item.invalidate_mask_cache()
        self.sam_panel.set_status(f"{result.backend} mask saved (score {result.score:.2f})")
        self.statusBar().showMessage(
            f"SAM: {result.backend} mask saved (score {result.score:.2f})",
            4000,
        )
        self._mark_dirty()

    def _mask_count(self) -> int:
        return sum(1 for a in self.project.annotations if a.type in ("mask", "tracked-mask"))

    def _next_mask_color(self) -> str:
        return MASK_PALETTE[self._mask_count() % len(MASK_PALETTE)]

    def _current_prompt_points(self) -> list[dict]:
        return [
            {"x": float(p.x), "y": float(p.y), "type": p.type}
            for p in self.project.sam_points
        ]

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

        remaining = clip.start_time + clip.display_duration - self.project.current_time
        duration_s = propagation_window_s(
            remaining,
            self.sam_panel.track_to_end_check.isChecked(),
            float(self.sam_panel.track_window_spin.value()),
        )
        self._retrack_target_id = None
        self._pending_prompt_points = self._current_prompt_points()
        self._start_propagation(
            Path(clip.path),
            self.project.current_time,
            duration_s,
            list(self.project.sam_points),
            self._next_mask_color(),
        )

    def _retrack_mask(self, annotation_id: str) -> None:
        """Explicit re-run of propagation for an existing tracked mask, replacing
        its frames in place. Never triggered automatically."""
        ann = self._find_annotation(annotation_id)
        if ann is None or ann.type != "tracked-mask":
            return
        if not ann.prompt_points:
            QMessageBox.information(
                self, "Re-track unavailable",
                "This mask was created before NeuroEdit saved prompt points with "
                "masks, so it cannot be re-tracked. Place new SAM points and run "
                "Video Propagation instead.",
            )
            return
        clip = self.project.active_clip
        if not clip:
            QMessageBox.information(self, "No video", "Import a video before re-tracking.")
            return
        if getattr(self, "_sam_propagation_thread", None) is not None:
            return
        points = [
            SamPoint(
                x=float(p.get("x", 0.0)),
                y=float(p.get("y", 0.0)),
                type="negative" if p.get("type") == "negative" else "positive",
            )
            for p in ann.prompt_points
        ]
        self._retrack_target_id = ann.id
        self._pending_prompt_points = list(ann.prompt_points)
        self._start_propagation(
            Path(clip.path),
            ann.frame_time,
            max(1.0, ann.ann_duration or 5.0),
            points,
            ann.color,
        )

    def _start_propagation(
        self,
        video_path: Path,
        start_time_s: float,
        duration_s: float,
        points: list[SamPoint],
        mask_color_hex: str,
    ) -> None:
        self._pending_mask_color = mask_color_hex
        self._sam_run_started_iso = datetime.datetime.now().isoformat(timespec="seconds")
        self._sam_run_start_monotonic = time.monotonic()
        self.sam_panel.set_status(
            f"Tracking {format_time(start_time_s)} → {format_time(start_time_s + duration_s)}…"
        )
        self.sam_panel.set_busy(True)
        self.statusBar().showMessage("SAM: running video propagation…")
        diagnostics.log(
            "sam_job", job="propagate", state="started",
            window_s=f"{duration_s:.1f}",
        )

        mask_dir = self.store.project_path.parent / "masks"
        self._sam_propagation_thread = QThread(self)
        self._sam_propagation_worker = SamPropagationWorker(
            self.sam_backend,
            video_path,
            start_time_s,
            duration_s=duration_s,
            points=points,
            mask_dir=mask_dir,
            sample_rate=2.0,
            mask_color=hex_to_rgb(mask_color_hex),
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

    def _sam_run_record(self, result: str, frames: int, backend: str, message: str) -> dict:
        elapsed = time.monotonic() - getattr(self, "_sam_run_start_monotonic", time.monotonic())
        return {
            "started_iso": getattr(self, "_sam_run_started_iso", ""),
            "duration_s": round(elapsed, 1),
            "frames": frames,
            "result": result,
            "backend": backend,
            "message": message,
        }

    def _on_propagation_finished(self, result, error) -> None:  # type: ignore[no-untyped-def]
        self._stop_sam_heartbeat()
        self._sam_propagation_thread = None
        self._sam_propagation_worker = None
        self.sam_panel.set_busy(False)
        diagnostics.log(
            "sam_job", job="propagate", state="finished",
            ok=int(error is None and result is not None and bool(result.mask_frames)),
        )
        retrack_id = getattr(self, "_retrack_target_id", None)
        self._retrack_target_id = None

        if error:
            self.project.sam_last_run = self._sam_run_record("error", 0, "", str(error))
            self.sam_panel.set_status(f"Propagation failed: {error}")
            self.statusBar().showMessage("SAM: propagation failed", 5000)
            self._mark_dirty(history=False)
            QMessageBox.critical(self, "SAM propagation failed", str(error))
            return
        if result is None or not result.mask_frames:
            self.project.sam_last_run = self._sam_run_record(
                "canceled", 0, "", "Propagation canceled."
            )
            self._mark_dirty(history=False)
            return

        first_time = float(result.mask_frames[0]["time"])
        last_time = float(result.mask_frames[-1]["time"])
        frame_step = 1.0 / result.sample_rate
        ann_duration = max(frame_step, last_time - first_time + frame_step)
        target = self._find_annotation(retrack_id) if retrack_id else None
        if target is not None:
            # Re-track: regenerate the existing annotation's frames in place,
            # keeping its id, label, and color.
            target.frame_time = first_time
            target.ann_duration = ann_duration
            target.mask_path = str(result.mask_frames[0]["mask_path"])
            target.mask_frames = result.mask_frames
            target.score = float(result.score)
            target.sample_rate = float(result.sample_rate)
        else:
            annotation = Annotation(
                id=new_id(),
                frame_time=first_time,
                ann_duration=ann_duration,
                type="tracked-mask",
                label=self.project.draw_label or f"Mask {self._mask_count() + 1}",
                color=getattr(self, "_pending_mask_color", self.project.draw_color),
                visible=True,
                opacity=0.55,
                geometry={},
                mask_path=str(result.mask_frames[0]["mask_path"]),
                mask_frames=result.mask_frames,
                score=float(result.score),
                sample_rate=float(result.sample_rate),
                prompt_points=list(getattr(self, "_pending_prompt_points", [])),
            )
            self.project.annotations.append(annotation)
            self.project.sam_points.clear()
            self.project.active_panel = "labels"
        self.project.sam_last_run = self._sam_run_record(
            "success", len(result.mask_frames), result.backend, ""
        )
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

    def _cleanup_orphan_masks(self) -> None:
        """Delete mask PNGs no longer referenced by the project or any undo/redo
        snapshot. Runs only at close so deleting a mask annotation stays undoable
        for the whole session."""
        masks_dir = self.store.project_path.parent / "masks"
        history_snapshots = [
            json.loads(snapshot) for snapshot in (*self._undo_stack, *self._redo_stack)
        ]
        snapshots = [self.project.to_dict(), *history_snapshots]
        delete_orphan_masks(masks_dir, referenced_mask_paths(snapshots))

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
        # Workers are stopped, so no new mask files can appear mid-scan.
        try:
            self._cleanup_orphan_masks()
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(event)
