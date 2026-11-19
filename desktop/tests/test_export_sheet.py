"""The one export sheet and the non-modal background export around it."""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMenu, QMessageBox, QProgressDialog

from neuroedit_desktop import export_plan
from neuroedit_desktop.exporter import ExportCancelled, ProjectExporter
from neuroedit_desktop.export_plan import estimate_output_bytes
from neuroedit_desktop.models import (
    ProjectState,
    TranscriptSegment,
    VideoClip,
    new_id,
)
from neuroedit_desktop.project_copy import format_bytes
from neuroedit_desktop.ui.dialogs import ExportDialog
from test_main_window_headless import app, window  # noqa: F401

REPLACES = "Replaces the existing file"


@pytest.fixture(autouse=True)
def _clean_export_settings():
    def clear():
        settings = QSettings("NeuroEdit", "Desktop")
        settings.remove("export/lastFolder")
        settings.remove("export/pixelRate")

    clear()
    yield
    clear()


def _project(*, duration: float = 600.0, text: str | None = None, name: str = "Case 12") -> ProjectState:
    project = ProjectState(project_name=name)
    project.clips.append(
        VideoClip(id=new_id(), path="/tmp/not-there.mp4", name="A", duration=duration,
                  start_time=0.0, trim_start=0.0, trim_end=duration, width=1920, height=1080)
    )
    project.duration = duration
    if text is not None:
        project.transcript_segments.append(
            TranscriptSegment(id=new_id(), audio_track_id=None, start_time=1.0,
                              end_time=3.0, text=text)
        )
    return project


def _confirm(project: ProjectState) -> ProjectState:
    project.phi_review_confirmed = True
    project.deidentified_confirmed = True
    project.consent_confirmed = True
    return project


def _folder(tmp_path: Path, name: str = "out") -> Path:
    folder = tmp_path / name
    folder.mkdir(exist_ok=True)
    QSettings("NeuroEdit", "Desktop").setValue("export/lastFolder", str(folder))
    return folder


def _tick(dialog: ExportDialog) -> None:
    dialog.phi_check.setChecked(True)
    dialog.deid_check.setChecked(True)
    dialog.consent_check.setChecked(True)


# ── the sheet ────────────────────────────────────────────────────────────────

def test_export_disabled_until_required_checks(app, tmp_path):  # noqa: F811
    _folder(tmp_path)
    dialog = ExportDialog(_project())
    assert dialog.phi_check.isVisibleTo(dialog)
    assert not dialog.export_button.isEnabled()
    dialog.phi_check.setChecked(True)
    dialog.deid_check.setChecked(True)
    assert not dialog.export_button.isEnabled()
    dialog.consent_check.setChecked(True)
    assert dialog.export_button.isEnabled()
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_accept_is_refused_while_gate_is_open(app, tmp_path):  # noqa: F811
    _folder(tmp_path)
    dialog = ExportDialog(_project())
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted


def test_confirmed_project_shows_one_line_with_review_link(app, tmp_path):  # noqa: F811
    _folder(tmp_path)
    dialog = ExportDialog(_confirm(_project()))
    assert dialog.privacy_summary.isVisibleTo(dialog)
    assert dialog.summary_label.text() == "✓ PHI review, de-identification and consent confirmed"
    assert not dialog.phi_check.isVisibleTo(dialog)
    assert dialog.export_button.isEnabled()
    dialog.review_btn.click()
    assert dialog.phi_check.isVisibleTo(dialog)
    assert not dialog.privacy_summary.isVisibleTo(dialog)


def test_caption_check_required_only_when_burning_transcript_text(app, tmp_path):  # noqa: F811
    _folder(tmp_path)
    dialog = ExportDialog(_confirm(_project(text="Patient John Smith, 4 May")))
    assert dialog.export_button.isEnabled()
    assert not dialog.burn_captions_check.isChecked()
    dialog.burn_captions_check.setChecked(True)
    # The collapsed line opens: an unchecked required item is never hidden.
    assert dialog.caption_check.isVisibleTo(dialog)
    assert not dialog.export_button.isEnabled()
    dialog.caption_check.setChecked(True)
    assert dialog.export_button.isEnabled()
    dialog.burn_captions_check.setChecked(False)
    assert not dialog.caption_check.isVisibleTo(dialog)

    blank = ExportDialog(_confirm(_project(text="   ")))
    blank.burn_captions_check.setChecked(True)
    assert not blank.caption_check.isVisibleTo(blank)
    assert blank.export_button.isEnabled()


