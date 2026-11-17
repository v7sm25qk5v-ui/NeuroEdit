from concurrent.futures import Future

import pytest
from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox

from neuroedit_desktop.models import TimelineMarker
from neuroedit_desktop.project_store import ProjectStore
from neuroedit_desktop.ui import update_workflow as module
from neuroedit_desktop.update_install import InstallTarget, PreparedInstall
from neuroedit_desktop.update_release import parse_release
from test_main_window_headless import app, window  # noqa: F401
from test_update_release import payload


class Service(QObject):
    checking = Signal()
    available = Signal(object)
    up_to_date = Signal()
    progress = Signal(int, int)
    downloaded = Signal(str, object)
    error = Signal(str)
    cancelled = Signal()

    def __init__(self, _version, parent=None):
        super().__init__(parent)
        self.checks = 0
        self.cancelled_count = 0
        self.disposed = False

    def check_for_updates(self):
        self.checks += 1
        self.checking.emit()

    def download_update(self, release):
        self.requested = release

    def cancel(self):
        self.cancelled_count += 1

    def dispose(self):
        self.disposed = True


@pytest.fixture
def flow(window, tmp_path, monkeypatch):  # noqa: F811
    window._startup_sam_timer.stop()
    monkeypatch.setattr(module, 'UpdateService', Service)
    monkeypatch.setattr(module, 'inspect_install_target', lambda: InstallTarget('darwin', tmp_path / 'NeuroEdit.app'))
    result = module.UpdateWorkflow(window)
    window._update_workflow = result
    yield result
    result._future = None
    result.dispose()
    QSettings('NeuroEdit', 'Desktop').remove(module._REOPEN_KEY)


def downloaded(flow, tmp_path):
    release = parse_release(payload(), 'darwin', '0.5.18')
    path = tmp_path / 'download' / release.asset.name
    path.parent.mkdir()
    path.write_bytes(b'abc')
    flow._available(release)
    flow._downloaded(str(path), release)
    return path


def prepared(flow, tmp_path):
    stage = tmp_path / 'stage'
    stage.mkdir()
    flow._prepared = PreparedInstall(InstallTarget('darwin', tmp_path / 'NeuroEdit.app'), stage, stage / 'NeuroEdit.app')


def test_menu_opens_one_checker_without_startup_network(flow, window):  # noqa: F811
    assert flow.service.checks == 0
    window.check_updates_action.trigger()
    assert flow.dialog.isVisible() and flow.service.checks == 1
    window.check_updates_action.trigger()
    assert flow.service.checks == 1
    flow.dialog.reject()
    window.check_updates_action.trigger()
    assert flow.service.checks == 2


def test_available_download_is_explicit_and_notes_show_full_tag(flow, tmp_path):
    downloaded(flow, tmp_path)
    assert 'v0.5.19-alpha.1' in flow.dialog.version_label.text()
    assert not hasattr(flow.service, 'requested')
    flow.download()
    assert flow.service.requested == flow.release


def test_source_checkout_offers_manual_install(flow, monkeypatch):
    monkeypatch.setattr(module, 'inspect_install_target', lambda: InstallTarget('darwin', None, 'Install the packaged app first.'))
    flow._available(parse_release(payload(), 'darwin', '0.5.18'))
    assert flow.dialog.action_button.isHidden()
    assert flow.dialog.instruction_label.text() == 'Install the packaged app first.'


def test_cancel_and_close_remove_only_owned_download(flow, tmp_path):
    path = downloaded(flow, tmp_path)
    other = path.parent / 'other-file'
    other.write_text('keep')
    flow.dialog.reject()
    assert not path.exists() and other.read_text() == 'keep'
    assert flow.service.cancelled_count > 0


def test_preparation_failure_never_closes_or_launches(flow, tmp_path, monkeypatch):
    downloaded(flow, tmp_path)
    future = Future()
    future.set_exception(ValueError('malformed archive'))
    monkeypatch.setattr(flow, '_busy', lambda: False)
    monkeypatch.setattr(flow._executor, 'submit', lambda *args: future)
    monkeypatch.setattr(module, 'launch_prepared_install', lambda p: pytest.fail('must not launch'))
    with monkeypatch.context() as patch:
        patch.setattr(flow.window, 'close', lambda: pytest.fail('must not close'))
        flow.install()
        flow._poll_prepare()
    assert flow._future is None
    assert 'could not be prepared' in flow.dialog.status_label.text()


def test_close_is_blocked_during_preparation(flow):
    flow._future = Future()
    event = QCloseEvent()
    flow.window.closeEvent(event)
    assert not event.isAccepted() and not flow.service.disposed


