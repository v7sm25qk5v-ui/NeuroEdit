from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QFont, QFontDatabase, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

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
    """The transparent aperture+scalpel mark SVG matched to the resolved theme."""
    name = "neuroedit-mark-dark.svg" if theme == "dark" else "neuroedit-mark-light.svg"
    return _RESOURCES / name


def _render_svg_pixmap(svg_path: Path, size: int) -> QPixmap | None:
    """Rasterize an SVG at device pixel ratio so the mark stays crisp on HiDPI displays."""
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
