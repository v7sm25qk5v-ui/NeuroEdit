from __future__ import annotations

from pathlib import Path

# Auto-assigned SAM mask colors: cyan, magenta, yellow, green, orange, blue,
# pink, lime. Colorblind-aware and deliberately without red — red reads as
# blood/danger on surgical video.
MASK_PALETTE = [
    "#22d3ee", "#e879f9", "#facc15", "#4ade80",
    "#fb923c", "#60a5fa", "#f472b6", "#a3e635",
]

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".webm"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".heic", ".bmp", ".webp"}


def format_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes = int(seconds // 60)
    remainder = seconds % 60
    return f"{minutes}:{remainder:04.1f}"


def hex_to_rgb(color_hex: str) -> tuple[int, int, int]:
    value = color_hex.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def propagation_window_s(remaining_s: float, to_clip_end: bool, window_s: float) -> float:
    """Effective SAM propagation window clamped to the clip length and at least 1 s."""
    if to_clip_end:
        return max(1.0, remaining_s)
    return max(1.0, min(window_s, remaining_s))


def referenced_mask_paths(project_dicts: list[dict]) -> set[str]:
    """Every mask PNG referenced by the given project dicts, as resolved path strings."""
    referenced: set[str] = set()
    for data in project_dicts:
        for ann in data.get("annotations") or []:
            mask_path = ann.get("mask_path")
            if mask_path:
                referenced.add(str(Path(str(mask_path)).resolve()))
            for frame in ann.get("mask_frames") or []:
                frame_path = frame.get("mask_path")
                if frame_path:
                    referenced.add(str(Path(str(frame_path)).resolve()))
    return referenced


def delete_orphan_masks(masks_dir: Path, referenced: set[str]) -> int:
    """Delete unreferenced files directly inside masks_dir."""
    if not masks_dir.is_dir():
        return 0
    masks_dir = masks_dir.resolve()
    removed = 0
    for path in masks_dir.iterdir():
        resolved = path.resolve()
        if not resolved.is_file() or resolved.parent != masks_dir:
            continue
        if str(resolved) in referenced:
            continue
        try:
            resolved.unlink()
            removed += 1
        except OSError:
            pass
    return removed
