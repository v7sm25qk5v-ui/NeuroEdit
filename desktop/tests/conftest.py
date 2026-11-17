"""Keep desktop tests out of the user's native application preferences."""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings


@pytest.fixture(scope="session", autouse=True)
def isolated_app_settings(tmp_path_factory):
    original_init = QSettings.__init__
    settings_path = tmp_path_factory.mktemp("app-settings") / "NeuroEdit.ini"

    def isolated_init(self, *args, **kwargs):
        # The explicit organization/application constructor uses NativeFormat
        # on macOS even when setDefaultFormat() selects IniFormat.
        if args == ("NeuroEdit", "Desktop"):
            original_init(self, str(settings_path), QSettings.Format.IniFormat, **kwargs)
        else:
            original_init(self, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(QSettings, "__init__", isolated_init)
        assert Path(QSettings("NeuroEdit", "Desktop").fileName()) == settings_path
        yield


@pytest.fixture(scope="session", autouse=True)
def close_qt_windows_at_exit(isolated_app_settings):
    """Destroy leftover windows before Python shuts down.

    Each MainWindow owns a media player and audio output. Dozens of them left
    alive until interpreter exit are torn down in an arbitrary order, which has
    crashed the process (exit code 139) after an otherwise green run.
    """
    yield
    import gc

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    app.closeAllWindows()
    for widget in app.topLevelWidgets():
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    gc.collect()
