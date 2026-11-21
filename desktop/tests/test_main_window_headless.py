"""Full headless MainWindow construction: panel switching, resize without
right-panel horizontal scroll, autosave round trip, new-project reset, and the
export report PHI flag block."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QMimeData, QPointF, QSettings, QTimer, QUrl
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtGui import QKeySequence
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from neuroedit_desktop.models import Annotation, ProjectState, VideoClip, new_id
from neuroedit_desktop.project_store import ProjectStore
from neuroedit_desktop.sam_backend import SamBackend, SamBackendInfo
from neuroedit_desktop.ui import styles as ui_styles
from neuroedit_desktop.ui import main_window as main_window_module
from neuroedit_desktop.ui.labels_panel import LabelsPanel
from neuroedit_desktop.ui.main_window import MainWindow
from neuroedit_desktop.ui.tutorial import TutorialOverlay, build_default_steps


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def _forbid_modal_dialogs(monkeypatch):
    """An un-stubbed QMessageBox blocks forever offscreen; fail loudly instead.
    Tests that expect a dialog override these with their own monkeypatch."""
    from PySide6.QtWidgets import QMessageBox

    def make(name):
        def forbidden(*args, **kwargs):
            raise AssertionError(f"un-stubbed QMessageBox.{name} opened in a test")
        return forbidden

    for name in ("question", "information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(make(name)))


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
    # A bound single-shot callback can outlive this fixture and run after its
    # settings are restored, opening an offscreen modal in a later UI test.
    monkeypatch.setattr(MainWindow, "_maybe_show_first_run_tutorial", lambda self: None)
    _forbid_modal_dialogs(monkeypatch)
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
        win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
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


def test_imovie_style_editing_shortcuts_are_wired(window, monkeypatch):
    calls: list[object] = []
    monkeypatch.setattr(window, "_toggle_play", lambda: calls.append("play"))
    monkeypatch.setattr(window, "_step_frame", lambda direction: calls.append(direction))

    portable = QKeySequence.SequenceFormat.PortableText
    assert window.split_clip_action.shortcut().toString(portable) == "Ctrl+B"
    assert {shortcut.key().toString(portable)
            for shortcut in window.editor_shortcuts["play_pause"]} == {"Space"}
    assert {shortcut.key().toString(portable)
            for shortcut in window.editor_shortcuts["previous_frame"]} == {"Left"}
    assert {shortcut.key().toString(portable)
            for shortcut in window.editor_shortcuts["next_frame"]} == {"Right"}
    assert {
        tool: shortcut.key().toString(portable)
        for tool, shortcut in window.tool_shortcuts.items()
    } == {
        "select": "V", "sam": "S", "rect": "R", "ellipse": "E",
        "arrow": "A", "text": "T", "brush": "B", "redact": "X",
    }

    window.editor_shortcuts["play_pause"][0].activated.emit()
    window.editor_shortcuts["previous_frame"][0].activated.emit()
    window.editor_shortcuts["next_frame"][0].activated.emit()

    assert calls == ["play", -1, 1]


def test_tutorial_rectangle_step_waits_for_the_user_click(window):
    window.project.active_tool = "select"
    step = next(
        step for step in build_default_steps(window)
        if step.title == "Choose the Rectangle Tool"
    )

    step.on_enter()

    assert window.project.active_tool == "select"
    step.target_resolver().click()
    assert window.project.active_tool == "rect"


def test_tutorial_includes_freehand_brush_practice(window):
    step = next(
        step for step in build_default_steps(window)
        if step.title == "Add a Freehand Highlight"
    )

    step.on_enter()

    assert window.project.active_tool == "brush"
    assert step.target_resolver() is window.video_view
    assert "click and drag" in step.body.lower()


def test_tutorial_next_button_path_reaches_completion(window, app):
    overlay = TutorialOverlay(window, build_default_steps(window))
    finished: list[bool] = []
    overlay.finished.connect(lambda: finished.append(True))

    for _ in overlay.steps:
        overlay.advance()
        app.processEvents()

    assert finished == [True]
    assert overlay.isHidden()


def test_split_clip_action_keeps_total_duration(window):
    window.project = ProjectState(current_time=4.0)
    window.project.clips.append(
        VideoClip(
            id="clip", path="/tmp/source.mp4", name="Source", duration=8.0,
            start_time=0.0, trim_start=0.0, trim_end=8.0,
        )
    )
    window.timeline.set_project(window.project)

    window.split_clip_action.trigger()

    assert len(window.project.clips) == 2
    assert window.project.duration == pytest.approx(8.0)


def test_take_still_split_keeps_reserved_gap_and_source_bounds(window):
    window.project = ProjectState(current_time=4.0)
    window.project.clips.append(
        VideoClip(
            id="clip", path="/tmp/source.mp4", name="Source", duration=8.0,
            start_time=0.0, trim_start=0.0, trim_end=8.0,
        )
    )

    window._insert_timeline_gap(4.0, 5.0)

    left, right = window.project.clips
    assert left.start_time == pytest.approx(0.0)
    assert left.trim_end == pytest.approx(4.0)
    assert left.source_out_limit == pytest.approx(4.0)
    assert right.start_time == pytest.approx(9.0)
    assert right.trim_start == pytest.approx(4.0)
    assert right.source_in_limit == pytest.approx(4.0)


def test_take_still_starts_without_centered_title(window, tmp_path, monkeypatch):
    still_path = tmp_path / "still.png"
    monkeypatch.setattr(window, "_render_current_still", lambda _time: still_path)
    window.project = ProjectState(current_time=0.0)
    window.timeline.set_project(window.project)

    window._take_still()

    assert window.project.slides[-1].title == ""


def test_timeline_annotation_activation_selects_its_label(window):
    window.project.clips.append(
        VideoClip(
            id="clip", path="/tmp/source.mp4", name="Source", duration=8.0,
            trim_end=8.0,
        )
    )
    annotation = Annotation(
        id="label-1", frame_time=2.0, ann_duration=3.0, type="rect",
        label="Optic nerve", color="#00e5ff",
    )
    window.project.annotations.append(annotation)

    window._timeline_item_activated("annotation", annotation.id)

    assert window.project.active_panel == "labels"
    assert window.project.selected_annotation_id == annotation.id
    assert window.project.current_time == pytest.approx(annotation.frame_time)


def test_project_dirty_clamps_playhead_to_new_total(window, monkeypatch):
    window.project = ProjectState(current_time=9.0)
    window.project.clips.append(
        VideoClip(
            id="clip", path="/tmp/source.mp4", name="Source", duration=10.0,
            start_time=0.0, trim_start=0.0, trim_end=5.0,
        )
    )
    window.timeline.set_project(window.project)
    monkeypatch.setattr(window, "_sync_player_to_timeline", lambda **kwargs: None)

    window._mark_project_dirty()

    assert window.project.current_time == pytest.approx(5.0)


def test_labels_panel_is_reexported_from_main_window():
    assert main_window_module.LabelsPanel is LabelsPanel


def test_wordmark_registers_bundled_brand_font(app):
    font = main_window_module._wordmark_font(15)

    assert font.family() == "Space Grotesk"


class _DropEvent:
    def __init__(self, mime_data: QMimeData) -> None:
        self._mime_data = mime_data
        self.accepted = False

    def mimeData(self) -> QMimeData:
        return self._mime_data

    def position(self) -> QPointF:
        return QPointF(0, 0)  # top-left corner of the window, not the timeline

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
    imported: list[list[Path]] = []
    monkeypatch.setattr(window, "_import_media_files", imported.append)

    window.dropEvent(event)

    assert window.acceptDrops() is True
    assert event.accepted is True
    assert imported == [[video, image]]


def test_multi_file_import_loads_preview_and_marks_dirty_once(window, tmp_path, monkeypatch):
    video = tmp_path / "recording.mov"
    image = tmp_path / "still.png"
    loaded: list[str] = []
    history_before = len(window._undo_stack)
    image_data = QImage(10, 10, QImage.Format.Format_RGB32)
    assert image_data.save(str(image))
    monkeypatch.setattr(main_window_module, "probe_video", lambda path: (1.0, 1920, 1080))
    monkeypatch.setattr(window, "_load_active_clip", lambda: loaded.append("preview"))

    window._import_media_files([video, image])
    _wait_for_import(window)

    assert [Path(clip.path) for clip in window.project.clips[-2:]] == [video, image]
    assert window.project.active_clip_id == window.project.clips[-2].id
    assert loaded == ["preview"]
    assert len(window._undo_stack) == history_before + 1


def test_import_video_delegates_to_batch_import(window, tmp_path, monkeypatch):
    paths = [tmp_path / "first.mov", tmp_path / "second.mp4"]
    imported: list[list[Path]] = []

    def fake_get_open_file_names(_parent, title, *_args, **_kwargs):
        assert title == "Add Video Files (Keep in Place)"
        return [str(path) for path in paths], ""

    monkeypatch.setattr(
        main_window_module.QFileDialog,
        "getOpenFileNames",
        fake_get_open_file_names,
    )
    monkeypatch.setattr(window, "_import_media_files", imported.append)

    window._import_video()

    assert imported == [paths]


def test_media_explorer_buttons_advertise_reference_import(window):
    button_texts = {
        button.text()
        for button in window.media_panel.findChildren(QPushButton)
    }

    assert "Add Video Files…" in button_texts
    assert "Link Video Folder…" in button_texts


def test_media_import_buttons_fit_at_minimum_and_wide_sizes(window, app):
    buttons = [button for button in window.media_panel.findChildren(QPushButton)
               if button.text() in {"Add Video Files…", "Link Video Folder…"}]
    assert len(buttons) == 2
    for width, height in ((window.minimumWidth(), window.minimumHeight()), (1440, 900)):
        window.resize(width, height)
        window.show()
        app.processEvents()
        for button in buttons:
            window.media_scroll.ensureWidgetVisible(button)
            app.processEvents()
            viewport = window.media_scroll.viewport()
            assert viewport.rect().contains(button.mapTo(viewport, button.rect().center()))
            assert button.width() >= button.sizeHint().width()


def test_link_video_folder_keeps_external_paths_across_save(
    window, tmp_path, monkeypatch
):
    media_folder = tmp_path / "External SSD" / "Case Videos"
    media_folder.mkdir(parents=True)
    first = media_folder / "A recording.mov"
    second = media_folder / "b recording.mp4"
    ignored_image = media_folder / "still.jpg"
    nested = media_folder / "Archive" / "nested.mov"
    nested.parent.mkdir()
    for path in (first, second, ignored_image, nested):
        path.touch()
    monkeypatch.setattr(
        main_window_module.QFileDialog,
        "getExistingDirectory",
        lambda _parent, title, *_args, **_kwargs: (
            str(media_folder)
            if title == "Link Video Folder (Keep Files in Place)"
            else ""
        ),
    )
    monkeypatch.setattr(main_window_module, "probe_video", lambda path: (1.0, 1920, 1080))
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)

    window._link_video_folder()
    _wait_for_import(window)
    window.store.save(window.project)
    _store, reopened = ProjectStore.open(window.store.project_path)

    assert [Path(clip.path) for clip in reopened.clips] == [first, second]
    assert window.media_panel.path_label.text() == str(media_folder)
    assert not list(window.store.project_path.parent.glob("*.mov"))
    assert not list(window.store.project_path.parent.glob("*.mp4"))


def test_import_image_delegates_to_batch_import(window, tmp_path, monkeypatch):
    paths = [tmp_path / "first.png", tmp_path / "second.jpg"]
    imported: list[list[Path]] = []
    monkeypatch.setattr(
        main_window_module.QFileDialog,
        "getOpenFileNames",
        lambda *_args, **_kwargs: ([str(path) for path in paths], ""),
    )
    monkeypatch.setattr(window, "_import_media_files", imported.append)

    window._import_image()

    assert imported == [paths]


def _wait_for_import(window):
    for _ in range(500):
        QApplication.processEvents()
        if getattr(window, "_import_thread", None) is None:
            return
        QTest.qWait(10)
    pytest.fail("Import did not finish")


def test_import_probe_does_not_block_and_stale_results_are_discarded(window, tmp_path, monkeypatch):
    import time
    video = tmp_path / "recording.mov"
    def slow_probe(_path):
        time.sleep(0.2)
        return (1.0, 1920, 1080)
    monkeypatch.setattr(main_window_module, "probe_video", slow_probe)
    ticks = []
    timer = QTimer(window)
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    window._import_media_files([video])
    QTest.qWait(30)
    timer.stop()
    assert ticks
    assert window._import_thread is not None
    window.project.project_name = "Changed while importing"
    _wait_for_import(window)
    assert not window.project.clips


def test_appearance_action_persists_and_reapplies_theme(window, app):
    settings = QSettings("NeuroEdit", "Desktop")

    window.theme_actions["dark"].trigger()
    app.processEvents()

    assert settings.value(ui_styles.THEME_SETTING_KEY) == "dark"
    assert window.theme_actions["dark"].isChecked()
    assert ui_styles.resolve_theme_mode("dark") == "dark"
    assert ui_styles.VIDEO_CANVAS == ui_styles.DARK_THEME.video_canvas

    window.theme_actions["light"].trigger()
    app.processEvents()

    assert settings.value(ui_styles.THEME_SETTING_KEY) == "light"
    assert window.theme_actions["light"].isChecked()
    assert ui_styles.VIDEO_CANVAS == ui_styles.LIGHT_THEME.video_canvas


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


@pytest.mark.parametrize(
    "status",
    (QMediaPlayer.MediaStatus.NoMedia, QMediaPlayer.MediaStatus.InvalidMedia),
)
def test_terminal_media_status_clears_pending_seek(window, status):
    """A source that cannot load must release the timeline playback clock."""
    window._pending_seek_ms = 1887
    window._pending_play = True

    window._media_status_changed(status)

    assert window._pending_seek_ms is None
    assert window._pending_play is False


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


def test_new_project_resets_state(window, app, monkeypatch):
    window.project.project_name = "Old Case"
    window.project.clips.append(
        VideoClip(id=new_id(), path="/tmp/a.mp4", name="A", duration=4.0,
                  start_time=0.0, trim_start=0.0, trim_end=4.0)
    )
    window.dirty = False  # skip the save prompt
    # A non-empty case that only exists in the autosave folder must be asked
    # about (NE-018); this test exercises the Discard path.
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Discard
    )
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
    # Beside the project, never beside the MP4 that people share.
    assert report_path == window.store.project_path.parent / "Export Reports" / "out.export-report.txt"
    assert not (tmp_path / "out.export-report.txt").exists()
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


@pytest.mark.parametrize('trim_start, speed, position, expected_seek', [
    (5, 1.0, 5010, []), (20, 1.0, 5000, [20010]), (20, 2.0, 5000, [20020]),
])
def test_same_source_cut_does_not_reload_player(window, monkeypatch, trim_start, speed, position, expected_seek):
    window.project.clips = [
        VideoClip(id='a', path='/tmp/source.mp4', name='Source', duration=30,
                  start_time=0, trim_start=0, trim_end=5),
        VideoClip(id='b', path='/tmp/source.mp4', name='Source', duration=30,
                  start_time=5, trim_start=trim_start, trim_end=trim_start + 5, speed=speed),
    ]
    window.project.active_clip_id = 'a'
    window.project.current_time = 5.01
    window.project.playback_rate = 1.5
    monkeypatch.setattr(window, '_cached_clip_media_problem', lambda c: None)
    monkeypatch.setattr(window.player, 'source', lambda: QUrl.fromLocalFile('/tmp/source.mp4'))
    monkeypatch.setattr(window.player, 'position', lambda: position)
    loads, seeks = [], []
    monkeypatch.setattr(window.player, 'setSource', loads.append)
    monkeypatch.setattr(window.player, 'setPosition', seeks.append)
    monkeypatch.setattr(window.player, 'play', lambda: None)
    window._sync_player_to_timeline(play=True)
    assert loads == []
    assert seeks == expected_seek
    assert window.player.playbackRate() == pytest.approx(speed * window.project.playback_rate)
    assert window.project.active_clip_id == 'b'
    assert window._pending_seek_ms is None


def test_small_user_seek_reaches_the_exact_source_time(window, monkeypatch):
    window.project.clips = [
        VideoClip(id="trimmed", path="/tmp/source.mp4", name="Source", duration=30,
                  start_time=0, trim_start=5, trim_end=10),
    ]
    window.project.active_clip_id = "trimmed"
    window.project.current_time = 1.0
    seeks = []
    monkeypatch.setattr(window, "_cached_clip_media_problem", lambda _clip: None)
    monkeypatch.setattr(window.player, "source", lambda: QUrl.fromLocalFile("/tmp/source.mp4"))
    monkeypatch.setattr(window.player, "position", lambda: 6000)
    monkeypatch.setattr(window.player, "setPosition", seeks.append)

    window._step_frame(1)

    assert seeks == [6033]
    assert window.project.current_time == pytest.approx(1.0 + 1 / 30)


def test_retimed_viewer_protects_decoded_frame_before_redaction_boundary(window):
    from PySide6.QtCore import QSizeF
    from PySide6.QtGui import QColor, QPainter
    from PySide6.QtMultimedia import QVideoFrame

    window.project.clips = [VideoClip(id="slow", path="source.mp4", name="Slow",
                                      trim_end=2, speed=0.5)]
    window.project.active_clip_id = "slow"
    window.project.current_time = 1.99
    window.project.annotations = [Annotation(
        id="redact", type="redact", label="", color="#000000", frame_time=2, ann_duration=1,
        geometry={"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5},
    )]
    view = window.video_view
    view.set_project(window.project)
    view.annotation_item.set_size(QSizeF(64, 36))
    image = QImage(64, 36, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    frame = QVideoFrame(image)
    frame.setStartTime(1_000_000)
    view.video_item.videoSink().setVideoFrame(frame)

    painter = QPainter(image)
    view.annotation_item._paint_impl(painter)
    painter.end()

    assert image.pixelColor(32, 18) == QColor("black")
    assert image.pixelColor(4, 4) == QColor("white")


def test_video_transition_holds_frame_until_target_and_clears_in_gap(window):
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtMultimedia import QVideoFrame
    view = window.video_view
    image = QImage(64, 36, QImage.Format.Format_RGB32)
    image.fill(QColor('red'))
    frame = QVideoFrame(image)
    frame.setStartTime(0)
    frame.setEndTime(33333)
    view.video_item.videoSink().setVideoFrame(frame)
    view.begin_video_transition(2000)
    view.video_item.videoSink().setVideoFrame(QVideoFrame())
    assert view.transition_item.isVisible()
    assert view.transition_item.pixmap().toImage().pixelColor(1, 1) == QColor('red')
    view.finish_transition_seek()
    view.video_item.videoSink().setVideoFrame(frame)  # source's unwanted first frame
    assert view.transition_item.isVisible()
    frame = QVideoFrame(image)
    frame.setStartTime(2000000)
    frame.setEndTime(2033333)
    view.video_item.videoSink().setVideoFrame(frame)
    assert not view.transition_item.isVisible()
    view.begin_video_transition(0)
    view.show_black()
    assert not view.transition_item.isVisible()


def test_different_source_transition_seeks_even_if_load_is_synchronous(window, monkeypatch):
    clip = VideoClip(id='new', path='/tmp/new.mp4', name='New', duration=10,
                     start_time=0, trim_start=2, trim_end=10)
    window.project.clips = [clip]
    window.project.current_time = 0.5
    window._timeline_playing = True
    monkeypatch.setattr(window, '_cached_clip_media_problem', lambda c: None)
    seeks, plays = [], []
    monkeypatch.setattr(window.player, 'setPosition', seeks.append)
    monkeypatch.setattr(window.player, 'play', lambda: plays.append(True))
    monkeypatch.setattr(window.player, 'setSource', lambda source:
                        window._media_status_changed(QMediaPlayer.MediaStatus.LoadedMedia))
    monkeypatch.setattr(window.player, 'mediaStatus', lambda: QMediaPlayer.MediaStatus.LoadedMedia)
    window._sync_player_to_timeline(play=True)
    assert seeks == [2500]
    assert plays == [True]
    assert window._pending_seek_ms is None


def test_real_video_cuts_do_not_render_black_between_sources(window, tmp_path):
    import subprocess
    import time

    from PySide6.QtTest import QTest

    from neuroedit_desktop.exporter import resolve_ffmpeg

    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        pytest.skip('Real decoder smoke test requires ffmpeg')
    paths = [tmp_path / 'red.mp4', tmp_path / 'blue.mp4']
    for path, color in zip(paths, ['red', 'blue']):
        subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
                        f'color=c={color}:s=160x90:r=30:d=1', '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', str(path)], check=True, timeout=20)
    window.project.clips = [
        VideoClip(id='a', path=str(paths[0]), name='Red', duration=1,
                  start_time=0, trim_start=0, trim_end=0.5),
        VideoClip(id='b', path=str(paths[0]), name='Red', duration=1,
                  start_time=0.5, trim_start=0.5, trim_end=1),
        VideoClip(id='c', path=str(paths[1]), name='Blue', duration=1,
                  start_time=1, trim_start=0.2, trim_end=1),
    ]
    window._invalidate_project_end_time()
    window.project.current_time = 0
    window.video_view.set_image(None)
    window.video_view.set_project(window.project)
    window._toggle_play()
    samples = []
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and window._timeline_playing:
        QTest.qWait(10)
        image = window.video_view.viewport().grab().toImage()
        color = image.pixelColor(image.width() // 2, image.height() // 2)
        samples.append((color.red(), color.green(), color.blue()))
    assert not window._timeline_playing, 'Playback stalled at a cut'
    first_red = next(i for i, (r, g, b) in enumerate(samples) if r > 180 and b < 40)
    first_blue = next(i for i, (r, g, b) in enumerate(samples) if b > 180 and r < 40)
    assert first_blue > first_red
    assert all(max(rgb) > 80 for rgb in samples[first_red:first_blue + 1])


def test_magnetic_clip_reorder_is_one_undoable_edit(window, monkeypatch):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    window.project = ProjectState(zoom=100, active_clip_id='a')
    window.project.clips = [
        VideoClip(id=clip_id, path='/tmp/example.mp4', name=clip_id, duration=5,
                  start_time=i * 5, trim_start=0, trim_end=5)
        for i, clip_id in enumerate(['a', 'b', 'c'])
    ]
    window.timeline.set_project(window.project)
    monkeypatch.setattr(window, '_sync_player_to_timeline', lambda **kwargs: None)
    monkeypatch.setattr(window, '_load_active_clip', lambda: None)
    window._seed_history()
    canvas = window.timeline.canvas
    y = canvas._track_y(0) + 20

    def mouse(kind, x, buttons):
        button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
        event = QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button, buttons,
                            Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(canvas, event)

    mouse(QEvent.Type.MouseButtonPress, canvas.LABEL_W + 100, Qt.MouseButton.LeftButton)
    for t in [8, 12, 14, 9]:
        mouse(QEvent.Type.MouseMove, canvas.LABEL_W + t * 100, Qt.MouseButton.LeftButton)
    assert len(window._undo_stack) == 1
    mouse(QEvent.Type.MouseButtonRelease, canvas.LABEL_W + 900, Qt.MouseButton.NoButton)
    assert [(c.id, c.start_time) for c in window.project.clips] == [
        ('b', 0), ('a', 5), ('c', 10),
    ]
    assert len(window._undo_stack) == 2
    window.undo()
    assert [(c.id, c.start_time) for c in window.project.clips] == [('a', 0), ('b', 5), ('c', 10)]
    window.redo()
    assert [(c.id, c.start_time) for c in window.project.clips] == [
        ('b', 0), ('a', 5), ('c', 10),
    ]


def test_relink_preserves_clip_state_undo_and_reopens(window, tmp_path, monkeypatch):
    missing = tmp_path / "missing.mov"
    replacement = tmp_path / "replacement.mov"
    replacement.touch()
    clip = window.project.add_clip(missing, duration=10, width=100, height=100)
    clip.trim_start, clip.trim_end = 2, 6
    clip.source_in_limit, clip.source_out_limit = 1, 8
    clip.start_time = 4
    window.project.phi_review_confirmed = True
    window.project.deidentified_confirmed = True
    window.project.phi_review_progress = {clip.id: True}
    window._seed_history()
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    monkeypatch.setattr(main_window_module, "probe_video", lambda path: (7.0, 300, 200))
    assert window._relink_reference(clip, "clip", replacement)
    assert clip.path == str(missing)
    monkeypatch.setattr(main_window_module, "probe_video", lambda path: (12.0, 300, 200))
    assert window._relink_reference(clip, "clip", replacement) is None
    assert (clip.id, clip.start_time, clip.trim_start, clip.trim_end, clip.source_out_limit) == (
        window.project.clips[0].id, 4, 2, 6, 8
    )
    assert not window.project.phi_review_confirmed
    assert not window.project.deidentified_confirmed
    assert not window.project.phi_review_progress
    window.store.save(window.project)
    _, loaded = ProjectStore.open(window.store.project_path)
    assert loaded.clips[0].path == str(replacement)
    assert (loaded.clips[0].width, loaded.clips[0].height) == (300, 200)
    window.undo()
    assert window.project.clips[0].path == str(missing)
    window.redo()
    assert window.project.clips[0].path == str(replacement)


def test_import_cancel_discards_completed_items(window, tmp_path, monkeypatch):
    import time
    def slow_probe(_path):
        time.sleep(0.1)
        return (1.0, 100, 100)
    monkeypatch.setattr(main_window_module, "probe_video", slow_probe)
    window._import_media_files([tmp_path / "a.mov", tmp_path / "b.mov"])
    QTest.qWait(130)
    window._import_worker.cancel()
    _wait_for_import(window)
    assert not window.project.clips


def test_import_partial_failure_commits_successes_in_order(window, tmp_path, monkeypatch):
    paths = [tmp_path / name for name in ("a.mov", "bad.mov", "b.mov")]
    monkeypatch.setattr(main_window_module, "probe_video", lambda path: (
        (0.0, 0, 0) if path.name == "bad.mov" else (1.0, 100, 100)
    ))
    warnings = []
    monkeypatch.setattr(main_window_module.QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    history_before = len(window._undo_stack)
    window._import_media_files(paths)
    _wait_for_import(window)
    assert [Path(clip.path) for clip in window.project.clips] == [paths[0], paths[2]]
    assert len(window._undo_stack) == history_before + 1
    assert "bad.mov" in warnings[0]
    window.undo()
    assert not window.project.clips


def test_import_cancel_after_worker_result_before_delivery(window, tmp_path, monkeypatch):
    import threading
    finished_probe = threading.Event()
    def probe(_path):
        finished_probe.set()
        return (1.0, 100, 100)
    monkeypatch.setattr(main_window_module, "probe_video", probe)
    window._import_media_files([tmp_path / "a.mov"])
    assert finished_probe.wait(2)
    window._import_progress.canceled.emit()
    assert window._import_worker._cancelled
    _wait_for_import(window)
    assert not window.project.clips


def test_close_during_import_discards_results(window, tmp_path, monkeypatch):
    import threading
    import time
    started = threading.Event()
    def probe(_path):
        started.set()
        time.sleep(0.1)
        return (1.0, 100, 100)
    monkeypatch.setattr(main_window_module, "probe_video", probe)
    window._import_media_files([tmp_path / "a.mov"])
    assert started.wait(2)
    window.close()
    QApplication.processEvents()
    assert not window.project.clips


def test_relink_one_split_reference_preserves_default_source_extent(window, tmp_path, monkeypatch):
    old = tmp_path / "missing.mov"
    new = tmp_path / "new.mov"
    new.touch()
    first = window.project.add_clip(old, duration=10, width=100, height=100)
    first.trim_end = 5
    sibling = window.project.add_clip(old, duration=10, width=100, height=100)
    sibling.trim_start = 5
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    monkeypatch.setattr(main_window_module, "probe_video", lambda path: (20.0, 100, 100))
    assert window._relink_reference(first, "clip", new) is None
    assert first.effective_source_out_limit == 10
    assert sibling.path == str(old)
    assert sibling.trim_start == 5


def test_relink_missing_audio_and_slide_image(window, tmp_path, monkeypatch):
    from neuroedit_desktop.models import AudioTrack, Slide
    track = AudioTrack(id="audio-id", path=str(tmp_path / "lost.wav"), name="Narration", duration=4)
    slide = Slide(id="slide-id", title="Still", content="", image_path=str(tmp_path / "lost.png"))
    window.project.audio_tracks.append(track)
    window.project.slides.append(slide)
    audio = tmp_path / "new.wav"
    audio.touch()
    image = tmp_path / "new.png"
    assert QImage(10, 10, QImage.Format.Format_RGB32).save(str(image))
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    monkeypatch.setattr(window.audio_panel, "_probe_audio_duration", lambda _path: 3.0)
    assert window._relink_reference(track, "audio", audio)
    assert track.path.endswith("lost.wav")
    monkeypatch.setattr(window.audio_panel, "_probe_audio_duration", lambda _path: 5.0)
    assert window._relink_reference(track, "audio", audio) is None
    assert window._relink_reference(slide, "slide", image) is None
    assert track.path == str(audio)
    assert slide.image_path == str(image)


def test_import_final_preview_does_not_reprobe_on_ui_thread(window, tmp_path, monkeypatch):
    import threading
    import time
    video = tmp_path / "video.mov"
    video.touch()
    calls = []
    def slow_probe(_path):
        calls.append(threading.get_ident())
        time.sleep(0.15)
        return (1.0, 100, 100)
    monkeypatch.setattr(main_window_module, "probe_video", slow_probe)
    ticks = []
    timer = QTimer(window)
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    window._import_media_files([video])
    _wait_for_import(window)
    timer.stop()
    assert ticks
    assert calls and all(ident != threading.get_ident() for ident in calls)
    assert len(calls) == 1
    assert window.project.clips[0].path == str(video)


def test_relink_menu_repairs_the_selected_reference(window, tmp_path, monkeypatch):
    first = window.project.add_clip(tmp_path / "first.mov", duration=5, width=100, height=100)
    second = window.project.add_clip(tmp_path / "second.mov", duration=5, width=100, height=100)
    replacement = tmp_path / "replacement.mov"
    replacement.touch()
    monkeypatch.setattr(main_window_module, "probe_video", lambda _path: (6.0, 100, 100))
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    monkeypatch.setattr(main_window_module.QInputDialog, "getItem", lambda _parent, _title, _label, items, *_args: (items[1], True))
    monkeypatch.setattr(main_window_module.QFileDialog, "getOpenFileName", lambda *_args: (str(replacement), ""))
    window.relink_media_action.trigger()
    assert first.path.endswith("first.mov")
    assert second.path == str(replacement)


# --- NE-014: view-only timeline actions are not document edits --------------


def _timeline_mouse(canvas, kind, time_s, *, buttons):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    x = canvas.LABEL_W + time_s * canvas.project.zoom
    y = canvas._track_y(0) + 20
    event = QMouseEvent(
        kind, QPointF(x, y), QPointF(x, y),
        Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton,
        buttons, Qt.KeyboardModifier.NoModifier,
    )
    {
        QEvent.Type.MouseButtonPress: canvas.mousePressEvent,
        QEvent.Type.MouseMove: canvas.mouseMoveEvent,
        QEvent.Type.MouseButtonRelease: canvas.mouseReleaseEvent,
    }[kind](event)


def _timeline_drag(window, *times):
    """Press at the first time, move through the rest, release at the last."""
    from PySide6.QtCore import QEvent, Qt

    canvas = window.timeline.canvas
    down, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    _timeline_mouse(canvas, QEvent.Type.MouseButtonPress, times[0], buttons=down)
    for time_s in times[1:]:
        _timeline_mouse(canvas, QEvent.Type.MouseMove, time_s, buttons=down)
    _timeline_mouse(canvas, QEvent.Type.MouseButtonRelease, times[-1], buttons=none)


@pytest.fixture()
def reviewed(window, tmp_path, monkeypatch):
    """Two 10 s clips, a completed PHI review, and one step on the redo stack."""
    monkeypatch.setattr(window, "_sync_player_to_timeline", lambda **_kwargs: None)
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)
    for name in ("first", "second"):
        window.project.add_clip(tmp_path / f"{name}.mov", duration=10, width=100, height=100)
    window.project.active_clip_id = window.project.clips[0].id
    window.project.phi_review_confirmed = True
    window.project.deidentified_confirmed = True
    window.project.audio_reviewed_for_phi = True
    window.project.phi_review_progress = {window.project.clips[0].id: True}
    window._seed_history()
    window.project.project_name = "renamed"
    window._push_history()
    window.undo()
    window.dirty = False
    window.timeline.canvas.snap_enabled = False
    assert _review_state(window) == (True, True, True, True, 1, 1)
    return window


def _review_state(window):
    project = window.project
    return (
        project.phi_review_confirmed,
        project.deidentified_confirmed,
        project.audio_reviewed_for_phi,
        bool(project.phi_review_progress),
        len(window._undo_stack),
        len(window._redo_stack),
    )


@pytest.mark.parametrize("action", ["zoom", "zoom_in_button", "fit", "fit_twice"])
def test_timeline_zoom_keeps_phi_review_and_history(reviewed, action):
    timeline = reviewed.timeline
    before = _review_state(reviewed)
    zoom_before = reviewed.project.zoom

    if action == "zoom":
        timeline._set_zoom(120.0)
    elif action == "zoom_in_button":
        timeline._set_zoom(reviewed.project.zoom * 1.25)
    else:
        timeline._zoom_to_fit()
        if action == "fit_twice":
            timeline._zoom_to_fit()
            timeline._set_zoom(37.0)

    assert reviewed.project.zoom != zoom_before
    assert _review_state(reviewed) == before
    assert reviewed.dirty, "the new zoom is still saved with the project"


@pytest.mark.parametrize("time_s", [
    pytest.param(15.0, id="click-other-clip"),
    pytest.param(5.0, id="click-active-clip"),
    pytest.param(10.03, id="click-trim-handle"),
])
def test_timeline_click_keeps_phi_review_and_history(reviewed, time_s):
    before = _review_state(reviewed)

    _timeline_drag(reviewed, time_s)

    assert _review_state(reviewed) == before
    assert reviewed.timeline.canvas.selected_item is not None


def test_trim_dragged_out_and_back_is_not_an_edit(reviewed):
    before = _review_state(reviewed)

    _timeline_drag(reviewed, 19.97, 16.0, 14.0, 20.0)

    assert reviewed.project.clips[1].trim_end == pytest.approx(10.0)
    assert _review_state(reviewed) == before


def _edit_trim(window):
    _timeline_drag(window, 19.97, 18.0, 16.0)
    assert window.project.clips[1].trim_end == pytest.approx(6.0)


def _edit_move(window):
    first = window.project.clips[0].id
    _timeline_drag(window, 5.0, 12.0, 18.0)
    assert window.project.clips[1].id == first


def _edit_split(window):
    window.project.current_time = 4.0
    window.timeline._cut_active_clip()
    assert len(window.project.clips) == 3


def _edit_delete(window):
    canvas = window.timeline.canvas
    canvas.selected_item = ("clip", window.project.clips[1].id)
    canvas._delete_selected_item()
    assert len(window.project.clips) == 1


def _edit_fade(window):
    window.timeline._set_fade("in", 1.5)
    assert window.project.active_clip.fade_in == 1.5


@pytest.mark.parametrize("edit", [_edit_trim, _edit_move, _edit_split, _edit_delete, _edit_fade])
def test_timeline_edits_still_reset_review_with_one_undo_step(reviewed, edit):
    edit(reviewed)

    # Review invalidated, exactly one new undo step, redo discarded.
    assert _review_state(reviewed) == (False, False, False, False, 2, 0)
    assert reviewed.dirty


def test_selecting_another_clip_then_undoing_an_edit_restores_the_document(reviewed):
    _timeline_drag(reviewed, 15.0)          # select the second clip: no undo step
    _edit_trim(reviewed)                     # one undo step
    reviewed.undo()

    assert reviewed.project.clips[1].trim_end == pytest.approx(10.0)
    assert reviewed.project.phi_review_confirmed
    assert len(reviewed._undo_stack) == 1


def test_zoom_is_autosaved_even_after_a_cached_history_snapshot(reviewed):
    import json

    reviewed._push_history()                 # leaves a cached autosave snapshot
    reviewed.timeline._set_zoom(150.0)
    reviewed._autosave()

    saved = json.loads(reviewed.store.project_path.read_text())
    assert saved["zoom"] == 150.0
    assert saved["phi_review_confirmed"] is True
    assert not reviewed.dirty


# ── NE-017 / NE-018 / NE-021 ──────────────────────────────────────────────

@pytest.fixture()
def make_window_with_autosave(app, tmp_path, monkeypatch):
    """Factory: build a MainWindow whose autosave project.json holds given bytes."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(SamBackend, "probe", lambda self: SamBackendInfo("missing", "none", "stubbed"))
    monkeypatch.setattr(MainWindow, "_maybe_show_first_run_tutorial", lambda self: None)
    _forbid_modal_dialogs(monkeypatch)
    settings = QSettings("NeuroEdit", "Desktop")
    keys = ("storage/projectRoot", "storage/promptShown", "tutorial/seen")
    original = {key: settings.value(key) for key in keys}
    settings.setValue("storage/projectRoot", str(tmp_path / "Autosave"))
    settings.setValue("storage/promptShown", True)
    settings.setValue("tutorial/seen", True)
    made = []
    readonly_dirs = []

    def make(payload: bytes | None, warnings: list, readonly: bool = False):
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[1:]))
        bad = tmp_path / "Autosave" / "project.json"
        bad.parent.mkdir(parents=True, exist_ok=True)
        if payload is not None:
            bad.write_bytes(payload)
        if readonly:
            for name in ("masks", "audio", "stills"):
                (bad.parent / name).mkdir(exist_ok=True)
            readonly_dirs.append(bad.parent)
            bad.parent.chmod(0o555)
        try:
            win = MainWindow()
        finally:
            if readonly:
                bad.parent.chmod(0o755)
        made.append(win)
        if readonly:
            bad.parent.chmod(0o555)
        return win

    yield make
    for directory in readonly_dirs:
        directory.chmod(0o755)
    QApplication.processEvents()
    for win in made:
        thread = getattr(win, "_sam_probe_thread", None)
        if thread is not None:
            thread.quit()
            thread.wait(5_000)
        win.close()
        win.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    for key, value in original.items():
        settings.setValue(key, value if value is not None else "")