def test_audio_review_is_a_note_not_a_gate(app, tmp_path):  # noqa: F811
    _folder(tmp_path)
    project = _confirm(_project())
    dialog = ExportDialog(project)
    assert not dialog.audio_group.isVisibleTo(dialog)  # original audio removed, no narration
    dialog.mute_source_audio_check.setChecked(False)
    assert dialog.audio_group.isVisibleTo(dialog)
    assert "Original operating-room clip audio is being kept" in dialog.audio_warning.text()
    assert dialog.export_button.isEnabled()  # unreviewed audio never blocks


def test_estimate_follows_preset_and_audio(app, tmp_path):  # noqa: F811
    _folder(tmp_path)
    dialog = ExportDialog(_project(duration=600.0))
    where = "this Mac" if sys.platform == "darwin" else "this computer"
    size_1080 = format_bytes(estimate_output_bytes(1920, 1080, 600.0, audio_kbps=None))
    assert dialog.estimate_label.text() == f"About {size_1080} · about 2 min on {where}"
    dialog.preset_buttons["720p"].setChecked(True)
    size_720 = format_bytes(estimate_output_bytes(1280, 720, 600.0, audio_kbps=None))
    assert dialog.estimate_label.text().startswith(f"About {size_720} ·")
    assert size_720 != size_1080
    dialog.mute_source_audio_check.setChecked(False)  # now the export carries audio
    with_audio = format_bytes(estimate_output_bytes(1280, 720, 600.0, audio_kbps=192))
    assert dialog.estimate_label.text().startswith(f"About {with_audio} ·")


def test_estimate_uses_learned_pixel_rate(app, tmp_path):  # noqa: F811
    _folder(tmp_path)
    QSettings("NeuroEdit", "Desktop").setValue("export/pixelRate", 38_000_000.0)  # 10x slower
    dialog = ExportDialog(_project(duration=600.0))
    assert "about 16 min" in dialog.estimate_label.text()


def test_automatic_frame_rate_label_and_choice(app, tmp_path, monkeypatch):  # noqa: F811
    _folder(tmp_path)
    dialog = ExportDialog(_project(), fps_probe=lambda _path: 25.0)
    assert dialog.fps_combo.itemText(0) == "Automatic (matches your video: 25 fps)"
    assert dialog.export_settings().fps == 25
    dialog.fps_combo.setCurrentIndex(dialog.fps_combo.findData(24))
    assert dialog.export_settings().fps == 24
    assert [dialog.fps_combo.itemData(i) for i in range(1, 6)] == [24, 25, 30, 50, 60]

    monkeypatch.setattr(export_plan, "source_fps", lambda _path: 59.94)
    assert ExportDialog(_project()).fps_combo.itemText(0).endswith("60 fps)")
    assert not hasattr(dialog, "crf_spin") and not hasattr(dialog, "width_spin")


def test_remembered_folder_and_fallback(app, tmp_path, monkeypatch):  # noqa: F811
    folder = _folder(tmp_path, "cases")
    dialog = ExportDialog(_project())
    assert dialog._folder == folder
    assert dialog.folder_label.text() == "cases"

    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(other)))
    dialog.folder_button.click()
    assert dialog.folder_label.text() == "elsewhere"
    assert dialog.output_path() == other / "Case 12.mp4"
    dialog.remember_folder()
    assert QSettings("NeuroEdit", "Desktop").value("export/lastFolder") == str(other)
    assert ExportDialog(_project())._folder == other

    other.rmdir()  # the remembered folder disappears
    assert ExportDialog(_project())._folder in (Path.home() / "Movies", Path.home())


