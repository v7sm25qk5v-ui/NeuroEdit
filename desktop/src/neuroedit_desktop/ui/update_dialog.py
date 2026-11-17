from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class UpdateDialog(QDialog):
    """Display update status; the controller performs all update operations."""

    check_requested = Signal()
    download_requested = Signal()
    install_requested = Signal()
    cancel_requested = Signal()
    release_page_requested = Signal()

    def __init__(self, current_version: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Software Update")
        self.setMinimumWidth(480)
        self.resize(520, 380)
        self._current_version = current_version
        self._state = "idle"
        self._install_available = True
        self._install_reason = ""

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        self.status_label = QLabel("Check for a newer version of NeuroEdit.")
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.version_label = QLabel()
        self.version_label.setTextFormat(Qt.TextFormat.PlainText)
        self.version_label.setWordWrap(True)
        layout.addWidget(self.version_label)
        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        layout.addWidget(self.notes)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.instruction_label = QLabel()
        self.instruction_label.setTextFormat(Qt.TextFormat.PlainText)
        self.instruction_label.setWordWrap(True)
        layout.addWidget(self.instruction_label)

        buttons = QHBoxLayout()
        self.release_button = QPushButton("Open Releases")
        self.release_button.clicked.connect(self.release_page_requested)
        buttons.addWidget(self.release_button)
        buttons.addStretch()
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.close_button)
        self.action_button = QPushButton()
        buttons.addWidget(self.action_button)
        layout.addLayout(buttons)
        self.action_button.clicked.connect(self._action)
        self._render()

    def _action(self) -> None:
        if self._state in ("idle", "error", "up_to_date"):
            self.check_requested.emit()
        elif self._state == "available":
            self.download_requested.emit()
        elif self._state == "downloaded":
            self.install_requested.emit()

    def _cancel_active(self) -> None:
        if self._state in ("checking", "downloading"):
            self._state = "cancelled"
            self.cancel_requested.emit()

    def reject(self) -> None:
        if self._state == "installing":
            return
        self._cancel_active()
        super().reject()

    def closeEvent(self, event) -> None:
        if self._state == "installing":
            event.ignore()
            return
        self._cancel_active()
        super().closeEvent(event)

    def _render(self) -> None:
        state = self._state
        active = state in ("checking", "downloading")
        self.close_button.setText("Cancel" if active else "Close")
        self.close_button.setEnabled(state != "installing")
        self.progress.setVisible(active)
        self.notes.setVisible(state in ("available", "downloading", "downloaded"))
        self.version_label.setVisible(state in ("available", "downloading", "downloaded"))
        manual = state in ("available", "downloaded") and not self._install_available
        self.instruction_label.setVisible(manual)
        self.instruction_label.setText(
            self._install_reason or "Install this update manually from the releases page."
        )
        self.release_button.setVisible(state in ("available", "downloaded", "error"))
        actions = {"idle": "Check for Updates", "up_to_date": "Check Again", "error": "Retry",
                   "available": "Download", "downloaded": "Install and Restart"}
        self.action_button.setVisible(state in actions and not manual)
        if state in actions:
            self.action_button.setText(actions[state])

    def set_checking(self) -> None:
        self._state = "checking"
        self.status_label.setText("Checking for updates…")
        self.progress.setRange(0, 0)
        self._render()

    def set_up_to_date(self) -> None:
        self._state = "up_to_date"
        self.status_label.setText(f"NeuroEdit {self._current_version} is up to date.")
        self._render()

    def set_available(self, release) -> None:
        self._state = "available"
        self.status_label.setText("An update is available.")
        latest = getattr(release, "tag_name", release.version)
        self.version_label.setText(f"Current version: {self._current_version}\nNew version: {latest}")
        self.notes.setPlainText(release.body or "No release notes are available.")
        self._render()

    def set_download_progress(self, received: int, total: int | None) -> None:
        self._state = "downloading"
        self.status_label.setText("Downloading update…")
        if total and total > 0:
            self.progress.setRange(0, 1000)
            self.progress.setValue(min(1000, max(0, int(received * 1000 / total))))
        else:
            self.progress.setRange(0, 0)
        self._render()

    def set_downloaded(self) -> None:
        self._state = "downloaded"
        self.status_label.setText("The update is ready to install. NeuroEdit will restart.")
        self._render()

    def set_installing(self) -> None:
        self._state = "installing"
        self.status_label.setText("Installing update…")
        self._render()

    def set_error(self, message: str) -> None:
        self._state = "error"
        self.status_label.setText(message)
        self._render()

    def set_install_capability(self, available: bool, reason: str = "") -> None:
        self._install_available = available
        self._install_reason = reason
        self._render()
