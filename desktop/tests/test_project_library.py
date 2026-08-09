"""Project Library search/filter/sort over the cached recents metadata."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from neuroedit_desktop.ui.main_window import ProjectLibraryDialog  # noqa: E402
from neuroedit_desktop.ui.project_library import ThumbnailWorker, _thumbnail_path  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def library(app, tmp_path, monkeypatch):
    """Two temp projects in recents (Beta first = most recent), with the
    thumbnail thread stubbed out so no ffmpeg subprocess runs in tests."""
    alpha = tmp_path / "Alpha" / "project.json"
    alpha.parent.mkdir()
    alpha.write_text(
        json.dumps({"project_name": "Alpha Case", "clips": []}), encoding="utf-8"
    )
    beta = tmp_path / "Beta" / "project.json"
    beta.parent.mkdir()
    beta.write_text(
        json.dumps(
            {
                "project_name": "Beta Case",
                "clips": [{"path": str(tmp_path / "gone.mp4"), "duration": 4.0}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        ProjectLibraryDialog, "_start_thumb_thread", lambda self, tasks: None
    )
    settings = QSettings("NeuroEdit", "Desktop")
    original = settings.value("recentProjects", []) or []
    settings.setValue("recentProjects", [str(beta), str(alpha)])
    dialog = ProjectLibraryDialog()
    try:
        yield dialog
    finally:
        dialog.close()
        settings.setValue("recentProjects", original)


def _row_names(dialog: ProjectLibraryDialog) -> list[str]:
    names = []
    for i in range(dialog.list_widget.count()):
        item = dialog.list_widget.item(i)
        if item and item.data(Qt.ItemDataRole.UserRole):
            names.append(item.text().splitlines()[0].split("  ⚠")[0])
    return names


def test_default_order_is_most_recent_first(library):
    assert _row_names(library) == ["Beta Case", "Alpha Case"]


def test_search_filters_by_project_name(library):
    library.search_input.setText("alpha")
    assert _row_names(library) == ["Alpha Case"]


def test_search_no_match_shows_placeholder(library):
    library.search_input.setText("zzz")
    assert _row_names(library) == []
    texts = [
        library.list_widget.item(i).text() for i in range(library.list_widget.count())
    ]
    assert any("No projects match" in text for text in texts)


def test_sort_by_name(library):
    library.sort_combo.setCurrentIndex(library.sort_combo.findData("name"))
    assert _row_names(library) == ["Alpha Case", "Beta Case"]


def test_sort_missing_media_first(library):
    # Force name order first to prove the missing sort actually reorders.
    library.sort_combo.setCurrentIndex(library.sort_combo.findData("name"))
    library.sort_combo.setCurrentIndex(library.sort_combo.findData("missing"))
    assert _row_names(library)[0] == "Beta Case"  # has 1 missing source file


def test_thumbnail_worker_does_not_emit_stale_thumbnail_after_failed_refresh(
    app, tmp_path, monkeypatch
):
    project = tmp_path / "Case" / "project.json"
    project.parent.mkdir()
    project.write_text(json.dumps({"project_name": "Case"}), encoding="utf-8")
    thumb = _thumbnail_path(project)
    thumb.write_bytes(b"old preview")
    os.utime(thumb, (project.stat().st_mtime - 10, project.stat().st_mtime - 10))

    monkeypatch.setitem(
        sys.modules,
        "imageio_ffmpeg",
        types.SimpleNamespace(get_ffmpeg_exe=lambda: "/usr/bin/false"),
    )

    def fail_ffmpeg(cmd, capture_output, timeout):
        return subprocess.CompletedProcess(cmd, returncode=1)

    monkeypatch.setattr(subprocess, "run", fail_ffmpeg)
    emitted = []
    worker = ThumbnailWorker([(str(project), str(tmp_path / "source.mp4"), 10.0)])
    worker.thumbnail_ready.connect(lambda project_path, thumb_path: emitted.append(thumb_path))

    worker.run()

    assert emitted == []
    assert not thumb.exists()