def test_default_name_never_collides_and_typed_collision_is_noted(app, tmp_path):  # noqa: F811
    folder = _folder(tmp_path)
    (folder / "Case 12.mp4").write_bytes(b"x")
    dialog = ExportDialog(_confirm(_project()))
    assert dialog.name_edit.text() == "Case 12 2"
    assert not dialog.replace_note.isVisibleTo(dialog)
    dialog.name_edit.setText("Case 12")
    assert dialog.replace_note.isVisibleTo(dialog)
    assert dialog.replace_note.text() == REPLACES
    assert dialog.export_button.isEnabled()  # a note, not a block
    dialog.name_edit.setText("   ")
    assert not dialog.export_button.isEnabled()


def test_suggestions_are_quiet_and_exclude_gate_items(app, tmp_path):  # noqa: F811
    _folder(tmp_path)
    dialog = ExportDialog(_project())
    assert dialog.suggestions_toggle.isVisibleTo(dialog)
    assert "suggestion" in dialog.suggestions_toggle.text()
    assert not dialog.suggestions_label.isVisibleTo(dialog)
    dialog.suggestions_toggle.click()
    assert dialog.suggestions_label.isVisibleTo(dialog)
    text = dialog.suggestions_label.text()
    for covered in ("consent", "Complete a PHI review", "Confirm de-identification"):
        assert covered not in text
    assert "learning objective" in text


def test_preferences_round_trip_per_project(app, tmp_path):  # noqa: F811
    _folder(tmp_path)
    project = _project(text="hello")
    dialog = ExportDialog(project)
    assert dialog.selected_preset().key == "1080p"
    dialog.preset_buttons["720p"].setChecked(True)
    dialog.mute_source_audio_check.setChecked(False)
    dialog.burn_captions_check.setChecked(True)
    dialog.fps_combo.setCurrentIndex(dialog.fps_combo.findData(25))
    dialog.save_preferences(project)
    assert project.export_preferences == {
        "quality": "720p", "mute_source_audio": False, "burn_captions": True, "fps": 25,
    }

    reloaded = ProjectState.from_dict(project.to_dict())
    again = ExportDialog(reloaded)
    assert again.selected_preset().key == "720p"
    assert not again.mute_source_audio_check.isChecked()
    assert again.burn_captions_check.isChecked()
    assert again.fps_combo.currentData() == 25

    again.fps_combo.setCurrentIndex(0)
    again.save_preferences(reloaded)
    assert reloaded.export_preferences["fps"] == "auto"


def test_old_project_without_export_preferences_loads():
    data = ProjectState(project_name="Old").to_dict()
    del data["export_preferences"]
    assert ProjectState.from_dict(data).export_preferences == {}


# ── entry points ─────────────────────────────────────────────────────────────

def test_command_e_action_and_button_call_export(window, monkeypatch):  # noqa: F811
    action = window.export_movie_action
    assert action.text() == "Export Movie…"
    assert action.shortcut() == QKeySequence("Ctrl+E")
    assert any(action in menu.actions() for menu in window.menuBar().findChildren(QMenu))
    clashes = [a for a in window.findChildren(QAction) if a.shortcut() == QKeySequence("Ctrl+E")]
    assert clashes == [action]
    assert not [s for s in window.findChildren(QShortcut) if s.key() == QKeySequence("Ctrl+E")]

    calls = []
    monkeypatch.setattr(window, "_export_project", lambda: calls.append("export"))
    action.trigger()
    window.export_btn.click()
    assert calls == ["export", "export"]


# ── background export ────────────────────────────────────────────────────────

class _Run:
    """A stand-in for ProjectExporter.export that the test controls."""

    def __init__(self, monkeypatch):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.canceled = threading.Event()
        self.failures: list[Exception] = []  # raised by the first runs, in order
        self.runs = 0
        self.warnings: list[str] = []
        run = self

        def export(exporter):
            run.runs += 1
            run.entered.set()
            while not run.release.wait(0.005):
                if exporter.cancelled():
                    run.canceled.set()
                    raise ExportCancelled()
            if run.failures:
                raise run.failures.pop(0)
            return run.warnings

        monkeypatch.setattr(ProjectExporter, "export", export)

    def wait_started(self):
        assert self.entered.wait(3.0), "export never started"


