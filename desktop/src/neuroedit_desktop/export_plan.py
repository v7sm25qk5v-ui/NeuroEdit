"""Export choices and estimates shared by the export sheet and the exporter.

One source of truth for the quality presets, the hardware-encoder bitrate (and
therefore the file-size estimate), the encode-time estimate, automatic frame
rate, and export file naming. No Qt widgets here, so it imports cheaply.
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from neuroedit_desktop.models import ProjectState
from neuroedit_desktop.project_copy import is_dataless


@dataclass(frozen=True)
class QualityPreset:
    key: str
    label: str
    help: str
    width: int
    height: int
    crf: int  # software encoder (libx264) only; the Mac hardware encoder uses video_bitrate_bps


QUALITY_PRESETS: tuple[QualityPreset, ...] = (
    QualityPreset(
        "1080p", "Standard (1080p)",
        "Best for teaching videos, conference screens and general sharing.",
        1920, 1080, 20,
    ),
    QualityPreset(
        "720p", "Smaller file (720p)",
        "Smaller files for email, quick review or phones.",
        1280, 720, 23,
    ),
    QualityPreset(
        "4k", "Large screen (4K)",
        "For large displays when your footage is 4K.",
        3840, 2160, 18,
    ),
)


def preset_for_key(key: str | None) -> QualityPreset:
    return next((preset for preset in QUALITY_PRESETS if preset.key == key), QUALITY_PRESETS[0])


def video_bitrate_bps(width: int, height: int) -> int:
    """Target bitrate of the Mac hardware (VideoToolbox) encoder for an output size."""
    pixels = width * height
    if pixels >= 3840 * 2160:
        return 45_000_000
    if pixels >= 1920 * 1080:
        return 12_000_000
    return 5_000_000


_CONTAINER_OVERHEAD = 1.02


def estimate_output_bytes(width: int, height: int, duration_s: float, *, audio_kbps: int | None) -> int:
    """Expected MP4 size. VideoToolbox holds its average bitrate closely (measured
    within ~5%), so this is a good estimate on a Mac; with the software encoder
    (CRF) it is only a rough guide."""
    seconds = max(0.0, duration_s)
    bits = video_bitrate_bps(width, height) * seconds
    if audio_kbps:
        bits += audio_kbps * 1000 * seconds
    return int(bits / 8 * _CONTAINER_OVERHEAD)


# Output pixels per second the export pipeline sustains. Measured on an M3 Pro:
# VideoToolbox encodes 1080p at ~190 fps whatever the content, and one stream
# saturates it (parallel encodes give no speed-up).
DEFAULT_PIXEL_RATE = 380_000_000.0


def estimate_encode_seconds(
    width: int, height: int, fps: int, duration_s: float, *, pixel_rate: float | None = None,
) -> float:
    rate = pixel_rate if pixel_rate and pixel_rate > 0 and math.isfinite(pixel_rate) else DEFAULT_PIXEL_RATE
    return max(0.0, width * height * fps * max(0.0, duration_s) / rate)


def format_time_estimate(seconds: float) -> str:
    """Plain wording for an estimate: 'less than a minute', 'about 3 min', 'about 1 h 5 min'."""
    if not math.isfinite(seconds) or seconds < 45:
        return "less than a minute"
    minutes = max(1, round(seconds / 60))
    if minutes < 60:
        return f"about {minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"about {hours} h {rest} min" if rest else f"about {hours} h"


STANDARD_FPS: tuple[int, ...] = (24, 25, 30, 50, 60)
DEFAULT_FPS = 30


def snap_fps(fps: float | None) -> int | None:
    """Map a probed source rate to an export rate: 29.97 → 30, 59.94 → 60,
    23.976 → 24, 25 → 25. Faster than 60 exports at 60; odd slow rates at 30."""
    if fps is None or not math.isfinite(fps) or fps <= 0:
        return None
    nearest = min(STANDARD_FPS, key=lambda standard: abs(standard - fps))
    if abs(nearest - fps) <= 1.0:
        return nearest
    return 60 if fps > 60 else DEFAULT_FPS


_fps_cache: dict[tuple[str, int, int], float | None] = {}


def source_fps(path: Path) -> float | None:
    """Frame rate stored in a video file, or None. Never reads an iCloud-evicted
    (dataless) file: opening one would block while macOS downloads all of it."""
    try:
        stat = path.stat()
    except OSError:
        return None
    if is_dataless(path):
        return None
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if key in _fps_cache:
        return _fps_cache[key]
    fps: float | None = None
    try:
        import cv2  # noqa: PLC0415

        cap = cv2.VideoCapture(str(path))
        try:
            if cap.isOpened():
                fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or None
        finally:
            cap.release()
    except Exception:  # noqa: BLE001 - a probe failure just means "unknown"
        fps = None
    _fps_cache[key] = fps
    return fps


def automatic_fps(
    project: ProjectState, *, probe: Callable[[Path], float | None] = source_fps,
) -> int:
    """The export rate that matches the video: the snapped rate covering the most
    timeline time across video clips. 30 when nothing can be probed."""
    weights: dict[int, float] = {}
    for clip in project.clips:
        if clip.media_type != "video" or clip.display_duration <= 0:
            continue
        snapped = snap_fps(probe(Path(clip.path)))
        if snapped is not None:
            weights[snapped] = weights.get(snapped, 0.0) + clip.display_duration
    if not weights:
        return DEFAULT_FPS
    # Ties go to the higher rate so motion is never thrown away.
    return max(weights, key=lambda fps: (weights[fps], fps))


_UNSAFE_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
DEFAULT_EXPORT_NAME = "NeuroEdit Export"


def readable_export_name(project_name: str) -> str:
    """A file name people recognise: the project name, minus characters macOS or
    Windows reject, with spaces kept."""
    name = _UNSAFE_NAME_CHARS.sub(" ", project_name or "")
    name = " ".join(name.split()).strip(" .")
    return name[:120].rstrip(" .") or DEFAULT_EXPORT_NAME


def unique_export_path(folder: Path, name: str, suffix: str = ".mp4") -> Path:
    """`folder/name.mp4`, or `name 2.mp4`, `name 3.mp4`… so an earlier export is
    never replaced by default."""
    stem = readable_export_name(name)
    candidate = folder / f"{stem}{suffix}"
    number = 2
    while candidate.exists():
        candidate = folder / f"{stem} {number}{suffix}"
        number += 1
    return candidate
