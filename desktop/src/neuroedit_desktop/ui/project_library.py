from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
)

from neuroedit_desktop.ui.styles import DANGER, SUCCESS, TEXT_MUTED, TEXT_PRIMARY


def relative_time(ts: float) -> str:
    now = datetime.datetime.now()
    dt = datetime.datetime.fromtimestamp(ts)
    delta = now - dt
    days = delta.days
    if days < 1:
        return "Opened today"
    if days == 1:
        return "Opened yesterday"
    if days < 7:
        return f"Opened {days} days ago"
    if days < 14:
        return "Opened last week"
    if days < 28:
        weeks = days // 7
        return f"Opened {weeks} weeks ago"
    # No strftime "%-d": that flag is platform-specific and raises on Windows.
    return f"{dt.strftime('%b')} {dt.day}, {dt.year}"


def _read_project_meta(path: Path) -> dict:
    result = {
        "project_name": None,
        "total_duration": 0.0,
        "media_count": 0,
        "clip_count": 0,
        "audio_count": 0,
        "slide_count": 0,
        "missing_count": 0,
        "first_source_path": None,
        "first_clip_duration": 0.0,
        "thumbnail_allowed": False,
        "ok": False,
    }
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        result["project_name"] = data.get("project_name")
        # A source-frame thumbnail is a new persistent image derivative. Only
        # create one after the project has an explicit de-identification attestation.
        result["thumbnail_allowed"] = bool(data.get("deidentified_confirmed", False))
        clips = data.get("clips") or []
        audio = data.get("audio_tracks") or data.get("audio") or []
        slides = data.get("slides") or []
        for clip in clips:
            dur = clip.get("duration") or 0.0
            result["total_duration"] += float(dur)
            src = clip.get("path") or clip.get("source_path")
            if src and result["first_source_path"] is None:
                result["first_source_path"] = src
                result["first_clip_duration"] = float(dur)
            if src and not Path(src).exists():
                result["missing_count"] += 1
        result["clip_count"] = len(clips)
        result["audio_count"] = len(audio)
        result["slide_count"] = len(slides)
        result["media_count"] = len(clips) + len(audio) + len(slides)
        for track in audio:
            src = track.get("path") or track.get("source_path")
            if src and not Path(src).exists():
                result["missing_count"] += 1
        for slide in slides:
            src = slide.get("image_path") or slide.get("source_path")
            if src and not Path(src).exists():
                result["missing_count"] += 1
        result["ok"] = True
    except Exception:  # noqa: BLE001
        pass
    return result


def _thumbnail_path(project_path: Path) -> Path:
    return project_path.parent / ".neuroedit-thumbnail.jpg"


def _make_gray_placeholder(width: int = 160, height: int = 90) -> QPixmap:
    img = QImage(width, height, QImage.Format.Format_RGB32)
    img.fill(QColor("#2c3340"))
    return QPixmap.fromImage(img)


class ThumbnailWorker(QObject):
    thumbnail_ready = Signal(str, str)  # project_path, thumb_path

    def __init__(self, tasks: list[tuple[str, str, float]]) -> None:
        super().__init__()
        self._tasks = tasks
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    def run(self) -> None:
        try:
            import imageio_ffmpeg

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # noqa: BLE001
            return
        for project_path, source_path, clip_dur in self._tasks:
            if self._stopped:
                break
            thumb = _thumbnail_path(Path(project_path))
            try:
                proj_mtime = Path(project_path).stat().st_mtime
                if thumb.exists() and thumb.stat().st_mtime >= proj_mtime:
                    self.thumbnail_ready.emit(project_path, str(thumb))
                    continue
                if thumb.exists():
                    thumb.unlink()
                offset = clip_dur * 0.15 if clip_dur > 0 else 5.0
                # No manual quoting: subprocess passes list args verbatim, so
                # wrapping the path in quote characters breaks paths with spaces.
                cmd = [
                    ffmpeg,
                    "-y",
                    "-ss",
                    str(offset),
                    "-i",
                    source_path,
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(thumb),
                ]
                completed = subprocess.run(cmd, capture_output=True, timeout=15)
                if completed.returncode == 0 and thumb.exists():
                    self.thumbnail_ready.emit(project_path, str(thumb))
            except Exception:  # noqa: BLE001
                pass


