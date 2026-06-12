from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from neuroedit_desktop.ui.styles import (
    ThemeMode,
    apply_app_style,
    save_theme_mode,
    stored_theme_mode,
    theme_preference_exists,
)

_RESOURCES = Path(__file__).parent / "resources"


def _choose_first_run_theme(app: QApplication) -> ThemeMode:
    if theme_preference_exists():
        return stored_theme_mode()

    apply_app_style(app, "light")
    dialog = QMessageBox()
    dialog.setWindowTitle("Choose Appearance")
    dialog.setText("Choose NeuroEdit's appearance.")
    dialog.setInformativeText(
        "Light uses the warm cream Figma direction. Dark keeps the high-contrast editor theme. "
        "System follows your OS setting."
    )
    light_btn = dialog.addButton("Light", QMessageBox.ButtonRole.AcceptRole)
    dark_btn = dialog.addButton("Dark", QMessageBox.ButtonRole.AcceptRole)
    system_btn = dialog.addButton("System", QMessageBox.ButtonRole.AcceptRole)
    dialog.setDefaultButton(light_btn)
    dialog.exec()

    clicked = dialog.clickedButton()
    mode: ThemeMode = "light"
    if clicked == dark_btn:
        mode = "dark"
    elif clicked == system_btn:
        mode = "system"
    save_theme_mode(mode)
    return mode


def main() -> int:
    # Render crisply at fractional Windows display scaling (125%/150%) instead of
    # rounding the scale factor, which otherwise overflows fixed-size layouts.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    mode = _choose_first_run_theme(app)
    apply_app_style(app, mode)

    # App icon — shown in dock/taskbar and OS window decorations
    icon = QIcon()
    for size in (16, 32, 64, 128, 256, 512):
        p = _RESOURCES / f"icon_{size}.png"
        if p.exists():
            icon.addFile(str(p))
    if not icon.isNull():
        app.setWindowIcon(icon)

    from neuroedit_desktop.ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
