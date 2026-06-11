from __future__ import annotations

import math
import re
import subprocess
import time
import wave
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QDir, QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtMultimedia import (
    QAudioInput,
    QMediaCaptureSession,
    QMediaDevices,
    QMediaRecorder,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileSystemModel,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTextEdit,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from neuroedit_desktop.models import (
    AudioTrack,
    ProjectState,
    Slide,
    TimelineMarker,
    TranscriptSegment,
    VideoClip,
    new_id,
)
from neuroedit_desktop.ui.styles import (
    ACCENT_AMBER,
    ACCENT_CYAN,
    ACCENT_EMERALD,
    ACCENT_RED,
    BG_CARD,
    BG_PRIMARY,
    BG_SECONDARY,
    BG_TERTIARY,
    BORDER,
    BORDER_BRIGHT,
    PRIMARY,
    SELECTION_OUTLINE,
    TEXT_DIM,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)


def fmt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes = int(seconds // 60)
    remainder = seconds % 60
    return f"{minutes}:{remainder:04.1f}"


def project_end_time(project: ProjectState) -> float:
    # Content ends only. Feeding project.duration or current_time back in here
    # let the timeline end ratchet upward one second per seek-to-end (the seek
    # clamp uses this value), which then padded exports with a black tail.
    ends: list[float] = []
    ends.extend(clip.start_time + clip.display_duration for clip in project.clips)
    ends.extend(track.start_time + max(0.1, track.duration) for track in project.audio_tracks)
    ends.extend(slide.start_time + max(0.1, slide.duration) for slide in project.slides)
    ends.extend(marker.time + 1.0 for marker in project.markers)
    return max(1.0, max(ends, default=1.0))


class MediaExplorerPanel(QWidget):
    import_videos_requested = Signal()
    import_images_requested = Signal()
    file_import_requested = Signal(str)
    clip_selected = Signal(str)

    MEDIA_NAME_FILTERS = [
        "*.mp4", "*.mov", "*.m4v", "*.avi", "*.webm",
        "*.png", "*.jpg", "*.jpeg", "*.heic", "*.bmp", "*.webp",
    ]

    def __init__(self, project: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.setObjectName("mediaExplorer")
        self.setMinimumWidth(230)

        title = QLabel("Media Explorer")
        title.setProperty("role", "title")
        hint = QLabel("Double-click files to import, or clips to jump to them.")
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)

        import_video = QPushButton("Import Videos")
        import_video.setProperty("variant", "primary")
        import_image = QPushButton("Import Images")
        import_image.setProperty("variant", "cyan")
        import_video.clicked.connect(lambda _checked=False: self.import_videos_requested.emit())
        import_image.clicked.connect(lambda _checked=False: self.import_images_requested.emit())

        import_row = QVBoxLayout()
        import_row.setSpacing(6)
        import_row.addWidget(import_video)
        import_row.addWidget(import_image)

        self.clip_list = QListWidget()
        self.clip_list.itemDoubleClicked.connect(self._clip_activated)

        select_clip = QPushButton("Jump to Selected Clip")
        select_clip.clicked.connect(self._select_current_clip)

        self.path_label = QLabel("")
        self.path_label.setProperty("role", "muted")
        self.path_label.setWordWrap(True)

        home_btn = QPushButton("Home")
        movies_btn = QPushButton("Movies")
        up_btn = QPushButton("Up")
        home_btn.clicked.connect(lambda: self._set_root(Path.home()))
        movies_btn.clicked.connect(lambda: self._set_root(Path.home() / "Movies"))
        up_btn.clicked.connect(self._go_up)

        nav_row = QHBoxLayout()
        nav_row.setSpacing(6)
        nav_row.addWidget(home_btn)
        nav_row.addWidget(movies_btn)
        nav_row.addWidget(up_btn)

        self.file_model = QFileSystemModel(self)
        self.file_model.setFilter(
            QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot
        )
        self.file_model.setNameFilters(self.MEDIA_NAME_FILTERS)
        self.file_model.setNameFilterDisables(False)
        self.file_model.setRootPath(str(Path.home()))

        self.file_tree = QTreeView()
        self.file_tree.setModel(self.file_model)
        self.file_tree.setHeaderHidden(True)
        self.file_tree.setAnimated(True)
        self.file_tree.doubleClicked.connect(self._file_activated)
        for column in range(1, self.file_model.columnCount()):
            self.file_tree.hideColumn(column)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addLayout(import_row)
        section = QLabel("Timeline Media")
        section.setProperty("role", "muted")
        layout.addWidget(section)
        layout.addWidget(self.clip_list, 1)
        layout.addWidget(select_clip)
        files = QLabel("Files")
        files.setProperty("role", "muted")
        layout.addWidget(files)
        layout.addLayout(nav_row)
        layout.addWidget(self.path_label)
        layout.addWidget(self.file_tree, 2)

        root = Path.home() / "Movies"
        self._set_root(root if root.exists() else Path.home())
        self.refresh()

    def set_project(self, project: ProjectState) -> None:
        self.project = project
        self.refresh()

    def refresh(self) -> None:
        selected = self.project.active_clip_id
        self.clip_list.clear()
        for clip in sorted(self.project.clips, key=lambda c: c.start_time):
            end = clip.start_time + clip.display_duration
            item = QListWidgetItem(
                f"{clip.name}\n{fmt_time(clip.start_time)} - {fmt_time(end)}"
                f"  ({fmt_time(clip.display_duration)})"
            )
            item.setToolTip(clip.path)
            item.setData(Qt.ItemDataRole.UserRole, clip.id)
            self.clip_list.addItem(item)
            if clip.id == selected:
                self.clip_list.setCurrentItem(item)

    def _selected_clip_id(self) -> str | None:
        item = self.clip_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _clip_activated(self, item: QListWidgetItem) -> None:
        self.clip_selected.emit(str(item.data(Qt.ItemDataRole.UserRole)))

    def _select_current_clip(self) -> None:
        clip_id = self._selected_clip_id()
        if clip_id:
            self.clip_selected.emit(clip_id)

    def _set_root(self, path: Path) -> None:
        if not path.exists():
            path = Path.home()
        self._root_path = path
        self.file_tree.setRootIndex(self.file_model.index(str(path)))
        self.path_label.setText(str(path))

    def _go_up(self) -> None:
        root = getattr(self, "_root_path", Path.home())
        parent = root.parent if root.parent != root else root
        self._set_root(parent)

    def _file_activated(self, index) -> None:
        path = Path(self.file_model.filePath(index))
        if path.is_dir():
            self._set_root(path)
            return
        self.file_import_requested.emit(str(path))


class TimelineCanvas(QWidget):
    seek_requested = Signal(float)
    project_changed = Signal()
    item_activated = Signal(str, str)  # (kind, item_id)

    LABEL_W = 92
    RULER_H = 30
    TRACK_H = 46
    TRACKS: list[tuple[str, str, str]] = [
        ("video", "Video", PRIMARY),
        ("audio", "Audio", ACCENT_RED),
        ("slides", "Slides", "#8b5cf6"),
        ("markers", "Markers", ACCENT_AMBER),
    ]

    HANDLE_PX = 6
    MARKER_HIT_PX = 12
    SNAP_PX = 10.0

    def __init__(self, project: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self._drag: tuple[str, str, float, float] | None = None
        self._slide_lanes_key: tuple | None = None
        self._slide_lanes_value: dict[str, int] = {}
        # Widget-level selection only — never serialized or snapshotted.
        self.selected_item: tuple[str, str] | None = None  # (kind, item_id)
        self.snap_enabled = True
        self.setMouseTracking(True)
        self.refresh_geometry()

    def set_project(self, project: ProjectState) -> None:
        self.project = project
        self._prune_selection()
        self.refresh_geometry()
        self.update()

    def refresh_geometry(self) -> None:
        self._prune_selection()
        width = int(self.LABEL_W + project_end_time(self.project) * self.project.zoom + 420)
        height = self.RULER_H + sum(self._track_heights())
        self.setMinimumSize(max(width, 900), height)
        self.resize(max(width, 900), height)

    def _prune_selection(self) -> None:
        if self.selected_item is None:
            return
        kind, item_id = self.selected_item
        pools = {
            "clip": self.project.clips,
            "audio": self.project.audio_tracks,
            "slide": self.project.slides,
            "marker": self.project.markers,
        }
        if not any(item.id == item_id for item in pools.get(kind, [])):
            self.selected_item = None

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(BG_SECONDARY))

        # Floor must match the hit-test floor (1.0) or paint and clicks disagree
        # once zoom-to-fit drops below the old 10 px/s minimum.
        zoom = max(1.0, self.project.zoom)
        end_time = project_end_time(self.project)
        width = self.width()

        painter.fillRect(QRectF(0, 0, width, self.RULER_H), QColor(BG_TERTIARY))
        painter.fillRect(QRectF(0, 0, self.LABEL_W, self.height()), QColor(BG_TERTIARY))
        painter.setPen(QPen(QColor(BORDER), 1))
        painter.drawLine(0, self.RULER_H, width, self.RULER_H)
        painter.drawLine(self.LABEL_W, 0, self.LABEL_W, self.height())

        self._paint_ruler(painter, zoom, end_time)
        self._paint_tracks(painter, zoom)
        self._paint_playhead(painter, zoom)

    def _paint_ruler(self, painter: QPainter, zoom: float, end_time: float) -> None:
        step = 1 if zoom >= 150 else 5 if zoom >= 60 else 10 if zoom >= 30 else 30
        painter.setFont(self.font())
        for tick in range(0, int(math.ceil(end_time + step)), step):
            x = self.LABEL_W + tick * zoom
            painter.setPen(QPen(QColor(BORDER_BRIGHT), 1))
            painter.drawLine(QPointF(x, 0), QPointF(x, 12))
            painter.setPen(QColor(TEXT_DIM))
            painter.drawText(QRectF(x - 22, 13, 44, 14), Qt.AlignmentFlag.AlignCenter, fmt_time(tick))

    def _paint_tracks(self, painter: QPainter, zoom: float) -> None:
        heights = self._track_heights()
        for idx, (_key, label, color) in enumerate(self.TRACKS):
            track_h = heights[idx]
            y = self._track_y(idx, heights)
            painter.fillRect(
                QRectF(0, y, self.width(), track_h),
                QColor(BG_PRIMARY if idx % 2 else BG_SECONDARY),
            )
            painter.setPen(QPen(QColor(BORDER), 1))
            painter.drawLine(0, y + track_h, self.width(), y + track_h)
            painter.setPen(QColor(color))
            painter.drawText(QRectF(10, y, self.LABEL_W - 18, track_h), Qt.AlignmentFlag.AlignVCenter, label)

        self._paint_video_blocks(painter, zoom)
        self._paint_audio_blocks(painter, zoom)
        self._paint_slide_blocks(painter, zoom)
        self._paint_markers(painter, zoom)

    def _block_rect(self, start: float, duration: float, track_idx: int, zoom: float) -> QRectF:
        x = self.LABEL_W + start * zoom
        y = self._track_y(track_idx) + 6
        return QRectF(x, y, max(28.0, duration * zoom), self.TRACK_H - 12)

    def _track_heights(self) -> list[int]:
        heights = [self.TRACK_H for _track in self.TRACKS]
        heights[2] = max(self.TRACK_H, self.TRACK_H * self._slide_lane_count())
        return heights

    def _track_y(self, track_idx: int, heights: list[int] | None = None) -> int:
        heights = heights or self._track_heights()
        return self.RULER_H + sum(heights[:track_idx])

    def _slide_lanes(self) -> dict[str, int]:
        # Memoized on slide geometry: paint and hit-testing call this once per
        # slide, which made each repaint O(slides^2) without the cache.
        key = tuple(
            (slide.id, round(slide.start_time, 3), round(slide.duration, 3))
            for slide in self.project.slides
        )
        if key == self._slide_lanes_key:
            return self._slide_lanes_value
        lanes: list[float] = []
        assigned: dict[str, int] = {}
        ordered = sorted(self.project.slides, key=lambda slide: (slide.start_time, slide.id))
        for slide in ordered:
            start = slide.start_time
            end = slide.start_time + max(0.25, slide.duration)
            for lane, lane_end in enumerate(lanes):
                if start >= lane_end - 0.001:
                    lanes[lane] = end
                    assigned[slide.id] = lane
                    break
            else:
                assigned[slide.id] = len(lanes)
                lanes.append(end)
        self._slide_lanes_key = key
        self._slide_lanes_value = assigned
        return assigned

    def _slide_lane_count(self) -> int:
        lanes = self._slide_lanes()
        return max(1, max(lanes.values(), default=0) + 1)

    def _slide_block_rect(self, slide: Slide, zoom: float) -> QRectF:
        lane = self._slide_lanes().get(slide.id, 0)
        x = self.LABEL_W + slide.start_time * zoom
        y = self._track_y(2) + lane * self.TRACK_H + 6
        return QRectF(x, y, max(28.0, max(0.25, slide.duration) * zoom), self.TRACK_H - 12)

    def _paint_block(
        self,
        painter: QPainter,
        rect: QRectF,
        label: str,
        color: str,
        fill_alpha: int = 46,
        *,
        selected: bool = False,
    ) -> None:
        fill = QColor(color).lighter(112) if selected else QColor(color)
        fill.setAlpha(fill_alpha)
        painter.setPen(QPen(QColor(color), 1.3))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 8, 8)
        if selected:
            painter.setPen(QPen(QColor(SELECTION_OUTLINE), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 8, 8)
        painter.setPen(QColor(TEXT_PRIMARY))
        text_rect = rect.adjusted(8, 0, -8, 0)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, label)

    def _paint_video_blocks(self, painter: QPainter, zoom: float) -> None:
        dragged_id = (
            self._drag[1]
            if self._drag is not None and self._drag[0].startswith("clip")
            else None
        )
        dragged_clip = None
        for clip in self.project.clips:
            if clip.id == dragged_id:
                dragged_clip = clip
                continue
            self._paint_video_clip(painter, clip, zoom, dragging=False)
        if dragged_clip is not None:
            self._paint_video_clip(painter, dragged_clip, zoom, dragging=True)

    def _paint_video_clip(
        self,
        painter: QPainter,
        clip: VideoClip,
        zoom: float,
        *,
        dragging: bool,
    ) -> None:
        rect = self._block_rect(clip.start_time, clip.display_duration, 0, zoom)
        active = clip.id == self.project.active_clip_id
        if dragging:
            glow = rect.adjusted(-7, -7, 7, 7)
            glow_color = QColor(ACCENT_CYAN)
            glow_color.setAlpha(55)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow_color)
            painter.drawRoundedRect(glow, 11, 11)
            rect = rect.adjusted(-4, -4, 4, 4)
        color = ACCENT_CYAN if dragging else PRIMARY
        fill_alpha = 110 if dragging else 70 if active else 46
        selected = self.selected_item == ("clip", clip.id)
        self._paint_block(painter, rect, clip.name, color, fill_alpha, selected=selected)
        max_clip_s, _guidance = recommended_continuous_clip_seconds(self.project)
        if clip.media_type == "video" and clip.display_duration > max_clip_s:
            painter.setPen(QPen(QColor(ACCENT_RED), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 8, 8)
            painter.setPen(QColor(ACCENT_RED))
            painter.drawText(
                rect.adjusted(8, 4, -8, -4),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                "over guidance",
            )
        # Trim-handle accents at left and right edges.
        handle_color = QColor("#ffffff")
        handle_color.setAlpha(190 if dragging else 140)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(handle_color)
        h = self.HANDLE_PX + (2 if dragging else 0)
        painter.drawRect(QRectF(rect.left(), rect.top() + 4, h, rect.height() - 8))
        painter.drawRect(QRectF(rect.right() - h, rect.top() + 4, h, rect.height() - 8))
        if active or dragging:
            painter.setPen(QPen(QColor("#ffffff"), 2 if dragging else 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 8, 8)

    def _paint_audio_blocks(self, painter: QPainter, zoom: float) -> None:
        for track in self.project.audio_tracks:
            rect = self._block_rect(track.start_time, max(0.25, track.duration), 1, zoom)
            selected = self.selected_item == ("audio", track.id)
            self._paint_block(painter, rect, track.name, ACCENT_RED, 42, selected=selected)
            painter.setPen(QPen(QColor(ACCENT_RED), 1))
            bars = max(6, min(42, int(rect.width() / 8)))
            for idx in range(bars):
                x = rect.left() + 8 + idx * 7
                bar_h = 6 + (idx % 5) * 3
                painter.drawLine(
                    QPointF(x, rect.center().y() - bar_h / 2),
                    QPointF(x, rect.center().y() + bar_h / 2),
                )

    def _paint_slide_blocks(self, painter: QPainter, zoom: float) -> None:
        for slide in self.project.slides:
            rect = self._slide_block_rect(slide, zoom)
            selected = self.selected_item == ("slide", slide.id)
            self._paint_block(
                painter, rect, slide.title or "(untitled slide)", "#8b5cf6", 42, selected=selected
            )

    def _paint_markers(self, painter: QPainter, zoom: float) -> None:
        y_top = self._track_y(3)
        for marker in self.project.markers:
            x = self.LABEL_W + marker.time * zoom
            color = QColor(marker.color)
            if self.selected_item == ("marker", marker.id):
                color = color.lighter(112)
                painter.setPen(QPen(QColor(SELECTION_OUTLINE), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(QRectF(x - 3, y_top + 2, 19, 16))
            painter.setPen(QPen(color, 2))
            painter.drawLine(QPointF(x, y_top + 6), QPointF(x, y_top + self.TRACK_H - 5))
            painter.setBrush(color)
            painter.drawPolygon([
                QPointF(x, y_top + 5),
                QPointF(x + 12, y_top + 10),
                QPointF(x, y_top + 15),
            ])
            painter.setPen(color)
            painter.drawText(QRectF(x + 5, y_top + 14, 150, 18), marker.label)

    def _paint_playhead(self, painter: QPainter, zoom: float) -> None:
        x = self.LABEL_W + self.project.current_time * zoom
        painter.setPen(QPen(QColor(ACCENT_RED), 2))
        painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        painter.setBrush(QColor(ACCENT_RED))
        painter.drawEllipse(QPointF(x, 4), 5, 5)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)

        pos = event.position()
        if pos.x() < self.LABEL_W:
            return
        time_s = max(0.0, (pos.x() - self.LABEL_W) / max(1.0, self.project.zoom))
        hit = self._hit_block(pos.x(), pos.y())
        if hit is not None:
            kind, item_id, offset = hit
            self.selected_item = ("clip" if kind.startswith("clip") else kind, item_id)
            origin_start = self._item_start_time(kind, item_id)
            self._drag = (kind, item_id, offset, origin_start)
            if kind.startswith("clip"):
                self.project.active_clip_id = item_id
                self.project_changed.emit()
            self.update()
            if kind in ("clip-trim-start", "clip-trim-end"):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        marker = self._hit_marker(pos.x(), pos.y())
        if marker is not None:
            self.selected_item = ("marker", marker.id)
            self.update()
            return
        if self.selected_item is not None:
            self.selected_item = None
            self.update()
        self.seek_requested.emit(min(time_s, project_end_time(self.project)))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag is None:
            self._update_hover_cursor(event.position())
            return super().mouseMoveEvent(event)
        kind, item_id, offset, origin_start = self._drag
        zoom = max(1.0, self.project.zoom)
        time_at = max(0.0, (event.position().x() - self.LABEL_W) / zoom)
        insert_direction = None
        # Shift bypasses snapping for the duration of the drag.
        snap = not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        base_kind = "clip" if kind.startswith("clip") else kind

        if kind == "clip":
            new_start = max(0.0, time_at - offset)
            if snap:
                new_start = self._snap_time(new_start, base_kind, item_id)
            if new_start < origin_start - 0.05:
                insert_direction = "left"
            elif new_start > origin_start + 0.05:
                insert_direction = "right"
            for clip in self.project.clips:
                if clip.id == item_id:
                    clip.start_time = new_start
                    break
        elif kind == "clip-trim-start":
            if snap:
                time_at = self._snap_time(time_at, base_kind, item_id)
            for clip in self.project.clips:
                if clip.id == item_id:
                    self._apply_trim_start(clip, time_at)
                    break
        elif kind == "clip-trim-end":
            if snap:
                time_at = self._snap_time(time_at, base_kind, item_id)
            for clip in self.project.clips:
                if clip.id == item_id:
                    self._apply_trim_end(clip, time_at)
                    break
        elif kind == "audio":
            new_start = max(0.0, time_at - offset)
            if snap:
                new_start = self._snap_time(new_start, base_kind, item_id)
            for track in self.project.audio_tracks:
                if track.id == item_id:
                    track.start_time = new_start
                    break
        elif kind == "slide":
            new_start = max(0.0, time_at - offset)
            if snap:
                new_start = self._snap_time(new_start, base_kind, item_id)
            for slide in self.project.slides:
                if slide.id == item_id:
                    slide.start_time = new_start
                    break

        if kind.startswith("clip"):
            self.project.arrange_clips_without_overlap(
                item_id,
                insert_anchor=time_at if kind == "clip" else None,
                insert_direction=insert_direction,
            )
        self.project.duration = project_end_time(self.project)
        self.refresh_geometry()
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        had_drag = self._drag is not None
        self._drag = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if had_drag:
            self.project_changed.emit()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mouseDoubleClickEvent(event)
        self._drag = None  # cancel drag started by the preceding mousePressEvent
        pos = event.position()
        if pos.x() < self.LABEL_W:
            return
        hit = self._hit_block(pos.x(), pos.y())
        if hit is not None:
            kind, item_id, _ = hit
            base_kind = "clip" if kind.startswith("clip") else kind
            self.item_activated.emit(base_kind, item_id)
            return
        marker = self._hit_marker(pos.x(), pos.y())
        if marker is not None:
            # Premiere convention: double-click edits the marker. Seeking to it
            # is still available by clicking the ruler at the marker position.
            self._edit_marker(marker)

    def _hit_marker(self, x: float, y: float) -> TimelineMarker | None:
        zoom = max(1.0, self.project.zoom)
        y_top = self._track_y(3)
        if not (y_top <= y <= y_top + self.TRACK_H):
            return None
        for marker in self.project.markers:
            mx = self.LABEL_W + marker.time * zoom
            if abs(x - mx) <= self.MARKER_HIT_PX:
                return marker
        return None

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        pos = event.pos()
        marker = self._hit_marker(pos.x(), pos.y())
        if marker is not None:
            menu = QMenu(self)
            edit_action = menu.addAction("Edit Marker…")
            delete_action = menu.addAction("Delete Marker")
            menu.addSeparator()
            delete_all_action = menu.addAction("Delete All Markers")
            chosen = menu.exec(event.globalPos())
            if chosen == edit_action:
                self._edit_marker(marker)
            elif chosen == delete_action:
                self._delete_marker(marker)
            elif chosen == delete_all_action:
                self._delete_all_markers()
            return
        hit = self._hit_block(pos.x(), pos.y())
        if hit is not None and hit[0].startswith("clip"):
            clip = next((c for c in self.project.clips if c.id == hit[1]), None)
            if clip is None:
                return
            menu = QMenu(self)
            rename_action = menu.addAction("Rename Clip…")
            if menu.exec(event.globalPos()) == rename_action:
                self._rename_clip(clip)

    def _edit_marker(self, marker: TimelineMarker) -> None:
        label, ok = QInputDialog.getText(self, "Edit Marker", "Marker label:", text=marker.label)
        if not ok or not label.strip():
            return
        marker.label = label.strip()
        self.update()
        self.project_changed.emit()

    def _delete_marker(self, marker: TimelineMarker) -> None:
        self.project.markers = [m for m in self.project.markers if m.id != marker.id]
        self._prune_selection()
        self.update()
        self.project_changed.emit()

    def _delete_all_markers(self) -> None:
        if not self.project.markers:
            return
        reply = QMessageBox.question(
            self,
            "Delete All Markers",
            f"Delete all {len(self.project.markers)} markers?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.project.markers = []
        self._prune_selection()
        self.update()
        self.project_changed.emit()

    def _rename_clip(self, clip: VideoClip) -> None:
        name, ok = QInputDialog.getText(self, "Rename Clip", "Clip name:", text=clip.name)
        if not ok or not name.strip():
            return
        clip.name = name.strip()
        self.update()
        self.project_changed.emit()

    def _snap_time(self, t: float, exclude_kind: str, exclude_id: str) -> float:
        """Snap `t` to the nearest target within SNAP_PX screen pixels.

        Targets: t=0, the playhead, clip/slide/audio edges, and marker times —
        excluding the dragged item itself. Pixel-space threshold so snapping
        does not fight fine adjustments at high zoom.
        """
        if not self.snap_enabled:
            return t
        threshold = self.SNAP_PX / max(1.0, self.project.zoom)
        targets: list[float] = [0.0, self.project.current_time]
        for clip in self.project.clips:
            if exclude_kind == "clip" and clip.id == exclude_id:
                continue
            targets.append(clip.start_time)
            targets.append(clip.start_time + clip.display_duration)
        for track in self.project.audio_tracks:
            if exclude_kind == "audio" and track.id == exclude_id:
                continue
            targets.append(track.start_time)
            targets.append(track.start_time + max(0.1, track.duration))
        for slide in self.project.slides:
            if exclude_kind == "slide" and slide.id == exclude_id:
                continue
            targets.append(slide.start_time)
            targets.append(slide.start_time + max(0.25, slide.duration))
        targets.extend(marker.time for marker in self.project.markers)
        best = min(targets, key=lambda target: abs(target - t))
        return best if abs(best - t) <= threshold else t

    def _update_hover_cursor(self, pos: QPointF) -> None:
        hit = self._hit_block(pos.x(), pos.y())
        if hit is not None and hit[0] in ("clip-trim-start", "clip-trim-end"):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def _item_start_time(self, kind: str, item_id: str) -> float:
        if kind.startswith("clip"):
            for clip in self.project.clips:
                if clip.id == item_id:
                    return clip.start_time
        if kind == "audio":
            for track in self.project.audio_tracks:
                if track.id == item_id:
                    return track.start_time
        if kind == "slide":
            for slide in self.project.slides:
                if slide.id == item_id:
                    return slide.start_time
        return 0.0

    def _apply_trim_start(self, clip, time_at: float) -> None:
        # Move the clip's left edge to `time_at` while keeping its right edge fixed.
        zoom_min_dur = 0.05
        old_right = clip.start_time + clip.display_duration
        time_at = max(0.0, min(time_at, old_right - zoom_min_dur))
        delta = time_at - clip.start_time  # >0 trims more from start
        new_trim_start = clip.trim_start + delta
        new_trim_start = max(0.0, min(new_trim_start, clip.trim_end - zoom_min_dur))
        clip.trim_start = new_trim_start
        clip.start_time = time_at

    def _apply_trim_end(self, clip, time_at: float) -> None:
        zoom_min_dur = 0.05
        time_at = max(clip.start_time + zoom_min_dur, time_at)
        new_duration = time_at - clip.start_time
        new_trim_end = clip.trim_start + new_duration
        if clip.duration > 0:
            new_trim_end = min(clip.duration, new_trim_end)
        clip.trim_end = max(clip.trim_start + zoom_min_dur, new_trim_end)

    def _hit_block(self, x: float, y: float) -> tuple[str, str, float] | None:
        zoom = max(1.0, self.project.zoom)
        h = self.HANDLE_PX
        for clip in self.project.clips:
            rect = self._block_rect(clip.start_time, clip.display_duration, 0, zoom)
            if not rect.contains(x, y):
                continue
            if rect.width() > h * 3 and x <= rect.left() + h:
                return "clip-trim-start", clip.id, 0.0
            if rect.width() > h * 3 and x >= rect.right() - h:
                return "clip-trim-end", clip.id, 0.0
            return "clip", clip.id, (x - rect.left()) / zoom
        for track in self.project.audio_tracks:
            rect = self._block_rect(track.start_time, max(0.25, track.duration), 1, zoom)
            if rect.contains(x, y):
                return "audio", track.id, (x - rect.left()) / zoom
        for slide in self.project.slides:
            rect = self._slide_block_rect(slide, zoom)
            if rect.contains(x, y):
                return "slide", slide.id, (x - rect.left()) / zoom
        return None


class RichTimelineWidget(QWidget):
    seek_requested = Signal(float)
    project_changed = Signal()
    item_activated = Signal(str, str)  # (kind, item_id)

    def __init__(self, project: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("timeline")
        self.project = project
        self.time_label = QLabel("0:00.0")
        self.time_label.setProperty("role", "muted")

        zoom_in = QPushButton("+")
        zoom_out = QPushButton("-")
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(2, 300)
        self.zoom_slider.setFixedWidth(160)
        self.zoom_slider.setValue(int(project.zoom))
        self.fit_btn = QPushButton("Fit")
        self.fit_btn.setToolTip("Zoom so the whole timeline fits (Shift+Z). Press again to go back.")
        self.snap_btn = QPushButton("Snap")
        self.snap_btn.setCheckable(True)
        self.snap_btn.setChecked(True)
        self.snap_btn.setToolTip(
            "Snap dragged blocks to the playhead, block edges, and markers "
            "(hold Shift while dragging to bypass)."
        )
        self._pre_fit_state: tuple[float, int] | None = None
        self.marker_btn = QPushButton("Mark")
        self.cut_btn = QPushButton("Cut")
        self.marker_btn.setProperty("variant", "amber")
        self.cut_btn.setProperty("variant", "cyan")

        # Active-clip transition spinners.
        self.fade_in_input = QDoubleSpinBox()
        self.fade_in_input.setRange(0.0, 5.0)
        self.fade_in_input.setSingleStep(0.25)
        self.fade_in_input.setSuffix(" s")
        self.fade_in_input.setToolTip("Fade-in duration on the active clip (0 = none).")
        self.fade_out_input = QDoubleSpinBox()
        self.fade_out_input.setRange(0.0, 5.0)
        self.fade_out_input.setSingleStep(0.25)
        self.fade_out_input.setSuffix(" s")
        self.fade_out_input.setToolTip("Fade-out duration on the active clip (0 = none).")
        self.fade_in_input.valueChanged.connect(lambda v: self._set_fade("in", v))
        self.fade_out_input.valueChanged.connect(lambda v: self._set_fade("out", v))

        self.fade_color_combo = QComboBox()
        self.fade_color_combo.setToolTip("Color the active clip fades to / from.")
        for label, value in [("Black", "#000000"), ("White", "#ffffff")]:
            self.fade_color_combo.addItem(label, value)
        self.fade_color_combo.currentIndexChanged.connect(self._fade_color_changed)

        zoom_in.clicked.connect(lambda: self._set_zoom(self.project.zoom * 1.25))
        zoom_out.clicked.connect(lambda: self._set_zoom(self.project.zoom * 0.8))
        self.zoom_slider.valueChanged.connect(lambda value: self._set_zoom(float(value)))
        self.fit_btn.clicked.connect(self._zoom_to_fit)
        self._fit_shortcut = QShortcut(QKeySequence("Shift+Z"), self)
        self._fit_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._fit_shortcut.activated.connect(self._zoom_to_fit)
        self.snap_btn.toggled.connect(self._snap_toggled)
        self.marker_btn.clicked.connect(self._add_marker)
        self.cut_btn.clicked.connect(self._cut_active_clip)

        toolbar_widget = QWidget()
        toolbar = QHBoxLayout(toolbar_widget)
        toolbar.setContentsMargins(10, 6, 10, 6)
        toolbar.setSpacing(8)
        title = QLabel("Timeline")
        title.setProperty("role", "title")
        toolbar.addWidget(title)
        toolbar.addWidget(self.time_label)
        toolbar.addSpacing(8)
        zoom_label = QLabel("Zoom")
        zoom_label.setProperty("role", "muted")
        toolbar.addWidget(zoom_label)
        toolbar.addWidget(zoom_out)
        toolbar.addWidget(self.zoom_slider)
        toolbar.addWidget(zoom_in)
        toolbar.addWidget(self.fit_btn)
        toolbar.addWidget(self.snap_btn)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setFixedWidth(1)
        sep.setFixedHeight(22)
        sep.setStyleSheet(f"background: {BORDER_BRIGHT};")
        toolbar.addSpacing(8)
        toolbar.addWidget(sep)
        toolbar.addSpacing(8)
        toolbar.addWidget(self.marker_btn)
        toolbar.addWidget(self.cut_btn)
        fade_in_label = QLabel("Fade in")
        fade_in_label.setProperty("role", "muted")
        toolbar.addWidget(fade_in_label)
        toolbar.addWidget(self.fade_in_input)
        fade_out_label = QLabel("out")
        fade_out_label.setProperty("role", "muted")
        toolbar.addWidget(fade_out_label)
        toolbar.addWidget(self.fade_out_input)
        toolbar.addWidget(self.fade_color_combo)
        toolbar.addStretch(1)

        self.toolbar_scroll = QScrollArea()
        self.toolbar_scroll.setWidget(toolbar_widget)
        self.toolbar_scroll.setWidgetResizable(False)
        self.toolbar_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.toolbar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.toolbar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.toolbar_scroll.setFixedHeight(toolbar_widget.sizeHint().height() + 18)

        self.canvas = TimelineCanvas(project)
        self.canvas.seek_requested.connect(self.seek_requested)
        self.canvas.project_changed.connect(self.project_changed)
        self.canvas.item_activated.connect(self.item_activated)

        self.scroll = QScrollArea()
        self.scroll.setWidget(self.canvas)
        self.scroll.setWidgetResizable(False)
        self.scroll.setFixedHeight(self._timeline_scroll_height())
        self.scroll.horizontalScrollBar().valueChanged.connect(self._scroll_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toolbar_scroll)
        layout.addWidget(self.scroll)
        self.refresh()

    def set_project(self, project: ProjectState) -> None:
        self.project = project
        self.canvas.set_project(project)
        self.refresh()

    def refresh(self) -> None:
        self.project.duration = project_end_time(self.project)
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(int(max(2.0, min(300.0, self.project.zoom))))
        self.zoom_slider.blockSignals(False)
        self.time_label.setText(
            f"{fmt_time(self.project.current_time)} / {fmt_time(self.project.duration)}"
        )
        self.canvas.refresh_geometry()
        self.canvas.update()
        self.scroll.setFixedHeight(self._timeline_scroll_height())

        clip = self.project.active_clip
        for spin, value in (
            (self.fade_in_input, clip.fade_in if clip else 0.0),
            (self.fade_out_input, clip.fade_out if clip else 0.0),
        ):
            spin.blockSignals(True)
            spin.setEnabled(clip is not None)
            spin.setValue(float(value))
            spin.blockSignals(False)

        self.fade_color_combo.blockSignals(True)
        self.fade_color_combo.setEnabled(clip is not None)
        if clip is not None:
            idx = self.fade_color_combo.findData(
                (clip.fade_color or "#000000").lower(),
            )
            if idx < 0 and (clip.fade_color or "").lower() == "#ffffff":
                idx = self.fade_color_combo.findData("#ffffff")
            self.fade_color_combo.setCurrentIndex(max(0, idx))
        self.fade_color_combo.blockSignals(False)

    def _timeline_scroll_height(self) -> int:
        return min(self.canvas.minimumHeight() + 20, 300)

    def _set_fade(self, side: str, value: float) -> None:
        clip = self.project.active_clip
        if clip is None:
            return
        if side == "in":
            clip.fade_in = max(0.0, float(value))
        else:
            clip.fade_out = max(0.0, float(value))
        self.project_changed.emit()
        self.canvas.update()

    def _fade_color_changed(self, _idx: int) -> None:
        clip = self.project.active_clip
        if clip is None:
            return
        clip.fade_color = self.fade_color_combo.currentData() or "#000000"
        self.project_changed.emit()
        self.canvas.update()

    def _set_zoom(self, value: float) -> None:
        self.project.zoom = max(2.0, min(300.0, value))
        self.project_changed.emit()
        self.refresh()

    def _snap_toggled(self, checked: bool) -> None:
        self.canvas.snap_enabled = bool(checked)

    def _zoom_to_fit(self) -> None:
        viewport_width = self.scroll.viewport().width()
        fit_zoom = (viewport_width - TimelineCanvas.LABEL_W - 24) / max(
            0.5, project_end_time(self.project)
        )
        fit_zoom = max(2.0, min(300.0, fit_zoom))
        if self._pre_fit_state is not None and abs(self.project.zoom - fit_zoom) < 0.5:
            # Already at fit: toggle back to the zoom/scroll from before fitting.
            zoom, scroll_value = self._pre_fit_state
            self._pre_fit_state = None
            self._set_zoom(zoom)
            self.scroll.horizontalScrollBar().setValue(scroll_value)
            return
        self._pre_fit_state = (self.project.zoom, self.scroll.horizontalScrollBar().value())
        self._set_zoom(fit_zoom)
        self.scroll.horizontalScrollBar().setValue(0)

    def _scroll_changed(self, value: int) -> None:
        self.project.scroll_left = float(value)

    def _add_marker(self) -> None:
        label, ok = QInputDialog.getText(self, "Add Marker", "Marker label:", text="Key moment")
        if not ok or not label.strip():
            return
        self.project.markers.append(
            TimelineMarker(
                id=new_id(),
                time=self.project.current_time,
                label=label.strip(),
                color=ACCENT_AMBER,
            )
        )
        self.project.duration = project_end_time(self.project)
        self.project_changed.emit()
        self.refresh()

    def _cut_active_clip(self) -> None:
        # Find the clip the playhead is actually over (not just the active one).
        playhead = self.project.current_time
        target = next(
            (c for c in self.project.clips
             if c.start_time < playhead < c.start_time + c.display_duration),
            None,
        )
        if target is None:
            return

        cut_offset = playhead - target.start_time  # seconds into the timeline-visible portion
        original_trim_end = target.trim_end
        split_trim = target.trim_start + cut_offset

        # Need at least a tiny sliver on each side for a meaningful split.
        if split_trim - target.trim_start < 0.05:
            return
        if original_trim_end - split_trim < 0.05:
            return

        # Trim the first piece. Its fade-out moves to the new right piece, since
        # the cut point is no longer the end of the source material.
        target.trim_end = split_trim
        right_fade_out = target.fade_out
        target.fade_out = 0.0

        # Build the second piece, referencing the same source media. media_type
        # must carry over or a cut image clip turns into an unloadable "video".
        right = VideoClip(
            id=new_id(),
            path=target.path,
            name=f"{target.name} (cont.)",
            duration=target.duration,
            start_time=playhead,
            trim_start=split_trim,
            trim_end=original_trim_end,
            width=target.width,
            height=target.height,
            thumbnail_path=target.thumbnail_path,
            media_type=target.media_type,
            fade_in=0.0,
            fade_out=right_fade_out,
            fade_color=target.fade_color,
        )
        idx = self.project.clips.index(target)
        self.project.clips.insert(idx + 1, right)

        self.project.duration = project_end_time(self.project)
        self.project_changed.emit()
        self.refresh()


class SlidePreview(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.slide: Slide | None = None
        self.setMinimumHeight(120)

    def set_slide(self, slide: Slide | None) -> None:
        self.slide = slide
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(6, 6, self.width() - 12, self.height() - 12)
        if self.slide is None:
            painter.fillRect(rect, QColor(BG_CARD))
            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "No slide selected")
            return
        painter.setPen(QPen(QColor(BORDER_BRIGHT), 1))
        if getattr(self.slide, "overlay", False):
            # Render a checker pattern to indicate transparency.
            painter.setBrush(QColor(BG_CARD))
            painter.drawRoundedRect(rect, 12, 12)
            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(
                rect.adjusted(0, 0, 0, -rect.height() + 18),
                Qt.AlignmentFlag.AlignCenter,
                "(overlay — drawn over underlying clip)",
            )
        else:
            painter.setBrush(QColor(self.slide.background))
            painter.drawRoundedRect(rect, 12, 12)
        image_path = getattr(self.slide, "image_path", None)
        if image_path:
            pix = QPixmap(image_path)
            if not pix.isNull():
                painter.drawPixmap(rect, pix, QRectF(pix.rect()))
        painter.setPen(QColor(self.slide.text_color))
        title_rect = rect.adjusted(16, 16, -16, -rect.height() / 2)
        body_rect = rect.adjusted(18, rect.height() / 2, -18, -16)

        family = getattr(self.slide, "font_family", "") or self.font().family()
        bold = getattr(self.slide, "bold", True)
        italic = getattr(self.slide, "italic", False)

        from PySide6.QtGui import QFont
        title_font = QFont(family)
        title_font.setBold(bold)
        title_font.setItalic(italic)
        title_font.setPointSize(self._fit_font_size(
            self.slide.title, title_rect, self.slide.font_size + 2,
            bold=bold, italic=italic, family=family, min_size=9, max_size=22,
        ))
        painter.setFont(title_font)
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom | Qt.TextFlag.TextWordWrap,
            self.slide.title,
        )

        body_font = QFont(family)
        body_font.setBold(False)
        body_font.setItalic(italic)
        body_font.setPointSize(self._fit_font_size(
            self.slide.content or "", body_rect, max(8, self.slide.font_size - 4),
            bold=False, italic=italic, family=family, min_size=7, max_size=16,
        ))
        painter.setFont(body_font)
        painter.drawText(
            body_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            self.slide.content,
        )

    def _fit_font_size(
        self,
        text: str,
        rect: QRectF,
        desired: int,
        *,
        bold: bool,
        min_size: int,
        max_size: int,
        italic: bool = False,
        family: str | None = None,
    ) -> int:
        """Shrink the font until `text` (with word wrap) fits inside `rect`."""
        if not text or rect.width() <= 0 or rect.height() <= 0:
            return max(min_size, min(desired, max_size))
        from PySide6.QtGui import QFont, QFontMetricsF
        size = max(min_size, min(desired, max_size))
        while size > min_size:
            font = QFont(family or self.font().family())
            font.setBold(bold)
            font.setItalic(italic)
            font.setPointSize(size)
            metrics = QFontMetricsF(font)
            bounding = metrics.boundingRect(
                rect, int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignHCenter), text,
            )
            if bounding.width() <= rect.width() and bounding.height() <= rect.height():
                return size
            size -= 1
        return min_size


class SlideEditorPanel(QWidget):
    project_changed = Signal()

    BG_PRESETS = ["#0a0a1a", "#1a0a2e", "#0a1a0a", "#1a1a0a", "#1a0a0a", "#0d1b2a"]
    TEXT_PRESETS = ["#ffffff", "#e2e8f0", ACCENT_CYAN, ACCENT_AMBER, ACCENT_EMERALD, ACCENT_RED]

    def __init__(self, project: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self._refreshing = False

        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(112)
        self.list_widget.setWordWrap(True)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.currentItemChanged.connect(self._selection_changed)
        self.preview = SlidePreview()
        self.title_input = QLineEdit()
        self.content_input = QTextEdit()
        self.content_input.setFixedHeight(76)
        self.duration_input = QDoubleSpinBox()
        self.duration_input.setRange(0.5, 120.0)
        self.duration_input.setSingleStep(0.5)
        self.duration_input.setSuffix(" s")
        self.font_size_input = QSpinBox()
        self.font_size_input.setRange(10, 96)
        for spin in (self.duration_input, self.font_size_input):
            spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)

        self.font_family_combo = QFontComboBox()
        self.font_family_combo.setEditable(False)
        self.bold_check = QCheckBox("Bold")
        self.bold_check.setChecked(True)
        self.italic_check = QCheckBox("Italic")
        self.overlay_check = QCheckBox("Overlay (transparent)")
        self.overlay_check.setToolTip(
            "When on, the slide is drawn as text on top of the underlying image/video "
            "instead of replacing the frame."
        )

        self.title_input.textChanged.connect(self._apply_fields)
        self.content_input.textChanged.connect(self._apply_fields)
        self.duration_input.valueChanged.connect(self._apply_fields)
        self.font_size_input.valueChanged.connect(self._apply_fields)
        self.font_family_combo.currentFontChanged.connect(self._apply_fields)
        self.bold_check.toggled.connect(self._apply_fields)
        self.italic_check.toggled.connect(self._apply_fields)
        self.overlay_check.toggled.connect(self._apply_fields)

        new_btn = QPushButton("New Slide")
        new_btn.setProperty("variant", "primary")
        add_btn = QPushButton("Place at Current Time")
        add_btn.setProperty("variant", "cyan")
        delete_btn = QPushButton("Delete Slide")
        delete_btn.setProperty("variant", "danger")
        new_btn.clicked.connect(self._create_slide)
        add_btn.clicked.connect(self._place_selected_at_current_time)
        delete_btn.clicked.connect(self._delete_selected)

        header = QHBoxLayout()
        title = QLabel("Slides")
        title.setProperty("role", "title")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(new_btn)

        style_row = QHBoxLayout()
        style_row.addWidget(self.font_family_combo, 1)
        style_row.addWidget(self.bold_check)
        style_row.addWidget(self.italic_check)

        form = QFormLayout()
        # Stack labels above fields so the form (and thus this panel) doesn't
        # demand the label+field combined width — keeps the side panel compact.
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.addRow("Title", self.title_input)
        form.addRow("Body", self.content_input)
        form.addRow("Duration", self.duration_input)
        form.addRow("Font", self.font_size_input)
        form.addRow("Style", style_row)
        form.addRow("", self.overlay_check)

        bg_row = QHBoxLayout()
        for color in self.BG_PRESETS:
            bg_row.addWidget(self._color_button(color, lambda c=color: self._set_slide_color("background", c)))
        bg_pick = QPushButton("Custom")
        bg_pick.clicked.connect(lambda: self._choose_color("background"))
        bg_row.addWidget(bg_pick)

        text_row = QHBoxLayout()
        for color in self.TEXT_PRESETS:
            text_row.addWidget(self._color_button(color, lambda c=color: self._set_slide_color("text_color", c)))
        text_pick = QPushButton("Custom")
        text_pick.clicked.connect(lambda: self._choose_color("text_color"))
        text_row.addWidget(text_pick)

        actions = QHBoxLayout()
        actions.addWidget(add_btn)
        actions.addWidget(delete_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addWidget(self.list_widget, 1)
        layout.addWidget(self.preview)
        layout.addLayout(form)
        layout.addWidget(QLabel("Background"))
        layout.addLayout(bg_row)
        layout.addWidget(QLabel("Text Color"))
        layout.addLayout(text_row)
        layout.addLayout(actions)
        self.refresh()

    def set_project(self, project: ProjectState) -> None:
        self.project = project
        self.refresh()

    def select_slide(self, slide_id: str) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item and str(item.data(Qt.ItemDataRole.UserRole)) == slide_id:
                self.list_widget.setCurrentItem(item)
                break

    def refresh(self) -> None:
        self._refreshing = True
        current_id = self._selected_id()
        self.list_widget.clear()
        for slide in self.project.slides:
            end_time = slide.start_time + slide.duration
            overlay = "overlay" if slide.overlay else "full slide"
            item = QListWidgetItem(
                f"{slide.title or '(untitled)'}\n"
                f"{fmt_time(slide.start_time)} - {fmt_time(end_time)}  |  {slide.duration:g}s  |  {overlay}"
            )
            item.setSizeHint(QSize(0, 54))
            item.setData(Qt.ItemDataRole.UserRole, slide.id)
            self.list_widget.addItem(item)
            if slide.id == current_id:
                self.list_widget.setCurrentItem(item)
        if self.list_widget.currentItem() is None and self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
        self._refreshing = False
        self._load_selected()

    def _color_button(self, color: str, callback) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(24, 24)
        btn.setStyleSheet(
            f"QPushButton {{ background: {color}; border: 1px solid {BORDER_BRIGHT};"
            f" border-radius: 12px; padding: 0; }}"
            f"QPushButton:hover {{ border-color: white; }}"
        )
        btn.clicked.connect(callback)
        return btn

    def _selected_id(self) -> str | None:
        item = self.list_widget.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _selected_slide(self) -> Slide | None:
        slide_id = self._selected_id()
        if slide_id is None:
            return None
        return next((slide for slide in self.project.slides if slide.id == slide_id), None)

    def _selection_changed(self) -> None:
        if not self._refreshing:
            self._load_selected()

    def _load_selected(self) -> None:
        slide = self._selected_slide()
        self._refreshing = True
        self.preview.set_slide(slide)
        for w in (
            self.title_input, self.content_input, self.duration_input,
            self.font_size_input, self.font_family_combo, self.bold_check,
            self.italic_check, self.overlay_check,
        ):
            w.setEnabled(slide is not None)
        if slide is None:
            self.title_input.clear()
            self.content_input.clear()
            self.duration_input.setValue(5.0)
            self.font_size_input.setValue(20)
            self.bold_check.setChecked(True)
            self.italic_check.setChecked(False)
            self.overlay_check.setChecked(False)
        else:
            self.title_input.setText(slide.title)
            self.content_input.setPlainText(slide.content)
            self.duration_input.setValue(slide.duration)
            self.font_size_input.setValue(slide.font_size)
            if slide.font_family:
                from PySide6.QtGui import QFont
                self.font_family_combo.setCurrentFont(QFont(slide.font_family))
            self.bold_check.setChecked(slide.bold)
            self.italic_check.setChecked(slide.italic)
            self.overlay_check.setChecked(slide.overlay)
        self._refreshing = False

    def _create_slide(self) -> None:
        slide = Slide(
            id=new_id(),
            title="New Slide",
            content="",
            duration=5.0,
            start_time=self.project.current_time,
            background="#0d1b2a",
            text_color="#ffffff",
            font_size=20,
        )
        self.project.slides.append(slide)
        self.project.duration = project_end_time(self.project)
        self.project_changed.emit()
        self.refresh()
        for row in range(self.list_widget.count()):
            if self.list_widget.item(row).data(Qt.ItemDataRole.UserRole) == slide.id:
                self.list_widget.setCurrentRow(row)
                break

    def _apply_fields(self) -> None:
        if self._refreshing:
            return
        slide = self._selected_slide()
        if slide is None:
            return
        slide.title = self.title_input.text()
        slide.content = self.content_input.toPlainText()
        slide.duration = float(self.duration_input.value())
        slide.font_size = int(self.font_size_input.value())
        slide.font_family = self.font_family_combo.currentFont().family()
        slide.bold = self.bold_check.isChecked()
        slide.italic = self.italic_check.isChecked()
        slide.overlay = self.overlay_check.isChecked()
        self.project.duration = project_end_time(self.project)
        self.preview.set_slide(slide)
        self.project_changed.emit()
        self._refresh_list_labels()

    def _refresh_list_labels(self) -> None:
        current = self._selected_id()
        for row, slide in enumerate(self.project.slides):
            item = self.list_widget.item(row)
            if item is not None:
                end_time = slide.start_time + slide.duration
                overlay = "overlay" if slide.overlay else "full slide"
                item.setText(
                    f"{slide.title or '(untitled)'}\n"
                    f"{fmt_time(slide.start_time)} - {fmt_time(end_time)}  |  {slide.duration:g}s  |  {overlay}"
                )
                item.setSizeHint(QSize(0, 54))
                item.setData(Qt.ItemDataRole.UserRole, slide.id)
                if slide.id == current:
                    self.list_widget.setCurrentItem(item)

    def _set_slide_color(self, field: Literal["background", "text_color"], color: str) -> None:
        slide = self._selected_slide()
        if slide is None:
            return
        setattr(slide, field, color)
        self.preview.set_slide(slide)
        self.project_changed.emit()

    def _choose_color(self, field: Literal["background", "text_color"]) -> None:
        slide = self._selected_slide()
        if slide is None:
            return
        color = QColorDialog.getColor(QColor(getattr(slide, field)), self, "Slide Color")
        if color.isValid():
            self._set_slide_color(field, color.name())

    def _place_selected_at_current_time(self) -> None:
        slide = self._selected_slide()
        if slide is None:
            return
        slide.start_time = self.project.current_time
        self.project.duration = project_end_time(self.project)
        self.project_changed.emit()
        self.refresh()

    def _delete_selected(self) -> None:
        slide_id = self._selected_id()
        if slide_id is None:
            return
        self.project.slides = [slide for slide in self.project.slides if slide.id != slide_id]
        self.project.duration = project_end_time(self.project)
        self.project_changed.emit()
        self.refresh()


class AudioPanel(QWidget):
    project_changed = Signal()
    seek_requested = Signal(float)

    def __init__(self, project: ProjectState, audio_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.audio_dir = audio_dir
        self._refreshing = False
        self._recording_path: Path | None = None
        self._recording_started = 0.0
        self.capture_session = QMediaCaptureSession(self)
        self.recorder = QMediaRecorder(self)
        self.capture_session.setRecorder(self.recorder)
        self.audio_input: QAudioInput | None = None

        title = QLabel("Voice Recorder")
        title.setProperty("role", "title")
        self.status = QLabel("Ready")
        self.status.setProperty("role", "muted")
        self.timer_label = QLabel("0:00.0")
        self.timer_label.setStyleSheet(f"font-size: 24px; font-weight: 800; color: {TEXT_PRIMARY};")

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Recording name...")
        self.record_btn = QPushButton("Record")
        self.record_btn.setProperty("variant", "danger")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.import_btn = QPushButton("Import Audio")
        self.import_btn.setProperty("variant", "cyan")
        self.record_btn.clicked.connect(self._start_recording)
        self.stop_btn.clicked.connect(self._stop_recording)
        self.import_btn.clicked.connect(self._import_audio)

        controls = QHBoxLayout()
        controls.addWidget(self.record_btn)
        controls.addWidget(self.stop_btn)
        controls.addWidget(self.import_btn)

        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._selection_changed)
        self.track_name = QLineEdit()
        self.track_name.textChanged.connect(self._apply_track_fields)
        self.start_input = QDoubleSpinBox()
        self.start_input.setRange(0.0, 24 * 60 * 60)
        self.start_input.setSingleStep(0.5)
        self.start_input.setSuffix(" s")
        self.duration_input = QDoubleSpinBox()
        self.duration_input.setRange(0.1, 24 * 60 * 60)
        self.duration_input.setSingleStep(0.5)
        self.duration_input.setSuffix(" s")
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.start_input.valueChanged.connect(self._apply_track_fields)
        self.duration_input.valueChanged.connect(self._apply_track_fields)
        self.volume_slider.valueChanged.connect(self._apply_track_fields)
        delete_btn = QPushButton("Delete Track")
        delete_btn.setProperty("variant", "danger")
        delete_btn.clicked.connect(self._delete_selected)

        self.audio_phi_check = QCheckBox("Audio reviewed for spoken PHI")
        self.audio_phi_check.setToolTip(
            "Confirm you listened to the narration/audio for spoken identifiers "
            "(patient name, MRN, date of birth). Recorded in the export report; "
            "exports with audio warn when this is unchecked."
        )
        self.audio_phi_check.toggled.connect(self._apply_audio_phi_flag)

        form = QFormLayout()
        form.addRow("Name", self.track_name)
        form.addRow("Start", self.start_input)
        form.addRow("Duration", self.duration_input)
        form.addRow("Volume", self.volume_slider)

        transcript_title = QLabel("Transcript Editing")
        transcript_title.setProperty("role", "title")
        transcript_hint = QLabel(
            "Import or write timestamped transcript segments, then jump the timeline from text."
        )
        transcript_hint.setProperty("role", "muted")
        transcript_hint.setWordWrap(True)

        self.transcript_search = QLineEdit()
        self.transcript_search.setPlaceholderText("Search transcript...")
        self.transcript_search.textChanged.connect(self.refresh_transcript)

        self.transcript_list = QListWidget()
        self.transcript_list.currentItemChanged.connect(self._transcript_selection_changed)
        self.transcript_list.itemDoubleClicked.connect(self._transcript_item_activated)

        import_transcript_btn = QPushButton("Import Transcript")
        import_transcript_btn.setProperty("variant", "cyan")
        add_segment_btn = QPushButton("Add Segment")
        add_segment_btn.clicked.connect(self._add_transcript_segment)
        import_transcript_btn.clicked.connect(self._import_transcript)

        self.segment_start = QDoubleSpinBox()
        self.segment_start.setRange(0.0, 24 * 60 * 60)
        self.segment_start.setSingleStep(0.5)
        self.segment_start.setSuffix(" s")
        self.segment_end = QDoubleSpinBox()
        self.segment_end.setRange(0.0, 24 * 60 * 60)
        self.segment_end.setSingleStep(0.5)
        self.segment_end.setSuffix(" s")
        self.segment_speaker = QLineEdit()
        self.segment_speaker.setPlaceholderText("Narrator, surgeon...")
        self.segment_text = QTextEdit()
        self.segment_text.setAcceptRichText(False)
        self.segment_text.setPlaceholderText("Transcript text...")
        self.segment_text.setFixedHeight(72)
        self.segment_start.valueChanged.connect(self._apply_transcript_fields)
        self.segment_end.valueChanged.connect(self._apply_transcript_fields)
        self.segment_speaker.textChanged.connect(self._apply_transcript_fields)
        self.segment_text.textChanged.connect(self._apply_transcript_fields)

        seek_segment_btn = QPushButton("Jump to Segment")
        seek_segment_btn.clicked.connect(self._seek_selected_transcript)
        delete_segment_btn = QPushButton("Delete Segment")
        delete_segment_btn.setProperty("variant", "danger")
        delete_segment_btn.clicked.connect(self._delete_transcript_segment)

        transcript_buttons = QHBoxLayout()
        transcript_buttons.addWidget(import_transcript_btn)
        transcript_buttons.addWidget(add_segment_btn)

        transcript_actions = QHBoxLayout()
        transcript_actions.addWidget(seek_segment_btn)
        transcript_actions.addWidget(delete_segment_btn)

        transcript_form = QFormLayout()
        transcript_form.addRow("Start", self.segment_start)
        transcript_form.addRow("End", self.segment_end)
        transcript_form.addRow("Speaker", self.segment_speaker)
        transcript_form.addRow("Text", self.segment_text)

        self.clock = QTimer(self)
        self.clock.setInterval(100)
        self.clock.timeout.connect(self._tick_recording)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(self.status)
        layout.addWidget(self.timer_label)
        layout.addWidget(self.name_input)
        layout.addLayout(controls)
        layout.addWidget(QLabel("Audio Tracks"))
        layout.addWidget(self.list_widget, 1)
        layout.addLayout(form)
        layout.addWidget(delete_btn)
        layout.addWidget(self.audio_phi_check)
        layout.addWidget(transcript_title)
        layout.addWidget(transcript_hint)
        layout.addWidget(self.transcript_search)
        layout.addWidget(self.transcript_list, 1)
        layout.addLayout(transcript_buttons)
        layout.addLayout(transcript_form)
        layout.addLayout(transcript_actions)
        self.refresh()

    def set_project(self, project: ProjectState, audio_dir: Path | None = None) -> None:
        self.project = project
        if audio_dir is not None:
            self.audio_dir = audio_dir
        self.refresh()

    def select_track(self, track_id: str) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item and str(item.data(Qt.ItemDataRole.UserRole)) == track_id:
                self.list_widget.setCurrentItem(item)
                break

    def _apply_audio_phi_flag(self, checked: bool) -> None:
        if self._refreshing:
            return
        self.project.audio_reviewed_for_phi = checked
        self.project_changed.emit()

    def refresh(self) -> None:
        self._refreshing = True
        current_id = self._selected_id()
        self.audio_phi_check.setChecked(self.project.audio_reviewed_for_phi)
        self.list_widget.clear()
        for track in self.project.audio_tracks:
            item = QListWidgetItem(
                f"{track.name}  |  {fmt_time(track.start_time)}  |  {fmt_time(track.duration)}"
            )
            item.setData(Qt.ItemDataRole.UserRole, track.id)
            self.list_widget.addItem(item)
            if track.id == current_id:
                self.list_widget.setCurrentItem(item)
        if self.list_widget.currentItem() is None and self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
        self._refreshing = False
        self._load_selected_track()
        self.refresh_transcript()

    def _selected_id(self) -> str | None:
        item = self.list_widget.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _selected_track(self) -> AudioTrack | None:
        track_id = self._selected_id()
        if track_id is None:
            return None
        return next((track for track in self.project.audio_tracks if track.id == track_id), None)

    def _selected_transcript_id(self) -> str | None:
        item = self.transcript_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _selected_transcript(self) -> TranscriptSegment | None:
        segment_id = self._selected_transcript_id()
        if segment_id is None:
            return None
        return next(
            (segment for segment in self.project.transcript_segments if segment.id == segment_id),
            None,
        )

    def _selection_changed(self) -> None:
        if not self._refreshing:
            self._load_selected_track()

    def _load_selected_track(self) -> None:
        track = self._selected_track()
        self._refreshing = True
        enabled = track is not None
        self.track_name.setEnabled(enabled)
        self.start_input.setEnabled(enabled)
        self.duration_input.setEnabled(enabled)
        self.volume_slider.setEnabled(enabled)
        if track is None:
            self.track_name.clear()
            self.start_input.setValue(0.0)
            self.duration_input.setValue(0.1)
            self.volume_slider.setValue(100)
        else:
            self.track_name.setText(track.name)
            self.start_input.setValue(track.start_time)
            self.duration_input.setValue(max(0.1, track.duration))
            self.volume_slider.setValue(int(max(0.0, min(1.0, track.volume)) * 100))
        self._refreshing = False
        self.refresh_transcript()

    def _start_recording(self) -> None:
        default_input = QMediaDevices.defaultAudioInput()
        if default_input.isNull():
            self.status.setText("No microphone available.")
            return
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self._recording_path = self.audio_dir / f"voice_{int(time.time())}.m4a"
        self.audio_input = QAudioInput(default_input, self)
        self.capture_session.setAudioInput(self.audio_input)
        self.recorder.setOutputLocation(QUrl.fromLocalFile(str(self._recording_path)))
        self.recorder.record()
        self._recording_started = time.monotonic()
        self.clock.start()
        self.record_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status.setText("Recording...")

    def _stop_recording(self) -> None:
        self.recorder.stop()
        self.clock.stop()
        elapsed = max(0.1, time.monotonic() - self._recording_started)
        path = self._recording_path
        self._recording_path = None
        self.record_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if path is None:
            return
        name = self.name_input.text().strip() or f"Voice {time.strftime('%H:%M:%S')}"
        self.project.audio_tracks.append(
            AudioTrack(
                id=new_id(),
                path=str(path),
                name=name,
                start_time=self.project.current_time,
                duration=elapsed,
                type="voice",
                volume=1.0,
            )
        )
        self.name_input.clear()
        self.project.duration = project_end_time(self.project)
        self.status.setText(f"Saved {name}")
        self.project_changed.emit()
        self.refresh()

    def _tick_recording(self) -> None:
        elapsed = max(0.0, time.monotonic() - self._recording_started)
        self.timer_label.setText(fmt_time(elapsed))

    def _import_audio(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Import Audio",
            str(Path.home()),
            "Audio Files (*.wav *.m4a *.mp3 *.aac *.aiff *.caf);;All Files (*)",
        )
        if not path_str:
            return
        path = Path(path_str)
        duration = self._probe_audio_duration(path)
        self.project.audio_tracks.append(
            AudioTrack(
                id=new_id(),
                path=str(path),
                name=path.stem,
                start_time=self.project.current_time,
                duration=duration,
                type="music",
                volume=1.0,
            )
        )
        self.project.duration = project_end_time(self.project)
        self.project_changed.emit()
        self.refresh()

    def _probe_audio_duration(self, path: Path) -> float:
        if path.suffix.lower() == ".wav":
            try:
                with wave.open(str(path), "rb") as wav:
                    return max(0.1, wav.getnframes() / float(wav.getframerate()))
            except Exception:  # noqa: BLE001
                pass
        # Non-wav (m4a/mp3/aac): probe with the bundled ffmpeg. Falling back to
        # a guessed 5.0 s silently truncated imported audio in the export mix.
        duration = self._ffmpeg_audio_duration(path)
        return duration if duration > 0 else 5.0

    def _ffmpeg_audio_duration(self, path: Path) -> float:
        try:
            import imageio_ffmpeg  # noqa: PLC0415

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            proc = subprocess.run(
                [ffmpeg, "-hide_banner", "-i", str(path)],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            match = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", proc.stderr)
            if match:
                hours, minutes, seconds = match.groups()
                return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        except Exception:  # noqa: BLE001
            pass
        return 0.0

    def _apply_track_fields(self) -> None:
        if self._refreshing:
            return
        track = self._selected_track()
        if track is None:
            return
        track.name = self.track_name.text()
        track.start_time = float(self.start_input.value())
        track.duration = float(self.duration_input.value())
        track.volume = self.volume_slider.value() / 100.0
        self.project.duration = project_end_time(self.project)
        self.project_changed.emit()
        self._refresh_list_labels()

    def _refresh_list_labels(self) -> None:
        for row, track in enumerate(self.project.audio_tracks):
            item = self.list_widget.item(row)
            if item is not None:
                item.setText(f"{track.name}  |  {fmt_time(track.start_time)}  |  {fmt_time(track.duration)}")
                item.setData(Qt.ItemDataRole.UserRole, track.id)

    def refresh_transcript(self) -> None:
        if not hasattr(self, "transcript_list"):
            return
        current_id = self._selected_transcript_id()
        query = self.transcript_search.text().strip().lower()
        selected_track_id = self._selected_id()
        segments = sorted(self.project.transcript_segments, key=lambda segment: segment.start_time)
        self._refreshing = True
        self.transcript_list.clear()
        for segment in segments:
            if selected_track_id and segment.audio_track_id not in (None, selected_track_id):
                continue
            haystack = f"{segment.speaker} {segment.text}".lower()
            if query and query not in haystack:
                continue
            speaker = f"{segment.speaker}: " if segment.speaker else ""
            item = QListWidgetItem(
                f"{fmt_time(segment.start_time)} - {fmt_time(segment.end_time)}\n"
                f"{speaker}{segment.text}"
            )
            item.setData(Qt.ItemDataRole.UserRole, segment.id)
            self.transcript_list.addItem(item)
            if segment.id == current_id:
                self.transcript_list.setCurrentItem(item)
        if self.transcript_list.currentItem() is None and self.transcript_list.count() > 0:
            self.transcript_list.setCurrentRow(0)
        self._refreshing = False
        self._load_selected_transcript()

    def _transcript_selection_changed(self) -> None:
        if not self._refreshing:
            self._load_selected_transcript()

    def _load_selected_transcript(self) -> None:
        segment = self._selected_transcript()
        self._refreshing = True
        enabled = segment is not None
        self.segment_start.setEnabled(enabled)
        self.segment_end.setEnabled(enabled)
        self.segment_speaker.setEnabled(enabled)
        self.segment_text.setEnabled(enabled)
        if segment is None:
            self.segment_start.setValue(0.0)
            self.segment_end.setValue(0.5)
            self.segment_speaker.clear()
            self.segment_text.clear()
        else:
            self.segment_start.setValue(segment.start_time)
            self.segment_end.setValue(max(segment.start_time + 0.1, segment.end_time))
            self.segment_speaker.setText(segment.speaker)
            self.segment_text.setPlainText(segment.text)
        self._refreshing = False

    def _apply_transcript_fields(self) -> None:
        if self._refreshing:
            return
        segment = self._selected_transcript()
        if segment is None:
            return
        segment.start_time = float(self.segment_start.value())
        segment.end_time = max(segment.start_time + 0.1, float(self.segment_end.value()))
        segment.speaker = self.segment_speaker.text()
        segment.text = self.segment_text.toPlainText()
        self.project_changed.emit()
        self._refresh_transcript_list_labels()

    def _refresh_transcript_list_labels(self) -> None:
        for row in range(self.transcript_list.count()):
            item = self.transcript_list.item(row)
            if item is None:
                continue
            segment_id = str(item.data(Qt.ItemDataRole.UserRole))
            segment = next(
                (candidate for candidate in self.project.transcript_segments if candidate.id == segment_id),
                None,
            )
            if segment is None:
                continue
            speaker = f"{segment.speaker}: " if segment.speaker else ""
            item.setText(
                f"{fmt_time(segment.start_time)} - {fmt_time(segment.end_time)}\n"
                f"{speaker}{segment.text}"
            )

    def _add_transcript_segment(self) -> None:
        track = self._selected_track()
        start = track.start_time if track else self.project.current_time
        end = start + 3.0
        if track is not None:
            end = min(track.start_time + max(0.1, track.duration), end)
        segment = TranscriptSegment(
            id=new_id(),
            audio_track_id=track.id if track else None,
            start_time=start,
            end_time=max(start + 0.1, end),
            text="New transcript segment",
        )
        self.project.transcript_segments.append(segment)
        self.project_changed.emit()
        self.refresh_transcript()
        self._select_transcript_segment(segment.id)

    def _select_transcript_segment(self, segment_id: str) -> None:
        for row in range(self.transcript_list.count()):
            item = self.transcript_list.item(row)
            if item and str(item.data(Qt.ItemDataRole.UserRole)) == segment_id:
                self.transcript_list.setCurrentItem(item)
                break

    def _import_transcript(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Import Transcript",
            str(Path.home()),
            "Transcript Files (*.srt *.vtt *.txt);;All Files (*)",
        )
        if not path_str:
            return
        path = Path(path_str)
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            text = path.read_text(encoding="latin-1")
        segments = self._parse_transcript_text(text)
        if not segments:
            self.status.setText("No timestamped transcript segments found.")
            return
        track = self._selected_track()
        track_id = track.id if track else None
        offset = track.start_time if track else 0.0
        imported = [
            TranscriptSegment(
                id=new_id(),
                audio_track_id=track_id,
                start_time=offset + start,
                end_time=offset + max(start + 0.1, end),
                text=segment_text,
                speaker=speaker,
            )
            for start, end, speaker, segment_text in segments
        ]
        self.project.transcript_segments.extend(imported)
        self.status.setText(f"Imported {len(imported)} transcript segment(s).")
        self.project_changed.emit()
        self.refresh_transcript()

    def _parse_transcript_text(self, text: str) -> list[tuple[float, float, str, str]]:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        segments = self._parse_srt_like_transcript(normalized)
        if segments:
            return segments
        return self._parse_line_transcript(normalized)

    def _parse_srt_like_transcript(self, text: str) -> list[tuple[float, float, str, str]]:
        blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
        segments: list[tuple[float, float, str, str]] = []
        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if lines and lines[0].isdigit():
                lines = lines[1:]
            if len(lines) < 2 or "-->" not in lines[0]:
                continue
            start_raw, end_raw = [part.strip() for part in lines[0].split("-->", 1)]
            start = self._parse_timestamp(start_raw)
            end = self._parse_timestamp(end_raw.split()[0])
            if start is None or end is None:
                continue
            speaker, content = self._split_speaker(" ".join(lines[1:]))
            segments.append((start, max(start + 0.1, end), speaker, content))
        return segments

    def _parse_line_transcript(self, text: str) -> list[tuple[float, float, str, str]]:
        segments: list[tuple[float, float, str, str]] = []
        pattern = re.compile(
            r"^\s*(?:\[)?(?P<start>\d{1,2}:\d{2}(?::\d{2})?(?:[\.,]\d+)?)"
            r"(?:\s*(?:-->|-|–|to)\s*"
            r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?(?:[\.,]\d+)?))?"
            r"(?:\])?\s*(?P<text>.*)$"
        )
        pending: list[tuple[float, str, str]] = []
        for line in text.splitlines():
            match = pattern.match(line)
            if match is None:
                continue
            start = self._parse_timestamp(match.group("start"))
            if start is None:
                continue
            end = self._parse_timestamp(match.group("end") or "")
            speaker, content = self._split_speaker(match.group("text").strip())
            if end is not None:
                segments.append((start, max(start + 0.1, end), speaker, content))
            else:
                pending.append((start, speaker, content))
        for index, (start, speaker, content) in enumerate(pending):
            next_start = pending[index + 1][0] if index + 1 < len(pending) else start + 3.0
            segments.append((start, max(start + 0.1, next_start), speaker, content))
        return sorted(segments, key=lambda segment: segment[0])

    def _parse_timestamp(self, value: str) -> float | None:
        if not value:
            return None
        clean = value.strip().replace(",", ".")
        parts = clean.split(":")
        try:
            if len(parts) == 2:
                minutes, seconds = parts
                return int(minutes) * 60 + float(seconds)
            if len(parts) == 3:
                hours, minutes, seconds = parts
                return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        except ValueError:
            return None
        return None

    def _split_speaker(self, text: str) -> tuple[str, str]:
        if ":" not in text:
            return "", text
        speaker, content = text.split(":", 1)
        if len(speaker.split()) <= 3:
            return speaker.strip(), content.strip()
        return "", text

    def _seek_selected_transcript(self) -> None:
        segment = self._selected_transcript()
        if segment is not None:
            self.seek_requested.emit(segment.start_time)

    def _transcript_item_activated(self, item: QListWidgetItem) -> None:
        segment_id = str(item.data(Qt.ItemDataRole.UserRole))
        segment = next(
            (candidate for candidate in self.project.transcript_segments if candidate.id == segment_id),
            None,
        )
        if segment is not None:
            self.seek_requested.emit(segment.start_time)

    def _delete_transcript_segment(self) -> None:
        segment_id = self._selected_transcript_id()
        if segment_id is None:
            return
        self.project.transcript_segments = [
            segment for segment in self.project.transcript_segments if segment.id != segment_id
        ]
        self.project_changed.emit()
        self.refresh_transcript()

    def _delete_selected(self) -> None:
        track_id = self._selected_id()
        if track_id is None:
            return
        self.project.audio_tracks = [track for track in self.project.audio_tracks if track.id != track_id]
        # Keep unattached segments (audio_track_id is None); only drop the
        # deleted track's own segments.
        self.project.transcript_segments = [
            segment for segment in self.project.transcript_segments
            if segment.audio_track_id != track_id
        ]
        self.project.duration = project_end_time(self.project)
        self.project_changed.emit()
        self.refresh()


VIDEO_TYPE_TIPS = {
    "educational": {
        "structure": [
            "Open with patient positioning and draping overview (30-60 s).",
            "Show pre-op imaging as an intro slide before footage.",
            "Walk through anatomy identification before the procedure begins.",
            "End with post-op outcome and key teaching points.",
        ],
        "anatomy": [
            "Highlight cortical anatomy and sulcal landmarks with SAM masks.",
            "Label dural sinuses before they are opened.",
            "Mark eloquent cortex boundaries clearly with color-coded overlays.",
            "Annotate cranial nerves with arrows and consistent colors.",
        ],
        "cuts": [
            "Cut away immediately after repetitive drilling segments.",
            "Use slow-motion for complex microsurgical steps.",
            "Add a freeze-frame and label when a key structure is first exposed.",
            "Cut to close-up angles when placing clips or sutures.",
        ],
        "timing": [
            "Target 10-20 minutes for a full educational case.",
            "Each major step should be 1-3 minutes.",
            "Spend at least 2 minutes on pathology identification.",
            "Leave closure visible enough for trainees to understand it.",
        ],
        "narration": [
            "Narrate decision-making, not just actions.",
            "Call out anatomical structures as they appear.",
            "Mention tactile cues and tissue quality.",
            "Highlight what to avoid and why.",
        ],
    },
    "case-study": {
        "structure": [
            "Start with chief complaint and imaging.",
            "Describe intraoperative findings as they appear.",
            "Document complications and how they were managed.",
            "Close with post-op course and outcome.",
        ],
        "anatomy": [
            "Use SAM to delineate tumor margins from normal parenchyma.",
            "Mark vascular anatomy relevant to resection.",
            "Annotate unexpected findings with timestamped labels.",
            "Show before and after resection views.",
        ],
        "cuts": [
            "Preserve footage of unexpected findings.",
            "Time-lapse long retraction periods rather than cutting entirely.",
            "Keep decision-making moments intact.",
            "Cut between intraoperative and post-op imaging cleanly.",
        ],
        "timing": [
            "Case study videos work best at 5-12 minutes.",
            "Pre-op context: 1-2 minutes maximum.",
            "Intraoperative footage: 3-8 minutes.",
            "Post-op outcome: 1-2 minutes.",
        ],
        "narration": [
            "Discuss pre-op differential and surgical plan.",
            "Narrate key intraoperative decisions and rationale.",
            "Address complications honestly and constructively.",
            "Discuss what you would do differently.",
        ],
    },
    "surgical-report": {
        "structure": [
            "Follow chronological procedural order strictly.",
            "Document patient position, setup, and approach.",
            "Include all major operative steps with timestamps.",
            "Log blood loss, operative time, and closure method.",
        ],
        "anatomy": [
            "Document every anatomical structure encountered systematically.",
            "Label structures at first identification.",
            "Record anatomical variants.",
            "Show complete extent of resection or repair.",
        ],
        "cuts": [
            "Minimize cuts and preserve procedural completeness.",
            "Use chapter markers instead of cutting long segments.",
            "Speed up repetitive but necessary steps.",
            "Never cut during complication management.",
        ],
        "timing": [
            "Length mirrors operative time; no strict limit.",
            "Use chapter markers every 5-10 minutes.",
            "Speed up non-critical segments to reduce total length.",
            "Full closure documentation is mandatory.",
        ],
        "narration": [
            "Use precise anatomical and surgical terminology.",
            "State instrument names and implant specifications.",
            "Narrate blood loss estimates and irrigation volumes.",
            "Document deviations from the planned approach.",
        ],
    },
    "conference": {
        "structure": [
            "Hook the audience in the first 15 seconds.",
            "Show pre-op imaging briefly.",
            "Focus on the most technically impressive segments.",
            "End with one high-impact outcome image or metric.",
        ],
        "anatomy": [
            "Use bold labels legible from a distance.",
            "Annotate only 2-3 key structures.",
            "Use SAM masks to focus attention, not document everything.",
            "Remove clutter; less annotation is more.",
        ],
        "cuts": [
            "Target 3-7 minutes total.",
            "Every cut should tighten the narrative.",
            "Begin clips mid-action, not during setup.",
            "Use jump cuts freely for conference pacing.",
        ],
        "timing": [
            "Ideal conference video: 3-5 minutes.",
            "Each highlighted moment: 20-60 seconds.",
            "Pause briefly at the key surgical moment.",
            "Leave time for take-home points.",
        ],
        "narration": [
            "Lead with why this matters.",
            "State the novel technique clearly.",
            "Avoid long case history.",
            "Close with a memorable surgical pearl.",
        ],
    },
    "training": {
        "structure": [
            "Open with learning objectives.",
            "Start with relevant anatomy review.",
            "Present steps in strict sequential order.",
            "End with summary or quiz points.",
        ],
        "anatomy": [
            "Label every relevant anatomical structure.",
            "Use color coding: arteries red, veins blue, nerves yellow.",
            "Add persistent SAM masks for critical structures.",
            "Include reference anatomy when useful.",
        ],
        "cuts": [
            "Do not cut away from difficult maneuvers.",
            "Use freeze-frame and zoom for fine steps.",
            "Play critical moments twice: normal speed, then slow.",
            "Add chapter markers at every operative step.",
        ],
        "timing": [
            "Training videos can be 20-45 minutes.",
            "Spend 3-5 minutes per major operative step.",
            "Include deliberate pauses with quiz prompts.",
            "End with a 2-3 minute summary.",
        ],
        "narration": [
            "Explain the why behind every decision.",
            "Describe instrument feel and tissue feedback.",
            "Mention common errors and how to recognize them.",
            "Reference landmarks continuously.",
        ],
    },
    "research": {
        "structure": [
            "Open with hypothesis or research question.",
            "Show representative cases sequentially.",
            "Highlight the specific finding under study.",
            "Close with quantitative summary.",
        ],
        "anatomy": [
            "Apply a consistent annotation scheme across cases.",
            "Use SAM for reproducible structure segmentation.",
            "Export labeled stills as manuscript figures.",
            "Standardize color codes across the series.",
        ],
        "cuts": [
            "Keep clips equivalent in length for comparability.",
            "Show pre- and post-intervention footage for each case.",
            "Avoid stylistic cuts; prioritize consistency.",
            "Include failed cases and complications when relevant.",
        ],
        "timing": [
            "Research supplements: 3-8 minutes per case.",
            "Journal video abstracts: 2-3 minutes.",
            "Show at least 3 representative cases.",
            "Balance time equally across cases.",
        ],
        "narration": [
            "Use precise, reproducible terminology.",
            "Describe observations factually.",
            "Reference classification or grading systems.",
            "State inclusion and exclusion criteria.",
        ],
    },
}


VIDEO_GOALS = [
    ("talk-adjunct", "Talk adjunct clip"),
    ("standalone-publication", "Standalone publication"),
    ("teaching-module", "Teaching module"),
    ("m-and-m-qi", "M&M / QI review"),
    ("trainee-feedback", "Trainee feedback"),
    ("social-short", "Short-form / social"),
]


def recommended_continuous_clip_seconds(project: ProjectState) -> tuple[float, str]:
    goal = project.video_goal
    if goal == "talk-adjunct":
        minutes = project.target_presentation_minutes
        if minutes < 5:
            return 20.0, "2-4 minute talk: keep continuous operative clips under 15-20 seconds."
        if minutes <= 10:
            return 60.0, "5-10 minute talk: keep continuous operative clips under 30-60 seconds."
        if minutes <= 15:
            return 90.0, "11-15 minute talk: keep continuous operative clips under 60-90 seconds."
        return 120.0, "15+ minute talk: keep continuous operative clips under 120 seconds."
    if goal == "standalone-publication":
        return 600.0, "Publication video: target one 8-10 minute final video with 3-4 objectives."
    if goal == "teaching-module":
        return 300.0, "Teaching module: break major operative steps into 3-5 minute chapters."
    if goal == "m-and-m-qi":
        return 120.0, "M&M/QI: keep each event or decision-point segment under 2 minutes."
    if goal == "trainee-feedback":
        return 180.0, "Trainee feedback: keep focused review segments under 3 minutes."
    if goal == "social-short":
        return 45.0, "Short-form video: keep continuous clips under 45 seconds."
    return 60.0, "Keep continuous clips short and tied to one learning objective."


def project_preflight_warnings(project: ProjectState) -> list[str]:
    warnings: list[str] = []
    max_clip_s, guidance = recommended_continuous_clip_seconds(project)
    long_clips = [
        clip for clip in project.clips
        if clip.media_type == "video" and clip.display_duration > max_clip_s
    ]
    if long_clips:
        names = ", ".join(clip.name for clip in long_clips[:3])
        extra = "" if len(long_clips) <= 3 else f" and {len(long_clips) - 3} more"
        warnings.append(f"{guidance} Over-limit clips: {names}{extra}.")
    if project.duration > 120 and not project.markers:
        warnings.append("Add chapter markers for videos longer than 2 minutes.")
    if not project.storyboard_objective.strip():
        warnings.append("Add a primary learning objective before export.")
    if not project.storyboard_steps.strip():
        warnings.append("Outline the operative steps in the storyboard.")
    if not project.intended_audience.strip():
        warnings.append("Specify the intended audience.")
    if project.clips and not project.consent_confirmed:
        warnings.append("Confirm patient consent or institutional authorization.")
    if project.clips and not project.deidentified_confirmed:
        warnings.append("Confirm de-identification before distribution.")
    if project.clips and not project.phi_review_confirmed:
        warnings.append("Complete a PHI review before export.")
    if project.audio_tracks and not project.audio_reviewed_for_phi:
        warnings.append(
            "Audio has not been reviewed for spoken PHI (Audio panel checkbox)."
        )
    if (
        project.clips
        and not project.phi_review_confirmed
        and not any(ann.type == "redact" for ann in project.annotations)
    ):
        warnings.append(
            "No redaction boxes added. Use the Redact tool (the █ button) to cover any "
            "burned-in patient identifiers — name, MRN, DOB, dates — before export."
        )
    if not project.edit_disclosure.strip():
        warnings.append("Add an edit disclosure describing cuts, speed changes, labels, or overlays.")
    tiny_labels = [ann.label for ann in project.annotations if ann.show_label and ann.font_size < 14]
    if tiny_labels:
        warnings.append("Some annotation labels may be too small for conference screens.")
    if project.video_goal in {"talk-adjunct", "standalone-publication", "teaching-module"}:
        if not project.audio_tracks:
            warnings.append("Consider adding narration or captions for educational clarity.")
    return warnings


class TipsPanel(QWidget):
    project_changed = Signal()

    def __init__(self, project: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.setObjectName("infoPanel")
        self._refreshing = False

        title = QLabel("Operative Workflow")
        title.setProperty("role", "title")
        intro = QLabel("Set the video goal, storyboard the teaching arc, and check export readiness.")
        intro.setProperty("role", "muted")
        intro.setWordWrap(True)

        self.goal_combo = QComboBox()
        for key, label in VIDEO_GOALS:
            self.goal_combo.addItem(label, key)
        self.goal_combo.currentIndexChanged.connect(self._apply_fields)

        self.presentation_minutes = QDoubleSpinBox()
        self.presentation_minutes.setRange(1.0, 120.0)
        self.presentation_minutes.setSingleStep(1.0)
        self.presentation_minutes.setSuffix(" min")
        self.presentation_minutes.valueChanged.connect(self._apply_fields)

        self.audience_input = QLineEdit()
        self.audience_input.setPlaceholderText("Residents, fellows, conference audience...")
        self.audience_input.editingFinished.connect(self._apply_fields)

        self.story_fields: dict[str, QTextEdit] = {}
        story_specs = [
            ("storyboard_objective", "Objective", "What should the viewer learn?"),
            ("storyboard_case_context", "Case Context", "Brief presentation, imaging, setup."),
            ("storyboard_key_anatomy", "Key Anatomy", "Structures that must be labeled."),
            ("storyboard_steps", "Operative Steps", "Stepwise story beats or chapters."),
            ("storyboard_decision_points", "Decision Points", "Why cuts, maneuvers, or strategy changed."),
            ("storyboard_teaching_pearl", "Pearl / Pitfall", "What to avoid or remember."),
            ("storyboard_final_point", "Final Point", "Closing takeaway."),
        ]

        storyboard_layout = QFormLayout()
        for attr, label, placeholder in story_specs:
            field = QTextEdit()
            field.setAcceptRichText(False)
            field.setPlaceholderText(placeholder)
            field.setFixedHeight(58 if attr != "storyboard_steps" else 82)
            field.textChanged.connect(self._apply_fields)
            self.story_fields[attr] = field
            storyboard_layout.addRow(label, field)

        self.consent_check = QCheckBox("Patient consent / institutional authorization confirmed")
        self.staff_check = QCheckBox("Staff notice/consent addressed when applicable")
        self.deid_check = QCheckBox("Video is de-identified")
        self.phi_check = QCheckBox("PHI review completed")
        for checkbox in (
            self.consent_check, self.staff_check, self.deid_check, self.phi_check,
        ):
            checkbox.stateChanged.connect(self._apply_fields)

        self.edit_disclosure = QTextEdit()
        self.edit_disclosure.setAcceptRichText(False)
        self.edit_disclosure.setPlaceholderText("Example: repetitive drilling shortened; labels and overlays added.")
        self.edit_disclosure.setFixedHeight(66)
        self.edit_disclosure.textChanged.connect(self._apply_fields)

        self.guidance = QTextEdit()
        self.guidance.setReadOnly(True)
        self.guidance.setFixedHeight(230)

        form = QFormLayout()
        form.addRow("Video Goal", self.goal_combo)
        form.addRow("Talk Length", self.presentation_minutes)
        form.addRow("Audience", self.audience_input)

        privacy_layout = QVBoxLayout()
        privacy_layout.setSpacing(4)
        privacy_layout.addWidget(self.consent_check)
        privacy_layout.addWidget(self.staff_check)
        privacy_layout.addWidget(self.deid_check)
        privacy_layout.addWidget(self.phi_check)
        privacy_layout.addWidget(QLabel("Edit Disclosure"))
        privacy_layout.addWidget(self.edit_disclosure)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(QLabel("Storyboard"))
        layout.addLayout(storyboard_layout)
        layout.addWidget(QLabel("Privacy / Distribution"))
        layout.addLayout(privacy_layout)
        layout.addWidget(QLabel("Guidance / Preflight"))
        layout.addWidget(self.guidance)
        self.refresh()

    def set_project(self, project: ProjectState) -> None:
        self.project = project
        self.refresh()

    def refresh(self) -> None:
        self._refreshing = True
        idx = self.goal_combo.findData(self.project.video_goal)
        self.goal_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.presentation_minutes.setValue(float(self.project.target_presentation_minutes))
        self.audience_input.setText(self.project.intended_audience)
        for attr, field in self.story_fields.items():
            field.setPlainText(str(getattr(self.project, attr)))
        self.consent_check.setChecked(self.project.consent_confirmed)
        self.staff_check.setChecked(self.project.staff_notice_confirmed)
        self.deid_check.setChecked(self.project.deidentified_confirmed)
        self.phi_check.setChecked(self.project.phi_review_confirmed)
        self.edit_disclosure.setPlainText(self.project.edit_disclosure)
        self._refreshing = False
        self._refresh_guidance()

    def _apply_fields(self) -> None:
        if self._refreshing:
            return
        self.project.video_goal = str(self.goal_combo.currentData())
        self.project.target_presentation_minutes = float(self.presentation_minutes.value())
        self.project.intended_audience = self.audience_input.text()
        for attr, field in self.story_fields.items():
            setattr(self.project, attr, field.toPlainText())
        self.project.consent_confirmed = self.consent_check.isChecked()
        self.project.staff_notice_confirmed = self.staff_check.isChecked()
        self.project.deidentified_confirmed = self.deid_check.isChecked()
        self.project.phi_review_confirmed = self.phi_check.isChecked()
        self.project.edit_disclosure = self.edit_disclosure.toPlainText()
        self._refresh_guidance()
        self.project_changed.emit()

    def _refresh_guidance(self) -> None:
        tips = VIDEO_TYPE_TIPS.get(self.project.video_type, VIDEO_TYPE_TIPS["educational"])
        title = self.project.video_type.replace("-", " ").title()
        _limit, clip_guidance = recommended_continuous_clip_seconds(self.project)
        warnings = project_preflight_warnings(self.project)
        sections = [
            ("Structure", ACCENT_AMBER, tips["structure"]),
            ("Anatomy to Label", ACCENT_CYAN, tips["anatomy"]),
            ("Cut Strategy", "#8b5cf6", tips["cuts"]),
            ("Timing", ACCENT_EMERALD, tips["timing"]),
            ("Narration", ACCENT_RED, tips["narration"]),
        ]
        html = [
            f"<h3 style='color:{TEXT_PRIMARY}; margin-bottom:0;'>Guidance</h3>",
            f"<p style='color:{TEXT_MUTED};'>For: {title} video</p>",
            f"<p style='color:{ACCENT_CYAN};'><b>Duration rule:</b> {clip_guidance}</p>",
        ]
        if warnings:
            html.append(f"<h3 style='color:{ACCENT_RED}; margin-top:12px;'>Preflight Issues</h3><ul>")
            for warning in warnings:
                html.append(f"<li style='color:{TEXT_SECONDARY}; margin-bottom:6px;'>{warning}</li>")
            html.append("</ul>")
        else:
            html.append(f"<p style='color:{ACCENT_EMERALD};'><b>Preflight:</b> No blocking issues found.</p>")
        for heading, color, items in sections:
            html.append(f"<h3 style='color:{color}; margin-top:14px;'>{heading}</h3>")
            html.append("<ul>")
            for item in items:
                html.append(f"<li style='color:{TEXT_SECONDARY}; margin-bottom:6px;'>{item}</li>")
            html.append("</ul>")
        self.guidance.setHtml("".join(html))
