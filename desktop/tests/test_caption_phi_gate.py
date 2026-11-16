"""NE-015: caption/transcript text passes a PHI gate before leaving the app
(burned-in captions, SRT/VTT sidecar files, and guided review)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialogButtonBox, QFileDialog, QMessageBox

from neuroedit_desktop.models import (
    AudioTrack,
    ProjectState,
    TranscriptSegment,
    VideoClip,
    new_id,
)
from neuroedit_desktop.ui.export_workflow import project_export_includes_audio
from neuroedit_desktop.ui.main_window import ExportChecklistDialog, PhiReviewDialog
from test_main_window_headless import app, window  # noqa: F401


def _project(text: str | None = "Patient John Smith, 4 May") -> ProjectState:
    project = ProjectState()
    project.clips.append(
        VideoClip(id=new_id(), path="/tmp/a.mp4", name="Clip A", duration=10.0,
                  start_time=0.0, trim_start=0.0, trim_end=10.0)
    )
    if text is not None:
        project.transcript_segments.append(
            TranscriptSegment(id=new_id(), audio_track_id=None, start_time=1.0,
                              end_time=3.0, text=text)
        )
    return project


def _checklist(project, *, burns_captions: bool) -> ExportChecklistDialog:
    # Source audio muted and no audio tracks: the audio item is hidden.
    includes_audio = project_export_includes_audio(project, keeps_source_audio=False)
    assert includes_audio is False
    return ExportChecklistDialog(
        project,
        export_includes_audio=includes_audio,
        keeps_source_audio=False,
        burns_captions=burns_captions,
    )


def _tick_required(dialog) -> None:
    dialog.phi_check.setChecked(True)
    dialog.deid_check.setChecked(True)
    dialog.consent_check.setChecked(True)


def _ok(dialog):
    return dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)


# ── export checklist ─────────────────────────────────────────────────────────

def test_checklist_blocks_burned_captions_until_ticked_even_with_muted_audio(app):  # noqa: F811
    project = _project()
    dialog = _checklist(project, burns_captions=True)
    assert not dialog.audio_check.isVisibleTo(dialog)
    assert dialog.caption_check.isVisibleTo(dialog)
    _tick_required(dialog)
    assert not _ok(dialog).isEnabled()
    dialog.caption_check.setChecked(True)
    assert _ok(dialog).isEnabled()
    dialog.apply_to_project(project)
    # The confirmation is saved so the sidecar export does not ask again.
    assert project.phi_review_progress.get("transcript") is True


def test_checklist_has_no_caption_item_without_transcript_text(app):  # noqa: F811
    for project in (_project(None), _project("   ")):
        dialog = _checklist(project, burns_captions=True)
        assert not dialog.caption_check.isVisibleTo(dialog)
        _tick_required(dialog)
        assert _ok(dialog).isEnabled()


def test_checklist_has_no_caption_item_when_not_burned_in(app):  # noqa: F811
    dialog = _checklist(_project(), burns_captions=False)
    assert not dialog.caption_check.isVisibleTo(dialog)
    _tick_required(dialog)
    assert _ok(dialog).isEnabled()


def test_checklist_caption_item_prefilled_when_already_confirmed(app):  # noqa: F811
    project = _project()
    project.phi_review_progress = {"transcript": True}
    dialog = _checklist(project, burns_captions=True)
    assert dialog.caption_check.isChecked()
    _tick_required(dialog)
    assert _ok(dialog).isEnabled()


def test_hidden_caption_item_does_not_clobber_saved_confirmation(app):  # noqa: F811
    project = _project()
    project.phi_review_progress = {"transcript": True}
    dialog = _checklist(project, burns_captions=False)
    dialog.apply_to_project(project)
    assert project.phi_review_progress == {"transcript": True}


# ── guided review ────────────────────────────────────────────────────────────

def test_guided_review_has_transcript_stop_only_with_text(app):  # noqa: F811
    with_text = PhiReviewDialog(_project())
    assert [key for key, *_ in with_text.stops] == [with_text.stops[0][0], "transcript"]
    assert "John Smith" in with_text.stops[-1][1] + with_text.stops[-1][2]
    for project in (_project(None), _project("  ")):
        assert "transcript" not in [key for key, *_ in PhiReviewDialog(project).stops]


def test_guided_review_shows_speaker_in_exported_caption_text(app):  # noqa: F811
    project = _project("Stable")
    project.transcript_segments[0].speaker = "Patient Jane Smith"
    stop = PhiReviewDialog(project).stops[-1]
    assert "Patient Jane Smith: Stable" in stop[1]


def test_guided_review_displays_caption_markup_as_plain_text(app):  # noqa: F811
    text = '<span style="color:transparent">Jane Smith</span> Stable'
    dialog = PhiReviewDialog(_project(text))
    dialog._go_next()
    assert text in dialog.item_label.text().replace("\n", " ")
    assert dialog.item_label.textFormat() == Qt.TextFormat.PlainText


def test_guided_review_needs_transcript_stop_to_complete(app):  # noqa: F811
    project = _project()
    dialog = PhiReviewDialog(project)
    completed = []
    dialog.review_completed.connect(lambda: completed.append(True))
    dialog._mark_and_next()  # the clip
    dialog._go_next()  # skip the transcript
    assert not completed
    assert dialog.progress_dict() == {dialog.stops[0][0]: True}

    resumed = PhiReviewDialog(project := _project())
    project.phi_review_progress = {resumed.stops[0][0]: True}
    resumed = PhiReviewDialog(project)
    assert resumed._index == 1  # resumes at the transcript stop
    done = []
    resumed.review_completed.connect(lambda: done.append(True))
    resumed._mark_and_next()
    assert done == [True]
    assert resumed.progress_dict() == {resumed.stops[0][0]: True, "transcript": True}


def test_old_progress_without_transcript_stop_still_loads(app):  # noqa: F811
    project = _project()
    clip_id = project.clips[0].id
    project.phi_review_progress = {clip_id: True, "deleted-item": True}
    dialog = PhiReviewDialog(ProjectState.from_dict(project.to_dict()))
    assert dialog.progress_dict() == {clip_id: True}
    assert dialog._index == 1


def test_transcript_stop_follows_audio_stops_not_required_without_text(app):  # noqa: F811
    project = _project(None)
    project.audio_tracks.append(
        AudioTrack(id=new_id(), path="/tmp/v.m4a", name="Voice", start_time=0.0, duration=4.0)
    )
    assert len(PhiReviewDialog(project).stops) == 2


# ── sidecar export ───────────────────────────────────────────────────────────

class _Prompts:
    def __init__(self, monkeypatch, answer):
        self.asked = 0
        self.answer = answer

        def question(*_args, **_kwargs):
            self.asked += 1
            return self.answer

        monkeypatch.setattr(QMessageBox, "question", staticmethod(question))


def _stub_save_dialog(monkeypatch, path):
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(path), "SubRip captions (*.srt)")),
    )


def test_sidecar_declined_writes_nothing(window, tmp_path, monkeypatch):  # noqa: F811
    window.project.transcript_segments = _project().transcript_segments
    out = tmp_path / "caps.srt"
    _stub_save_dialog(monkeypatch, out)
    prompts = _Prompts(monkeypatch, QMessageBox.StandardButton.No)
    window._export_captions()
    assert prompts.asked == 1
    assert not out.exists()
    assert not window.project.phi_review_progress.get("transcript")


def test_sidecar_confirmed_once_per_transcript_state(window, tmp_path, monkeypatch):  # noqa: F811
    window.project.transcript_segments = _project().transcript_segments
    out = tmp_path / "caps.srt"
    _stub_save_dialog(monkeypatch, out)
    prompts = _Prompts(monkeypatch, QMessageBox.StandardButton.Yes)
    window._export_captions()
    assert prompts.asked == 1
    assert "John Smith" in out.read_text(encoding="utf-8")
    out.unlink()
    window._export_captions()  # unchanged transcript: no second question
    assert prompts.asked == 1
    assert out.exists()


def test_sidecar_without_text_asks_nothing(window, tmp_path, monkeypatch):  # noqa: F811
    window.project.transcript_segments = _project("  ").transcript_segments
    out = tmp_path / "caps.srt"
    _stub_save_dialog(monkeypatch, out)
    prompts = _Prompts(monkeypatch, QMessageBox.StandardButton.No)
    window._export_captions()
    assert prompts.asked == 0


def test_editing_transcript_text_resets_confirmation(window, tmp_path, monkeypatch):  # noqa: F811
    """Goes through the real signal path (audio panel -> main window)."""
    window.project.transcript_segments = _project().transcript_segments
    out = tmp_path / "caps.srt"
    _stub_save_dialog(monkeypatch, out)
    prompts = _Prompts(monkeypatch, QMessageBox.StandardButton.Yes)
    window._export_captions()
    assert window.project.phi_review_progress.get("transcript") is True

    monkeypatch.setattr(window, "_sync_player_to_timeline", lambda **_kwargs: None)
    window.project.transcript_segments[0].text = "Patient Jane Roe, 9 June"
    window.audio_panel.project_changed.emit()
    assert not window.project.phi_review_progress.get("transcript")

    window._export_captions()
    assert prompts.asked == 2


# ── model ────────────────────────────────────────────────────────────────────

def test_confirmation_round_trips_and_old_projects_load():
    project = _project()
    project.phi_review_progress = {"transcript": True}
    restored = ProjectState.from_dict(project.to_dict())
    assert restored.phi_review_progress == {"transcript": True}
    old = project.to_dict()
    del old["phi_review_progress"]
    assert ProjectState.from_dict(old).phi_review_progress == {}


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