@pytest.mark.parametrize(
    "payload",
    [b'{"clips": "not-a-list"', b"", b'{"clips": 5, "slides": "x"}'],
    ids=["truncated", "zero-byte", "wrong-types"],
)
def test_unreadable_autosave_is_preserved_before_autosave(make_window_with_autosave, tmp_path, payload):
    warnings = []
    win = make_window_with_autosave(payload, warnings)
    root = tmp_path / "Autosave"

    win._mark_dirty()
    win._autosave()

    kept = sorted(root.glob("project.unreadable-*.json"))
    assert len(kept) == 1 and kept[0].read_bytes() == payload
    assert win.store.project_path.read_text() != payload.decode("utf-8", "ignore")
    assert str(kept[0]) in warnings[0][1]  # the warning names the preserved file


def test_unreadable_autosave_skips_orphan_mask_cleanup(make_window_with_autosave, tmp_path):
    win = make_window_with_autosave(b"{broken", [])
    mask = tmp_path / "Autosave" / "masks" / "maybe-referenced.png"
    mask.write_bytes(b"png")

    win._cleanup_orphan_masks()

    assert mask.exists()


def test_clean_start_does_not_warn_or_preserve(window, tmp_path):
    assert window._preserved_unreadable is None
    assert not list((tmp_path / "Autosave").glob("*.unreadable-*"))


