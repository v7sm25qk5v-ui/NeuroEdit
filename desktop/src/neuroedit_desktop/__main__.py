from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from neuroedit_desktop.ui.main_window import MainWindow
from neuroedit_desktop.ui.styles import apply_app_style


def main() -> int:
    app = QApplication(sys.argv)
    apply_app_style(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