def _pump(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    assert condition()


def _finish(win):
    _pump(lambda: win._export_thread is None)


@pytest.fixture()
def ready(window, tmp_path, monkeypatch):  # noqa: F811
    """A window with one reviewed clip whose sheet auto-accepts."""
    monkeypatch.setattr(window, "_sync_player_to_timeline", lambda **_kwargs: None)
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    clip = window.project.add_clip(tmp_path / "a.mov", duration=10, width=100, height=100)
    window.project.active_clip_id = clip.id
    _confirm(window.project)
    window.project.audio_reviewed_for_phi = True
    window.project.project_name = "Case 12"
    window._seed_history()
    window.out_dir = _folder(tmp_path)

    def accepting_exec(self):
        self.accept()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ExportDialog, "exec", accepting_exec)
    alerts = []
    monkeypatch.setattr(QApplication, "alert", staticmethod(lambda w, ms=0: alerts.append(w)))
    window.alerts = alerts
    return window


def test_export_is_not_modal_and_button_shows_progress(ready, monkeypatch):
    run = _Run(monkeypatch)
    ready._export_project()
    run.wait_started()
    assert ready._export_thread is not None
    assert QApplication.activeModalWidget() is None
    assert not ready.findChildren(QProgressDialog)
    assert ready.isEnabled() and ready.export_btn.isEnabled()
    assert ready.export_btn.text().startswith("Exporting")
    assert "qlineargradient" in ready.export_btn.styleSheet()

    # Before 3% there is no time estimate; after, the label counts down.
    ready._export_progress(1, "Starting")
    assert ready.export_btn.text() == "Exporting…"
    ready._export_started_perf = time.perf_counter() - 60
    ready._export_eta_s = None
    ready._export_progress(50, "Rendering")
    assert ready.export_btn.text() == "Exporting 50% · 1 min left"

    # A second request while one runs only says so.
    ready._export_project()
    assert ready.statusBar().currentMessage() == "An export is already running."
    assert run.runs == 1

    run.release.set()
    _finish(ready)
    assert ready.export_btn.text() == "Export"
    assert ready.export_btn.styleSheet() == ""


def test_time_left_wording():
    from neuroedit_desktop.ui.export_workflow import ExportWorkflowMixin as Mixin

    assert Mixin._format_time_left(10) == "less than a minute left"
    assert Mixin._format_time_left(95) == "2 min left"
    assert Mixin._format_time_left(3900) == "1 h 5 min left"


def test_cancel_from_button_menu_reaches_worker(ready, monkeypatch):
    run = _Run(monkeypatch)
    ready._export_project()
    run.wait_started()
    ready.export_btn.click()  # exporting: opens the menu rather than another sheet
    assert [a.text() for a in ready._export_menu.actions()] == ["Cancel Export"]
    ready._export_menu.actions()[0].trigger()
    assert ready.export_btn.text() == "Canceling…"
    assert run.canceled.wait(3.0)
    _finish(ready)
    assert ready.statusBar().currentMessage() == "Export canceled."
    assert getattr(ready, "_export_toast", None) is None


def test_completion_shows_toast_not_a_modal_and_report_stays_with_project(ready, monkeypatch):
    run = _Run(monkeypatch)
    run.warnings = ["Skipped something"]
    revealed = []
    monkeypatch.setattr(ready, "_reveal_path", lambda path: revealed.append(path))
    ready._export_project()
    run.wait_started()
    ready._export_started_perf = time.perf_counter() - 20  # a 20 s export of a 10 s timeline
    run.release.set()
    _finish(ready)

    toast = ready._export_toast
    assert toast is not None and toast.isVisibleTo(ready)
    assert toast.label.text().startswith("Exported “Case 12.mp4”")
    assert QApplication.activeModalWidget() is None
    assert ready.alerts == [ready]  # Dock bounce when the app is in the background
    toast.show_button.click()
    assert revealed == [ready.out_dir / "Case 12.mp4"]

    reports = ready.store.project_path.parent / "Export Reports"
    report = reports / "Case 12.export-report.txt"
    assert report.exists() and "Skipped something" in report.read_text(encoding="utf-8")
    assert not (ready.out_dir / "Case 12.export-report.txt").exists()
    from neuroedit_desktop.ui.dialogs import load_export_history

    assert load_export_history()[0]["report"] == str(report)

    # Measured speed feeds the next estimate: a 10 s timeline (the 100 px source
    # recommends 720p) exported in about 20 s.
    rate = float(QSettings("NeuroEdit", "Desktop").value("export/pixelRate", 0.0, type=float))
    assert rate == pytest.approx(1280 * 720 * 30 * 10 / 20, rel=0.2)
    assert ExportDialog(ready.project)._pixel_rate == pytest.approx(rate)

    toast.dismissed.emit()
    assert ready._export_toast is None