def _scratch_case(window, tmp_path):
    window.project.add_clip(tmp_path / "case.mov", duration=10, width=100, height=100)
    window._mark_dirty()
    window._autosave()
    assert not window.dirty


@pytest.mark.parametrize("answer", ["cancel", "discard", "save"])
def test_new_project_asks_before_replacing_clean_scratch_case(window, tmp_path, monkeypatch, answer):
    from PySide6.QtWidgets import QMessageBox

    _scratch_case(window, tmp_path)
    old_project = window.project
    prompts = []
    button = {
        "cancel": QMessageBox.StandardButton.Cancel,
        "discard": QMessageBox.StandardButton.Discard,
        "save": QMessageBox.StandardButton.Save,
    }[answer]
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: prompts.append(a[1]) or button)
    saved_as = []
    monkeypatch.setattr(window, "_save_project_as", lambda: saved_as.append(True))
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)

    window._new_project()

    assert len(prompts) == 1
    if answer == "discard":
        assert window.project is not old_project and window.project.clips == []
    else:
        assert window.project is old_project  # nothing replaced, nothing deleted
        assert (window.store.project_path.parent / "project.json").exists()
    # "save" with Save As not actually moving the store keeps the case open.
    assert bool(saved_as) == (answer == "save")


def test_new_project_after_successful_save_as_starts_fresh(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    _scratch_case(window, tmp_path)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Save)

    def fake_save_as():
        window.store = ProjectStore.create(tmp_path / "Saved")

    monkeypatch.setattr(window, "_save_project_as", fake_save_as)
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)

    window._new_project()

    assert window.project.clips == []


