from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from neuroedit_desktop.models import AudioTrack, ProjectState
from neuroedit_desktop.project_store import ProjectStore
from neuroedit_desktop.ui.main_window import MainWindow
from neuroedit_desktop.ui.main_window_utils import delete_orphan_masks


def test_save_ignores_planted_temporary_symlink(tmp_path: Path) -> None:
    store = ProjectStore.create(tmp_path / "project")
    victim = tmp_path / "victim"
    victim.write_text("private")
    (store.project_path.parent / "project.json.tmp").symlink_to(victim)
    store.save(ProjectState(project_name="Safe"))
    assert victim.read_text() == "private"
    assert ProjectStore.open(store.project_path)[1].project_name == "Safe"


def test_create_rejects_redirected_managed_directory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "masks").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        ProjectStore.create(project)


def test_create_rejects_managed_junction(tmp_path: Path, monkeypatch) -> None:
    managed = tmp_path / "project" / "masks"
    monkeypatch.setattr(Path, "is_junction", lambda path: path == managed)
    with pytest.raises(ValueError):
        ProjectStore.create(managed.parent)


def test_cleanup_rejects_redirected_root_and_child_links(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    victim = tmp_path / "victim"
    victim.mkdir()
    target = victim / "outside.png"
    target.write_bytes(b"keep")
    masks = project / "masks"
    masks.symlink_to(victim, target_is_directory=True)
    assert delete_orphan_masks(masks, set()) == 0
    assert target.exists()
    masks.unlink()
    masks.mkdir()
    (masks / "link.png").symlink_to(target)
    orphan = masks / "orphan.png"
    orphan.write_bytes(b"orphan")
    assert delete_orphan_masks(masks, set()) == 1
    assert target.exists() and (masks / "link.png").is_symlink()


@pytest.mark.parametrize("path_kind", [
    "traversal", "source_link", "source_hardlink", "destination_link",
])
def test_migration_rejects_managed_escapes(tmp_path: Path, path_kind: str) -> None:
    old = tmp_path / "old"
    new = tmp_path / "new"
    (old / "audio").mkdir(parents=True)
    (new / "audio").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_bytes(b"private")
    if path_kind == "traversal":
        source = old / "audio" / ".." / ".." / "outside"
    else:
        source = old / "audio" / "voice.m4a"
        if path_kind == "source_link":
            source.symlink_to(outside)
        elif path_kind == "source_hardlink":
            source.hardlink_to(outside)
        else:
            source.write_bytes(b"audio")
            (new / "audio" / source.name).symlink_to(outside)
    project = ProjectState(audio_tracks=[AudioTrack(id="a", path=str(source), name="A")])
    with pytest.raises(ValueError):
        MainWindow._migrate_managed_assets(project, old, new)
    assert outside.read_bytes() == b"private"


def test_migration_preserves_external_links_and_copies_managed(tmp_path: Path) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    source = old / "audio" / "voice.m4a"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"audio")
    external = tmp_path / "external.m4a"
    external.write_bytes(b"external")
    project = ProjectState(audio_tracks=[AudioTrack(id="a", path=str(source), name="A"),
                                         AudioTrack(id="b", path=str(external), name="B")])
    MainWindow._migrate_managed_assets(project, old, new)
    assert Path(project.audio_tracks[0].path).read_bytes() == b"audio"
    assert project.audio_tracks[1].path == str(external)


def test_migration_rejects_hardlinked_destination(tmp_path: Path) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    source = old / "audio" / "voice.m4a"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"audio")
    victim = tmp_path / "victim"
    victim.write_bytes(b"private")
    destination = new / "audio" / source.name
    destination.parent.mkdir(parents=True)
    destination.hardlink_to(victim)
    project = ProjectState(audio_tracks=[AudioTrack(id="a", path=str(source), name="A")])
    with pytest.raises(ValueError):
        MainWindow._migrate_managed_assets(project, old, new)
    assert victim.read_bytes() == b"private"
