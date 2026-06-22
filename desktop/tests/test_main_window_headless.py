"""Full headless MainWindow construction: panel switching, resize without
right-panel horizontal scroll, autosave round trip, new-project reset, and the
export report PHI flag block."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QMimeData, QSettings, QUrl
from PySide6.QtWidgets import QApplication

from neuroedit_desktop.models import ProjectState, VideoClip, new_id
from neuroedit_desktop.project_store import ProjectStore
from neuroedit_desktop.sam_backend import SamBackend, SamBackendInfo
from neuroedit_desktop.ui import styles as ui_styles
from neuroedit_desktop.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


@pytest.fixture()
def window(app, tmp_path, monkeypatch):
    """A real MainWindow whose autosave root is redirected to tmp_path so tests
    never touch the user's project storage. SamBackend.probe is stubbed: the
    real probe imports torch on a worker thread (minutes-cold on an iCloud
    venv), which both stalls the suite and leaves a live QThread at teardown."""
    monkeypatch.setattr(
        SamBackend,
        "probe",
        lambda self: SamBackendInfo("missing", "none", "stubbed for tests"),
    )
    settings = QSettings("NeuroEdit", "Desktop")
    original_root = settings.value("storage/projectRoot", "")
    original_prompt = settings.value("storage/promptShown", False, type=bool)
    original_tutorial = settings.value("tutorial/seen", False, type=bool)
    original_theme = settings.value(ui_styles.THEME_SETTING_KEY, "")
    settings.setValue("storage/projectRoot", str(tmp_path / "Autosave"))
    # First-run prompts are modal; they must never fire inside a test run.
    settings.setValue("storage/promptShown", True)
    settings.setValue("tutorial/seen", True)
    settings.setValue(ui_styles.THEME_SETTING_KEY, "light")
    ui_styles.apply_app_style(app, "light")
    win = MainWindow()
    try:
        yield win
    finally:
        # Let the (stubbed, fast) SAM probe thread finish before the window
        # dies or Qt aborts: "QThread: Destroyed while thread is still running".
        QApplication.processEvents()
        probe_thread = getattr(win, "_sam_probe_thread", None)
        if probe_thread is not None:
            probe_thread.quit()
            probe_thread.wait(5_000)
        win.close()
        settings.setValue("storage/projectRoot", original_root)
        settings.setValue("storage/promptShown", original_prompt)
        settings.setValue("tutorial/seen", original_tutorial)
        if original_theme:
            settings.setValue(ui_styles.THEME_SETTING_KEY, original_theme)
        else:
            settings.remove(ui_styles.THEME_SETTING_KEY)


def test_construct_and_switch_all_panels(window, app):
    for panel in ("sam", "labels", "tips", "slides", "audio"):
        window._set_panel(panel)
        app.processEvents()
        assert window.project.active_panel == panel


class _DropEvent:
    def __init__(self, mime_data: QMimeData) -> None:
        self._mime_data = mime_data
        self.accepted = False

    def mimeData(self) -> QMimeData:
        return self._mime_data

    def acceptProposedAction(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.accepted = False


def test_drop_imports_supported_local_media(window, tmp_path, monkeypatch):
    video = tmp_path / "recording.mov"
    image = tmp_path / "still.png"
    unsupported = tmp_path / "notes.txt"
    for path in (video, image, unsupported):
        path.touch()
    mime_data = QMimeData()
    mime_data.setUrls([QUrl.fromLocalFile(str(path)) for path in (video, image, unsupported)])
    event = _DropEvent(mime_data)
    imported: list[str] = []
    monkeypatch.setattr(window, "_import_media_file", imported.append)

    window.dropEvent(event)

    assert window.acceptDrops() is True
    assert event.accepted is True
    assert imported == [str(video), str(image)]


def test_appearance_action_persists_and_reapplies_theme(window, app):
    settings = QSettings("NeuroEdit", "Desktop")

    window.theme_actions["dark"].trigger()
    app.processEvents()

    assert settings.value(ui_styles.THEME_SETTING_KEY) == "dark"
    assert window.theme_actions["dark"].isChecked()
    assert ui_styles.resolve_theme_mode("dark") == "dark"
    assert ui_styles.VIDEO_CANVAS == "#000000"

    window.theme_actions["light"].trigger()
    app.processEvents()

    assert settings.value(ui_styles.THEME_SETTING_KEY) == "light"
    assert window.theme_actions["light"].isChecked()
    assert ui_styles.VIDEO_CANVAS == "#11100e"


@pytest.mark.parametrize("size", [(1085, 600), (1280, 720), (1920, 1080)])
def test_right_panel_never_scrolls_horizontally(window, app, size):
    width, height = size
    window.resize(width, height)
    window.show()
    app.processEvents()
    for panel in ("sam", "labels", "tips", "slides", "audio"):
        window._set_panel(panel)
        app.processEvents()
        assert window.panel_scroll.horizontalScrollBar().maximum() == 0, (
            f"{panel} panel scrolls horizontally at {width}x{height}"
        )


def test_deleting_clip_under_playhead_clears_preview(window):
    """Deleting the clip under the playhead must blank the preview to black —
    the deleted clip's last frame can't be left frozen on screen."""
    from PySide6.QtCore import QUrl

    clip = VideoClip(id=new_id(), path="/tmp/x.mp4", name="X", duration=5.0,
                     start_time=0.0, trim_start=0.0, trim_end=5.0)
    window.project.clips.append(clip)
    window.project.active_clip_id = clip.id
    window.project.current_time = 1.0
    # Simulate a loaded, visible video frame.
    window.video_view.video_item.setVisible(True)
    window.player.setSource(QUrl.fromLocalFile("/tmp/x.mp4"))

    # Delete it through the real timeline path (canvas → project_changed).
    window.timeline.canvas.selected_item = ("clip", clip.id)
    window.timeline.canvas._delete_selected_item()

    assert window.project.clips == []
    assert window.video_view.video_item.isVisible() is False
    assert window.player.source().isEmpty()


def test_sync_shows_black_when_no_clip_under_playhead(window):
    from PySide6.QtCore import QUrl

    window.project.clips.clear()
    window.project.current_time = 2.0
    window.video_view.video_item.setVisible(True)
    window.player.setSource(QUrl.fromLocalFile("/tmp/gone.mp4"))

    window._sync_player_to_timeline(play=False)

    assert window.video_view.video_item.isVisible() is False
    assert window.player.source().isEmpty()


def test_position_changed_ignored_when_source_cleared(window):
    """Regression: after a clip plays into a still/gap, _sync_player_to_timeline
    clears the source and QMediaPlayer emits positionChanged(0). That stale
    event must NOT snap current_time back to the active clip's start (which
    looped playback on the first clip instead of advancing to the still)."""
    clip = VideoClip(id=new_id(), path="/tmp/x.mp4", name="X", duration=10.0,
                     start_time=0.0, trim_start=0.0, trim_end=2.5)
    window.project.clips.append(clip)
    window.project.active_clip_id = clip.id
    window.project.current_time = 3.0  # advanced past the clip, into the gap

    # Source is empty (cleared on entering the gap); a spurious 0 arrives.
    assert window.player.source().isEmpty()
    window._position_changed(0)

    assert window.project.current_time == 3.0


def test_position_changed_ignored_while_seek_pending(window):
    """Regression: crossing into a trimmed next clip mid-playback,
    _sync_player_to_timeline stashes _pending_seek_ms and defers the seek until
    the media loads. Until then QMediaPlayer plays from 0, whose position maps
    to (start_time - trim_start) — back inside the preceding still. While a seek
    is pending those events must be ignored so the playhead doesn't bounce."""
    from PySide6.QtCore import QUrl

    clip = VideoClip(id=new_id(), path="/tmp/x.mp4", name="after still",
                     duration=120.0, start_time=6.865, trim_start=1.865, trim_end=114.0)
    window.project.clips.append(clip)
    window.project.active_clip_id = clip.id
    window.project.current_time = 6.9
    window.player.setSource(QUrl.fromLocalFile("/tmp/x.mp4"))  # non-empty
    window._pending_seek_ms = 1887  # seek to trim_start not applied yet

    window._position_changed(0)  # would map to 6.865 - 1.865 = 5.0
    assert window.project.current_time == 6.9


