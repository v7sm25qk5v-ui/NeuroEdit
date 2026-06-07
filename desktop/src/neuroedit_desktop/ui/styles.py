from __future__ import annotations

import sys

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

BG_PRIMARY = "#090a0f"
BG_SECONDARY = "#10131a"
BG_TERTIARY = "#151923"
BG_CARD = "#1b202b"
BG_HOVER = "#242a36"
BORDER = "#2c3340"
BORDER_BRIGHT = "#465161"
PRIMARY = "#4f7cff"
PRIMARY_HOVER = "#3f68dc"
ACCENT_CYAN = "#22d3ee"
ACCENT_EMERALD = "#10b981"
ACCENT_AMBER = "#f59e0b"
ACCENT_RED = "#ef4444"
TEXT_PRIMARY = "#e2e8f0"
TEXT_SECONDARY = "#94a3b8"
TEXT_MUTED = "#64748b"
TEXT_DIM = "#475569"


APP_STYLESHEET = f"""
QMainWindow,
QWidget#appRoot {{
    background: {BG_PRIMARY};
    color: {TEXT_PRIMARY};
}}

QWidget {{
    color: {TEXT_PRIMARY};
    selection-background-color: {PRIMARY};
    selection-color: white;
}}

QWidget#appHeader {{
    background: {BG_TERTIARY};
    border-bottom: 1px solid {BORDER};
}}

QStatusBar {{
    background: {BG_TERTIARY};
    border-top: 1px solid {BORDER};
    color: {TEXT_MUTED};
}}

QLabel {{
    color: {TEXT_SECONDARY};
}}

QLabel[role="title"] {{
    color: {TEXT_PRIMARY};
    font-size: 15px;
    font-weight: 700;
}}

QLabel[role="muted"] {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}

QFrame#controlsBar,
TimelineWidget,
RichTimelineWidget {{
    background: {BG_SECONDARY};
    border-top: 1px solid {BORDER};
}}

QStackedWidget#rightPanel {{
    background: {BG_SECONDARY};
    border-left: 1px solid {BORDER};
}}

SamPanel,
LabelsPanel,
SlideEditorPanel,
AudioPanel,
QTextEdit#infoPanel {{
    background: {BG_SECONDARY};
}}

QPushButton,
QToolButton {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 7px;
    color: {TEXT_SECONDARY};
    padding: 7px 11px;
    font-weight: 600;
}}

QPushButton[role="panelTab"] {{
    background: transparent;
    border: 1px solid transparent;
    color: {TEXT_SECONDARY};
    padding: 5px 9px;
}}

QPushButton[role="panelTab"]:hover {{
    background: {BG_HOVER};
    border-color: {BORDER};
    color: {TEXT_PRIMARY};
}}

QPushButton[role="panelTab"]:checked {{
    background: {BG_HOVER};
    border-color: {BORDER_BRIGHT};
    color: {TEXT_PRIMARY};
}}

QPushButton:hover,
QToolButton:hover {{
    background: {BG_HOVER};
    border-color: {BORDER_BRIGHT};
    color: {TEXT_PRIMARY};
}}

QPushButton:checked,
QToolButton:checked,
QPushButton[variant="primary"] {{
    background: {PRIMARY};
    border-color: {PRIMARY};
    color: white;
}}

QPushButton[variant="cyan"] {{
    background: rgba(34, 211, 238, 0.10);
    border-color: rgba(34, 211, 238, 0.35);
    color: {ACCENT_CYAN};
}}

QPushButton[variant="emerald"] {{
    background: rgba(16, 185, 129, 0.18);
    border-color: rgba(16, 185, 129, 0.55);
    color: #d1fae5;
}}

QPushButton[variant="emerald"]:hover {{
    background: {ACCENT_EMERALD};
    border-color: {ACCENT_EMERALD};
    color: white;
}}

QPushButton[variant="amber"] {{
    background: rgba(245, 158, 11, 0.12);
    border-color: rgba(245, 158, 11, 0.35);
    color: {ACCENT_AMBER};
}}

QPushButton[variant="danger"] {{
    background: rgba(239, 68, 68, 0.10);
    border-color: rgba(239, 68, 68, 0.28);
    color: {ACCENT_RED};
}}

QLineEdit,
QComboBox,
QTextEdit,
QListWidget,
QSpinBox,
QDoubleSpinBox {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    color: {TEXT_PRIMARY};
    padding: 7px 9px;
}}

QLineEdit:focus,
QComboBox:focus,
QTextEdit:focus,
QListWidget:focus,
QSpinBox:focus,
QDoubleSpinBox:focus {{
    border-color: {PRIMARY};
}}

QComboBox::drop-down {{
    border: none;
    width: 22px;
}}

QComboBox QAbstractItemView {{
    background: {BG_TERTIARY};
    border: 1px solid {BORDER_BRIGHT};
    border-radius: 8px;
    color: {TEXT_PRIMARY};
    selection-background-color: {PRIMARY};
}}

QListWidget {{
    outline: none;
}}

QListWidget::item {{
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 9px;
    margin: 2px;
    color: {TEXT_SECONDARY};
}}

QListWidget::item:hover {{
    background: {BG_HOVER};
    border-color: {BORDER};
    color: {TEXT_PRIMARY};
}}

QListWidget::item:selected {{
    background: {BG_CARD};
    border-color: {BORDER_BRIGHT};
    color: {TEXT_PRIMARY};
}}

QSlider::groove:horizontal {{
    height: 4px;
    background: {BORDER};
    border-radius: 2px;
}}

QSlider::sub-page:horizontal {{
    background: {PRIMARY};
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    background: white;
    border: 2px solid {PRIMARY};
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 7px;
}}

QSplitter::handle {{
    background: {BORDER};
}}

QSplitter::handle:horizontal {{
    width: 1px;
}}

QScrollBar:vertical,
QScrollBar:horizontal {{
    background: {BG_SECONDARY};
    width: 8px;
    height: 8px;
    margin: 0;
}}

QScrollBar::handle:vertical,
QScrollBar::handle:horizontal {{
    background: {BORDER_BRIGHT};
    border-radius: 4px;
    min-height: 28px;
    min-width: 28px;
}}

QMenu {{
    background: {BG_TERTIARY};
    border: 1px solid {BORDER};
    color: {TEXT_PRIMARY};
}}

QMenu::item:selected {{
    background: {PRIMARY};
    color: white;
}}
"""


def _ui_font() -> QFont:
    """Platform-native UI font. The previous hardcoded ".AppleSystemUIFont"
    does not exist on Windows/Linux, where Qt fell back to an oversized default
    face that overflowed the toolbar. Use each platform's native UI font."""
    if sys.platform == "darwin":
        return QFont(".AppleSystemUIFont", 12)
    if sys.platform == "win32":
        return QFont("Segoe UI", 9)
    return QFont("Sans Serif", 10)


def apply_app_style(app: QApplication) -> None:
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
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)
    app.setStyleSheet(APP_STYLESHEET)
