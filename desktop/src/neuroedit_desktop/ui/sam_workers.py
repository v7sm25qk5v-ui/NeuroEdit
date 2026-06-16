from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from neuroedit_desktop.models import SamPoint
from neuroedit_desktop.sam_backend import SamBackend, SamCancelled


class SamProbeWorker(QObject):
    """Probes the SAM backend and warms the model weights in the background.
    PyTorch import (5-15s) + first model download (~375 MB) + MPS compile
    all happen here so segmentation clicks later are instant."""
    finished = Signal(object)   # emits SamBackendInfo
    progress = Signal(str)

    def __init__(self, backend: SamBackend) -> None:
        super().__init__()
        self.backend = backend
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        from neuroedit_desktop.sam_backend import SamBackendInfo
        try:
            self.progress.emit("Importing PyTorch…")
            info = self.backend.probe()
            if info.status == "ready":
                self.progress.emit(info.message)
        except Exception as exc:  # noqa: BLE001
            info = SamBackendInfo(status="missing", device="none", message=str(exc))
        self.finished.emit(info)


class SamSegmentWorker(QObject):
    """Runs SamBackend.segment_frame on a background thread. Model load + MPS
    inference on a 1080p frame takes several seconds — must not block UI."""
    finished = Signal(object, object)  # (result_or_none, error_msg_or_none)
    progress = Signal(str)

    def __init__(
        self,
        backend: SamBackend,
        video_path: Path,
        time_s: float,
        points: list[SamPoint],
        mask_dir: Path,
        mask_color: tuple[int, int, int] | None = None,
    ) -> None:
        super().__init__()
        self.backend = backend
        self.video_path = video_path
        self.time_s = time_s
        self.points = points
        self.mask_dir = mask_dir
        self.mask_color = mask_color
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            result = self.backend.segment_frame(
                self.video_path, self.time_s, self.points, self.mask_dir,
                progress=self.progress.emit,
                mask_color=self.mask_color,
            )
            self.finished.emit(result, None)
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(None, str(exc))


class SamPropagationWorker(QObject):
    finished = Signal(object, object)  # (result_or_none, error_msg_or_none)
    progress = Signal(str)

    def __init__(
        self,
        backend: SamBackend,
        video_path: Path,
        start_time_s: float,
        duration_s: float,
        points: list[SamPoint],
        mask_dir: Path,
        sample_rate: float = 2.0,
        mask_color: tuple[int, int, int] | None = None,
    ) -> None:
        super().__init__()
        self.backend = backend
        self.video_path = video_path
        self.start_time_s = start_time_s
        self.duration_s = duration_s
        self.points = points
        self.mask_dir = mask_dir
        self.sample_rate = sample_rate
        self.mask_color = mask_color
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            result = self.backend.propagate_video(
                self.video_path,
                self.start_time_s,
                self.duration_s,
                self.points,
                self.mask_dir,
                progress=self.progress.emit,
                sample_rate=self.sample_rate,
                cancelled=lambda: self._cancelled,
                mask_color=self.mask_color,
            )
            self.finished.emit(result, None)
        except SamCancelled:
            self.finished.emit(None, None)
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(None, str(exc))


class SamDownloadWorker(QObject):
    """Authenticates with HuggingFace and downloads SAM3 weights via warmup()."""
    finished = Signal(object)  # SamBackendInfo
    progress = Signal(str)

    def __init__(self, backend: SamBackend, token: str) -> None:
        super().__init__()
        self.backend = backend
        self.token = token

    def run(self) -> None:
        from neuroedit_desktop.sam_backend import SamBackendInfo
        try:
            if self.token:
                self.progress.emit("Authenticating with HuggingFace…")
                self.backend.login(self.token)
            self.progress.emit("Downloading SAM3 weights (~3.2 GB, this may take several minutes)…")
            info = self.backend.warmup(self.progress.emit)
            self.finished.emit(info)
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(SamBackendInfo(status="missing", device="none", message=str(exc)))