def test_media_status_applies_pending_seek_only_when_loaded(window):
    """The deferred seek is applied once — and only once — the media reports
    loaded; earlier statuses (LoadingMedia, etc.) leave it pending."""
    from PySide6.QtMultimedia import QMediaPlayer

    window._pending_seek_ms = 1887
    window._pending_play = False

    window._media_status_changed(QMediaPlayer.MediaStatus.LoadingMedia)
    assert window._pending_seek_ms == 1887  # not yet

    window._media_status_changed(QMediaPlayer.MediaStatus.LoadedMedia)
    assert window._pending_seek_ms is None  # applied + cleared


def test_autosave_restore_round_trip(tmp_path):
    store = ProjectStore.create(tmp_path / "proj")
    project = ProjectState(project_name="Round Trip")
    project.clips.append(
        VideoClip(id=new_id(), path="/tmp/a.mp4", name="A", duration=4.0,
                  start_time=0.0, trim_start=0.0, trim_end=4.0)
    )
    project.captions_enabled = True
    store.save(project)
    assert store.project_path.exists()
    _store2, restored = ProjectStore.open(store.project_path)
    assert restored.project_name == "Round Trip"
    assert len(restored.clips) == 1
    assert restored.captions_enabled is True


def test_new_project_resets_state(window, app):
    window.project.project_name = "Old Case"
    window.project.clips.append(
        VideoClip(id=new_id(), path="/tmp/a.mp4", name="A", duration=4.0,
                  start_time=0.0, trim_start=0.0, trim_end=4.0)
    )
    window.dirty = False  # skip the save prompt
    window._new_project()
    assert window.project.project_name == "Untitled Case"
    assert window.project.clips == []
    assert window.store.project_path.name == "project.json"


