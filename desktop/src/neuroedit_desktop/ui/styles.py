from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

ThemeMode = Literal["light", "dark", "system"]
ResolvedTheme = Literal["light", "dark"]

THEME_SETTING_KEY = "appearance/themeMode"


@dataclass(frozen=True)
class ThemeTokens:
    bg_primary: str
    bg_secondary: str
    bg_tertiary: str
    bg_card: str
    bg_hover: str
    border: str
    border_bright: str
    primary: str
    primary_hover: str
    accent_cyan: str
    accent_emerald: str
    accent_amber: str
    accent_red: str
    accent_slides: str
    selection_outline: str
    text_primary: str
    text_secondary: str
    text_muted: str
    text_dim: str
    on_primary: str
    on_primary_hover: str
    on_success: str
    video_canvas: str
    timeline_video: str
    timeline_audio: str
    timeline_slides: str
    timeline_markers: str
    playhead: str


LIGHT_THEME = ThemeTokens(
    bg_primary="#e6ecf2",
    bg_secondary="#f5f8fb",
    bg_tertiary="#dde5ed",
    bg_card="#fbfcfe",
    bg_hover="#d3dfea",
    border="#c4d1dd",
    border_bright="#93a7ba",
    primary="#33383e",
    primary_hover="#4a5058",
    accent_cyan="#2f6690",
    accent_emerald="#276749",
    accent_amber="#76500f",
    accent_red="#9f2f24",
    accent_slides="#76588a",
    selection_outline="#2a6fb0",
    text_primary="#25292e",
    text_secondary="#4a525b",
    text_muted="#56606b",
    text_dim="#77818c",
    on_primary="#ffffff",
    on_primary_hover="#ffffff",
    on_success="#ffffff",
    video_canvas="#15171a",
    timeline_video="#6f9cc4",
    timeline_audio="#7aa58e",
    timeline_slides="#a38bb5",
    timeline_markers="#b8914a",
    playhead="#9f2f24",
)

DARK_THEME = ThemeTokens(
    bg_primary="#161819",
    bg_secondary="#1c1f22",
    bg_tertiary="#22262a",
    bg_card="#2a2e33",
    bg_hover="#33383e",
    border="#3a4047",
    border_bright="#56606b",
    primary="#8fb4d8",
    primary_hover="#a6c4e2",
    accent_cyan="#7cc0dc",
    accent_emerald="#3ccf93",
    accent_amber="#f5b23d",
    accent_red="#f26b6b",
    accent_slides="#b6a0dc",
    selection_outline="#FFD60A",
    text_primary="#e7eaee",
    text_secondary="#b4bcc5",
    text_muted="#9ba5b0",
    text_dim="#78828d",
    on_primary="#15181b",
    on_primary_hover="#15181b",
    on_success="#06281a",
    video_canvas="#000000",
    timeline_video="#8fb4d8",
    timeline_audio="#7fb89c",
    timeline_slides="#b6a0dc",
    timeline_markers="#f5b23d",
    playhead="#f26b6b",
)

THEMES: dict[ResolvedTheme, ThemeTokens] = {
    "light": LIGHT_THEME,
    "dark": DARK_THEME,
}

VALID_THEME_MODES: tuple[ThemeMode, ...] = ("light", "dark", "system")


def _settings(settings: QSettings | None = None) -> QSettings:
    return settings or QSettings("NeuroEdit", "Desktop")


def theme_preference_exists(settings: QSettings | None = None) -> bool:
    return _settings(settings).contains(THEME_SETTING_KEY)


def stored_theme_mode(settings: QSettings | None = None) -> ThemeMode:
    raw = _settings(settings).value(THEME_SETTING_KEY, "light")
    value = str(raw).lower()
    if value in VALID_THEME_MODES:
        return value  # type: ignore[return-value]
    return "light"


def save_theme_mode(mode: ThemeMode, settings: QSettings | None = None) -> None:
    if mode not in VALID_THEME_MODES:
        raise ValueError(f"Unknown theme mode: {mode}")
    _settings(settings).setValue(THEME_SETTING_KEY, mode)


