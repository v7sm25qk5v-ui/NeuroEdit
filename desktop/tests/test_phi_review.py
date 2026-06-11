"""P3 privacy/PHI features: audio review flag, pre-export checklist, guided
PHI review stops, and the configurable storage root."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from neuroedit_desktop.models import (
    AudioTrack,
    ProjectState,
    Slide,
    VideoClip,
    new_id,
)
from neuroedit_desktop.ui.editor_panels import project_preflight_warnings
from neuroedit_desktop.ui.main_window import (
    ExportChecklistDialog,
    PhiReviewDialog,
    default_project_root,
    legacy_project_root,
    recommended_project_root,
)


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def _project_with_media() -> ProjectState:
    project = ProjectState()
    project.clips.append(
        VideoClip(id=new_id(), path="/tmp/a.mp4", name="Clip A", duration=10.0,
                  start_time=0.0, trim_start=0.0, trim_end=10.0)
    )
    project.slides.append(Slide(id=new_id(), title="Intro", start_time=10.0))
    project.audio_tracks.append(
        AudioTrack(id=new_id(), path="/tmp/voice.m4a", name="Narration",
                   start_time=0.0, duration=8.0)
    )
    return project


def test_audio_reviewed_flag_round_trips():
    project = ProjectState()
    assert project.audio_reviewed_for_phi is False
    project.audio_reviewed_for_phi = True
    restored = ProjectState.from_dict(project.to_dict())
    assert restored.audio_reviewed_for_phi is True


def test_preflight_warns_on_unreviewed_audio():
    project = _project_with_media()
    assert any("spoken PHI" in w for w in project_preflight_warnings(project))
    project.audio_reviewed_for_phi = True
    assert not any("spoken PHI" in w for w in project_preflight_warnings(project))


def test_checklist_blocks_until_required_checked(app):
    project = _project_with_media()
    dialog = ExportChecklistDialog(
        project, export_includes_audio=True, keeps_source_audio=False
    )
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()
    dialog.phi_check.setChecked(True)
    dialog.deid_check.setChecked(True)
    assert not ok.isEnabled()
    dialog.consent_check.setChecked(True)
    assert ok.isEnabled()
    # The audio item warns but never gates the OK button.
    assert not dialog.audio_check.isChecked()
    dialog.apply_to_project(project)
    assert project.phi_review_confirmed
    assert project.deidentified_confirmed
    assert project.consent_confirmed
    assert project.audio_reviewed_for_phi is False


def test_checklist_prefills_from_project(app):
    project = _project_with_media()
    project.phi_review_confirmed = True
    project.deidentified_confirmed = True
    project.consent_confirmed = True
    project.audio_reviewed_for_phi = True
    dialog = ExportChecklistDialog(
        project, export_includes_audio=True, keeps_source_audio=True
    )
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert ok.isEnabled()
    assert dialog.audio_check.isChecked()


def test_checklist_silent_export_ignores_audio_flag(app):
    project = _project_with_media()
    project.audio_reviewed_for_phi = True
    dialog = ExportChecklistDialog(
        project, export_includes_audio=False, keeps_source_audio=False
    )
    dialog.audio_check.setChecked(False)
    dialog.apply_to_project(project)
    # A silent export must not clobber the project-level audio review flag.
    assert project.audio_reviewed_for_phi is True


def test_phi_review_builds_stop_per_item(app):
    project = _project_with_media()
    dialog = PhiReviewDialog(project)
    assert len(dialog.stops) == 3
    labels = [label for label, _hint, _t in dialog.stops]
    assert any("Clip A" in label for label in labels)
    assert any("Intro" in label for label in labels)
    assert any("Narration" in label for label in labels)


def test_phi_review_completion_signal(app):
    project = _project_with_media()
    dialog = PhiReviewDialog(project)
    completed = []
    dialog.review_completed.connect(lambda: completed.append(True))
    seeks = []
    dialog.seek_requested.connect(seeks.append)
    for _ in range(len(dialog.stops)):
        dialog._mark_and_next()
    assert completed == [True]
    assert len(seeks) >= len(dialog.stops) - 1


def test_phi_review_skip_does_not_complete(app):
    project = _project_with_media()
    dialog = PhiReviewDialog(project)
    completed = []
    dialog.review_completed.connect(lambda: completed.append(True))
    dialog._mark_and_next()
    dialog._go_next()  # skip
    dialog._mark_and_next()
    assert completed == []


def test_default_project_root_respects_setting(app):
    settings = QSettings("NeuroEdit", "Desktop")
    original = settings.value("storage/projectRoot", "")
    try:
        settings.setValue("storage/projectRoot", "")
        assert default_project_root() == legacy_project_root()
        settings.setValue("storage/projectRoot", str(recommended_project_root()))
        assert default_project_root() == recommended_project_root()
    finally:
        settings.setValue("storage/projectRoot", original)
