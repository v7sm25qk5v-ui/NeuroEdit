from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from neuroedit_desktop.ui.update_dialog import UpdateDialog


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(app):
    dialog = UpdateDialog("0.5.16-alpha")
    dialog.show()
    app.processEvents()
    yield dialog
    dialog.close()


def test_available_download_and_explicit_install(dialog):
    events = []
    dialog.download_requested.connect(lambda: events.append("download"))
    dialog.install_requested.connect(lambda: events.append("install"))
    dialog.set_available(SimpleNamespace(version="0.5.17-alpha", body="<b>literal</b>"))
    assert "0.5.16-alpha" in dialog.version_label.text()
    assert "0.5.17-alpha" in dialog.version_label.text()
    assert dialog.notes.toPlainText() == "<b>literal</b>"
    dialog.action_button.click()
    assert events == ["download"]
    dialog.set_download_progress(25, 100)
    assert dialog.progress.value() == 250
    assert dialog.action_button.isHidden()
    dialog.set_downloaded()
    assert events == ["download"]
    dialog.action_button.click()
    assert events == ["download", "install"]


def test_cancel_and_close_emit_once(dialog):
    events = []
    dialog.cancel_requested.connect(lambda: events.append("cancel"))
    dialog.set_checking()
    dialog.close_button.click()
    assert events == ["cancel"]
    dialog.show()
    dialog.set_download_progress(10, None)
    assert dialog.progress.maximum() == 0
    dialog.close()
    assert events == ["cancel", "cancel"]


def test_error_retry_and_manual_install(dialog):
    events = []
    dialog.check_requested.connect(lambda: events.append("check"))
    dialog.release_page_requested.connect(lambda: events.append("releases"))
    dialog.set_error("The update could not be checked.")
    dialog.action_button.click()
    assert events == ["check"]
    dialog.set_install_capability(False, "Install manually from the releases page.")
    dialog.set_available(SimpleNamespace(version="1.0", body="notes"))
    assert dialog.action_button.isHidden()
    assert "manually" in dialog.instruction_label.text()
    dialog.release_button.click()
    assert events == ["check", "releases"]
    dialog.set_up_to_date()
    assert "up to date" in dialog.status_label.text()


def test_long_versions_wrap_as_plain_text(dialog, app):
    dialog.set_available(SimpleNamespace(version="very-long-version-" * 15, body="notes"))
    app.processEvents()
    assert dialog.version_label.wordWrap()
    assert dialog.version_label.textFormat() == Qt.TextFormat.PlainText
    assert dialog.version_label.height() >= dialog.version_label.fontMetrics().height() * 2