def system_theme_mode(app: QGuiApplication | None = None) -> ResolvedTheme:
    app = app or QGuiApplication.instance()
    if app is None:
        return "light"
    try:
        scheme = app.styleHints().colorScheme()
    except AttributeError:
        return "light"
    return "dark" if scheme == Qt.ColorScheme.Dark else "light"


def resolve_theme_mode(
    mode: ThemeMode | None = None,
    *,
    system_mode: ResolvedTheme | None = None,
) -> ResolvedTheme:
    mode = mode or stored_theme_mode()
    if mode == "system":
        return system_mode or system_theme_mode()
    return mode


def _rgba(hex_color: str, alpha: float) -> str:
    value = hex_color.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha:.2f})"


# ── Shape / spacing scale (px) ──────────────────────────────────────────────
RADIUS_SM = 10
RADIUS_MD = 12
RADIUS_LG = 16
SPACE_XS, SPACE_SM, SPACE_MD, SPACE_LG = 4, 8, 12, 16
ICON_SM, ICON_MD = 18, 32

_ICON_DIR = Path(tempfile.gettempdir()) / "neuroedit-ui-icons"
_CHEVRON_POINTS = {"up": "2,6.5 5,3.5 8,6.5", "down": "2,3.5 5,6.5 8,3.5"}


def _chevron_icon(direction: str, color: str) -> str:
    """Write a themed chevron SVG for QSS ``image: url(...)`` and return its path."""
    path = _ICON_DIR / f"chevron-{direction}-{color.lstrip('#').lower()}.svg"
    if not path.exists():
        _ICON_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" width="10" height="10">'
            f'<polyline points="{_CHEVRON_POINTS[direction]}" fill="none" stroke="{color}"'
            ' stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
            encoding="utf-8",
        )
    return path.as_posix()


