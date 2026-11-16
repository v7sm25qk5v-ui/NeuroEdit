"""One decoder for still images, so preview, import, and export agree.

OpenCV and Qt disagree about which formats carry an orientation tag (OpenCV
applies it for PNG and WebP, Qt only for JPEG and TIFF), so every place that
shows or measures a still clip must go through this function.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QImage, QImageReader


def read_upright_image(path: str | Path) -> QImage:
    """Read a still with its orientation tag applied. Null image on failure."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    return reader.read()
