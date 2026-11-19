"""Shared export presets, estimates, automatic frame rate and naming."""
from __future__ import annotations

from pathlib import Path

import pytest

from neuroedit_desktop import export_plan
from neuroedit_desktop.models import ProjectState


def test_presets_keep_their_keys_and_sizes():
    assert [p.key for p in export_plan.QUALITY_PRESETS] == ["1080p", "720p", "4k"]
    assert export_plan.preset_for_key("4k").width == 3840
    assert export_plan.preset_for_key("missing") is export_plan.QUALITY_PRESETS[0]


def test_bitrate_matches_the_hardware_encoder_tiers():
    assert export_plan.video_bitrate_bps(3840, 2160) == 45_000_000
    assert export_plan.video_bitrate_bps(1920, 1080) == 12_000_000
    assert export_plan.video_bitrate_bps(1280, 720) == 5_000_000


def test_size_estimate_is_bitrate_times_duration():
    size = export_plan.estimate_output_bytes(1920, 1080, 100, audio_kbps=192)
    expected = (12_000_000 + 192_000) * 100 / 8
    assert expected <= size <= expected * 1.05
    assert export_plan.estimate_output_bytes(1920, 1080, 100, audio_kbps=None) < size


def test_time_estimate_and_wording():
    seconds = export_plan.estimate_encode_seconds(1920, 1080, 30, 600)
    assert 85 < seconds < 115  # ~6x realtime at 1080p30: 10 min of video in under 2 min
    assert export_plan.estimate_encode_seconds(1920, 1080, 30, 600, pixel_rate=2 * export_plan.DEFAULT_PIXEL_RATE) == pytest.approx(seconds / 2)
    assert export_plan.format_time_estimate(10) == "less than a minute"
    assert export_plan.format_time_estimate(170) == "about 3 min"
    assert export_plan.format_time_estimate(3900) == "about 1 h 5 min"
    assert export_plan.format_time_estimate(7200) == "about 2 h"


@pytest.mark.parametrize(
    ("probed", "snapped"),
    [(29.97, 30), (59.94, 60), (23.976, 24), (25.0, 25), (50.0, 50), (120.0, 60),
     (15.0, 30), (0.0, None), (None, None), (float("nan"), None)],
)
def test_snap_fps(probed, snapped):
    assert export_plan.snap_fps(probed) == snapped


def _project_with(clips):
    project = ProjectState()
    for path, duration in clips:
        project.add_clip(Path(path), duration=duration, width=1920, height=1080)
    return project


def test_automatic_fps_follows_the_footage_that_covers_most_time():
    rates = {"a.mp4": 25.0, "b.mp4": 59.94}
    project = _project_with([("a.mp4", 100), ("b.mp4", 30)])
    assert export_plan.automatic_fps(project, probe=lambda p: rates[p.name]) == 25
    project = _project_with([("a.mp4", 10), ("b.mp4", 30)])
    assert export_plan.automatic_fps(project, probe=lambda p: rates[p.name]) == 60


def test_automatic_fps_defaults_to_30_when_nothing_is_known():
    assert export_plan.automatic_fps(ProjectState()) == 30
    project = _project_with([("a.mp4", 10)])
    assert export_plan.automatic_fps(project, probe=lambda _p: None) == 30


def test_source_fps_skips_missing_and_icloud_evicted_files(tmp_path, monkeypatch):
    assert export_plan.source_fps(tmp_path / "missing.mp4") is None
    evicted = tmp_path / "evicted.mp4"
    evicted.write_bytes(b"x")
    monkeypatch.setattr(export_plan, "is_dataless", lambda _p: True)
    assert export_plan.source_fps(evicted) is None


def test_readable_name_keeps_spaces_and_drops_unsafe_characters():
    assert export_plan.readable_export_name("Case 12: L4/L5 *final*") == "Case 12 L4 L5 final"
    assert export_plan.readable_export_name("  ...  ") == export_plan.DEFAULT_EXPORT_NAME
    assert len(export_plan.readable_export_name("x" * 300)) == 120


def test_unique_path_never_reuses_an_existing_export(tmp_path):
    first = export_plan.unique_export_path(tmp_path, "Case 12")
    assert first == tmp_path / "Case 12.mp4"
    first.write_bytes(b"done")
    second = export_plan.unique_export_path(tmp_path, "Case 12")
    assert second == tmp_path / "Case 12 2.mp4"
    second.write_bytes(b"done")
    assert export_plan.unique_export_path(tmp_path, "Case 12") == tmp_path / "Case 12 3.mp4"
