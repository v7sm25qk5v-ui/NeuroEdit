"""Regression locks for the bugs fixed in the 2026-06-09 review session, plus
the exporter no-audio-by-default contract."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from neuroedit_desktop.exporter import AudioSource, ExportSettings, ProjectExporter
from neuroedit_desktop.models import (
    AudioTrack,
    ProjectState,
    Slide,
    TranscriptSegment,
    VideoClip,
    new_id,
)
from neuroedit_desktop.ui.editor_panels import AudioPanel, RichTimelineWidget
from neuroedit_desktop.ui.main_window import ExportDialog


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def _clip(start: float, length: float, media_type: str = "video", **kwargs) -> VideoClip:
    return VideoClip(
        id=new_id(), path="/tmp/src.mp4", name="clip", duration=length,
        start_time=start, trim_start=0.0, trim_end=length,
        media_type=media_type, **kwargs,
    )


def test_audio_track_delete_keeps_unattached_transcripts(app, tmp_path):
    project = ProjectState()
    track = AudioTrack(id=new_id(), path="/tmp/v.m4a", name="Voice", duration=5.0)
    project.audio_tracks.append(track)
    project.transcript_segments.append(
        TranscriptSegment(id="attached", audio_track_id=track.id,
                          start_time=0.0, end_time=2.0, text="attached")
    )
    project.transcript_segments.append(
        TranscriptSegment(id="floating", audio_track_id=None,
                          start_time=2.0, end_time=4.0, text="floating")
    )
    panel = AudioPanel(project, tmp_path)
    panel.list_widget.setCurrentRow(0)
    panel._delete_selected()
    assert project.audio_tracks == []
    remaining = [segment.id for segment in project.transcript_segments]
    assert remaining == ["floating"]


def test_cut_preserves_media_type_and_moves_fade_out(app):
    project = ProjectState()
    clip = _clip(0.0, 8.0, media_type="image", fade_in=0.5, fade_out=1.0)
    project.clips.append(clip)
    project.current_time = 4.0
    timeline = RichTimelineWidget(project)
    timeline._cut_active_clip()
    assert len(project.clips) == 2
    left, right = project.clips
    assert right.media_type == "image"
    assert left.fade_in == 0.5
    assert left.fade_out == 0.0  # the cut point is no longer the media end
    assert right.fade_out == 1.0
    assert right.fade_in == 0.0
    assert right.trim_start == pytest.approx(4.0)


def test_exporter_duration_is_content_end_not_project_duration():
    project = ProjectState()
    project.clips.append(_clip(0.0, 6.0))
    project.slides.append(Slide(id=new_id(), title="End", start_time=6.0, duration=2.0))
    # Simulate the old ratchet: a stale display duration past real content.
    project.duration = 30.0
    project.current_time = 29.0
    exporter = ProjectExporter(
        project,
        ExportSettings(output_path=Path("/tmp/o.mp4"), width=1280, height=720,
                       fps=30, crf=20, label="t"),
    )
    assert exporter._duration() == pytest.approx(8.0)


def test_from_dict_tolerates_unknown_keys():
    project = ProjectState()
    project.clips.append(_clip(0.0, 3.0))
    data = project.to_dict()
    data["a_future_field"] = "ignored"
    data["clips"][0]["another_future_field"] = 42
    data["annotations"] = [
        {
            "id": "a1", "frame_time": 0.0, "ann_duration": 1.0, "type": "rect",
            "label": "x", "color": "#fff", "from_the_future": True,
        }
    ]
    restored = ProjectState.from_dict(data)
    assert restored.clips[0].name == "clip"
    assert restored.annotations[0].id == "a1"


def test_default_export_dialog_produces_no_source_audio(app):
    """The dialog's privacy default (mute source audio) must yield zero audio
    sources for a clips-only project — the export is silent unless the user
    opts in or adds narration."""
    project = ProjectState()
    project.clips.append(_clip(0.0, 5.0))
    dialog = ExportDialog(project)
    settings = dialog.export_settings(Path("/tmp/o.mp4"))
    assert settings.mute_source_audio is True
    exporter = ProjectExporter(project, settings)
    assert exporter._audio_sources("ffmpeg") == []


def test_export_rejects_missing_source_media(tmp_path):
    project = ProjectState()
    project.clips.append(_clip(0.0, 5.0))
    exporter = ProjectExporter(
        project,
        ExportSettings(
            output_path=tmp_path / "export.mp4", width=320, height=180,
            fps=30, crf=20, label="test",
        ),
    )

    with pytest.raises(RuntimeError, match="source media is missing"):
        exporter.export()


def test_audio_mux_replaces_output_only_after_success(tmp_path, monkeypatch):
    project = ProjectState()
    exporter = ProjectExporter(
        project,
        ExportSettings(
            output_path=tmp_path / "export.mp4", width=320, height=180,
            fps=30, crf=20, label="test",
        ),
    )
    tmp_video = tmp_path / "visual.mp4"
    output = tmp_path / "export.mp4"
    tmp_video.write_bytes(b"visual")
    output.write_bytes(b"existing")
    source = AudioSource(tmp_path / "audio.m4a", 0.0, 0.0, 1.0, 1.0)

    def write_staged(cmd: list[str], _message: str) -> None:
        Path(cmd[-1]).write_bytes(b"muxed")

    monkeypatch.setattr(exporter, "_run_ffmpeg", write_staged)
    exporter._mux_audio(tmp_video, output, [source], "ffmpeg", 1.0)

    assert output.read_bytes() == b"muxed"


def test_audio_mux_failure_preserves_existing_output(tmp_path, monkeypatch):
    project = ProjectState()
    exporter = ProjectExporter(
        project,
        ExportSettings(
            output_path=tmp_path / "export.mp4", width=320, height=180,
            fps=30, crf=20, label="test",
        ),
    )
    tmp_video = tmp_path / "visual.mp4"
    output = tmp_path / "export.mp4"
    tmp_video.write_bytes(b"visual")
    output.write_bytes(b"existing")
    source = AudioSource(tmp_path / "audio.m4a", 0.0, 0.0, 1.0, 1.0)

    def fail_mux(_cmd: list[str], _message: str) -> None:
        raise RuntimeError("ffmpeg failed")

    monkeypatch.setattr(exporter, "_run_ffmpeg", fail_mux)
    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        exporter._mux_audio(tmp_video, output, [source], "ffmpeg", 1.0)

    assert output.read_bytes() == b"existing"
