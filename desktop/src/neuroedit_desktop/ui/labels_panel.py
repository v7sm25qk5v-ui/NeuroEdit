from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from neuroedit_desktop.models import Annotation, ProjectState
from neuroedit_desktop.ui.styles import (
    BG_CARD,
    BG_HOVER,
    BORDER,
    BORDER_BRIGHT,
    DANGER,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)

SWATCH_COLORS = [
    "#00e5ff",
    "#ef4444",
    "#f59e0b",
    "#10b981",
    "#8b5cf6",
    "#f43f5e",
    "#ffffff",
    "#fb923c",
]

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




