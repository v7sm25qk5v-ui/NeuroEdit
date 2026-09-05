from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from neuroedit_desktop.models import Annotation, AudioTrack, ProjectState  # noqa: E402
from neuroedit_desktop.project_store import ProjectStore  # noqa: E402
from neuroedit_desktop.ui import main_window as module  # noqa: E402
from neuroedit_desktop.ui.main_window import MainWindow  # noqa: E402


class _Timer:
    def __init__(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False


def test_failed_close_keeps_autosave_and_heartbeat_running(monkeypatch) -> None:
    window = MainWindow.__new__(MainWindow)
    window.project = ProjectState()
    window.dirty = True
    window.autosave_timer = _Timer()
    window._sam_heartbeat_timer = _Timer()
    window._autosave_snapshot = None
    ignored = []
    errors = []

    def fail_save(_project) -> None:
        raise OSError("Disk unavailable")

    window.store = SimpleNamespace(save=fail_save)
    monkeypatch.setattr(module.QMessageBox, "critical", lambda *args: errors.append(args))
    window._shutdown_threads = lambda: pytest.fail("Canceled close must keep workers alive")

    window.closeEvent(SimpleNamespace(ignore=lambda: ignored.append(True)))

    assert ignored == [True]
    assert errors[0][1:] == ("Save failed", "Disk unavailable")
    assert window.dirty
    assert window.autosave_timer.active
    assert window._sam_heartbeat_timer.active


def test_save_as_folder_creation_failure_preserves_open_project(monkeypatch, tmp_path) -> None:
    window = MainWindow.__new__(MainWindow)
    window.project = ProjectState(project_name="Original")
    window.store = ProjectStore(tmp_path / "original" / "project.json")
    window.dirty = True
    original_project, original_store = window.project, window.store
    errors = []
    monkeypatch.setattr(module.QInputDialog, "getText", lambda *args, **kwargs: ("New", True))
    monkeypatch.setattr(module.QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path))
    monkeypatch.setattr(module.QMessageBox, "critical", lambda *args: errors.append(args))

    def fail_create(_folder):
        raise OSError("Read-only location")

    monkeypatch.setattr(module.ProjectStore, "create", fail_create)

    window._save_project_as()

    assert errors[0][1:] == ("Save failed", "Read-only location")
    assert window.project is original_project
    assert window.store is original_store
    assert window.dirty


@pytest.mark.parametrize("destination_kind", ["same", "symlink", "hardlink"])
def test_save_as_same_managed_asset_does_not_copy_over_itself(tmp_path: Path, destination_kind: str) -> None:
    old_root = tmp_path / "original"
    audio = old_root / "audio" / "voice.m4a"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"original audio")
    if destination_kind == "same":
        new_root = old_root
    elif destination_kind == "symlink":
        new_root = tmp_path / "alias"
        new_root.symlink_to(old_root, target_is_directory=True)
    else:
        new_root = tmp_path / "linked"
        target = new_root / "audio" / audio.name
        target.parent.mkdir(parents=True)
        target.hardlink_to(audio)
    project = ProjectState(audio_tracks=[AudioTrack(id="voice", path=str(audio), name="Voice")])

    MainWindow._migrate_managed_assets(project, old_root, new_root)

    assert Path(project.audio_tracks[0].path).read_bytes() == b"original audio"
    assert project.audio_tracks[0].path == str(new_root / "audio" / audio.name)


def test_new_project_cleanup_preserves_masks_in_saved_autosave(monkeypatch, tmp_path: Path) -> None:
    store = ProjectStore.create(tmp_path)
    saved_mask = tmp_path / "masks" / "saved.png"
    saved_mask.write_bytes(b"saved mask")
    orphan = tmp_path / "masks" / "orphan.png"
    orphan.write_bytes(b"orphan")
    saved = ProjectState(annotations=[Annotation(
        id="mask", frame_time=0.0, ann_duration=1.0, type="mask",
        label="Mask", color="#fff", mask_path=str(saved_mask),
    )])
    store.save(saved)
    window = MainWindow.__new__(MainWindow)
    window.store = store
    window.project = saved
    window.dirty = False
    window._load_active_clip = lambda: None
    window._update_history_actions = lambda: None
    window._update_title = lambda: None
    window.refresh = lambda: None
    monkeypatch.setattr(module, "default_project_root", lambda: tmp_path)

    window._new_project()

    window._cleanup_orphan_masks()

    _, recovered = ProjectStore.open(store.project_path)
    assert Path(recovered.annotations[0].mask_path).read_bytes() == b"saved mask"
    assert not orphan.exists()


@pytest.mark.parametrize("saved_data", [None, "invalid JSON"])
def test_mask_cleanup_handles_missing_or_unreadable_saved_project(tmp_path: Path, saved_data) -> None:
    store = ProjectStore.create(tmp_path)
    orphan = tmp_path / "masks" / "orphan.png"
    orphan.write_bytes(b"mask")
    window = MainWindow.__new__(MainWindow)
    window.store = store
    window.project = ProjectState()
    window._undo_stack = []
    window._redo_stack = []
    if saved_data is not None:
        store.project_path.write_text(saved_data)
        with pytest.raises(ValueError):
            window._cleanup_orphan_masks()
        assert orphan.exists()
    else:
        window._cleanup_orphan_masks()
        assert not orphan.exists()
