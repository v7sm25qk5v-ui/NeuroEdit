"""NE-029: export and caption robustness (items a-i)."""
from __future__ import annotations

import stat
import subprocess
import sys
import threading
from pathlib import Path

import cv2
import pytest
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from neuroedit_desktop import diagnostics
from neuroedit_desktop import exporter as exporter_module
from neuroedit_desktop.captions import (
    CaptionCue,
    build_caption_cues,
    cues_to_srt,
    cues_to_vtt,
)
from neuroedit_desktop.exporter import ExportSettings, ProjectExporter, resolve_ffmpeg
from neuroedit_desktop.models import Annotation, ProjectState, TranscriptSegment

SOFT = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]


@pytest.fixture(scope="module")
def qt_app():
    yield QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def ffmpeg() -> str:
    path = resolve_ffmpeg()
    assert path, "bundled ffmpeg required"
    return path


def _make_video(ffmpeg: str, path: Path, seconds: float = 1.0, audio: bool = False) -> None:
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
           f"testsrc=size=64x64:rate=30:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=duration={seconds}", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)


def _frames(path: Path) -> int:
    cap = cv2.VideoCapture(str(path))
    try:
        return int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        cap.release()


def _settings(out: Path, w=64, h=64, fps=30) -> ExportSettings:
    return ExportSettings(out, w, h, fps, 20, "test", mute_source_audio=True)


def _exporter(project, settings, monkeypatch) -> ProjectExporter:
    exp = ProjectExporter(project, settings)
    monkeypatch.setattr(exp, "_encoder_args", lambda _f: list(SOFT))
    return exp


# ------------------------------------------------------------------ a

def test_a_hardware_encoder_args_ignore_crf_and_dialog_says_so(qt_app, monkeypatch):
    exp = ProjectExporter(ProjectState(), ExportSettings(Path("x.mp4"), 1920, 1080, 30, 20, "t"))
    monkeypatch.setattr(exp, "_has_encoder", lambda _f, name: name == "h264_videotoolbox")
    a = exp._encoder_args("ffmpeg")
    exp.settings = ExportSettings(Path("x.mp4"), 1920, 1080, 30, 30, "t")
    assert exp._encoder_args("ffmpeg") == a  # CRF has no effect
    assert a[:4] == ["-c:v", "h264_videotoolbox", "-b:v", "12M"]
    monkeypatch.setattr(exp, "_has_encoder", lambda _f, name: False)
    assert exp._encoder_args("ffmpeg")[-2:] == ["-crf", "30"]

    from neuroedit_desktop.ui.dialogs import ExportDialog

    dialog = ExportDialog(ProjectState())
    text = dialog.crf_spin.toolTip().lower()
    assert "hardware" in text and "fixed" in text


# ------------------------------------------------------------------ b

def test_b_odd_dimensions_are_rounded_to_even():
    s = ExportSettings(Path("x.mp4"), 641, 361, 30, 20, "t")
    assert (s.width, s.height) == (640, 360)
    assert (ExportSettings(Path("x.mp4"), 1, 1, 30, 20, "t").width) == 2


def test_b_odd_request_exports_successfully(qt_app, tmp_path, monkeypatch, ffmpeg):
    src = tmp_path / "in.mp4"
    _make_video(ffmpeg, src)
    project = ProjectState()
    project.add_clip(src, 1.0, 64, 64)
    out = tmp_path / "out.mp4"
    exp = _exporter(project, _settings(out, 65, 63), monkeypatch)
    exp.export()
    cap = cv2.VideoCapture(str(out))
    assert (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))) == (64, 62)
    cap.release()


# ------------------------------------------------------------------ c

def test_c_overestimated_duration_still_gives_full_length(qt_app, tmp_path, monkeypatch, ffmpeg):
    src = tmp_path / "short.mp4"
    _make_video(ffmpeg, src, seconds=1.0)  # 30 frames on disk
    project = ProjectState()
    clip = project.add_clip(src, 2.0, 64, 64)  # probe claims 2 s
    assert clip.display_duration == 2.0
    out = tmp_path / "out.mp4"
    _exporter(project, _settings(out), monkeypatch).export()
    assert _frames(out) == 60


# ------------------------------------------------------------------ d

def test_d_audio_detection_ignores_file_name(qt_app, tmp_path, ffmpeg):
    exp = ProjectExporter(ProjectState(), _settings(tmp_path / "o.mp4"))
    silent = tmp_path / "Audio: test.mp4"
    _make_video(ffmpeg, silent)
    assert exp._has_audio_stream(silent, ffmpeg) is False
    folder = tmp_path / "Audio: dir"
    folder.mkdir()
    silent2 = folder / "Stream #0:1: Audio: x.mp4"
    _make_video(ffmpeg, silent2)
    assert exp._has_audio_stream(silent2, ffmpeg) is False
    with_audio = tmp_path / "Audio: with sound.mp4"
    _make_video(ffmpeg, with_audio, audio=True)
    assert exp._has_audio_stream(with_audio, ffmpeg) is True


# ------------------------------------------------------------------ e

