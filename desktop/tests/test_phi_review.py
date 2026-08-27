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
from neuroedit_desktop.ui.export_workflow import project_export_includes_audio
from neuroedit_desktop.ui.main_window import (
    ExportChecklistDialog,
    PhiReviewDialog,
    default_project_root,
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


def test_preflight_ignores_inactive_audio_for_spoken_phi():
    project = ProjectState()
    project.clips.append(
        VideoClip(id=new_id(), path="/tmp/a.mp4", name="Clip A", duration=10.0,
                  start_time=0.0, trim_start=0.0, trim_end=10.0)
    )
    project.audio_tracks.append(
        AudioTrack(id=new_id(), path="/tmp/muted.m4a", name="Muted",
                   start_time=0.0, duration=8.0, volume=0.0)
    )
    project.audio_tracks.append(
        AudioTrack(id=new_id(), path="/tmp/empty.m4a", name="Empty",
                   start_time=20.0, duration=0.0, volume=1.0)
    )

    warnings = project_preflight_warnings(project)

    assert not any("spoken PHI" in warning for warning in warnings)
    assert any("Consider adding narration" in warning for warning in warnings)


def test_export_audio_detection_ignores_inactive_audio_tracks():
    project = ProjectState()
    project.audio_tracks.append(
        AudioTrack(id=new_id(), path="/tmp/muted.m4a", name="Muted",
                   start_time=0.0, duration=8.0, volume=0.0)
    )
    project.audio_tracks.append(
        AudioTrack(id=new_id(), path="/tmp/empty.m4a", name="Empty",
                   start_time=20.0, duration=0.0, volume=1.0)
    )

    assert project_export_includes_audio(project, keeps_source_audio=False) is False

    project.audio_tracks.append(
        AudioTrack(id=new_id(), path="/tmp/voice.m4a", name="Narration",
                   start_time=0.0, duration=8.0, volume=1.0)
    )
    assert project_export_includes_audio(project, keeps_source_audio=False) is True
    assert project_export_includes_audio(ProjectState(), keeps_source_audio=True) is True


def test_preflight_privacy_warnings_cover_slide_only_exports():
    project = ProjectState()
    project.slides.append(
        Slide(id=new_id(), title="Imported still", image_path="/tmp/still.png")
    )

    warnings = project_preflight_warnings(project)

    assert any("consent" in warning for warning in warnings)
    assert any("de-identification" in warning for warning in warnings)
    assert any("PHI review" in warning for warning in warnings)
    assert any("No redaction boxes" in warning for warning in warnings)


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
    labels = [label for _key, label, _hint, _t in dialog.stops]
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


def test_phi_review_progress_round_trips_on_project():
    project = _project_with_media()
    project.phi_review_progress = {project.clips[0].id: True}
    restored = ProjectState.from_dict(project.to_dict())
    assert restored.phi_review_progress == {project.clips[0].id: True}


def test_phi_review_resumes_at_first_unreviewed_stop(app):
    project = _project_with_media()
    dialog = PhiReviewDialog(project)
    first_key = dialog.stops[0][0]
    project.phi_review_progress = {first_key: True}

    resumed = PhiReviewDialog(project)
    assert resumed._index == 1
    assert resumed.progress_dict() == {first_key: True}


def test_phi_review_partial_progress_is_exposed(app):
    project = _project_with_media()
    dialog = PhiReviewDialog(project)
    dialog._mark_and_next()
    dialog._go_next()  # skip the second stop
    assert dialog.progress_dict() == {dialog.stops[0][0]: True}


def test_phi_review_ignores_stale_progress_keys(app):
    project = _project_with_media()
    project.phi_review_progress = {"deleted-item-id": True}
    dialog = PhiReviewDialog(project)
    # Stale keys never count toward completion or the resume position.
    assert dialog._index == 0
    assert dialog.progress_dict() == {}


def test_phi_review_resumed_session_can_complete(app):
    project = _project_with_media()
    probe = PhiReviewDialog(project)
    project.phi_review_progress = {probe.stops[0][0]: True}

    dialog = PhiReviewDialog(project)
    completed = []
    dialog.review_completed.connect(lambda: completed.append(True))
    dialog._mark_and_next()  # stop 2
    dialog._mark_and_next()  # stop 3 → finish
    assert completed == [True]


def test_migrate_storage_root_copies_tree(tmp_path):
    from neuroedit_desktop.ui.main_window import migrate_storage_root

    old_root = tmp_path / "old" / "Autosave"
    (old_root / "masks").mkdir(parents=True)
    (old_root / "project.json").write_text("{}", encoding="utf-8")
    (old_root / "masks" / "m.png").write_bytes(b"png")
    new_root = tmp_path / "new" / "Autosave"

    error = migrate_storage_root(old_root, new_root)

    assert error is None
    assert (new_root / "project.json").read_text(encoding="utf-8") == "{}"
    assert (new_root / "masks" / "m.png").read_bytes() == b"png"
    # Copy, never move: originals stay until the user removes them.
    assert (old_root / "project.json").exists()


def test_default_project_root_respects_setting(app):
    settings = QSettings("NeuroEdit", "Desktop")
    original = settings.value("storage/projectRoot", "")
    try:
        settings.setValue("storage/projectRoot", "")
        assert default_project_root() == recommended_project_root()
        settings.setValue("storage/projectRoot", str(recommended_project_root()))
        assert default_project_root() == recommended_project_root()
    finally:
        settings.setValue("storage/projectRoot", original)