class ProjectLibraryDialog(QDialog):
    project_selected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Project Library")
        self.setMinimumSize(640, 420)
        self._thumb_thread = None
        self._thumb_worker = None
        # Threads that outlived a quick shutdown wait; kept referenced so the
        # QThread C++ object is not garbage-collected while still running.
        self._orphan_threads: list[tuple[QThread, ThumbnailWorker]] = []
        # Metadata cache: search/sort re-filter this without re-reading disk.
        self._entries: list[dict] = []
        self._thumb_pixmaps: dict[str, QPixmap] = {}
        self._build_ui()
        self._reload()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Recent Projects")
        title.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search projects…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._populate)
        self.sort_combo = QComboBox()
        for key, label in (
            ("recent", "Recently opened"),
            ("name", "Name (A–Z)"),
            ("missing", "Missing media first"),
        ):
            self.sort_combo.addItem(label, key)
        self.sort_combo.currentIndexChanged.connect(self._populate)
        filter_row.addWidget(self.search_input, 1)
        filter_row.addWidget(self.sort_combo)
        layout.addLayout(filter_row)

        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(False)
        self.list_widget.setSpacing(2)
        self.list_widget.setIconSize(QSize(160, 90))
        self.list_widget.itemDoubleClicked.connect(self._open_selected)
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.remove_btn = QPushButton("Remove from List")
        self.remove_btn.clicked.connect(self._remove_selected)
        open_btn = QPushButton("Open")
        open_btn.setDefault(True)
        open_btn.clicked.connect(self._open_selected)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.remove_btn)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(open_btn)
        layout.addLayout(btn_row)

    def _reload(self) -> None:
        """Read recents + per-project metadata from disk once; _populate()
        then filters/sorts the cache, so typing in the search box is free."""
        self._stop_thumb_thread()
        settings = QSettings("NeuroEdit", "Desktop")
        recents: list[str] = settings.value("recentProjects", []) or []

        self._entries = []
        thumb_tasks: list[tuple[str, str, float]] = []
        for order, path_str in enumerate(recents):
            p = Path(path_str)
            meta = _read_project_meta(p)
            try:
                mtime = p.stat().st_mtime
            except Exception:  # noqa: BLE001
                mtime = 0.0
            self._entries.append(
                {"path": path_str, "meta": meta, "mtime": mtime, "order": order}
            )
            if meta["thumbnail_allowed"] and meta["first_source_path"]:
                thumb_tasks.append(
                    (path_str, meta["first_source_path"], meta["first_clip_duration"])
                )

        self._populate()
        if thumb_tasks:
            self._start_thumb_thread(thumb_tasks)

    @staticmethod
    def _entry_display_name(entry: dict) -> str:
        p = Path(entry["path"])
        folder_name = p.parent.name if p.name == "project.json" else p.name
        return str(entry["meta"]["project_name"] or folder_name)

    def _filtered_sorted_entries(self) -> list[dict]:
        query = self.search_input.text().strip().lower()
        entries = [
            entry
            for entry in self._entries
            if not query or query in self._entry_display_name(entry).lower()
        ]
        sort_key = self.sort_combo.currentData()
        if sort_key == "name":
            entries.sort(key=lambda entry: self._entry_display_name(entry).lower())
        elif sort_key == "missing":
            entries.sort(key=lambda entry: (-entry["meta"]["missing_count"], entry["order"]))
        # "recent" keeps the recents (most recently opened first) order.
        return entries

    def _populate(self, *_args) -> None:
        self.list_widget.clear()
        placeholder_icon = QPixmap(_make_gray_placeholder())
        entries = self._filtered_sorted_entries()

        for entry in entries:
            path_str = entry["path"]
            p = Path(path_str)
            meta = entry["meta"]
            project_name = self._entry_display_name(entry)

            modified = relative_time(entry["mtime"]) if entry["mtime"] else ""

            dur = meta["total_duration"]
            if dur > 0:
                mins = int(dur) // 60
                secs = int(dur) % 60
                dur_str = f"{mins}:{secs:02d}"
            else:
                dur_str = ""

            parts = []
            if meta["clip_count"]:
                parts.append(
                    f"{meta['clip_count']} clip{'s' if meta['clip_count'] != 1 else ''}"
                )
            if meta["audio_count"]:
                parts.append(f"{meta['audio_count']} audio")
            if meta["slide_count"]:
                parts.append(
                    f"{meta['slide_count']} slide{'s' if meta['slide_count'] != 1 else ''}"
                )
            media_str = ", ".join(parts) if parts else ""

            detail_line = ""
            if dur_str and media_str:
                detail_line = f"{dur_str}  •  {media_str}"
            elif dur_str:
                detail_line = dur_str
            elif media_str:
                detail_line = media_str

            missing = meta["missing_count"]
            if meta["ok"] and missing > 0:
                status_suffix = f"  ⚠ {missing} source file{'s' if missing != 1 else ''} missing"
            elif not meta["ok"] and not p.exists():
                status_suffix = "  (not found)"
            else:
                status_suffix = ""

            lines = [project_name]
            if modified:
                lines.append(modified)
            if detail_line:
                lines.append(detail_line)
            display = "\n".join(lines)
            if status_suffix:
                display += status_suffix

            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, path_str)
            cached_thumb = self._thumb_pixmaps.get(path_str)
            item.setIcon(cached_thumb if cached_thumb else QPixmap(placeholder_icon))

            if meta["ok"] and missing == 0:
                item.setForeground(QColor(SUCCESS))
            elif meta["ok"] and missing > 0:
                item.setForeground(QColor(DANGER))
            elif not p.exists():
                item.setForeground(QColor(TEXT_MUTED))

            self.list_widget.addItem(item)

        if not self._entries:
            placeholder = QListWidgetItem("No recent projects")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_widget.addItem(placeholder)
        elif not entries:
            placeholder = QListWidgetItem("No projects match the search")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_widget.addItem(placeholder)

    def _start_thumb_thread(self, tasks: list[tuple[str, str, float]]) -> None:
        self._thumb_thread = QThread()
        self._thumb_worker = ThumbnailWorker(tasks)
        self._thumb_worker.moveToThread(self._thumb_thread)
        self._thumb_thread.started.connect(self._thumb_worker.run)
        self._thumb_worker.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._thumb_thread.start()

    def _stop_thumb_thread(self) -> None:
        thread, worker = self._thumb_thread, self._thumb_worker
        self._thumb_thread = None
        self._thumb_worker = None
        if worker is not None:
            worker.stop()
        if thread is None:
            return
        thread.quit()
        if not thread.wait(500):
            # Worker is mid-ffmpeg (bounded by its 15 s subprocess timeout).
            # Dropping the Python reference now could destroy a running QThread
            # and crash; park it instead and dispose when it finishes.
            self._orphan_threads.append((thread, worker))
            thread.finished.connect(
                lambda t=thread, w=worker: self._orphan_threads.remove((t, w))
            )

    def _on_thumbnail_ready(self, project_path: str, thumb_path: str) -> None:
        pix = QPixmap(thumb_path)
        if pix.isNull():
            return
        # Cache so re-filtering/sorting can restore the icon without ffmpeg.
        self._thumb_pixmaps[project_path] = pix
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == project_path:
                item.setIcon(pix)
                break

    def _show_context_menu(self, pos) -> None:
        item = self.list_widget.itemAt(pos)
        if item is None:
            return
        path_str = item.data(Qt.ItemDataRole.UserRole)
        if not path_str:
            return
        if sys.platform == "darwin":
            reveal_label = "Reveal in Finder"
        elif sys.platform == "win32":
            reveal_label = "Reveal in Explorer"
        else:
            reveal_label = "Open folder"
        menu = QMenu(self)
        open_act = menu.addAction("Open")
        reveal_act = menu.addAction(reveal_label)
        remove_act = menu.addAction("Remove from List")
        chosen = menu.exec(self.list_widget.mapToGlobal(pos))
        if chosen == open_act:
            self.list_widget.setCurrentItem(item)
            self._open_selected()
        elif chosen == reveal_act:
            folder = str(Path(path_str).parent)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        elif chosen == remove_act:
            self.list_widget.setCurrentItem(item)
            self._remove_selected()

    def _open_selected(self, *_) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        path_str = item.data(Qt.ItemDataRole.UserRole)
        if not path_str:
            return
        self.project_selected.emit(path_str)
        self.accept()

    def _remove_selected(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        path_str = item.data(Qt.ItemDataRole.UserRole)
        if not path_str:
            return
        settings = QSettings("NeuroEdit", "Desktop")
        recents: list[str] = settings.value("recentProjects", []) or []
        if path_str in recents:
            recents.remove(path_str)
        settings.setValue("recentProjects", recents)
        try:
            _thumbnail_path(Path(path_str)).unlink(missing_ok=True)
        except OSError:
            pass
        self._reload()

    def closeEvent(self, event) -> None:
        self._stop_thumb_thread()
        super().closeEvent(event)
