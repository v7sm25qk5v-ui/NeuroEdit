"""Working copies for video files the editor cannot seek accurately.

MPEG program streams (.mpg, .mpeg) have no seek index, and their timestamps
start about half a second in. On those files Qt's player shows the next
keyframe after a paused seek (up to ~0.5 s late) and OpenCV repeats one frame
for the first ~0.5 s, so the preview and the export would disagree about which
frame is on screen. Importing one makes an ordinary H.264 MP4 copy in the
project's media folder; the original file is never modified.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

CONVERT_EXTENSIONS = frozenset({".mpg", ".mpeg"})
MEDIA_DIR_NAME = "media"
_STAGE_PREFIX = ".neuroedit-convert-"
# Copies are named "<original stem>.neuroedit-<12 hex>.mp4". Only files with
# such a name are ever deleted by the app: a project's media folder may also
# hold the user's own footage.
_WORKING_COPY_NAME = re.compile(r"^.+\.neuroedit-[0-9a-f]{12}\.mp4$")
_STALE_STAGE_SECONDS = 10 * 60

ProgressCallback = Callable[[float], None]
CancelCallback = Callable[[], bool]


class ConversionCancelled(Exception):
    pass


class ConversionFailed(Exception):
    pass


def needs_conversion(path: Path) -> bool:
    return Path(path).suffix.lower() in CONVERT_EXTENSIONS


def is_working_copy_name(name: str) -> bool:
    return bool(_WORKING_COPY_NAME.match(name))


def is_stale_conversion_file(path: Path, *, now: float | None = None) -> bool:
    """A temporary file left by a conversion that was killed (e.g. a forced quit).
    A live conversion keeps writing, so its file is never this old."""
    if not path.name.startswith(_STAGE_PREFIX):
        return False
    try:
        age = (time.time() if now is None else now) - path.stat().st_mtime
    except OSError:
        return False
    return age > _STALE_STAGE_SECONDS


def rebase_working_copies(project, project_folder: Path) -> None:
    """Point clips at this folder's working copies when the project folder was
    moved or copied. Clip paths are stored absolute, so after a move they still
    name the old folder; the copy's name is unique to its source, so a file of
    that name in this folder's media folder is the same copy."""
    media_dir = project_folder / MEDIA_DIR_NAME
    for clip in getattr(project, "clips", []):
        path = Path(clip.path)
        if not is_working_copy_name(path.name) or path.is_file():
            continue
        local = media_dir / path.name
        if local.is_file() and not local.is_symlink():
            clip.path = str(local)


def working_copy_path(source: Path, media_dir: Path) -> Path:
    """Where the copy of `source` lives. The name changes when the source file
    does, so an edited original is converted again rather than reusing a stale copy."""
    stat = source.stat()
    key = f"{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    stem = re.sub(r"[^\w.-]+", "_", source.stem)[:80].strip("._") or "video"
    return media_dir / f"{stem}.neuroedit-{digest}.mp4"


def convert_to_working_copy(
    source: Path,
    media_dir: Path,
    *,
    cancelled: CancelCallback | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[Path, bool]:
    """Return (copy path, created). Reuses an existing complete copy of the same
    unchanged source. The copy appears atomically: there is never a partial file
    at its final name."""
    source = Path(source)
    _ensure_media_dir(media_dir)
    target = working_copy_path(source, media_dir)
    if target.is_file() and target.stat().st_size > 0:
        return target, False

    from neuroedit_desktop.exporter import require_ffmpeg  # noqa: PLC0415

    ffmpeg = require_ffmpeg()
    for leftover in media_dir.glob(f"{_STAGE_PREFIX}*"):
        if is_stale_conversion_file(leftover):
            leftover.unlink(missing_ok=True)
    total = _duration_seconds(ffmpeg, source, cancelled)
    fd, staged_name = tempfile.mkstemp(prefix=_STAGE_PREFIX, suffix=".mp4", dir=media_dir)
    os.close(fd)
    staged = Path(staged_name)
    cmd = [
        ffmpeg, "-y", "-hide_banner", "-nostdin", "-loglevel", "error",
        "-i", str(source),
        "-map", "0:v:0", "-map", "0:a:0?",
        # Deinterlace only frames flagged as interlaced, then square pixels:
        # the preview and the exporter treat non-square pixels differently.
        "-vf", "yadif=deint=interlaced,scale=trunc(iw*sar/2)*2:trunc(ih/2)*2,setsar=1",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-map_metadata", "-1", "-map_chapters", "-1",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        str(staged),
    ]
    with tempfile.TemporaryFile() as errors:
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errors, text=True)
        except OSError as exc:
            staged.unlink(missing_ok=True)
            raise ConversionFailed(f"Could not start FFmpeg: {exc}") from exc
        done_seconds = [0.0]

        def read_progress() -> None:
            # Runs beside the wait loop so a cancel never waits for ffmpeg's
            # next progress line.
            assert proc.stdout is not None
            for line in proc.stdout:
                if line.startswith("out_time_us="):
                    try:
                        done_seconds[0] = int(line.split("=", 1)[1]) / 1_000_000
                    except ValueError:
                        pass

        reader = threading.Thread(target=read_progress, daemon=True)
        reader.start()
        try:
            last = 0.0
            while True:
                if cancelled is not None and cancelled():
                    raise ConversionCancelled()
                try:
                    returncode = proc.wait(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if progress is not None and total > 0:
                    value = min(0.99, done_seconds[0] / total)
                    if value > last:
                        last = value
                        progress(value)
            reader.join(timeout=1)
            if returncode != 0 or staged.stat().st_size == 0:
                errors.seek(0)
                detail = errors.read().decode("utf-8", errors="replace").strip().splitlines()
                raise ConversionFailed(detail[-1] if detail else f"FFmpeg exited with {returncode}")
            os.replace(staged, target)
        except BaseException:
            if proc.poll() is None:
                # The partial file is discarded anyway; a polite stop can take
                # ffmpeg many seconds on HD footage and would hold up closing.
                proc.kill()
                proc.wait()
            staged.unlink(missing_ok=True)
            raise
    if progress is not None:
        progress(1.0)
    return target, True


def _ensure_media_dir(media_dir: Path) -> None:
    if media_dir.is_symlink() or media_dir.is_junction():
        raise ConversionFailed(f"The project's media folder is a link: {media_dir}")
    try:
        media_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConversionFailed(f"Could not create the media folder: {exc}") from exc


def _duration_seconds(ffmpeg: str, source: Path, cancelled: CancelCallback | None) -> float:
    """Container duration, used only to report progress."""
    try:
        proc = subprocess.Popen(
            [ffmpeg, "-hide_banner", "-nostdin", "-i", str(source)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
    except OSError:
        return 0.0
    deadline = time.monotonic() + 30
    try:
        while proc.poll() is None:
            if cancelled is not None and cancelled():
                raise ConversionCancelled()
            if time.monotonic() > deadline:
                return 0.0
            time.sleep(0.05)
        banner = proc.stderr.read() if proc.stderr else ""
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", banner)
    if not match:
        return 0.0
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
