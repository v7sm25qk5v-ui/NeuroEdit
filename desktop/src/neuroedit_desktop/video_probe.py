from __future__ import annotations

from pathlib import Path


def probe_video(path: Path) -> tuple[float, int, int]:
    try:
        import cv2
    except ImportError:
        return 0.0, 1920, 1080

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return 0.0, 1920, 1080

    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
    cap.release()

    duration = frame_count / fps if fps > 0 else 0.0
    return duration, width, height