def _build_stylesheet(t: ThemeTokens) -> str:
    up = _chevron_icon("up", t.text_secondary)
    down = _chevron_icon("down", t.text_secondary)
    up_dim = _chevron_icon("up", t.text_dim)
    down_dim = _chevron_icon("down", t.text_dim)
    return f"""
QMainWindow,
QWidget#appRoot {{
    background: {t.bg_primary};
    color: {t.text_primary};
}}

QWidget {{
    color: {t.text_primary};
    selection-background-color: {t.primary};
    selection-color: {t.on_primary};
}}

QWidget#appHeader {{
    background: {t.bg_tertiary};
    border-bottom: 1px solid {t.border};
}}

QStatusBar {{
    background: {t.bg_tertiary};
    border-top: 1px solid {t.border};
    color: {t.text_muted};
}}

QLabel {{
    color: {t.text_secondary};
}}

QLabel[role="title"] {{
    color: {t.text_primary};
    font-size: 15px;
    font-weight: 700;
}}

QLabel[role="muted"] {{
    color: {t.text_muted};
    font-size: 12px;
}}

QFrame#controlsBar,
TimelineWidget,
RichTimelineWidget {{
    background: {t.bg_secondary};
    border-top: 1px solid {t.border};
}}

QStackedWidget#rightPanel {{
    background: {t.bg_secondary};
    border-left: 1px solid {t.border};
}}

SamPanel,
LabelsPanel,
SlideEditorPanel,
AudioPanel,
QTextEdit#infoPanel {{
    background: {t.bg_secondary};
}}

QPushButton,
QToolButton {{
    background: {t.bg_card};
    border: 1px solid {t.border};
    border-radius: {RADIUS_MD}px;
    color: {t.text_primary};
    padding: 7px 11px;
    font-weight: 600;
}}

QPushButton[role="iconButton"] {{
    background: transparent;
    border-color: transparent;
    color: {t.text_muted};
    font-size: 15px;
    padding: 0;
}}

QPushButton[role="rateButton"] {{
    background: {t.bg_tertiary};
    color: {t.text_secondary};
    font-size: 11px;
    padding: 0;
}}

QPushButton[role="panelTab"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {t.text_secondary};
    padding: 5px 9px;
}}

QPushButton[role="panelTab"]:hover {{
    background: {t.bg_hover};
    border-color: {t.border};
    color: {t.text_primary};
}}

QPushButton[role="panelTab"]:checked {{
    background: {t.bg_hover};
    border-color: {t.border_bright};
    color: {t.text_primary};
}}

QPushButton:hover,
QToolButton:hover,
QPushButton[role="iconButton"]:hover,
QPushButton[role="rateButton"]:hover {{
    background: {t.bg_hover};
    border-color: {t.border_bright};
    color: {t.text_primary};
}}

QPushButton:checked,
QToolButton:checked,
QPushButton[role="iconButton"]:checked,
QPushButton[variant="primary"] {{
    background: {t.primary};
    border-color: {t.primary};
    color: {t.on_primary};
}}

QPushButton:pressed,
QToolButton:pressed,
QPushButton[role="iconButton"]:pressed,
QPushButton[role="rateButton"]:pressed {{
    background: {t.bg_tertiary};
    border-color: {t.border_bright};
}}

QPushButton:checked:hover,
QToolButton:checked:hover,
QPushButton[role="iconButton"]:checked:hover,
QPushButton[variant="primary"]:hover,
QPushButton:checked:pressed,
QToolButton:checked:pressed,
QPushButton[role="iconButton"]:checked:pressed,
QPushButton[variant="primary"]:pressed {{
    background: {t.primary_hover};
    border-color: {t.primary_hover};
    color: {t.on_primary_hover};
}}

QCheckBox:hover,
QRadioButton:hover {{
    color: {t.text_primary};
}}

QPushButton[variant="cyan"] {{
    background: {_rgba(t.accent_cyan, 0.10)};
    border-color: {_rgba(t.accent_cyan, 0.35)};
    color: {t.accent_cyan};
}}

QPushButton[variant="emerald"] {{
    background: {_rgba(t.accent_emerald, 0.15)};
    border-color: {_rgba(t.accent_emerald, 0.45)};
    color: {t.accent_emerald};
}}

QPushButton[variant="emerald"]:hover {{
    background: {t.accent_emerald};
    border-color: {t.accent_emerald};
    color: {t.on_success};
}}

QPushButton[variant="amber"] {{
    background: {_rgba(t.accent_amber, 0.12)};
    border-color: {_rgba(t.accent_amber, 0.35)};
    color: {t.accent_amber};
}}

QPushButton[variant="danger"] {{
    background: {_rgba(t.accent_red, 0.10)};
    border-color: {_rgba(t.accent_red, 0.28)};
    color: {t.accent_red};
}}

QPushButton:enabled:focus,
QToolButton:enabled:focus,
QPushButton[role="iconButton"]:enabled:focus {{
    border-color: {t.selection_outline};
    outline: none;
}}

QPushButton:disabled,
QToolButton:disabled,
QPushButton[role]:disabled,
QPushButton[variant]:disabled {{
    color: {t.text_dim};
    background: {t.bg_secondary};
    border-color: {t.border};
}}

QPushButton[role="iconButton"]:disabled {{
    background: transparent;
    border-color: transparent;
}}

QLineEdit,
QComboBox,
QTextEdit,
QListWidget,
QSpinBox,
QDoubleSpinBox {{
    background: {t.bg_card};
    border: 1px solid {t.border};
    border-radius: {RADIUS_MD}px;
    color: {t.text_primary};
    padding: 7px 9px;
}}

QSpinBox,
QDoubleSpinBox {{
    padding-right: 30px;
}}

QAbstractSpinBox::up-button,
QAbstractSpinBox::down-button {{
    subcontrol-origin: border;
    width: 24px;
    border: none;
    border-left: 1px solid {t.border};
    background: transparent;
}}

QAbstractSpinBox::up-button {{
    subcontrol-position: top right;
    border-top-right-radius: {RADIUS_MD - 1}px;
}}

QAbstractSpinBox::down-button {{
    subcontrol-position: bottom right;
    border-bottom-right-radius: {RADIUS_MD - 1}px;
}}

QAbstractSpinBox::up-button:hover,
QAbstractSpinBox::down-button:hover {{
    background: {t.bg_hover};
}}

QAbstractSpinBox::up-button:pressed,
QAbstractSpinBox::down-button:pressed {{
    background: {t.border};
}}

QAbstractSpinBox::up-arrow {{
    image: url("{up}");
    width: 10px;
    height: 10px;
}}

QAbstractSpinBox::down-arrow {{
    image: url("{down}");
    width: 10px;
    height: 10px;
}}

QAbstractSpinBox::up-arrow:disabled,
QAbstractSpinBox::up-arrow:off {{
    image: url("{up_dim}");
}}

QAbstractSpinBox::down-arrow:disabled,
QAbstractSpinBox::down-arrow:off {{
    image: url("{down_dim}");
}}

QLineEdit:focus,
QComboBox:focus,
QTextEdit:focus,
QListWidget:focus,
QSpinBox:focus,
QDoubleSpinBox:focus {{
    border-color: {t.primary};
}}

QComboBox {{
    padding-right: 30px;
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    border: none;
    width: 28px;
}}

QComboBox::down-arrow {{
    image: url("{down}");
    width: 10px;
    height: 10px;
}}

QComboBox::down-arrow:disabled {{
    image: url("{down_dim}");
}}

QComboBox QAbstractItemView {{
    background: {t.bg_tertiary};
    border: 1px solid {t.border_bright};
    border-radius: {RADIUS_MD}px;
    color: {t.text_primary};
    selection-background-color: {t.primary};
    selection-color: {t.on_primary};
}}

QListWidget {{
    outline: none;
}}

QListWidget::item {{
    border: 1px solid transparent;
    border-radius: {RADIUS_SM}px;
    padding: 9px;
    margin: 2px;
    color: {t.text_secondary};
}}

QListWidget::item:hover {{
    background: {t.bg_hover};
    border-color: {t.border};
    color: {t.text_primary};
}}

QListWidget::item:selected {{
    background: {t.bg_card};
    border-color: {t.border_bright};
    color: {t.text_primary};
}}

QSlider::groove:horizontal {{
    height: 4px;
    background: {t.border};
    border-radius: 2px;
}}

QSlider::sub-page:horizontal {{
    background: {t.primary};
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    background: {t.bg_secondary};
    border: 2px solid {t.primary};
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 7px;
}}

QSplitter::handle {{
    background: {t.border};
}}

QSplitter::handle:horizontal {{
    width: 1px;
}}

QScrollBar {{
    background: {t.bg_tertiary};
    border: none;
    border-radius: 6px;
    margin: 0;
}}

QScrollBar:vertical {{ width: 12px; }}
QScrollBar:horizontal {{ height: 12px; }}

QScrollBar::handle {{
    background: {t.text_dim};
    border: 2px solid {t.bg_tertiary};
    border-radius: 6px;
}}

QScrollBar::handle:vertical {{ min-height: 28px; }}
QScrollBar::handle:horizontal {{ min-width: 28px; }}
QScrollBar::handle:hover {{ background: {t.text_muted}; }}
QScrollBar::handle:pressed {{ background: {t.text_secondary}; }}
QScrollBar::handle:focus {{ background: {t.primary}; }}
QScrollBar::handle:disabled {{ background: {t.border_bright}; }}

QScrollBar::add-line,
QScrollBar::sub-line {{
    border: none;
    width: 0;
    height: 0;
    background: transparent;
}}

QScrollBar::add-page,
QScrollBar::sub-page,
QAbstractScrollArea::corner {{
    background: transparent;
}}

QMenu {{
    background: {t.bg_tertiary};
    border: 1px solid {t.border};
    color: {t.text_primary};
}}

QMenu::item:selected {{
    background: {t.primary};
    color: {t.on_primary};
}}
"""


