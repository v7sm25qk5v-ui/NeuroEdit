"""Smoothness fixture generator creates an openable PHI-free QA project."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from neuroedit_desktop.project_store import ProjectStore


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "make_smoothness_fixture.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("make_smoothness_fixture", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_fixture_creates_openable_project_with_expected_media(tmp_path, monkeypatch):
    script = _load_script()

    def fake_synthesize_clip(_ffmpeg: str, path: Path, _size: str, _seconds: int) -> None:
        path.write_bytes(b"video")

    def fake_synthesize_audio(_ffmpeg: str, path: Path, _seconds: int) -> None:
        path.write_bytes(b"audio")

    monkeypatch.setattr(script, "_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(script, "_synthesize_clip", fake_synthesize_clip)
    monkeypatch.setattr(script, "_synthesize_audio", fake_synthesize_audio)

    project_path = script.build_fixture(tmp_path / "fixture", register=False)
    _store, project = ProjectStore.open(project_path)

    assert project.project_name == "Smoothness Fixture"
    assert [clip.name for clip in project.clips] == [
        "fixture_1080p",
        "fixture_4k",
        "Missing source (intentional)",
    ]
    assert project.clips[0].height == 1080
    assert project.clips[1].height == 2160
    assert not Path(project.clips[2].path).exists()
    assert project.slides
    assert project.markers
    assert project.audio_tracks
    assert project.transcript_segments
    assert project.captions_enabled

    mask_annotations = [ann for ann in project.annotations if ann.type == "mask"]
    assert mask_annotations
    assert Path(mask_annotations[0].mask_path).exists()
