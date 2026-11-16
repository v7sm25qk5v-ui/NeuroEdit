"""ProjectStore.preserve_unreadable: an unreadable autosave is moved aside byte for byte."""
from __future__ import annotations

import pytest

from neuroedit_desktop.project_store import ProjectStore


@pytest.mark.parametrize("payload", [b'{"clips": "not-a-list"', b"", b'{"clips": 5}', b"\xff\xfe not json"])
def test_preserve_unreadable_keeps_exact_bytes(tmp_path, payload):
    path = tmp_path / "project.json"
    path.write_bytes(payload)

    kept = ProjectStore.preserve_unreadable(path)

    assert not path.exists()
    assert kept.parent == tmp_path and kept.name.startswith("project.unreadable-")
    assert kept.read_bytes() == payload


def test_preserve_unreadable_does_not_pile_up_identical_copies(tmp_path):
    path = tmp_path / "project.json"
    path.write_bytes(b"{broken")
    first = ProjectStore.preserve_unreadable(path)
    path.write_bytes(b"{broken")
    second = ProjectStore.preserve_unreadable(path)

    assert second == first
    assert not path.exists()
    assert len(list(tmp_path.glob("project.unreadable-*.json"))) == 1


def test_preserve_unreadable_keeps_different_content_separately(tmp_path):
    path = tmp_path / "project.json"
    path.write_bytes(b"{one")
    first = ProjectStore.preserve_unreadable(path)
    path.write_bytes(b"{two")
    second = ProjectStore.preserve_unreadable(path)

    assert first != second
    assert first.read_bytes() == b"{one" and second.read_bytes() == b"{two"


def test_preserve_unreadable_moves_file_even_when_it_cannot_be_read(tmp_path):
    import os

    if os.geteuid() == 0:
        pytest.skip("file permissions are not enforced for root")
    path = tmp_path / "project.json"
    path.write_bytes(b"{secret")
    path.chmod(0o000)

    kept = ProjectStore.preserve_unreadable(path)

    kept.chmod(0o600)
    assert not path.exists() and kept.name.endswith(".json") and ".unreadable-" in kept.name
    assert kept.read_bytes() == b"{secret"
