"""Coordinate user-approved updates with the editor's normal save/close flow."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

from neuroedit_desktop.project_store import ProjectStore
from neuroedit_desktop.update_install import (
    discard_prepared_install,
    inspect_install_target,
    launch_prepared_install,
    prepare_install,
)
from neuroedit_desktop.update_release import REPOSITORY
from neuroedit_desktop.update_service import UpdateService, installed_release_tag
from neuroedit_desktop.ui.update_dialog import UpdateDialog

_REOPEN_KEY = "updates/reopenProject"


class UpdateWorkflow(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.dialog = UpdateDialog(installed_release_tag(), window)
        self.dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.service = UpdateService(installed_release_tag(), parent=self)
        self.release = None
        self._download = None
        self._prepared = None
        self._future = None
        self._disposed = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="update-prepare")
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._poll_prepare)
        self.dialog.check_requested.connect(self.check)
        self.dialog.download_requested.connect(self.download)
        self.dialog.install_requested.connect(self.install)
        self.dialog.cancel_requested.connect(self.service.cancel)
        self.dialog.release_page_requested.connect(self.open_release)
        self.dialog.finished.connect(self._dialog_closed)
        self.service.checking.connect(self.dialog.set_checking)
        self.service.available.connect(self._available)
        self.service.up_to_date.connect(self.dialog.set_up_to_date)
        self.service.progress.connect(self.dialog.set_download_progress)
        self.service.downloaded.connect(self._downloaded)
        self.service.error.connect(self.dialog.set_error)

    def show(self) -> None:
        if self._disposed:
            return
        if self.dialog.isVisible():
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        self.dialog.show()
        self.check()

    def _clear_download(self) -> None:
        if self._download is not None:
            path, self._download = self._download, None
            try:
                path.unlink(missing_ok=True)
                path.parent.rmdir()
            except OSError:
                pass

    def _discard_prepared(self) -> None:
        if self._prepared is not None:
            prepared, self._prepared = self._prepared, None
            discard_prepared_install(prepared)

    def check(self) -> None:
        if self._disposed or self._future is not None:
            return
        self.service.cancel()
        self._clear_download()
        self._discard_prepared()
        self.release = None
        self.service.check_for_updates()

    def _available(self, release) -> None:
        self.release = release
        target = inspect_install_target()
        self.dialog.set_install_capability(target.supported, target.reason)
        self.dialog.set_available(release)

    def download(self) -> None:
        if self.release is None or self._disposed or self._future is not None:
            return
        self.dialog.set_download_progress(0, self.release.asset.size)
        self.service.download_update(self.release)

    def _downloaded(self, path: str, release) -> None:
        self._clear_download()
        self._download = Path(path)
        self.release = release
        self.dialog.set_downloaded()

    def _busy(self) -> bool:
        if self.window.audio_panel.recording_pending:
            return True
        for name in ("_export_thread", "_import_thread", "_sam_probe_thread",
                     "_sam_download_thread", "_sam_segment_thread", "_sam_propagation_thread"):
            thread = getattr(self.window, name, None)
            if thread is not None:
                # Even a stopped thread can have an unapplied result queued for
                # the GUI. Its owner clears this reference after completion.
                return True
        audio_probe = getattr(self.window.audio_panel, "_audio_import_future", None)
        return audio_probe is not None

    @property
    def install_pending(self) -> bool:
        return self._prepared is not None

    def install(self) -> None:
        if self._disposed or self._download is None or self.release is None or self._future:
            return
        if self._busy():
            self.dialog.set_error("Finish recording, importing, exporting, or segmentation before installing an update.")
            return
        target = inspect_install_target()
        if not target.supported:
            self.dialog.set_install_capability(False, target.reason)
            return
        self.dialog.set_installing()
        self._future = self._executor.submit(prepare_install, self._download, self.release, target)
        self._timer.start()

    def _poll_prepare(self) -> None:
        if self._future is None or not self._future.done():
            return
        future, self._future = self._future, None
        self._timer.stop()
        try:
            self._prepared = future.result()
        except Exception:
            self.dialog.set_error("The update could not be prepared. Try downloading it again, or install it from the releases page.")
            return
        self._clear_download()
        if self._busy():
            self._discard_prepared()
            self.dialog.set_error("Finish background work before installing. Check for updates again when it is complete.")
            return
        self.dialog.hide()
        # Only closeEvent's accepted path can launch the helper. Save failures,
        # pending recordings, and any rejected close leave the current app intact.
        if not self.window.close():
            self._discard_prepared()
            self.dialog.set_error("The update was not installed. Save your work and finish background tasks, then try again.")
            self.dialog.show()

    def can_close(self) -> bool:
        if self._future is not None:
            self.window.statusBar().showMessage("Preparing the update. Please wait before closing NeuroEdit.", 5000)
            return False
        return True

    def before_window_close(self) -> bool:
        """Called after successful save, before shutdown or possible forced exit."""
        if not self.can_close():
            return False
        if self._prepared is not None:
            settings = QSettings("NeuroEdit", "Desktop")
            previous = settings.value(_REOPEN_KEY, None)
            try:
                if self.window.store.project_path.is_file():
                    settings.setValue(_REOPEN_KEY, str(self.window.store.project_path.resolve()))
                else:
                    settings.remove(_REOPEN_KEY)
                settings.sync()
                if settings.status() != QSettings.Status.NoError:
                    raise OSError("Could not save restart state")
                launch_prepared_install(self._prepared)
            except Exception:
                if previous is None:
                    settings.remove(_REOPEN_KEY)
                else:
                    settings.setValue(_REOPEN_KEY, previous)
                settings.sync()
                self.dialog.set_error("The installer could not be started. Try again or use the releases page.")
                return False
            self._prepared = None  # Detached helper now owns staging and rollback.
        self.dispose()
        return True

    def _dialog_closed(self, _result: int) -> None:
        if self._future is None:
            self.service.cancel()
            self._clear_download()
            self._discard_prepared()

    def open_release(self) -> None:
        url = self.release.html_url if self.release is not None else REPOSITORY + "/releases/latest"
        QDesktopServices.openUrl(QUrl(url))

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._timer.stop()
        self.service.dispose()
        self.dialog.hide()
        self._clear_download()
        self._discard_prepared()
        self._executor.shutdown(wait=False, cancel_futures=True)


def resume_after_update(window) -> None:
    settings = QSettings("NeuroEdit", "Desktop")
    filename = settings.value(_REOPEN_KEY, "", type=str)
    if not filename:
        return
    settings.remove(_REOPEN_KEY)
    if Path(filename).name != "project.json":
        return
    try:
        store, project = ProjectStore.open(Path(filename))
        window._activate_project(store, project)
        window._validate_loaded_project_media("Update restart")
        window._load_active_clip()
        window.refresh()
        window._update_title()
    except Exception:
        QMessageBox.warning(window, "Reopen project", "NeuroEdit was restarted, but the last project could not be reopened. Use Open Project to locate it.")
