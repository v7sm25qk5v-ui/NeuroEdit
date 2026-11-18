# ruff: noqa: F811  (tests take the imported `window` fixture as an argument)
"""Save As copies managed files once, off the UI thread, with progress and cleanup."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path

import pytest

from neuroedit_desktop import project_copy
from neuroedit_desktop.project_copy import CopyCancelled, CopyJob, CopyProgress
from test_main_window_headless import app, window  # noqa: F401


def _file(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(os.urandom(size))
    return path


@pytest.mark.parametrize("clone", [True, False])
def test_copies_bytes_mode_and_times_with_progress(tmp_path, monkeypatch, clone):
    if not clone:
        monkeypatch.setattr(project_copy, "_try_clone", lambda *_: False)
    monkeypatch.setattr(project_copy, "CHUNK_BYTES", 1000)
    source = _file(tmp_path / "old" / "media" / "a.mp4", 4500)
    os.chmod(source, 0o600)
    os.utime(source, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    destination = tmp_path / "new" / "media" / "a.mp4"
    jobs = project_copy.plan_copies([(source, destination), (source, destination)])
    progress = CopyProgress()

    project_copy.copy_files(jobs, progress, lambda: False)

    assert len(jobs) == 1
    assert destination.read_bytes() == source.read_bytes()
    assert destination.stat().st_mode & 0o777 == 0o600
    assert destination.stat().st_mtime_ns == source.stat().st_mtime_ns
    assert (progress.done_bytes, progress.total_bytes, progress.count) == (4500, 4500, 1)
    assert not list(destination.parent.glob(".*partial"))


def test_an_already_copied_file_is_skipped(tmp_path):
    source = _file(tmp_path / "old" / "a.mp4", 100)
    destination = tmp_path / "new" / "a.mp4"
    project_copy.copy_files(project_copy.plan_copies([(source, destination)]), CopyProgress(), lambda: False)
    assert project_copy.plan_copies([(source, destination)]) == []
    destination.write_bytes(b"truncated")  # an interrupted earlier save is copied again
    assert len(project_copy.plan_copies([(source, destination)])) == 1


def test_cancel_removes_only_files_this_copy_created(tmp_path, monkeypatch):
    monkeypatch.setattr(project_copy, "_try_clone", lambda *_: False)
    monkeypatch.setattr(project_copy, "CHUNK_BYTES", 10)
    first = _file(tmp_path / "old" / "1.mp4", 50)
    second = _file(tmp_path / "old" / "2.mp4", 50)
    kept = _file(tmp_path / "new" / "2.mp4", 7)  # existed before this save
    progress = CopyProgress()
    jobs = [CopyJob(first, tmp_path / "new" / "1.mp4", 50), CopyJob(second, kept, 50)]

    with pytest.raises(CopyCancelled):
        project_copy.copy_files(jobs, progress, lambda: progress.done_bytes >= 70)

    assert not (tmp_path / "new" / "1.mp4").exists()
    assert kept.read_bytes() and kept.stat().st_size == 7
    assert sorted(p.name for p in (tmp_path / "new").iterdir()) == ["2.mp4"]
    assert first.exists() and second.exists()


def test_a_read_error_cleans_up_and_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(project_copy, "_try_clone", lambda *_: False)
    first = _file(tmp_path / "old" / "1.mp4", 20)
    jobs = [CopyJob(first, tmp_path / "new" / "1.mp4", 20),
            CopyJob(tmp_path / "old" / "missing.mp4", tmp_path / "new" / "2.mp4", 20)]
    with pytest.raises(FileNotFoundError):
        project_copy.copy_files(jobs, CopyProgress(), lambda: False)
    assert list((tmp_path / "new").iterdir()) == []


def test_space_check_counts_only_files_that_cannot_be_cloned(tmp_path, monkeypatch):
    source = _file(tmp_path / "old" / "a.mp4", 10)
    jobs = [CopyJob(source, tmp_path / "new" / "a.mp4", 10 * 1024**3)]
    usage = type("Usage", (), {"free": 2 * 1024**3})
    monkeypatch.setattr(project_copy.shutil, "disk_usage", lambda _path: usage)
    monkeypatch.setattr(project_copy, "_clone_supported", lambda: False)
    message = project_copy.space_problem(jobs, tmp_path / "new" / "Case")
    assert message and "10.0 GB" in message and "2.0 GB" in message
    monkeypatch.setattr(project_copy, "_clone_supported", lambda: True)  # same volume: a clone
    assert project_copy.space_problem(jobs, tmp_path / "new" / "Case") is None


def test_format_bytes():
    assert project_copy.format_bytes(512) == "512 bytes"
    assert project_copy.format_bytes(3 * 1024**2) == "3.0 MB"
    assert project_copy.format_bytes(int(2.5 * 1024**3)) == "2.5 GB"


# ── Save As in the window ─────────────────────────────────────────────────


@pytest.fixture()
def saved_media(window, tmp_path, monkeypatch):
    """A project in its autosave root with one imported video and a deep undo
    history whose snapshots all reference that video."""
    from neuroedit_desktop.ui import main_window as mw

    monkeypatch.setattr(window, "_sync_player_to_timeline", lambda **_k: None)
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    old_root = window.store.project_path.parent
    video = _file(old_root / mw.MEDIA_DIR_NAME / "case.neuroedit-abc.mp4", 300_000)
    window.project.add_clip(video, duration=10, width=100, height=100)
    window._mark_dirty()
    for index in range(12):
        window.project.project_name = f"Step {index}"
        window._mark_dirty()
    destination = tmp_path / "Chosen location"
    destination.mkdir()
    asked = []

    def save_dialog(*args, **kwargs):
        asked.append(args[1])
        return str(destination / "My Case"), ""

    monkeypatch.setattr(mw.QFileDialog, "getSaveFileName", save_dialog)
    return video, destination / "My Case", asked


def test_save_as_asks_once_and_copies_each_video_once(window, saved_media, monkeypatch):
    from neuroedit_desktop.ui import main_window as mw

    video, folder, asked = saved_media
    copies = []
    real_copy = project_copy._copy_one
    monkeypatch.setattr(project_copy, "_copy_one", lambda job, *a: copies.append(job) or real_copy(job, *a))
    monkeypatch.setattr(mw.QInputDialog, "getText", lambda *a, **k: pytest.fail("no separate name prompt"))
    monkeypatch.setattr(mw.QFileDialog, "getExistingDirectory", lambda *a, **k: pytest.fail("no folder picker"))
    dialogs = []
    real_run = window._run_save_copy

    def run(jobs):
        dialogs.append(len(jobs))
        return real_run(jobs)

    monkeypatch.setattr(window, "_run_save_copy", run)
    depth = len(window._undo_stack)

    window._save_project_as()

    new_video = folder / "media" / video.name
    assert asked == ["Save Project As"]
    assert [job.destination for job in copies] == [new_video], "one copy, not one per undo step"
    assert dialogs == [1]
    assert new_video.read_bytes() == video.read_bytes() and video.exists()
    assert window.store.project_path == folder / "project.json"
    assert window.project.project_name == "My Case"
    assert Path(window.project.clips[0].path) == new_video
    assert len(window._undo_stack) == depth
    window.undo()
    assert Path(window.project.clips[0].path) == new_video, "undo snapshots use the copy too"
    assert not window._save_in_progress


def test_cancelled_save_as_keeps_the_project_and_leaves_nothing_behind(window, saved_media, monkeypatch):
    video, folder, _asked = saved_media
    original_store = window.store

    real_copy = project_copy._copy_one
    monkeypatch.setattr(project_copy, "_try_clone", lambda *_: False)
    monkeypatch.setattr(project_copy, "CHUNK_BYTES", 50_000)

    def cancel_partway(job, progress, _cancelled):
        # The real chunked copy, cancelled once a partial file exists on disk.
        return real_copy(job, progress, lambda: progress.done_bytes > 0)

    monkeypatch.setattr(project_copy, "_copy_one", cancel_partway)
    window._save_project_as()

    assert window.store is original_store and window.dirty
    assert Path(window.project.clips[0].path) == video
    assert not folder.exists() or not any(p.is_file() for p in folder.rglob("*"))
    assert not window._save_in_progress


def test_save_as_reports_a_copy_error_without_switching_projects(window, saved_media, monkeypatch):
    from neuroedit_desktop.ui import main_window as mw

    _video, folder, _asked = saved_media
    original_store = window.store
    errors = []
    monkeypatch.setattr(mw.QMessageBox, "critical", lambda *a: errors.append(a[1:]))
    monkeypatch.setattr(project_copy, "_copy_one",
                        lambda *a: (_ for _ in ()).throw(PermissionError("Operation not permitted")))
    window._save_project_as()

    assert errors == [("Save failed", "Operation not permitted")]
    assert window.store is original_store
    assert not (folder / "project.json").exists()


def test_close_is_refused_while_a_save_is_copying(window, monkeypatch):
    from PySide6.QtGui import QCloseEvent

    monkeypatch.setattr(window, "_save_in_progress", True)
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()