def test_new_project_does_not_prompt_for_empty_scratch_or_saved_project(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    prompts = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: prompts.append(a[1]) or QMessageBox.StandardButton.Cancel)
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)

    window._new_project()  # empty scratch project
    window.store = ProjectStore.create(tmp_path / "Elsewhere")
    window.project.add_clip(tmp_path / "case.mov", duration=10, width=100, height=100)
    window.dirty = False
    window._new_project()  # clean project saved outside the autosave folder

    assert prompts == []
    assert window.project.clips == []


class _RunningThread:
    def __init__(self, running=True):
        self.running = running

    def isRunning(self):  # noqa: N802
        return self.running

    def quit(self):
        self.running = False

    def wait(self, _ms):
        return True


class _Worker:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


@pytest.mark.parametrize("thread_attr", ["_export_thread", "_sam_segment_thread", "_sam_propagation_thread"])
def test_close_during_job_keep_working_ignores_close(window, monkeypatch, thread_attr):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    thread, worker = _RunningThread(), _Worker()
    monkeypatch.setattr(window, thread_attr, thread, raising=False)
    monkeypatch.setattr(window, "_export_worker", worker, raising=False)
    prompts = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: prompts.append(a[1]) or QMessageBox.StandardButton.No)
    event = QCloseEvent()

    window.closeEvent(event)

    assert len(prompts) == 1
    assert not event.isAccepted()
    assert thread.running and not worker.cancelled
    assert not getattr(window, "_closing", False)
    monkeypatch.setattr(window, thread_attr, None)  # let fixture teardown close cleanly


