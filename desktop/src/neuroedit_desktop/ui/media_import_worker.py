from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal


class MediaImportWorker(QObject):
    """Probe (and, for MPG, first convert) each video off the GUI thread.

    Each result is `(path, (metadata, signature, media_path, created, error))`:
    `media_path` is the file the clip should use (a working copy for MPG),
    `created` says whether this run made that copy, and `error` is a short
    reason when a conversion failed.
    """

    finished = Signal(object, bool)
    progress = Signal(int)  # PROGRESS_STEPS per file
    status = Signal(str)

    PROGRESS_STEPS = 100

    def __init__(self, paths: list[Path], probe, convert=None) -> None:
        super().__init__()
        self.paths = paths
        self.probe = probe
        self.convert = convert
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        from neuroedit_desktop.media_convert import (
            ConversionCancelled,
            ConversionFailed,
            needs_conversion,
        )

        results = []
        steps = self.PROGRESS_STEPS
        for index, path in enumerate(self.paths):
            if self._cancelled:
                break
            media_path, created, error = path, False, None
            try:
                if self.convert is not None and needs_conversion(path):
                    self.status.emit(f"Converting {path.name} to a working copy...")
                    media_path, created = self.convert(
                        path,
                        cancelled=lambda: self._cancelled,
                        progress=lambda value, base=index * steps: self.progress.emit(
                            base + int(value * (steps - 1))
                        ),
                    )
                    self.status.emit("Reading video metadata...")
                before = self._file_signature(media_path)
                metadata = self.probe(media_path)
                after = self._file_signature(media_path)
                if before != after:
                    metadata = (0.0, 0, 0)
            except ConversionCancelled:
                break
            except ConversionFailed as exc:
                metadata, after = (0.0, 0, 0), None
                error = f"could not convert: {exc}"[:200]
            except Exception:  # noqa: BLE001
                metadata = (0.0, 0, 0)
                after = None
            results.append((path, (metadata, after, media_path, created, error)))
            self.progress.emit((index + 1) * steps)
        self.finished.emit(results, self._cancelled)

    @staticmethod
    def _file_signature(path: Path) -> tuple[int, int]:
        try:
            stat = path.stat()
            return stat.st_mtime_ns, stat.st_size
        except FileNotFoundError:
            return -1, -1
