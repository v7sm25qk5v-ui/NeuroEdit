"""Keep desktop tests out of the user's native application preferences."""
from __future__ import annotations

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
        assert QSettings("NeuroEdit", "Desktop").fileName() == str(settings_path)
        yield
