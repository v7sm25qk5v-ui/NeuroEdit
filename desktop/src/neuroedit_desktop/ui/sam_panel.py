from __future__ import annotations

import re

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from neuroedit_desktop.models import Annotation, ProjectState
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
