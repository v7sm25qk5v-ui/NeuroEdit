from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from neuroedit_desktop.ui.main_window import MainWindow
from neuroedit_desktop.ui.styles import apply_app_style

_RESOURCES = Path(__file__).parent / "resources"


def main() -> int:
    # Render crisply at fractional Windows display scaling (125%/150%) instead of
    # rounding the scale factor, which otherwise overflows fixed-size layouts.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    apply_app_style(app)

    # App icon — shown in dock/taskbar and OS window decorations
    icon = QIcon()
    for size in (16, 32, 64, 128, 256, 512):
        p = _RESOURCES / f"icon_{size}.png"
        if p.exists():
            icon.addFile(str(p))
    if not icon.isNull():
        app.setWindowIcon(icon)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