def test_close_during_export_close_anyway_runs_shutdown(window, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    thread, worker = _RunningThread(), _Worker()
    monkeypatch.setattr(window, "_export_thread", thread, raising=False)
    monkeypatch.setattr(window, "_export_worker", worker, raising=False)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    event = QCloseEvent()

    window.closeEvent(event)

    assert event.isAccepted()
    assert worker.cancelled and not thread.running
    assert window._closing


def test_close_without_job_does_not_prompt(window, monkeypatch):
    from PySide6.QtGui import QCloseEvent
    from PySide6.QtWidgets import QMessageBox

    prompts = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: prompts.append(a) or QMessageBox.StandardButton.No)
    event = QCloseEvent()

    window.closeEvent(event)

    assert prompts == []
    assert event.isAccepted()


def _stub_question(monkeypatch, answer):
    prompts = []
    monkeypatch.setattr(
        QMessageBox, "question",
        lambda *a, **k: prompts.append(a[1]) or answer,
    )
    return prompts


def _dirty_scratch_case(window, tmp_path):
    window.project.add_clip(tmp_path / "case.mov", duration=10, width=100, height=100)
    window._mark_dirty()
    assert window.dirty and window._is_unsaved_scratch_case()


def test_dirty_scratch_save_runs_save_as_then_starts_new_project(window, tmp_path, monkeypatch):
    _dirty_scratch_case(window, tmp_path)
    prompts = _stub_question(monkeypatch, QMessageBox.StandardButton.Save)
    saved = tmp_path / "Saved"
    calls = []

    def fake_save_as():
        calls.append(True)
        window.store = ProjectStore.create(saved)
        window.store.save(window.project)

    monkeypatch.setattr(window, "_save_project_as", fake_save_as)
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)

    window._new_project()

    assert prompts == ["Unsaved Case"] and calls == [True]
    assert window.project.clips == []
    assert "case.mov" in (saved / "project.json").read_text()  # saved case untouched
    assert window.store.project_path.parent != saved


