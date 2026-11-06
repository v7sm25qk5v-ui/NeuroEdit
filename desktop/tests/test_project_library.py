"""Project Library search/filter/sort over the cached recents metadata."""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from neuroedit_desktop.ui.main_window import ProjectLibraryDialog  # noqa: E402
from neuroedit_desktop.ui.project_library import (  # noqa: E402
    _read_project_meta,
    _thumbnail_path,
)


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


def test_project_meta_uses_timeline_duration_and_trimmed_thumbnail_offset(
    app, tmp_path, monkeypatch
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    project = tmp_path / "Trimmed" / "project.json"
    project.parent.mkdir()
    project.write_text(
        json.dumps(
            {
                "project_name": "Trimmed Case",
                "deidentified_confirmed": True,
                "clips": [
                    {
                        "path": str(source),
                        "duration": 100.0,
                        "start_time": 10.0,
                        "trim_start": 40.0,
                        "trim_end": 50.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    meta = _read_project_meta(project)
    assert meta["total_duration"] == pytest.approx(20.0)
    assert meta["first_clip_duration"] == pytest.approx(41.5)

    settings = QSettings("NeuroEdit", "Desktop")
    original = settings.value("recentProjects", []) or []
    settings.setValue("recentProjects", [str(project)])
    dialog = ProjectLibraryDialog()
    try:
        row_text = dialog.list_widget.item(0).text()
        assert "0:20" in row_text
        assert meta["thumbnail_allowed"] is False
    finally:
        dialog.close()
        settings.setValue("recentProjects", original)


def test_project_thumbnail_symlink_is_removed_without_touching_target(app, tmp_path):
    from PySide6.QtCore import QSettings

    project = tmp_path / "project.json"
    project.write_text(json.dumps({"project_name": "Case"}), encoding="utf-8")
    target = tmp_path / "private.jpg"
    target.write_bytes(b"private original")
    thumb = _thumbnail_path(project)
    thumb.symlink_to(target)
    settings = QSettings("NeuroEdit", "Desktop")
    original = settings.value("recentProjects", []) or []
    settings.setValue("recentProjects", [str(project)])
    dialog = ProjectLibraryDialog()
    try:
        assert not thumb.is_symlink()
        assert target.read_bytes() == b"private original"
    finally:
        dialog.close()
        settings.setValue("recentProjects", original)
