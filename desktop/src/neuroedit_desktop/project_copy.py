"""Copy a project's managed files (imported media, masks, stills, audio) for
Save As, off the UI thread, with progress, cancellation and cleanup.

Imported working copies are often several gigabytes. Save As used to copy them
with ``shutil.copy2`` on the UI thread, which froze the app, and ``copy2`` also
tried to copy macOS file flags: on an iCloud "dataless" file that fails with
"Operation not permitted". Here each file is cloned when the volume supports it
(APFS: instant, no extra space), otherwise copied in chunks so progress and
Cancel keep working. Only mode and timestamps are copied, never flags.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

CHUNK_BYTES = 8 * 1024 * 1024
SPACE_MARGIN_BYTES = 256 * 1024 * 1024
_SF_DATALESS = 0x40000000  # macOS: contents live only in iCloud (or another file provider)


class CopyCancelled(Exception):
    """The user cancelled the copy; files created so far were removed."""


@dataclass
class CopyJob:
    source: Path
    destination: Path
    size: int


@dataclass
class CopyProgress:
    """Shared between the copying thread and the UI (plain attributes; the UI
    only reads them)."""

    done_bytes: int = 0
    total_bytes: int = 0
    index: int = 0
    count: int = 0
    current: str = ""
    downloading: bool = False


def is_dataless(path: Path) -> bool:
    try:
        return bool(getattr(path.stat(), "st_flags", 0) & _SF_DATALESS)
    except OSError:
        return False


def _up_to_date(job: CopyJob) -> bool:
    """A previous Save As to the same folder already copied this file."""
    try:
        src, dst = job.source.stat(), job.destination.stat()
    except OSError:
        return False
    return dst.st_size == src.st_size and dst.st_mtime_ns == src.st_mtime_ns


def plan_copies(pairs: list[tuple[Path, Path]]) -> list[CopyJob]:
    """One job per destination, skipping files already copied."""
    jobs: dict[Path, CopyJob] = {}
    for source, destination in pairs:
        if destination in jobs:
            continue
        job = CopyJob(source, destination, source.stat().st_size)
        if not _up_to_date(job):
            jobs[destination] = job
    return list(jobs.values())


def _existing_ancestor(path: Path) -> Path:
    while not path.exists() and path.parent != path:
        path = path.parent
    return path


def space_problem(jobs: list[CopyJob], destination_root: Path) -> str | None:
    """A message when the destination clearly lacks room, else None. Files on
    the same volume can be cloned without using space, so they are not counted."""
    anchor = _existing_ancestor(destination_root)
    try:
        device = anchor.stat().st_dev
        free = shutil.disk_usage(anchor).free
    except OSError:
        return None
    needed = 0
    for job in jobs:
        try:
            same_volume = job.source.stat().st_dev == device
        except OSError:
            same_volume = False
        if not (same_volume and _clone_supported()):
            needed += job.size
    if needed and needed + SPACE_MARGIN_BYTES > free:
        return (
            f"This project needs {format_bytes(needed)} of free space at the chosen "
            f"location, but only {format_bytes(free)} is available. Free up space or "
            "choose another location."
        )
    return None


def format_bytes(count: int) -> str:
    value = float(count)
    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit in ("bytes", "KB") else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _clone_supported() -> bool:
    return sys.platform == "darwin" and _clonefile() is not None


_CLONEFILE = None


def _clonefile():
    global _CLONEFILE
    if _CLONEFILE is None and sys.platform == "darwin":
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            func = libc.clonefile
            func.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
            func.restype = ctypes.c_int
            _CLONEFILE = func
        except (OSError, AttributeError):
            _CLONEFILE = False
    return _CLONEFILE or None


def _try_clone(source: Path, target: Path) -> bool:
    func = _clonefile()
    if func is None:
        return False
    CLONE_NOFOLLOW = 0x0001  # noqa: N806
    return func(os.fsencode(source), os.fsencode(target), CLONE_NOFOLLOW) == 0


def _partial_name(destination: Path) -> Path:
    return destination.with_name(f".{destination.name}.neuroedit-partial")


def copy_files(
    jobs: list[CopyJob],
    progress: CopyProgress,
    cancelled: Callable[[], bool],
) -> None:
    """Copy every job. On cancel or error, remove the files this call created
    (never a file that existed before) and re-raise."""
    progress.total_bytes = sum(job.size for job in jobs)
    progress.count = len(jobs)
    created: list[Path] = []
    try:
        for index, job in enumerate(jobs, 1):
            progress.index, progress.current = index, job.source.name
            progress.downloading = is_dataless(job.source)
            if cancelled():
                raise CopyCancelled
            existed = job.destination.exists()
            _copy_one(job, progress, cancelled)
            if not existed:
                created.append(job.destination)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def _copy_one(job: CopyJob, progress: CopyProgress, cancelled: Callable[[], bool]) -> None:
    start = progress.done_bytes
    job.destination.parent.mkdir(parents=True, exist_ok=True)
    partial = _partial_name(job.destination)
    partial.unlink(missing_ok=True)
    try:
        if not _try_clone(job.source, partial):
            partial.unlink(missing_ok=True)
            with job.source.open("rb") as reader, partial.open("wb") as writer:
                while True:
                    if cancelled():
                        raise CopyCancelled
                    chunk = reader.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    writer.write(chunk)
                    progress.done_bytes += len(chunk)
            # Mode and times only: copying st_flags fails on iCloud dataless files.
            stat = job.source.stat()
            os.chmod(partial, stat.st_mode & 0o7777)
            os.utime(partial, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        os.replace(partial, job.destination)
    finally:
        partial.unlink(missing_ok=True)
    progress.done_bytes = start + job.size
