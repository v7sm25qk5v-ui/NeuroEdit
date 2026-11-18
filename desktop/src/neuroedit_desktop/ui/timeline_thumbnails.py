"""Small, on-demand filmstrip images. Decode off the GUI thread and keep no files."""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event
from time import monotonic

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

ThumbnailKey = tuple[str, int]
_CACHE_SIZE = 192
_CACHE_SECONDS = 45
MAX_VISIBLE_THUMBNAILS = 96
_BATCH_SIZE = 6
_POLL_MS = 12
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="timeline-thumbnails")
_running_decode: Future | None = None


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
        # Nearby tiles on a long GOP can share the frames already decoded by
        # the last seek. Grabbing forward avoids reconstructing the entire GOP
        # again for each thumbnail and skips conversion of intermediate frames.
        previous_ms = -1.0
        for ms in sorted(times_ms):
            if stop.is_set():
                break
            grabbed = False
            if 0 <= previous_ms <= ms and ms - previous_ms <= 1000:
                for _ in range(60):
                    if previous_ms >= ms:
                        break
                    if stop.is_set() or not cap.grab():
                        break
                    current_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                    if not current_ms > previous_ms:
                        break
                    previous_ms = current_ms
                grabbed = previous_ms >= ms
            if stop.is_set():
                break
            if grabbed:
                ok, frame = cap.retrieve()
            else:
                previous_ms = -1.0
                if not cap.set(cv2.CAP_PROP_POS_MSEC, ms):
                    continue
                ok, frame = cap.read()
            if ok and frame is not None:
                previous_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                height, width = frame.shape[:2]
                scale = min(1.0, 96 / width, 54 / height)
                frame = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))),
                                   interpolation=cv2.INTER_AREA)
                height, width = frame.shape[:2]
                frames[ms] = QImage(frame.data, width, height, frame.strides[0], QImage.Format.Format_BGR888).copy()
    finally:
        cap.release()
    return frames


def _decode_batch(path: str, times: list[int], stop: Event) -> dict[int, QImage]:
    try:
        return _decode_thumbnails(path, times, stop)
    except Exception:
        # Broken/unmounted media should leave the normal clip bar visible.
        return {}


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
            self._timer.start(0)
        return None

    def show(self, keys: list[ThumbnailKey]) -> None:
        if not keys:
            self.pause()
            return
        self._wanted = tuple(dict.fromkeys(keys))[:MAX_VISIBLE_THUMBNAILS]
        if self._active is not None:
            _, batch_keys, stop = self._active
            if not any(key in self._wanted for key in batch_keys):
                stop.set()
        if not self._timer.isActive():
            self._timer.start(0)

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
        global _running_decode
        if self._active is not None:
            future, keys, stop = self._active
            if not future.done():
                self._timer.start(_POLL_MS)
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
        # Load one still from each new source before filling its strip. A slow
        # source should not make the entire viewport wait for several seeks.
        seen_paths = {key[0] for key in self._cache}
        unseen = next((key for key in pending if key[0] not in seen_paths), None)
        if unseen is not None:
            path = unseen[0]
            keys = [unseen]
        # Submission is coordinated on the GUI thread. Never enqueue stale work
        # behind another canvas or hand worker ownership to Qt.
        if _running_decode is None or _running_decode.done():
            stop = Event()
            _running_decode = _executor.submit(_decode_batch, path, [key[1] for key in keys], stop)
            self._active = _running_decode, keys, stop
            self._accept_active = True
        self._timer.start(_POLL_MS)
