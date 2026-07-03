from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from neuroedit_desktop.models import ProjectState

if TYPE_CHECKING:
    from neuroedit_desktop.exporter import ExportSettings


class ExportWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(object, object, object)  # output_path_or_none, error_or_none, warnings

    def __init__(self, project: ProjectState, settings: ExportSettings) -> None:
        super().__init__()
        self.project = project
        self.settings = settings
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        from neuroedit_desktop.exporter import ExportCancelled, ProjectExporter

        try:
            exporter = ProjectExporter(
                self.project,
                self.settings,
                progress=self.progress.emit,
                cancelled=lambda: self._cancelled,
            )
            warnings = exporter.export()
            self.finished.emit(str(self.settings.output_path), None, warnings)
        except ExportCancelled:
            self.finished.emit(None, "Export canceled.", [])
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(None, str(exc), [])
