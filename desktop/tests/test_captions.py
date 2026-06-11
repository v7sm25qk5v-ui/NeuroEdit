"""P4 captions: cue generation from transcript segments, SRT/WebVTT output,
caption model fields, export-dialog settings, and burn-in render forcing."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from neuroedit_desktop.captions import (
    CaptionCue,
    build_caption_cues,
    cue_at_time,
    cues_to_srt,
    cues_to_vtt,
    wrap_caption_text,
)
from neuroedit_desktop.exporter import ExportSettings, ProjectExporter
from neuroedit_desktop.models import ProjectState, TranscriptSegment, new_id
from neuroedit_desktop.ui.main_window import ExportDialog


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def _segment(text: str, start: float = 0.0, end: float = 4.0, speaker: str = "") -> TranscriptSegment:
    return TranscriptSegment(
        id=new_id(), audio_track_id=None, start_time=start, end_time=end,
        text=text, speaker=speaker,
    )


def test_wrap_respects_max_chars():
    lines = wrap_caption_text("the quick brown fox jumps over the lazy dog", max_chars=15)
    assert all(len(line) <= 15 for line in lines)
    assert " ".join(lines) == "the quick brown fox jumps over the lazy dog"


def test_short_segment_is_single_cue():
    cues = build_caption_cues([_segment("Dissecting the dural margin now.")])
    assert len(cues) == 1
    assert cues[0].start == 0.0
    assert cues[0].end == 4.0
    assert len(cues[0].lines) <= 2


def test_long_segment_splits_into_sequential_cues():
    text = " ".join(["word"] * 60)  # far beyond 2 lines of 42 chars
    cues = build_caption_cues([_segment(text, 0.0, 12.0)])
    assert len(cues) > 1
    assert cues[0].start == 0.0
    assert cues[-1].end == pytest.approx(12.0)
    for earlier, later in zip(cues, cues[1:]):
        assert later.start == pytest.approx(earlier.end)
    assert all(len(cue.lines) <= 2 for cue in cues)


def test_speaker_prefix_and_empty_segments_skipped():
    cues = build_caption_cues([
        _segment("  ", 0.0, 1.0),
        _segment("clamp ready", 1.0, 2.0, speaker="Surgeon"),
    ])
    assert len(cues) == 1
    assert cues[0].lines[0].startswith("Surgeon: ")


def test_cue_at_time_boundaries():
    cues = [CaptionCue(1.0, 2.0, ("a",)), CaptionCue(2.0, 3.0, ("b",))]
    assert cue_at_time(cues, 0.5) is None
    assert cue_at_time(cues, 1.0).lines == ("a",)
    assert cue_at_time(cues, 2.0).lines == ("b",)  # half-open intervals
    assert cue_at_time(cues, 3.0) is None


def test_srt_format():
    srt = cues_to_srt([CaptionCue(0.0, 2.5, ("hello", "world")), CaptionCue(61.0, 62.0, ("next",))])
    blocks = srt.strip().split("\n\n")
    assert blocks[0] == "1\n00:00:00,000 --> 00:00:02,500\nhello\nworld"
    assert blocks[1] == "2\n00:01:01,000 --> 00:01:02,000\nnext"


def test_vtt_format():
    vtt = cues_to_vtt([CaptionCue(0.0, 2.5, ("hello",))])
    assert vtt.startswith("WEBVTT\n\n")
    assert "00:00:00.000 --> 00:00:02.500\nhello" in vtt


def test_caption_fields_round_trip():
    project = ProjectState()
    assert project.captions_enabled is False
    project.captions_enabled = True
    project.caption_size = "large"
    project.caption_position = "top"
    project.caption_background = False
    restored = ProjectState.from_dict(project.to_dict())
    assert restored.captions_enabled is True
    assert restored.caption_size == "large"
    assert restored.caption_position == "top"
    assert restored.caption_background is False


def _exporter(project: ProjectState, *, burn: bool) -> ProjectExporter:
    settings = ExportSettings(
        output_path=Path("/tmp/out.mp4"), width=1280, height=720,
        fps=30, crf=20, label="test", burn_captions=burn,
    )
    return ProjectExporter(project, settings)


def test_burned_captions_force_render():
    project = ProjectState()
    project.transcript_segments.append(_segment("visible caption", 1.0, 3.0))
    burn = _exporter(project, burn=True)
    # Inside the cue window the segment must re-render (caption gets painted);
    # a stream-copied segment would drop it.
    assert burn._segment_needs_render(1.0, 3.0, None) is True
    no_burn = _exporter(project, burn=False)
    assert no_burn._caption_cues == []
    # Cue edges become timeline boundaries only when burning.
    assert 1.0 in burn._timeline_boundaries(10.0)
    assert 3.0 in burn._timeline_boundaries(10.0)


def test_export_dialog_caption_and_advanced_settings(app):
    project = ProjectState()
    project.transcript_segments.append(_segment("hi", 0.0, 2.0))
    project.captions_enabled = True
    dialog = ExportDialog(project)
    assert dialog.burn_captions_check.isEnabled()
    assert dialog.burn_captions_check.isChecked()
    # Advanced fields glue to the preset until edited...
    settings = dialog.export_settings(Path("/tmp/x.mp4"))
    assert (settings.width, settings.height, settings.fps, settings.crf) == (1920, 1080, 30, 20)
    assert settings.burn_captions is True
    assert settings.audio_bitrate_k == 192
    # ...manual tweaks are respected...
    dialog.crf_spin.setValue(24)
    dialog.fps_combo.setCurrentIndex(dialog.fps_combo.findData(60))
    settings = dialog.export_settings(Path("/tmp/x.mp4"))
    assert settings.crf == 24
    assert settings.fps == 60
    # ...and switching presets re-glues every advanced field.
    dialog.preset_combo.setCurrentIndex(1)  # 720p preset
    settings = dialog.export_settings(Path("/tmp/x.mp4"))
    assert (settings.width, settings.height, settings.fps, settings.crf) == (1280, 720, 30, 23)


def test_export_dialog_captions_disabled_without_transcript(app):
    dialog = ExportDialog(ProjectState())
    assert not dialog.burn_captions_check.isEnabled()
    assert not dialog.export_settings(Path("/tmp/x.mp4")).burn_captions