def test_dirty_scratch_save_as_cancelled_keeps_case_open(window, tmp_path, monkeypatch):
    _dirty_scratch_case(window, tmp_path)
    old_project = window.project
    prompts = _stub_question(monkeypatch, QMessageBox.StandardButton.Save)
    monkeypatch.setattr(window, "_save_project_as", lambda: None)

    window._new_project()

    assert len(prompts) == 1
    assert window.project is old_project and window.dirty


def test_dirty_scratch_discard_starts_new_project(window, tmp_path, monkeypatch):
    _dirty_scratch_case(window, tmp_path)
    prompts = _stub_question(monkeypatch, QMessageBox.StandardButton.Discard)
    monkeypatch.setattr(window, "_load_active_clip", lambda: None)

    window._new_project()

    assert len(prompts) == 1
    assert window.project.clips == []


def test_dirty_scratch_cancel_changes_nothing(window, tmp_path, monkeypatch):
    _dirty_scratch_case(window, tmp_path)
    old_project = window.project
    prompts = _stub_question(monkeypatch, QMessageBox.StandardButton.Cancel)

    window._new_project()

    assert len(prompts) == 1
    assert window.project is old_project and window.dirty


def test_dirty_project_saved_elsewhere_keeps_generic_prompt(window, tmp_path, monkeypatch):
    window.store = ProjectStore.create(tmp_path / "Elsewhere")
    window.project.add_clip(tmp_path / "case.mov", duration=10, width=100, height=100)
    window._mark_dirty()
    prompts = _stub_question(monkeypatch, QMessageBox.StandardButton.Cancel)

    window._new_project()

    assert prompts == ["Unsaved Changes"]
    assert window.project.clips