def _fake_ffmpeg(tmp_path: Path) -> str:
    script = tmp_path / "fake_ffmpeg"
    script.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "sys.stderr.write('x' * 2_000_000)\n"
        "sys.stderr.flush()\n"
        "sys.stdin.buffer.read()\n"
        "sys.stderr.write('\\nBOOM-MARKER encoder exploded\\n')\n"
        "sys.exit(1)\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_e_chatty_ffmpeg_does_not_deadlock_and_message_survives(qt_app, tmp_path, monkeypatch):
    project = ProjectState()
    exp = _exporter(project, _settings(tmp_path / "o.mp4"), monkeypatch)
    monkeypatch.setattr(exp, "_render_frame", lambda _t: __import__("numpy").zeros((64, 64, 3), "uint8"))
    procs = []
    real_popen = subprocess.Popen

    def spy(*a, **k):
        p = real_popen(*a, **k)
        procs.append(p)
        return p

    monkeypatch.setattr(exporter_module.subprocess, "Popen", spy)
    seg = exporter_module.TimelineSegment(0.0, 2.0, "render")  # 60 frames > pipe buffer
    result: list[BaseException | None] = []

    def run():
        try:
            exp._encode_render_segment_with_ffmpeg(seg, tmp_path / "s.mp4", _fake_ffmpeg(tmp_path), 0, 1)
            result.append(None)
        except BaseException as exc:  # noqa: BLE001
            result.append(exc)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(30)
    for p in procs:
        if p.poll() is None:
            p.kill()
    assert not t.is_alive(), "render segment deadlocked on a chatty ffmpeg"
    assert isinstance(result[0], RuntimeError)
    assert "BOOM-MARKER encoder exploded" in str(result[0])


def test_e_real_ffmpeg_failure_reports_its_message(qt_app, tmp_path, monkeypatch, ffmpeg):
    exp = ProjectExporter(ProjectState(), _settings(tmp_path / "o.mp4"))
    monkeypatch.setattr(exp, "_encoder_args", lambda _f: ["-c:v", "no_such_encoder_xyz"])
    monkeypatch.setattr(exp, "_render_frame", lambda _t: __import__("numpy").zeros((64, 64, 3), "uint8"))
    seg = exporter_module.TimelineSegment(0.0, 0.2, "render")
    with pytest.raises(RuntimeError, match="no_such_encoder_xyz"):
        exp._encode_render_segment_with_ffmpeg(seg, tmp_path / "s.mp4", ffmpeg, 0, 1)


# ------------------------------------------------------------------ f

def test_f_vtt_escapes_markup_and_arrow_but_srt_is_unchanged():
    cue = CaptionCue(0.0, 1.0, ("A & B <i>x</i>", "a --> b"))
    vtt = cues_to_vtt([cue])
    body = vtt.split("\n\n", 1)[1].split("\n", 1)[1]
    assert "&amp;" in body and "&lt;i&gt;" in body
    assert "-->" not in body and "<" not in body
    assert cues_to_srt([cue]).endswith("A & B <i>x</i>\na --> b\n")


def test_f_short_cue_does_not_overlap_next():
    segs = [
        TranscriptSegment(id="a", audio_track_id=None, start_time=0.0, end_time=0.2, text="short"),
        TranscriptSegment(id="b", audio_track_id=None, start_time=0.5, end_time=2.0, text="next"),
    ]
    cues = build_caption_cues(segs)
    assert cues[0].end <= cues[1].start
    assert cues[0].end > cues[0].start


# ------------------------------------------------------------------ g

def test_g_report_warns_and_omits_free_text(tmp_path):
    from neuroedit_desktop.ui.export_workflow import ExportWorkflowMixin

    project = ProjectState(project_name="Jane Doe Case")
    project.video_goal = "teach Jane's surgery"
    project.storyboard_case_context = "MRN 12345"
    project.edit_disclosure = "contains Smith"
    project.intended_audience = "residents of Dr Who"
    project.consent_confirmed = True
    host = ExportWorkflowMixin()
    host._export_report_project = project
    path = host._write_export_report(tmp_path / "o.mp4", ["note one"])
    text = path.read_text(encoding="utf-8")
    first = text.splitlines()[0].lower()
    assert "case notes" in first and "not de-identified" in first
    for secret in ("Jane", "12345", "Smith", "Dr Who"):
        assert secret not in text
    assert "Consent/authorization confirmed: True" in text
    assert "- note one" in text


# ------------------------------------------------------------------ h

def _painter():
    image = QImage(400, 200, QImage.Format.Format_RGB888)
    return image, QPainter(image)


@pytest.mark.parametrize("kind", ["rect", "text"])
def test_h_zero_font_size_matches_preview_rule(qt_app, kind):
    def size_for(font_size):
        project = ProjectState()
        ann = Annotation(id="a", type=kind, frame_time=0.0, ann_duration=0.0, color="#ff0000",
                         label="hello", font_size=font_size,
                         geometry={"x": 0.1, "y": 0.3, "width": 0.3, "height": 0.3})
        exp = ProjectExporter(project, ExportSettings(Path("x.mp4"), 400, 200, 30, 20, "t"))
        image, painter = _painter()
        from PySide6.QtGui import QColor
        if kind == "rect":
            exp._paint_attached_label(painter, ann, 400, 200, QColor("#ff0000"))
            rect = exp._attached_label_rect(ann, 400, 200)
        else:
            exp._paint_text_label(painter, ann, 400, 200, QColor("#ff0000"))
            rect = None
        point = painter.font().pointSize()
        painter.end()
        return point, rect

    zero_pt, zero_rect = size_for(0)
    assert zero_pt == 15
    assert (zero_pt, zero_rect) == size_for(15)


# ------------------------------------------------------------------ i

def test_i_ffmpeg_path_is_logged_without_media_info(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "_enabled", True)
    monkeypatch.setattr(diagnostics, "_log_path", tmp_path / "d.log")
    monkeypatch.setattr(exporter_module, "resolve_ffmpeg", lambda: "/opt/tool/ffmpeg")
    diagnostics.log_ffmpeg()
    assert (tmp_path / "d.log").read_text().strip().endswith("ffmpeg path=/opt/tool/ffmpeg")
    monkeypatch.setattr(exporter_module, "resolve_ffmpeg", lambda: None)
    diagnostics.log_ffmpeg()
    assert "path=none" in (tmp_path / "d.log").read_text()
