import tempfile
from PySide6.QtCore import QSettings


def test_settings_guard():
    name = QSettings("NeuroEdit", "Desktop").fileName()
    print("SETTINGS_FILE", name)
    assert name.endswith("NeuroEdit.ini")
    assert name.startswith(("/private/var", "/var/folders", "/private/tmp", "/tmp", tempfile.gettempdir()))