def test_scratch_case_with_running_job_shows_info_not_question(window, tmp_path, monkeypatch):
    _dirty_scratch_case(window, tmp_path)
    old_project = window.project
    monkeypatch.setattr(window, "_export_thread", _RunningThread(), raising=False)
    prompts = _stub_question(monkeypatch, QMessageBox.StandardButton.Discard)
    infos = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: infos.append(a[1]))

    window._new_project()

    assert prompts == [] and infos == ["Background work in progress"]
    assert window.project is old_project
    monkeypatch.setattr(window, "_export_thread", None)


# ── Review round 2: autosave-root case, markers/transcript, blocked autosave ──

def _write_root_case(tmp_path, **content):
    """Put a saved scratch case into the autosave root's project.json."""
    from neuroedit_desktop.models import TimelineMarker, TranscriptSegment

    root = tmp_path / "Autosave"
    store = ProjectStore.create(root)
    project = ProjectState(project_name="Scratch")
    if content.get("clip"):
        project.add_clip(tmp_path / "scratch.mov", duration=10, width=100, height=100)
    if content.get("marker"):
        project.markers.append(TimelineMarker(id="m", time=1.0, label="x"))
    if content.get("transcript"):
        project.transcript_segments.append(
            TranscriptSegment(id="t", audio_track_id=None, start_time=0, end_time=1, text="hi")
        )
    store.save(project)
    return store.project_path


def _move_to_other_project(window, tmp_path):
    """Open-then-New setup: the current project is saved outside the root."""
    window.store = ProjectStore.create(tmp_path / "Other")
    window.project = ProjectState(project_name="Other")
    window.dirty = False
    window._load_active_clip = lambda: None


@pytest.mark.parametrize("answer", ["open", "cancel", "replace"])
def test_new_project_asks_about_case_left_in_autosave_root(window, tmp_path, monkeypatch, answer):
    root_file = _write_root_case(tmp_path, clip=True)
    before = root_file.read_bytes()
    _move_to_other_project(window, tmp_path)
    other_project = window.project
    button = {
        "open": QMessageBox.StandardButton.Open,
        "cancel": QMessageBox.StandardButton.Cancel,
        "replace": QMessageBox.StandardButton.Discard,
    }[answer]
    prompts = _stub_question(monkeypatch, button)
    # Opening the case reports its (non-existent) media, as startup restore does.
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    window._new_project()

    assert prompts == ["Unsaved case in the autosave folder"]
    assert root_file.read_bytes() == before
    if answer == "open":
        assert window.store.project_path == root_file
        assert window.project.project_name == "Scratch" and len(window.project.clips) == 1
    elif answer == "cancel":
        assert window.project is other_project
    else:
        assert window.project is not other_project and window.project.clips == []
        assert window.store.project_path == root_file


def test_new_project_ignores_empty_case_in_autosave_root(window, tmp_path, monkeypatch):
    _write_root_case(tmp_path)  # readable but empty
    _move_to_other_project(window, tmp_path)
    prompts = _stub_question(monkeypatch, QMessageBox.StandardButton.Cancel)

    window._new_project()

    assert prompts == []
    assert window.store.project_path == tmp_path / "Autosave" / "project.json"


def test_new_project_preserves_unreadable_case_in_autosave_root(window, tmp_path, monkeypatch):
    root_file = tmp_path / "Autosave" / "project.json"
    root_file.write_bytes(b'{"clips": "oops"')
    _move_to_other_project(window, tmp_path)
    prompts = _stub_question(monkeypatch, QMessageBox.StandardButton.Cancel)

    window._new_project()

    kept = list(root_file.parent.glob("project.unreadable-*.json"))
    assert prompts == [] and len(kept) == 1 and kept[0].read_bytes() == b'{"clips": "oops"'
    assert window.store.project_path == root_file and window.project.clips == []


def test_new_project_unmovable_unreadable_root_file_is_not_replaced(window, tmp_path, monkeypatch):
    root_file = tmp_path / "Autosave" / "project.json"
    root_file.write_bytes(b"{broken")
    _move_to_other_project(window, tmp_path)
    other_project = window.project
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[1]))

    def cannot_move(_path):
        raise PermissionError("read-only")

    monkeypatch.setattr(ProjectStore, "preserve_unreadable", staticmethod(cannot_move))

    window._new_project()

    assert len(warnings) == 1
    assert window.project is other_project
    assert root_file.read_bytes() == b"{broken"


