from __future__ import annotations

import copy
import json
import os
import shutil
import time
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QImage,
    QPixmap,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QDialog,
    QInputDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
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
from neuroedit_desktop.ui.branding import (
    _identity_mark_path,
    _render_svg_pixmap,
    _wordmark_font,
)
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
)
from neuroedit_desktop.ui.project_library import ProjectLibraryDialog
from neuroedit_desktop.ui.canvas import AnnotationGraphicsItem, VideoGraphicsView
from neuroedit_desktop.ui.sam_workers import (
    SamDownloadWorker,
    SamProbeWorker,
    SamPropagationWorker,
    SamSegmentWorker,
)
from neuroedit_desktop.ui.sam_panel import SamPanel
from neuroedit_desktop.ui.sam_workflow import SamWorkflowMixin
from neuroedit_desktop.ui.export_workflow import ExportWorkflowMixin
from neuroedit_desktop.ui.history import HistoryMixin
from neuroedit_desktop.ui.labels_panel import (
    ANATOMY_PRESETS,
    SWATCH_COLORS,
    LabelsPanel,
    _load_custom_presets,
)
from neuroedit_desktop.ui.main_window_utils import (
    IMAGE_EXTENSIONS,
    MASK_PALETTE,
    VIDEO_EXTENSIONS,
    delete_orphan_masks,
    format_time,
    hex_to_rgb,
    propagation_window_s,
    referenced_mask_paths,
)
from neuroedit_desktop.ui.editor_panels import (
    AudioPanel,
    MediaExplorerPanel,
    RichTimelineWidget,
    SlideEditorPanel,
    TipsPanel,
    project_end_time,
)
from neuroedit_desktop.ui.export_worker import ExportWorker
from neuroedit_desktop.ui.styles import (
    ACCENT_AMBER, ACCENT_CYAN, ACCENT_RED, ACCENT_SLIDES,
    BG_CARD, BG_HOVER,
    BORDER, BORDER_BRIGHT, PRIMARY,
    TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY, VIDEO_CANVAS,
)
from neuroedit_desktop.ui.tutorial import TutorialOverlay, build_default_steps
from neuroedit_desktop.video_probe import probe_video

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
    "ExportWorker",
    "IMAGE_EXTENSIONS",
    "LabelsPanel",
    "MASK_PALETTE",
    "PhiReviewDialog",
    "SamSetupDialog",
    "StorageLocationDialog",
    "VIDEO_EXTENSIONS",
    "delete_orphan_masks",
    "default_project_root",
    "format_time",
    "hex_to_rgb",
    "legacy_project_root",
    "migrate_storage_root",
    "propagation_window_s",
    "recommended_preset_key",
    "recommended_project_root",
    "referenced_mask_paths",
]

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

