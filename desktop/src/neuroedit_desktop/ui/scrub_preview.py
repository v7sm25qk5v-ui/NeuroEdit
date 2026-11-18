"""Latest-request video decoding for the temporary timeline scrub preview."""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Condition

from PySide6.QtGui import QImage

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scrub-preview")


@dataclass(frozen=True)
class ScrubTarget:
    # The clip mapping is part of the request so a late frame from another
    # split, source, or edit cannot be painted under this clip's overlays.
    clip_id: str
    path: str
    start: float
    trim_start: float
    trim_end: float
    source_ms: int

    @property
    def clip_key(self) -> tuple[str, str, float, float, float]:
        return self.clip_id, self.path, self.start, self.trim_start, self.trim_end


@dataclass(frozen=True)
class ScrubFrame:
    target: ScrubTarget
    image: QImage
    source_ms: float
    size: tuple[int, int]


class ScrubDecoder:
    """Keep one decoder for a drag and replace pending work as the pointer moves."""

    def __init__(self) -> None:
        self._condition = Condition()
        self._pending: ScrubTarget | None = None
        self._result: ScrubFrame | None = None
        self._stopped = False
        self._future = _executor.submit(self._decode)

    def request(self, target: ScrubTarget) -> None:
        with self._condition:
            if self._future.done():
                self._future = _executor.submit(self._decode)
            self._pending = target
            self._condition.notify()

    def take(self) -> ScrubFrame | None:
        with self._condition:
            if self._pending is not None and self._future.done():
                self._future = _executor.submit(self._decode)
            result, self._result = self._result, None
            return result

    def close(self) -> None:
        with self._condition:
            self._stopped = True
            self._pending = None
            self._result = None
            self._condition.notify()
        self._future.cancel()

    def _next_target(self) -> ScrubTarget | None:
        with self._condition:
            self._condition.wait_for(lambda: self._stopped or self._pending is not None, timeout=2.0)
            target, self._pending = self._pending, None
            return target if not self._stopped else None

    def _decode(self) -> None:
        import cv2

        cap = cv2.VideoCapture()
        path = None
        last_ms = -1.0
        try:
            while (target := self._next_target()) is not None:
                try:
                    if path != target.path:
                        cap.release()
                        path, last_ms = target.path, -1.0
                        cap.open(path, cv2.CAP_FFMPEG, [
                            cv2.CAP_PROP_N_THREADS, 2,
                            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 800,
                            cv2.CAP_PROP_READ_TIMEOUT_MSEC, 800,
                        ])
                    if not cap.isOpened():
                        continue
                    # Nearby forward seeks can reuse the decoder. A large or
                    # backwards jump uses the file's keyframe index instead.
                    if not 0 < target.source_ms - last_ms <= 400 or last_ms < 0:
                        if not cap.set(cv2.CAP_PROP_POS_MSEC, target.source_ms):
                            continue
                    else:
                        while last_ms < target.source_ms - 34:
                            if self._stopped:
                                return
                            if not cap.grab():
                                break
                            next_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                            if next_ms <= last_ms:
                                last_ms = -1.0
                                break
                            last_ms = next_ms
                        if last_ms < 0:
                            continue
                        ok, frame = cap.retrieve()
                        if not ok:
                            continue
                        self._publish(target, frame, last_ms, cv2)
                        continue
                    ok, frame = cap.read()
                    if ok:
                        last_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                        self._publish(target, frame, last_ms, cv2)
                except (cv2.error, OSError):
                    last_ms = -1.0
        finally:
            cap.release()

    def _publish(self, target: ScrubTarget, frame, source_ms: float, cv2) -> None:
        if (frame is None or not math.isfinite(source_ms)
                or abs(source_ms - target.source_ms) > 200):
            return
        h, w = frame.shape[:2]
        size = (w, h)
        scale = min(1.0, 640 / w, 360 / h)
        if scale < 1:
            frame = cv2.resize(frame, (max(1, round(w * scale)), max(1, round(h * scale))),
                               interpolation=cv2.INTER_AREA)
            h, w = frame.shape[:2]
        image = QImage(frame.data, w, h, frame.strides[0], QImage.Format.Format_BGR888).copy()
        with self._condition:
            if not self._stopped:
                self._result = ScrubFrame(target, image, source_ms, size)