def _apply_tokens(t: ThemeTokens) -> None:
    global BG_PRIMARY, BG_SECONDARY, BG_TERTIARY, BG_CARD, BG_HOVER
    global BORDER, BORDER_BRIGHT, PRIMARY, PRIMARY_HOVER
    global ACCENT_CYAN, ACCENT_EMERALD, ACCENT_AMBER, ACCENT_RED, ACCENT_SLIDES
    global SELECTION_OUTLINE, TEXT_PRIMARY, TEXT_SECONDARY, TEXT_MUTED, TEXT_DIM
    global SURFACE, SURFACE_RAISED, SURFACE_SUNKEN, SURFACE_HEADER
    global ACCENT_PRIMARY, ACCENT_CLINICAL, BORDER_SUBTLE, FOCUS_RING
    global DANGER, WARNING, SUCCESS, VIDEO_CANVAS
    global TIMELINE_VIDEO, TIMELINE_AUDIO, TIMELINE_SLIDES, TIMELINE_MARKERS, PLAYHEAD
    global APP_STYLESHEET

    BG_PRIMARY = t.bg_primary
    BG_SECONDARY = t.bg_secondary
    BG_TERTIARY = t.bg_tertiary
    BG_CARD = t.bg_card
    BG_HOVER = t.bg_hover
    BORDER = t.border
    BORDER_BRIGHT = t.border_bright
    PRIMARY = t.primary
    PRIMARY_HOVER = t.primary_hover
    ACCENT_CYAN = t.accent_cyan
    ACCENT_EMERALD = t.accent_emerald
    ACCENT_AMBER = t.accent_amber
    ACCENT_RED = t.accent_red
    ACCENT_SLIDES = t.accent_slides
    SELECTION_OUTLINE = t.selection_outline
    TEXT_PRIMARY = t.text_primary
    TEXT_SECONDARY = t.text_secondary
    TEXT_MUTED = t.text_muted
    TEXT_DIM = t.text_dim

    SURFACE = BG_SECONDARY
    SURFACE_RAISED = BG_CARD
    SURFACE_SUNKEN = BG_PRIMARY
    SURFACE_HEADER = BG_TERTIARY
    ACCENT_PRIMARY = PRIMARY
    ACCENT_CLINICAL = ACCENT_CYAN
    BORDER_SUBTLE = BORDER
    FOCUS_RING = PRIMARY
    DANGER = ACCENT_RED
    WARNING = ACCENT_AMBER
    SUCCESS = ACCENT_EMERALD
    VIDEO_CANVAS = t.video_canvas
    TIMELINE_VIDEO = t.timeline_video
    TIMELINE_AUDIO = t.timeline_audio
    TIMELINE_SLIDES = t.timeline_slides
    TIMELINE_MARKERS = t.timeline_markers
    PLAYHEAD = t.playhead
    APP_STYLESHEET = _build_stylesheet(t)


