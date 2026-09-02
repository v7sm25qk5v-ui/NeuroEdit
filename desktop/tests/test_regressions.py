"""Regression locks for the bugs fixed in the 2026-06-09 review session, plus
the exporter no-audio-by-default contract."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPointF, QSizeF, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPainter
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import QApplication

from neuroedit_desktop.exporter import AudioSource, ExportSettings, ProjectExporter
from neuroedit_desktop.models import (
    Annotation,
    AudioTrack,
    ProjectState,
    Slide,
    TranscriptSegment,
    VideoClip,
    new_id,
)
from neuroedit_desktop.ui.canvas import AnnotationGraphicsItem, VideoGraphicsView
from neuroedit_desktop.ui.editor_panels import AudioPanel, RichTimelineWidget
from neuroedit_desktop.ui.timeline_utils import project_end_time
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


def test_audio_panel_preserves_zero_duration_track_on_metadata_edit(app, tmp_path):
    project = ProjectState()
    track = AudioTrack(id=new_id(), path="/tmp/empty.m4a", name="Empty", duration=0.0)
    project.audio_tracks.append(track)
    panel = AudioPanel(project, tmp_path)
    panel.list_widget.setCurrentRow(0)

    panel.track_name.setText("Renamed placeholder")

    assert track.name == "Renamed placeholder"
    assert track.duration == pytest.approx(0.0)


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


def test_split_clip_source_bounds_prevent_duplicate_footage(app):
    project = ProjectState()
    project.clips.append(_clip(0.0, 10.0))
    project.current_time = 5.0
    timeline = RichTimelineWidget(project)

    timeline._cut_active_clip()
    left, right = project.clips
    timeline.canvas._apply_trim_end(left, 8.0)
    timeline.canvas._apply_trim_start(right, 2.0)

    assert left.trim_end == pytest.approx(5.0)
    assert right.trim_start == pytest.approx(5.0)
    assert project_end_time(project) == pytest.approx(10.0)
    restored = ProjectState.from_dict(project.to_dict())
    assert restored.clips[0].source_out_limit == pytest.approx(5.0)
    assert restored.clips[1].source_in_limit == pytest.approx(5.0)


def test_full_frame_still_preview_paints_visible_annotations(app, monkeypatch):
    project = ProjectState(current_time=1.0)
    project.slides.append(Slide(id="still", title="Still", start_time=0.0, duration=2.0))
    project.annotations.append(
        Annotation(
            id="arrow",
            frame_time=0.5,
            ann_duration=1.0,
            type="arrow",
            label="Target",
            color="#ffcc00",
            geometry={"x1": 0.2, "y1": 0.7, "x2": 0.6, "y2": 0.4},
        )
    )
    item = AnnotationGraphicsItem(project, QGraphicsVideoItem())
    item.set_size(QSizeF(320, 180))
    painted: list[str] = []
    fades: list[bool] = []
    monkeypatch.setattr(
        item,
        "_paint_shape",
        lambda _painter, ann, _w, _h, *, preview: painted.append(ann.id),
    )
    monkeypatch.setattr(
        item,
        "_paint_fade_overlay",
        lambda _painter, _w, _h: fades.append(True),
    )
    image = QImage(320, 180, QImage.Format.Format_RGB32)
    painter = QPainter(image)

    item._paint_impl(painter)
    painter.end()

    assert painted == ["arrow"]
    assert fades == []


def test_full_frame_still_export_paints_visible_annotations(monkeypatch):
    project = ProjectState(current_time=1.0)
    project.slides.append(Slide(id="still", title="Still", start_time=0.0, duration=2.0))
    project.annotations.append(
        Annotation(
            id="arrow",
            frame_time=0.5,
            ann_duration=1.0,
            type="arrow",
            label="Target",
            color="#ffcc00",
            geometry={"x1": 0.2, "y1": 0.7, "x2": 0.6, "y2": 0.4},
        )
    )
    exporter = ProjectExporter(
        project,
        ExportSettings(
            output_path=Path("/tmp/o.mp4"), width=320, height=180,
            fps=30, crf=20, label="test",
        ),
    )
    annotations: list[float] = []
    fades: list[float] = []
    monkeypatch.setattr(
        exporter,
        "_paint_annotations",
        lambda _painter, time_s, _w, _h: annotations.append(time_s),
    )
    monkeypatch.setattr(
        exporter,
        "_paint_fade",
        lambda _painter, time_s, _w, _h: fades.append(time_s),
    )

    exporter._render_frame(1.0)

    assert annotations == [1.0]
    assert fades == []


def test_arrow_tool_wins_over_slide_text_drag(app, monkeypatch):
    project = ProjectState(current_time=1.0, active_panel="slides", active_tool="arrow")
    project.slides.append(Slide(id="still", title="Still", start_time=0.0, duration=2.0))
    view = VideoGraphicsView(project)
    monkeypatch.setattr(view, "_scene_to_norm", lambda _position: (0.5, 0.2))
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(20, 20),
        QPointF(20, 20),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    view.mousePressEvent(event)

    assert view._slide_drag is None
    assert view._drag_start == (0.5, 0.2)


def test_brush_drag_creates_freehand_annotation(app, monkeypatch):
    project = ProjectState(current_time=1.0, active_tool="brush")
    view = VideoGraphicsView(project)
    positions = iter(((0.1, 0.1), (0.2, 0.2), (0.3, 0.25)))
    monkeypatch.setattr(view, "_scene_to_norm", lambda _position: next(positions))
    added: list[Annotation] = []
    view.annotation_added.connect(added.append)

    press = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(10, 10), QPointF(10, 10),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    move = QMouseEvent(
        QEvent.Type.MouseMove, QPointF(20, 20), QPointF(20, 20),
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    release = QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(30, 25), QPointF(30, 25),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )

    view.mousePressEvent(press)
    view.mouseMoveEvent(move)
    view.mouseReleaseEvent(release)

    assert len(added) == 1
    assert added[0].type == "brush"
    assert added[0].geometry["points"] == [[0.1, 0.1], [0.2, 0.2], [0.3, 0.25]]


def test_brush_annotation_renders_in_export():
    project = ProjectState()
    project.annotations.append(
        Annotation(
            id="brush",
            frame_time=0.0,
            ann_duration=1.0,
            type="brush",
            label="Highlight",
            color="#ffcc00",
            opacity=1.0,
            geometry={
                "points": [[0.1, 0.1], [0.5, 0.5], [0.9, 0.2]],
                "width_px": 12.0,
            },
        )
    )
    exporter = ProjectExporter(
        project,
        ExportSettings(
            output_path=Path("/tmp/o.mp4"), width=320, height=180,
            fps=30, crf=20, label="test",
        ),
    )

    frame = exporter._render_frame(0.5)

    assert frame[:, :, 0].max() > 200
    assert frame[:, :, 1].max() > 150


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


def test_zero_duration_slide_renders_for_minimum_export_span():
    project = ProjectState()
    project.slides.append(Slide(id=new_id(), title="Intro", start_time=0.0, duration=0.0))
    exporter = ProjectExporter(
        project,
        ExportSettings(output_path=Path("/tmp/o.mp4"), width=1280, height=720,
                       fps=30, crf=20, label="t"),
    )

    assert exporter._duration() == pytest.approx(0.1)
    assert exporter._timeline_boundaries(exporter._duration()) == [0.0, pytest.approx(0.1)]
    assert exporter._slide_at_time(0.05) is project.slides[0]


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


def test_export_rejects_missing_audio_track_source(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video")
    project = ProjectState()
    video_clip = _clip(0.0, 5.0)
    video_clip.path = str(clip)
    project.clips.append(video_clip)
    project.audio_tracks.append(
        AudioTrack(id=new_id(), path=str(tmp_path / "missing.m4a"), name="Narration", duration=5.0)
    )
    exporter = ProjectExporter(
        project,
        ExportSettings(
            output_path=tmp_path / "export.mp4", width=320, height=180,
            fps=30, crf=20, label="test",
        ),
    )

    with pytest.raises(RuntimeError, match="Narration"):
        exporter.export()


def test_export_source_preflight_ignores_inactive_audio_tracks(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video")
    project = ProjectState()
    video_clip = _clip(0.0, 5.0)
    video_clip.path = str(clip)
    project.clips.append(video_clip)
    project.audio_tracks.append(
        AudioTrack(id=new_id(), path=str(tmp_path / "missing-muted.m4a"), name="Muted", duration=5.0, volume=0.0)
    )
    project.audio_tracks.append(
        AudioTrack(id=new_id(), path=str(tmp_path / "missing-empty.m4a"), name="Empty", duration=0.0, volume=1.0)
    )
    exporter = ProjectExporter(
        project,
        ExportSettings(
            output_path=tmp_path / "export.mp4", width=320, height=180,
            fps=30, crf=20, label="test",
        ),
    )

    assert exporter._source_media() == [(video_clip.name, clip)]


def test_export_duration_ignores_inactive_audio_tracks(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video")
    project = ProjectState()
    video_clip = _clip(0.0, 5.0)
    video_clip.path = str(clip)
    project.clips.append(video_clip)
    project.audio_tracks.append(
        AudioTrack(
            id=new_id(),
            path=str(tmp_path / "muted.m4a"),
            name="Muted",
            start_time=30.0,
            duration=10.0,
            volume=0.0,
        )
    )
    project.audio_tracks.append(
        AudioTrack(
            id=new_id(),
            path=str(tmp_path / "empty.m4a"),
            name="Empty",
            start_time=40.0,
            duration=0.0,
            volume=1.0,
        )
    )
    exporter = ProjectExporter(
        project,
        ExportSettings(
            output_path=tmp_path / "export.mp4", width=320, height=180,
            fps=30, crf=20, label="test",
        ),
    )

    assert exporter._duration() == pytest.approx(5.0)


def test_export_warning_ignores_inactive_audio_tracks(tmp_path, monkeypatch):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video")
    project = ProjectState()
    video_clip = _clip(0.0, 5.0)
    video_clip.path = str(clip)
    project.clips.append(video_clip)
    project.audio_tracks.append(
        AudioTrack(id=new_id(), path=str(tmp_path / "muted.m4a"), name="Muted", duration=5.0, volume=0.0)
    )
    project.audio_tracks.append(
        AudioTrack(id=new_id(), path=str(tmp_path / "empty.m4a"), name="Empty", duration=0.0, volume=1.0)
    )
    exporter = ProjectExporter(
        project,
        ExportSettings(
            output_path=tmp_path / "export.mp4", width=320, height=180,
            fps=30, crf=20, label="test",
        ),
    )

    monkeypatch.setattr(exporter, "_find_ffmpeg", lambda: "ffmpeg")

    def write_video(path: Path, _ffmpeg: str, _tmp_dir: Path, _duration: float) -> None:
        path.write_bytes(b"visual")

    monkeypatch.setattr(exporter, "_encode_timeline_video", write_video)

    assert exporter.export() == []
    assert (tmp_path / "export.mp4").read_bytes() == b"visual"


def test_export_warns_when_active_audio_has_no_readable_stream(tmp_path, monkeypatch):
    clip = tmp_path / "clip.mp4"
    audio = tmp_path / "voice.m4a"
    clip.write_bytes(b"video")
    audio.write_bytes(b"not-audio")
    project = ProjectState()
    video_clip = _clip(0.0, 5.0)
    video_clip.path = str(clip)
    project.clips.append(video_clip)
    project.audio_tracks.append(
        AudioTrack(id=new_id(), path=str(audio), name="Narration", duration=5.0, volume=1.0)
    )
    exporter = ProjectExporter(
        project,
        ExportSettings(
            output_path=tmp_path / "export.mp4", width=320, height=180,
            fps=30, crf=20, label="test",
        ),
    )

    monkeypatch.setattr(exporter, "_find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(exporter, "_audio_sources", lambda _ffmpeg: [])

    def write_video(path: Path, _ffmpeg: str, _tmp_dir: Path, _duration: float) -> None:
        path.write_bytes(b"visual")

    monkeypatch.setattr(exporter, "_encode_timeline_video", write_video)

    assert exporter.export() == ["No readable audio streams were found, so the MP4 is silent."]
    assert (tmp_path / "export.mp4").read_bytes() == b"visual"


def test_export_rejects_missing_slide_image_source(tmp_path):
    project = ProjectState()
    project.slides.append(
        Slide(id=new_id(), title="Still", image_path=str(tmp_path / "missing.png"))
    )
    exporter = ProjectExporter(
        project,
        ExportSettings(
            output_path=tmp_path / "export.mp4", width=320, height=180,
            fps=30, crf=20, label="test",
        ),
    )

    with pytest.raises(RuntimeError, match="Still"):
        exporter.export()


def test_export_rejects_output_overwriting_slide_or_audio_source(tmp_path):
    source = tmp_path / "still.png"
    source.write_bytes(b"image")
    project = ProjectState()
    project.slides.append(Slide(id=new_id(), title="Still", image_path=str(source)))
    exporter = ProjectExporter(
        project,
        ExportSettings(
            output_path=source, width=320, height=180,
            fps=30, crf=20, label="test",
        ),
    )

    with pytest.raises(RuntimeError, match="source media files"):
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
