"""Dev-only performance diagnostics for manual QA.

A tester who reports "feels sluggish" can flip Help → Performance Diagnostics
(or set NEUROEDIT_DIAGNOSTICS=1) and reproduce the moment; the log then shows
timestamped paint/load/export/SAM events with the active view, without any
patient content. By design this module:

- writes OUTSIDE project media folders (per-user log dir, never the autosave
  or project tree), and
- never logs media paths or project names — only event names, durations, and
  counts — so a log file can be attached to a bug report safely.

Qt-free so it can be unit-tested headless and imported from workers.
"""
from __future__ import annotations

import datetime
import os
import sys
import time
from pathlib import Path

_enabled = os.environ.get("NEUROEDIT_DIAGNOSTICS", "") not in ("", "0", "false")
_log_path: Path | None = None

# Rolling paint stats per event name: (count, total_ms, max_ms). Summarized
# every _SUMMARY_EVERY samples so a 30 Hz scrub doesn't write 30 lines/second.
_paint_stats: dict[str, list[float]] = {}
_SUMMARY_EVERY = 120
# Paints over budget are logged immediately — these are the "felt" stutters.
FRAME_BUDGET_MS = 33.0


def is_enabled() -> bool:
    return _enabled


def set_enabled(enabled: bool) -> None:
    global _enabled
    _enabled = bool(enabled)
    if _enabled:
        log("diagnostics", state="enabled")


def log_dir() -> Path:
    """Per-user log location, deliberately outside any project/media folder."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "NeuroEdit"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
        return root / "NeuroEdit" / "Logs"
    return Path.home() / ".local" / "state" / "neuroedit" / "logs"


def log_path() -> Path:
    """One log file per app launch."""
    global _log_path
    if _log_path is None:
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        _log_path = log_dir() / f"diagnostics_{stamp}.log"
    return _log_path


def log(event: str, duration_ms: float | None = None, **fields) -> None:
    """Append one timestamped line. Values must be PHI-safe (no paths/names)."""
    if not _enabled:
        return
    parts = [datetime.datetime.now().isoformat(timespec="milliseconds"), event]
    if duration_ms is not None:
        parts.append(f"duration_ms={duration_ms:.1f}")
    parts.extend(f"{key}={value}" for key, value in fields.items())
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(" ".join(parts) + "\n")
    except OSError:
        pass


class timed:
    """Context manager: `with diagnostics.timed("project_load", clips=3): ...`"""

    def __init__(self, event: str, **fields) -> None:
        self.event = event
        self.fields = fields
        self._start = 0.0

    def __enter__(self) -> timed:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_exc) -> None:
        if _enabled:
            elapsed_ms = (time.perf_counter() - self._start) * 1000.0
            log(self.event, duration_ms=elapsed_ms, **self.fields)


def record_paint(event: str, elapsed_ms: float, **fields) -> None:
    """Aggregate high-frequency paint timings. Logs immediately when a paint
    blows the frame budget; otherwise logs an avg/max summary every
    _SUMMARY_EVERY paints."""
    if not _enabled:
        return
    if elapsed_ms > FRAME_BUDGET_MS:
        log(event, duration_ms=elapsed_ms, over_budget=1, **fields)
    stats = _paint_stats.setdefault(event, [0.0, 0.0, 0.0])
    stats[0] += 1
    stats[1] += elapsed_ms
    stats[2] = max(stats[2], elapsed_ms)
    if stats[0] >= _SUMMARY_EVERY:
        log(
            f"{event}_summary",
            count=int(stats[0]),
            avg_ms=f"{stats[1] / stats[0]:.1f}",
            max_ms=f"{stats[2]:.1f}",
            **fields,
        )
        _paint_stats[event] = [0.0, 0.0, 0.0]