def test_done_audio_result_still_blocks_install_until_gui_commit(flow, tmp_path):
    downloaded(flow, tmp_path)
    task = Future()
    task.set_result(4.0)
    flow.window.audio_panel._audio_import_future = task
    try:
        assert flow._busy()
        flow.install()
        assert flow._future is None
    finally:
        flow.window.audio_panel._audio_import_future = None


def test_failed_save_does_not_launch_or_stop_autosave(flow, tmp_path, monkeypatch):
    downloaded(flow, tmp_path)
    prepared(flow, tmp_path)
    flow.window.dirty = True
    monkeypatch.setattr(flow.window, '_has_active_background_job', lambda: False)
    monkeypatch.setattr(flow.window.store, 'save', lambda _project: (_ for _ in ()).throw(OSError('full')))
    errors = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args: errors.append(args))
    monkeypatch.setattr(module, 'launch_prepared_install', lambda p: pytest.fail('must not launch'))
    event = QCloseEvent()
    flow.window.closeEvent(event)
    assert not event.isAccepted() and errors
    assert flow.window.autosave_timer.isActive() and flow.window.dirty
    flow.window.dirty = False


def test_helper_launch_failure_keeps_app_and_restores_resume_key(flow, tmp_path, monkeypatch):
    downloaded(flow, tmp_path)
    prepared(flow, tmp_path)
    flow.window.store.save(flow.window.project)
    settings = QSettings('NeuroEdit', 'Desktop')
    settings.remove(module._REOPEN_KEY)
    monkeypatch.setattr(flow.window, '_has_active_background_job', lambda: False)
    monkeypatch.setattr(module, 'launch_prepared_install', lambda p: (_ for _ in ()).throw(OSError('denied')))
    event = QCloseEvent()
    flow.window.closeEvent(event)
    assert not event.isAccepted() and not flow.service.disposed
    assert flow.window.autosave_timer.isActive()
    assert not settings.contains(module._REOPEN_KEY)


def test_install_saves_before_helper_and_records_original_project(flow, tmp_path, monkeypatch):
    downloaded(flow, tmp_path)
    prepared(flow, tmp_path)
    flow.window.project.markers.append(TimelineMarker(id='update-test', time=0, label='saved'))
    flow.window.dirty = False
    monkeypatch.setattr(flow.window, '_has_active_background_job', lambda: False)
    launched = []
    def launch(_prepared):
        _, project = ProjectStore.open(flow.window.store.project_path)
        assert project.markers[0].label == 'saved'
        assert QSettings('NeuroEdit', 'Desktop').value(module._REOPEN_KEY) == str(flow.window.store.project_path.resolve())
        launched.append(True)
    monkeypatch.setattr(module, 'launch_prepared_install', launch)
    event = QCloseEvent()
    flow.window.closeEvent(event)
    assert event.isAccepted() and launched and flow.service.disposed
    assert flow._prepared is None


def test_empty_project_without_a_file_does_not_set_broken_resume_key(flow, tmp_path, monkeypatch):
    prepared(flow, tmp_path)
    monkeypatch.setattr(module, 'launch_prepared_install', lambda _prepared: None)
    assert not flow.window.store.project_path.exists()
    assert flow.before_window_close()
    assert not QSettings('NeuroEdit', 'Desktop').contains(module._REOPEN_KEY)


def test_clean_existing_project_keeps_unknown_fields_during_update(flow, tmp_path, monkeypatch):
    import json

    prepared(flow, tmp_path)
    flow.window.project.markers.append(TimelineMarker(id='existing', time=0, label='kept'))
    flow.window.store.save(flow.window.project)
    path = flow.window.store.project_path
    data = json.loads(path.read_text())
    data['schema_version'] = 99
    data['future_feature'] = {'preserve': True}
    path.write_text(json.dumps(data))
    original = path.read_bytes()
    flow.window.dirty = False
    monkeypatch.setattr(flow.window, '_has_active_background_job', lambda: False)
    monkeypatch.setattr(module, 'launch_prepared_install', lambda _prepared: None)
    event = QCloseEvent()
    flow.window.closeEvent(event)
    assert event.isAccepted()
    assert path.read_bytes() == original


def test_resume_opens_original_saved_project_once(window, tmp_path):  # noqa: F811
    store = ProjectStore.create(tmp_path / 'Saved case')
    project = window.project
    project.project_name = 'Resume this case'
    store.save(project)
    settings = QSettings('NeuroEdit', 'Desktop')
    settings.setValue(module._REOPEN_KEY, str(store.project_path))
    module.resume_after_update(window)
    assert window.store.project_path == store.project_path
    assert window.project.project_name == 'Resume this case'
    assert not settings.contains(module._REOPEN_KEY)