def test_export_report_contains_phi_flag_block(window, tmp_path):
    project = ProjectState(project_name="Report Case")
    project.consent_confirmed = True
    project.deidentified_confirmed = True
    project.phi_review_confirmed = True
    project.audio_reviewed_for_phi = True
    window._export_report_project = project
    output = tmp_path / "out.mp4"
    report_path = window._write_export_report(output, ["note one"])
    assert report_path == tmp_path / "out.export-report.txt"
    text = report_path.read_text(encoding="utf-8")
    assert "Consent/authorization confirmed: True" in text
    assert "De-identified: True" in text
    assert "PHI review completed: True" in text
    assert "Audio reviewed for spoken PHI: True" in text
    assert "- note one" in text


def test_single_frame_segmentation_stamps_sam_last_run(window):
    import time as _time

    class FakeResult:
        mask_path = "/tmp/mask.png"
        score = 0.9
        backend = "SAM3"

    window._sam_run_started_iso = "2026-06-11T00:00:00"
    window._sam_run_start_monotonic = _time.monotonic()
    window._on_segment_finished(FakeResult(), None)

    record = window.project.sam_last_run
    assert record["result"] == "success"
    assert record["frames"] == 1
    assert record["backend"] == "SAM3"


def test_export_settings_defaults_have_no_audio(tmp_path):
    from neuroedit_desktop.exporter import ExportSettings, ProjectExporter

    settings = ExportSettings(
        output_path=tmp_path / "o.mp4", width=1280, height=720,
        fps=30, crf=20, label="defaults",
    )
    exporter = ProjectExporter(ProjectState(), settings)
    # An empty project (and any project without readable audio) yields no
    # audio sources, so the muxer is skipped and the MP4 has no audio stream.
    assert exporter._audio_sources("ffmpeg") == []