@pytest.mark.parametrize("content", [{"marker": True}, {"transcript": True}], ids=["markers", "transcript"])
def test_markers_or_transcript_only_case_counts_as_content(window, tmp_path, monkeypatch, content):
    from neuroedit_desktop.models import TimelineMarker, TranscriptSegment

    if "marker" in content:
        window.project.markers.append(TimelineMarker(id="m", time=1.0, label="x"))
    else:
        window.project.transcript_segments.append(
            TranscriptSegment(id="t", audio_track_id=None, start_time=0, end_time=1, text="hi")
        )
    window._mark_dirty()
    assert window._is_unsaved_scratch_case()
    prompts = _stub_question(monkeypatch, QMessageBox.StandardButton.Cancel)

    window._new_project()

    assert prompts == ["Unsaved Case"]
    # the on-disk check uses the same definition
    _write_root_case(tmp_path, **content)
    _move_to_other_project(window, tmp_path)
    window._new_project()
    assert prompts[-1] == "Unsaved case in the autosave folder"


def test_unmovable_unreadable_autosave_is_never_overwritten(make_window_with_autosave, tmp_path, monkeypatch):
    import os

    if os.geteuid() == 0:
        pytest.skip("directory permissions are not enforced for root")
    warnings = []
    win = make_window_with_autosave(b"{broken", warnings, readonly=True)
    bad = tmp_path / "Autosave" / "project.json"
    assert len(warnings) == 1  # constructed fine, warned once
    other = win.project

    win._mark_dirty()
    win._autosave()
    assert win.dirty and bad.read_bytes() == b"{broken"

    win._new_project()  # warns instead of replacing
    assert len(warnings) == 2 and win.project is other
    assert bad.read_bytes() == b"{broken"
    assert not list(bad.parent.glob("*.unreadable-*")) and not list(bad.parent.glob("session-*"))

    win.store = ProjectStore.create(tmp_path / "Other")  # as after Save As
    win._autosave()
    assert (tmp_path / "Other" / "project.json").exists()


def test_preserved_unreadable_file_protects_masks_in_later_sessions(make_window_with_autosave, tmp_path):
    root = tmp_path / "Autosave"
    first = make_window_with_autosave(b'{"annotations": "x"', [])
    mask = root / "masks" / "referenced.png"
    mask.write_bytes(b"png")
    first.close()

    second = make_window_with_autosave(None, [])
    second._cleanup_orphan_masks()
    assert mask.exists()  # preserved file from session 1 may still reference it

    for kept in root.glob("project.unreadable-*.json"):
        kept.unlink()
    second._cleanup_orphan_masks()
    assert not mask.exists()


def test_blocked_autosave_cannot_be_overwritten_on_close(make_window_with_autosave, tmp_path, monkeypatch):
    from PySide6.QtGui import QCloseEvent

    def cannot_move(path):
        raise OSError("rename denied")

    monkeypatch.setattr(ProjectStore, "preserve_unreadable", staticmethod(cannot_move))
    warnings = []
    original = b"{broken-but-recoverable"
    win = make_window_with_autosave(original, warnings)
    win.project.project_name = "New work"
    win._mark_dirty()
    event = QCloseEvent()
    try:
        win.closeEvent(event)
        assert (tmp_path / "Autosave" / "project.json").read_bytes() == original
        assert not event.isAccepted()
        assert win.dirty
        assert "Save As" in warnings[-1][1]
    finally:
        win.dirty = False  # permit fixture teardown after the intentionally rejected close


def test_startup_autosave_warns_about_newer_schema(make_window_with_autosave):
    import json

    from neuroedit_desktop.models import SCHEMA_VERSION

    warnings = []
    win = make_window_with_autosave(json.dumps({"schema_version": SCHEMA_VERSION + 1}).encode(), warnings)
    assert [entry[0] for entry in warnings] == ["Project from a newer version"]
    assert not win.dirty


@pytest.mark.parametrize('field', ['storyboard_objective', 'storyboard_case_context', 'storyboard_key_anatomy', 'storyboard_steps', 'storyboard_decision_points', 'storyboard_teaching_pearl', 'storyboard_final_point', 'intended_audience', 'edit_disclosure'])
def test_notes_only_scratch_requires_confirmation(window, monkeypatch, field):
    from neuroedit_desktop.ui.tutorial import project_has_user_content

    setattr(window.project, field, "Important plan")
    window._mark_dirty()
    window._autosave()
    assert not window.dirty
    original = window.project
    prompts = []
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: prompts.append(args[1]) or QMessageBox.StandardButton.Cancel)
    window._new_project()
    assert window.project is original
    assert prompts == ['Unsaved Case']
    assert project_has_user_content(window)


def test_switching_projects_dismisses_hands_on_tutorial(window, tmp_path):
    overlay = TutorialOverlay(window, build_default_steps(window), read_only=False)
    window._tutorial_overlay = overlay
    project = ProjectState(storyboard_case_context="Existing user work")
    window._activate_project(ProjectStore.create(tmp_path / "Saved"), project)
    assert overlay.isHidden()
    assert window.project is project


def test_sam_probe_references_survive_result_until_thread_has_stopped(window, monkeypatch):
    import threading
    import time

    from PySide6.QtCore import QObject, Signal
    from neuroedit_desktop.ui import sam_workflow

    entered = threading.Event()
    release = threading.Event()

    class PausedWorker(QObject):
        progress = Signal(str)
        finished = Signal(object)

        def __init__(self, _backend):
            super().__init__()

        def cancel(self):
            release.set()

        def run(self):
            self.finished.emit(SamBackendInfo("missing", "none", "stub"))
            entered.set()
            release.wait(5)

    window._startup_sam_timer.stop()
    delivered = []
    original_handler = window._on_sam_probe_finished
    def on_result(info):
        original_handler(info)
        delivered.append(True)
    monkeypatch.setattr(window, "_on_sam_probe_finished", on_result)
    monkeypatch.setattr(sam_workflow, "SamProbeWorker", PausedWorker)
    window._load_sam_backend()
    thread, worker = window._sam_probe_thread, window._sam_probe_worker
    try:
        assert entered.wait(2)
        deadline = time.monotonic() + 2
        while not delivered and time.monotonic() < deadline:
            QApplication.processEvents()
        assert delivered
        assert window._sam_probe_thread is thread
        assert window._sam_probe_worker is worker
        assert thread.isRunning()
    finally:
        release.set()
    deadline = time.monotonic() + 2
    while window._sam_probe_thread is not None and time.monotonic() < deadline:
        QTest.qWait(10)
    assert window._sam_probe_thread is None
    assert window._sam_probe_worker is None


def test_sam_backend_is_probed_only_when_first_opened(window, monkeypatch):
    calls = []

    def probe(_backend):
        calls.append(True)
        return SamBackendInfo("missing", "none", "stub")

    monkeypatch.setattr(SamBackend, "probe", probe)
    QApplication.processEvents()
    assert not calls
    window._set_panel("sam")
    for _ in range(100):
        QTest.qWait(10)
        if calls and window._sam_probe_thread is None:
            break
    assert len(calls) == 1
    assert window._sam_probe_thread is None
    window._set_panel("tips")
    window._set_panel("sam")
    assert not window._startup_sam_timer.isActive()


def test_close_before_deferred_sam_probe_cancels_it(window, monkeypatch):
    calls = []
    monkeypatch.setattr(SamBackend, "probe", lambda self: calls.append(True))
    window._set_panel("sam")
    assert window._startup_sam_timer.isActive()
    window.close()
    QApplication.processEvents()
    assert not calls
    assert getattr(window, "_sam_probe_thread", None) is None
