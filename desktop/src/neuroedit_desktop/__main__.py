from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer
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

_ERROR_BURST_SECONDS = 10.0
_last_error_time: float | None = None


def _show_error_box() -> None:
    app = QApplication.instance()
    if app is not None and QThread.currentThread() is not app.thread():
        # Raised in a worker thread: widgets may only be used on the GUI thread.
        QTimer.singleShot(0, app, _show_error_box)
        return
    QMessageBox.warning(
        None, "NeuroEdit",
        "Something went wrong in NeuroEdit. Your work was not closed. "
        "Consider saving your project and restarting the app if it misbehaves.",
    )


def handle_unhandled_exception(exc_type, exc, tb, *, show=_show_error_box, now=time.monotonic) -> None:
    """sys.excepthook: log the traceback, tell the user once per burst, never raise.

    Privacy: exception messages often embed file paths, so only the exception
    type and the stack frames (code locations) are logged; the message box is
    fixed text.
    """
    global _last_error_time
    try:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        from neuroedit_desktop import diagnostics

        frames = "".join(traceback.format_tb(tb))
        diagnostics.log_crash(f"Unhandled {exc_type.__name__}\n{frames}")
        current = now()
        in_burst = _last_error_time is not None and 0 <= current - _last_error_time < _ERROR_BURST_SECONDS
        _last_error_time = current
        if not in_burst:
            show()
    except Exception:  # noqa: BLE001 - a crash handler must not crash
        pass


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
    sys.excepthook = handle_unhandled_exception
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