def test_failure_shows_details_and_try_again_restarts(ready, monkeypatch):
    run = _Run(monkeypatch)
    error = RuntimeError("There isn't enough free space to export.")
    error.details = "ffmpeg: No space left on device"
    run.failures = [error]
    shown = []

    def fake_exec(box):
        shown.append({
            "text": box.text(),
            "details": box.detailedText(),
            "icon": box.icon(),
            "buttons": [b.text() for b in box.buttons()],
        })
        box._choice = next(b for b in box.buttons() if b.text() == "Try Again")
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: box._choice)
    settings_seen = []
    original_start = type(ready)._start_export

    def spy(self, settings, snapshot=None):
        settings_seen.append((settings, snapshot))
        return original_start(self, settings, snapshot)

    monkeypatch.setattr(type(ready), "_start_export", spy)
    ready._export_project()
    run.release.set()
    _pump(lambda: len(shown) == 1)
    assert shown[0]["text"] == "There isn't enough free space to export."
    assert shown[0]["details"] == "ffmpeg: No space left on device"
    assert shown[0]["icon"] == QMessageBox.Icon.Critical
    assert "Try Again" in shown[0]["buttons"]

    _pump(lambda: run.runs == 2)  # the retry ran...
    _finish(ready)
    assert settings_seen[1][0] is settings_seen[0][0]  # ...with the same settings
    assert settings_seen[1][1] is not None  # ...on the same reviewed snapshot
    assert ready._export_toast is not None  # and it succeeded


def test_failure_without_details_has_no_details_pane(ready, monkeypatch):
    run = _Run(monkeypatch)
    run.failures = [RuntimeError("Something went wrong.")]
    shown = []

    def fake_exec(box):
        shown.append(box.detailedText())
        box._choice = next(b for b in box.buttons() if b.text() == "Close")
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: box._choice)
    ready._export_project()
    run.release.set()
    _pump(lambda: len(shown) == 1)
    _finish(ready)
    assert shown == [""]
    assert run.runs == 1


def test_sheet_choices_apply_without_an_undo_step(ready, monkeypatch):
    ready.project.audio_reviewed_for_phi = False
    ready.project.consent_confirmed = False
    undo_before = len(ready._undo_stack)
    run = _Run(monkeypatch)

    def choose(self):
        self.consent_check.setChecked(True)
        self.preset_buttons["720p"].setChecked(True)
        self.accept()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ExportDialog, "exec", choose)
    ready._export_project()
    run.wait_started()
    assert ready.project.consent_confirmed
    assert ready.project.export_preferences["quality"] == "720p"
    assert len(ready._undo_stack) == undo_before
    assert ready._export_worker_settings.width == 1280
    assert QSettings("NeuroEdit", "Desktop").value("export/lastFolder") == str(ready.out_dir)
    run.release.set()
    _finish(ready)


def test_guided_review_returns_to_the_sheet_with_choices_kept(ready, monkeypatch):
    ready.project.phi_review_confirmed = False
    run = _Run(monkeypatch)
    sheets = []

    def exec_sheet(self):
        sheets.append(self)
        if len(sheets) == 1:
            self.preset_buttons["4k"].setChecked(True)
            self.guided_btn.click()
            return QDialog.DialogCode.Rejected
        self.accept()
        return QDialog.DialogCode.Accepted

    def guided_review():
        ready.project.phi_review_confirmed = True

    monkeypatch.setattr(ExportDialog, "exec", exec_sheet)
    monkeypatch.setattr(ready, "_start_phi_review", guided_review)
    ready._export_project()
    run.wait_started()
    assert len(sheets) == 2
    assert sheets[1].selected_preset().key == "4k"  # remembered across the review
    run.release.set()
    _finish(ready)
