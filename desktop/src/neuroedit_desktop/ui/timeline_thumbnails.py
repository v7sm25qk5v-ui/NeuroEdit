"""Small, on-demand filmstrip images. Decode off the GUI thread and keep no files."""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future
from pathlib import Path
from threading import Event
from time import monotonic

from PySide6.QtCore import QCoreApplication, QObject, QRunnable, QThread, QThreadPool, QTimer, Signal
from PySide6.QtGui import QImage

ThumbnailKey = tuple[str, int]
_CACHE_SIZE = 192
_CACHE_SECONDS = 45
MAX_VISIBLE_THUMBNAILS = 96
_BATCH_SIZE = 4


def _decode_thumbnails(path: str, times_ms: list[int], stop: Event) -> dict[int, QImage]:
    if stop.is_set() or not Path(path).is_file():
        return {}
    import cv2

    cap = cv2.VideoCapture()
    frames = {}
    try:
        if not cap.open(path, cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_N_THREADS, 1,
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 800,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC, 800,
        ]):
            return {}
        for ms in times_ms:
            if stop.is_set():
                break
            if not cap.set(cv2.CAP_PROP_POS_MSEC, ms):
                continue
            ok, frame = cap.read()
            if ok and frame is not None:
                height, width = frame.shape[:2]
                scale = min(1.0, 96 / width, 54 / height)
                frame = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))),
                                   interpolation=cv2.INTER_AREA)
                height, width = frame.shape[:2]
                frames[ms] = QImage(frame.data, width, height, frame.strides[0], QImage.Format.Format_BGR888).copy()
    finally:
        cap.release()
    return frames


def _complete_decode(future: Future, path: str, times: list[int], stop: Event) -> None:
    try:
        future.set_result(_decode_thumbnails(path, times, stop))
    except Exception:
        # Broken/unmounted media should leave the normal clip bar visible.
        future.set_result({})


def _pool() -> QThreadPool:
    app = QCoreApplication.instance()
    pool = app.findChild(QThreadPool, "timelineThumbnailPool")
    if pool is None:
        pool = QThreadPool(app)
        pool.setObjectName("timelineThumbnailPool")
        pool.setMaxThreadCount(1)
        pool.setThreadPriority(QThread.Priority.LowPriority)
    return pool


class TimelineThumbnails(QObject):
    changed = Signal()

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self._cache: OrderedDict[ThumbnailKey, tuple[float, QImage | None]] = OrderedDict()
        self._wanted: tuple[ThumbnailKey, ...] = ()
        self._active: tuple[Future, list[ThumbnailKey], Event] | None = None
        self._accept_active = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance)

    def image(self, key: ThumbnailKey) -> QImage | None:
        entry = self._cache.get(key)
        if entry is not None and entry[0] > monotonic():
            self._cache.move_to_end(key)
            return entry[1]
        if entry is not None and not self._timer.isActive():
            self._timer.start(70)
        return None

    def show(self, keys: list[ThumbnailKey]) -> None:
        if not keys:
            self.pause()
            return
        self._wanted = tuple(dict.fromkeys(keys))[:MAX_VISIBLE_THUMBNAILS]
        if not self._timer.isActive():
            self._timer.start(70)

    def pause(self) -> None:
        self._wanted = ()
        self._timer.stop()
        if self._active is not None:
            self._active[2].set()

    def clear(self) -> None:
        self.pause()
        self._accept_active = False
        self._cache.clear()

    def _advance(self) -> None:
        if self._active is not None:
            future, keys, stop = self._active
            if not future.done():
                self._timer.start(30)
                return
            self._active = None
            if self._accept_active:
                frames = future.result()
                exp = monotonic() + _CACHE_SECONDS
                for key in keys:
                    if key in self._wanted:
                        # A cancelled batch may have decoded only some of its
                        # frames. Let the visible strip retry the others.
                        if not stop.is_set() or key[1] in frames:
                            self._cache[key] = exp, frames.get(key[1])
                            self._cache.move_to_end(key)
                while len(self._cache) > _CACHE_SIZE:
                    self._cache.popitem(last=False)
                if any(key in self._wanted and key[1] in frames for key in keys):
                    self.changed.emit()

        now = monotonic()
        pending = [key for key in self._wanted if self._cache.get(key, (0, None))[0] <= now]
        if not pending:
            return
        path = pending[0][0]
        keys = [key for key in pending if key[0] == path][:_BATCH_SIZE]
        future = Future()
        stop = Event()
        times = [key[1] for key in keys]
        # tryStart never leaves obscured or stale batches queued behind work
        # from another timeline. Qt owns the worker, which never touches widgets.
        if _pool().tryStart(QRunnable.create(lambda: _complete_decode(future, path, times, stop))):
            self._active = future, keys, stop
            self._accept_active = True
        self._timer.start(30)
