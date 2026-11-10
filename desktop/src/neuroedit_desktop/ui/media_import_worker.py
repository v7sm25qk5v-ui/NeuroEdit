from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal


class MediaImportWorker(QObject):
    finished = Signal(object, bool)
    progress = Signal(int)

    def __init__(self, paths: list[Path], probe) -> None:
        super().__init__()
        self.paths = paths
        self.probe = probe
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        results = []
        for index, path in enumerate(self.paths):
            if self._cancelled:
                break
            try:
                before = self._file_signature(path)
                metadata = self.probe(path)
                after = self._file_signature(path)
                if before != after:
                    metadata = (0.0, 0, 0)
            except Exception:  # noqa: BLE001
                metadata = (0.0, 0, 0)
                after = None
            results.append((path, (metadata, after)))
            self.progress.emit(index + 1)
        self.finished.emit(results, self._cancelled)

    @staticmethod
    def _file_signature(path: Path) -> tuple[int, int]:
        try:
            stat = path.stat()
            return stat.st_mtime_ns, stat.st_size
        except FileNotFoundError:
            return -1, -1