# Export the default light tokens at import time. App startup may switch this
# before UI modules are imported.
_apply_tokens(LIGHT_THEME)

EXPORTED_COLOR_NAMES = (
    "BG_PRIMARY", "BG_SECONDARY", "BG_TERTIARY", "BG_CARD", "BG_HOVER",
    "BORDER", "BORDER_BRIGHT", "PRIMARY", "PRIMARY_HOVER",
    "ACCENT_CYAN", "ACCENT_EMERALD", "ACCENT_AMBER", "ACCENT_RED", "ACCENT_SLIDES",
    "SELECTION_OUTLINE", "TEXT_PRIMARY", "TEXT_SECONDARY", "TEXT_MUTED", "TEXT_DIM",
    "SURFACE", "SURFACE_RAISED", "SURFACE_SUNKEN", "SURFACE_HEADER",
    "ACCENT_PRIMARY", "ACCENT_CLINICAL", "BORDER_SUBTLE", "FOCUS_RING",
    "DANGER", "WARNING", "SUCCESS", "VIDEO_CANVAS",
    "TIMELINE_VIDEO", "TIMELINE_AUDIO", "TIMELINE_SLIDES", "TIMELINE_MARKERS",
    "PLAYHEAD",
)

def _ui_font() -> QFont:
    """Platform-native UI font."""
    if sys.platform == "darwin":
        return QFont(".AppleSystemUIFont", 12)
    if sys.platform == "win32":
        return QFont("Segoe UI", 9)
    return QFont("Sans Serif", 10)


def apply_app_style(app: QApplication, mode: ThemeMode | None = None) -> ResolvedTheme:
    resolved = resolve_theme_mode(mode)
    tokens = THEMES[resolved]
    _apply_tokens(tokens)

    app.setStyle("Fusion")
    app.setFont(_ui_font())

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG_PRIMARY))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Base, QColor(BG_CARD))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(BG_HOVER))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(BG_TERTIARY))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Button, QColor(BG_CARD))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT_SECONDARY))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(PRIMARY))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(tokens.on_primary))
    app.setPalette(palette)
    app.setStyleSheet(APP_STYLESHEET)
    return resolved