class MainWindow(HistoryMixin, ExportWorkflowMixin, SamWorkflowMixin, QMainWindow):
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
        self.timeline.project_changed.connect(self._mark_review_relevant_project_dirty)
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
        self.slides_panel.project_changed.connect(self._mark_review_relevant_project_dirty)
        self.audio_panel.project_changed.connect(self._mark_review_relevant_project_dirty)
        self.audio_panel.review_state_changed.connect(self._mark_project_metadata_dirty)
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

    def _invalidate_review_attestations(self) -> None:
        """Require fresh review after content that can introduce PHI changes."""
        self.project.phi_review_confirmed = False
        self.project.deidentified_confirmed = False
        self.project.audio_reviewed_for_phi = False
        self.project.phi_review_progress = {}
        project_path = getattr(getattr(self, "store", None), "project_path", None)
        if isinstance(project_path, Path):
            try:
                (project_path.parent / ".neuroedit-thumbnail.jpg").unlink()
            except OSError:
                pass

    def _has_active_background_job(self) -> bool:
        for attr in (
            "_export_thread",
            "_sam_segment_thread",
            "_sam_propagation_thread",
        ):
            thread = getattr(self, attr, None)
            if thread is not None:
                try:
                    if thread.isRunning():
                        return True
                except RuntimeError:
                    continue
        return False

    def _confirm_project_replacement(self) -> bool:
        if self._has_active_background_job():
            QMessageBox.information(
                self,
                "Background work in progress",
                "Finish or cancel the current export or SAM job before changing projects.",
            )
            return False
        if not self.dirty:
            return True
        reply = QMessageBox.question(
            self,
            "Unsaved Changes",
            "Save changes to the current project before switching projects?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Cancel:
            return False
        if reply == QMessageBox.StandardButton.Save:
            self._save_project()
            return not self.dirty
        return True

    def _activate_project(self, store: ProjectStore, project: ProjectState) -> None:
        player = getattr(self, "player", None)
        if player is not None:
            player.stop()
        self.store = store
        self.project = project
        self.dirty = False
        if hasattr(self, "_media_warnings_shown"):
            self._media_warnings_shown.clear()
        if hasattr(self, "_media_problem_cache"):
            self._media_problem_cache.clear()
        self._invalidate_project_end_time()
        self._seed_history()

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
        self._change_storage_location()

    def _change_storage_location(self) -> None:
        old_root = default_project_root()
        dialog = StorageLocationDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        root = dialog.chosen_root()
        settings = QSettings("NeuroEdit", "Desktop")
        settings.setValue("storage/projectRoot", str(root))
        settings.setValue("storage/promptShown", True)
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

    # ── Project actions ───────────────────────────────────────────────────

    def _new_project(self) -> None:
        if not self._confirm_project_replacement():
            return
        self._activate_project(ProjectStore.create(default_project_root()), ProjectState())
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
        if not self._confirm_project_replacement():
            return
        load_start = time.perf_counter()
        try:
            store, project = ProjectStore.open(Path(path))
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return
        self._activate_project(store, project)
        self._add_to_recent(Path(path))
        self._validate_loaded_project_media("Open project")
        self._load_active_clip()
        self._log_project_load(load_start, "dialog")
        self.refresh()

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

        # Create <parent>/<name>/ as the project folder only after confirming
        # any existing document and staging a self-contained copy of managed assets.
        project_folder = Path(parent) / name
        project_path = project_folder / "project.json"
        if project_path.exists():
            reply = QMessageBox.question(
                self,
                "Replace Existing Project?",
                f"{project_path} already exists. Replace it with this project?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        old_store = self.store
        old_root = old_store.project_path.parent
        staged_project = copy.deepcopy(self.project)
        staged_project.project_name = name
        staged_store = ProjectStore.create(project_folder)
        try:
            self._migrate_managed_assets(staged_project, old_root, project_folder)
            staged_store.save(staged_project)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self._activate_project(staged_store, staged_project)
        self.refresh()
        self._update_title()
        self._add_to_recent(self.store.project_path)
        self.statusBar().showMessage(f"Saved {self.store.project_path}", 3000)
        self.project_name.blockSignals(True)
        self.project_name.setText(self.project.project_name)
        self.project_name.blockSignals(False)

    @staticmethod
    def _migrate_managed_assets(project: ProjectState, old_root: Path, new_root: Path) -> None:
        """Copy app-managed assets into Save As and rewrite their project paths."""
        def migrate(path_str: str | None) -> str | None:
            if not path_str:
                return path_str
            source = Path(path_str)
            try:
                relative = source.relative_to(old_root)
            except ValueError:
                return path_str
            if not relative.parts or relative.parts[0] not in {"masks", "audio", "stills"}:
                return path_str
            if not source.is_file():
                return path_str
            destination = new_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            return str(destination)

        for annotation in project.annotations:
            annotation.mask_path = migrate(annotation.mask_path)
            for frame in annotation.mask_frames:
                frame["mask_path"] = migrate(str(frame.get("mask_path") or "")) or ""
        for slide in project.slides:
            slide.image_path = migrate(slide.image_path)
        for track in project.audio_tracks:
            track.path = migrate(track.path) or track.path

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
        if not self._confirm_project_replacement():
            return
        load_start = time.perf_counter()
        try:
            store, project = ProjectStore.open(path)
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return
        self._activate_project(store, project)
        self._add_to_recent(path)
        self._validate_loaded_project_media("Open recent project")
        self._load_active_clip()
        self._log_project_load(load_start, "recent")
        self.refresh()

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
        self._mark_dirty(review_relevant=True)

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
        self._mark_dirty(review_relevant=True)
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
        self._mark_dirty(review_relevant=True)

    def _delete_annotation(self, annotation_id: str) -> None:
        self.project.annotations = [
            ann for ann in self.project.annotations if ann.id != annotation_id
        ]
        if self.project.selected_annotation_id == annotation_id:
            self.project.selected_annotation_id = None
        self._mark_dirty(review_relevant=True)

    def _update_annotation_duration(self, annotation_id: str, duration: float) -> None:
        for ann in self.project.annotations:
            if ann.id == annotation_id:
                ann.ann_duration = max(0.0, duration)
                break
        self._mark_dirty(review_relevant=True)

    def _find_annotation(self, annotation_id: str) -> Annotation | None:
        return next((a for a in self.project.annotations if a.id == annotation_id), None)

    def _update_annotation_label(self, annotation_id: str, text: str) -> None:
        ann = self._find_annotation(annotation_id)
        if ann is not None:
            ann.label = text
            self._mark_dirty(review_relevant=True)

    def _update_annotation_color(self, annotation_id: str, color: str) -> None:
        ann = self._find_annotation(annotation_id)
        if ann is not None:
            ann.color = color
            self._mark_dirty(review_relevant=True)

    def _set_annotation_visibility(self, annotation_id: str, visible: bool) -> None:
        ann = self._find_annotation(annotation_id)
        if ann is not None:
            ann.visible = bool(visible)
            self._mark_dirty(review_relevant=True)

    def _update_annotation_font_size(self, annotation_id: str, size: int) -> None:
        ann = self._find_annotation(annotation_id)
        if ann is not None:
            ann.font_size = max(8, int(size))
            self._mark_dirty(review_relevant=True)

    def _update_annotation_stroke(self, annotation_id: str, width: int) -> None:
        ann = self._find_annotation(annotation_id)
        if ann is not None:
            ann.geometry["width_px"] = float(max(1, int(width)))
            self._mark_dirty(review_relevant=True)

    def _update_annotation_opacity(self, annotation_id: str, opacity: float) -> None:
        ann = self._find_annotation(annotation_id)
        if ann is not None:
            ann.opacity = max(0.05, min(1.0, float(opacity)))
            self._mark_dirty(review_relevant=True)

    def _update_annotation_show_label(self, annotation_id: str, show: bool) -> None:
        ann = self._find_annotation(annotation_id)
        if ann is not None and ann.type in {"rect", "ellipse", "arrow"}:
            ann.show_label = bool(show)
            self._mark_dirty(review_relevant=True)

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
        self._mark_dirty(review_relevant=True)

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
        self._mark_dirty(review_relevant=True)

    def _set_annotation_end_to_playhead(self, annotation_id: str) -> None:
        ann = self._find_annotation(annotation_id)
        if ann is None:
            return
        new_duration = self.project.current_time - ann.frame_time
        ann.ann_duration = max(0.1, new_duration)
        self._mark_dirty(review_relevant=True)

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
        self._mark_dirty(review_relevant=True)

    def _start_inline_label_edit(self, annotation_id: str) -> None:
        ann = self._find_annotation(annotation_id)
        if ann is None:
            return
        self.project.active_panel = "labels"
        self._mark_dirty(history=False)
        self.labels_panel.set_selected_annotation(annotation_id)
        self.labels_panel.label_edit.setFocus()
        self.labels_panel.label_edit.selectAll()

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
            ("_sam_download_thread", "_sam_download_worker"),
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
        # safely on disk. Never close silently after a failed dirty save.
        if self.dirty:
            try:
                self.store.save(self.project)
                self.dirty = False
                self._autosave_snapshot = None
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "Save failed", str(exc))
                event.ignore()
                return
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
