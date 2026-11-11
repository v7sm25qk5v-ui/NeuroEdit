from types import SimpleNamespace

import pytest
from PySide6.QtMultimedia import QMediaRecorder
from PySide6.QtWidgets import QApplication

from neuroedit_desktop.models import ProjectState
from neuroedit_desktop.project_store import ProjectStore
from neuroedit_desktop.ui import audio_panel, main_window
from neuroedit_desktop.ui.audio_panel import AudioPanel
from neuroedit_desktop.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


class FakeRecorder:
    def __init__(self):
        self.stop_count = 0
        self.state = QMediaRecorder.RecorderState.RecordingState
        self.error_value = QMediaRecorder.Error.NoError

    def setOutputLocation(self, url):
        self.path = url.toLocalFile()

    def record(self):
        pass

    def stop(self):
        self.stop_count += 1

    def recorderState(self):
        return self.state

    def error(self):
        return self.error_value

    def errorString(self):
        return "Encoder failed"


@pytest.fixture
def recording(app, tmp_path, monkeypatch):
    project = ProjectState(current_time=2.0)
    panel = AudioPanel(project, tmp_path)
    panel.recorder = FakeRecorder()
    panel.capture_session = SimpleNamespace(setAudioInput=lambda value: None)
    monkeypatch.setattr(audio_panel.QMediaDevices, "defaultAudioInput", lambda: SimpleNamespace(isNull=lambda: False))
    monkeypatch.setattr(audio_panel, "QAudioInput", lambda *args: object())
    monkeypatch.setattr(panel, "_probe_audio_duration", lambda path: 3.5)
    panel._start_recording()
    return panel


def test_recording_uses_start_position_after_playhead_moves(recording):
    recording.project.current_time = 7.0
    recording._stop_recording()
    recording._recording_state_changed(QMediaRecorder.RecorderState.StoppedState)
    track, = recording.project.audio_tracks
    assert (track.start_time, track.duration) == (2.0, 3.5)


@pytest.mark.parametrize("already_stopped", [False, True])
def test_close_waits_for_recording_before_saving(recording, tmp_path, monkeypatch, already_stopped):
    if already_stopped:
        recording._stop_recording()
    window = MainWindow.__new__(MainWindow)
    window.project = recording.project
    window.audio_panel = recording
    window.statusBar = lambda: SimpleNamespace(showMessage=lambda *args: None)
    window.dirty = True
    saved = []
    store = ProjectStore.create(tmp_path / "saved")
    def save_then_fail(project):
        store.save(project)
        saved.append(project.to_dict())
        raise OSError("test save failure")
    window.store = SimpleNamespace(save=save_then_fail)
    monkeypatch.setattr(main_window.QMessageBox, "critical", lambda *args: None)
    ignored = []
    event = SimpleNamespace(ignore=lambda: ignored.append(True))
    window.closeEvent(event)
    window.closeEvent(event)
    assert not saved
    assert len(ignored) == 2
    if not already_stopped:
        recording._stop_recording()
    recording._recording_state_changed(QMediaRecorder.RecorderState.StoppedState)
    window.closeEvent(event)
    assert len(saved) == 1
    assert len(saved[0]["audio_tracks"]) == 1
    assert len(ProjectStore.open(store.project_path)[1].audio_tracks) == 1
    assert len(ignored) == 3  # failed save keeps window open


def test_recording_failure_stopped_state_unblocks_without_probing(recording, tmp_path, monkeypatch):
    path = recording._recording_path
    path.write_bytes(b"failed recording")
    recording.recorder.state = QMediaRecorder.RecorderState.StoppedState
    monkeypatch.setattr(recording, "_probe_audio_duration", lambda path: pytest.fail("must not probe"))
    recording._recording_failed(QMediaRecorder.Error.ResourceError, "Microphone unavailable")
    assert not recording.recording_pending
    assert not recording.project.audio_tracks
    assert path.exists() and str(path) in recording.status.text()
    recording._recording_state_changed(QMediaRecorder.RecorderState.StoppedState)
    assert not recording.project.audio_tracks


def test_recording_error_while_active_rejects_late_result(recording, monkeypatch):
    recording._recording_failed(QMediaRecorder.Error.ResourceError, "Device failed")
    assert recording.recording_pending
    monkeypatch.setattr(recording, "_probe_audio_duration", lambda path: pytest.fail("must not probe"))
    recording._recording_state_changed(QMediaRecorder.RecorderState.StoppedState)
    assert not recording.recording_pending
    assert not recording.project.audio_tracks
    assert "Device failed" in recording.status.text()


def test_failed_duration_and_project_replacement_retain_file(recording, monkeypatch):
    path = recording._recording_path
    path.write_bytes(b"audio")
    monkeypatch.setattr(recording, "_probe_audio_duration", lambda path: 0)
    recording._recording_state_changed(QMediaRecorder.RecorderState.StoppedState)
    assert not recording.project.audio_tracks and path.exists()
    assert str(path) in recording.status.text()


def test_recording_completion_after_project_change_does_not_attach(recording):
    original = recording.project
    recording.project = ProjectState(current_time=10)
    recording._recording_state_changed(QMediaRecorder.RecorderState.StoppedState)
    assert not original.audio_tracks and not recording.project.audio_tracks
    assert not recording.recording_pending


def test_recording_unchanged_playhead_and_delayed_completion(recording):
    recording._stop_recording()
    assert recording.recording_pending
    recording._recording_state_changed(QMediaRecorder.RecorderState.StoppedState)
    recording._recording_state_changed(QMediaRecorder.RecorderState.StoppedState)
    assert len(recording.project.audio_tracks) == 1
    assert recording.project.audio_tracks[0].start_time == 2.0
    assert recording._recording_start_time == 0.0


def test_close_after_recording_persists_track_in_real_window(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QEvent, QSettings
    from PySide6.QtGui import QCloseEvent

    monkeypatch.setattr(MainWindow, "_load_sam_backend", lambda self: None)
    monkeypatch.setattr(MainWindow, "_maybe_show_first_run_tutorial", lambda self: None)
    settings = QSettings("NeuroEdit", "Desktop")
    settings.setValue("storage/projectRoot", str(tmp_path / "autosave"))
    settings.setValue("storage/promptShown", True)
    settings.setValue("tutorial/seen", True)
    window = MainWindow()
    try:
        panel = window.audio_panel
        panel.recorder = FakeRecorder()
        panel.capture_session = SimpleNamespace(setAudioInput=lambda value: None)
        monkeypatch.setattr(audio_panel.QMediaDevices, "defaultAudioInput", lambda: SimpleNamespace(isNull=lambda: False))
        monkeypatch.setattr(audio_panel, "QAudioInput", lambda *args: object())
        monkeypatch.setattr(panel, "_probe_audio_duration", lambda path: 3.5)
        window.project.current_time = 2.0
        panel._start_recording()
        path = panel._recording_path
        path.write_bytes(b"fixture recording")
        window.project.current_time = 7.0
        first_close = QCloseEvent()
        window.closeEvent(first_close)
        assert not first_close.isAccepted()
        panel._stop_recording()
        panel._recording_state_changed(QMediaRecorder.RecorderState.StoppedState)
        final_close = QCloseEvent()
        window.closeEvent(final_close)
        assert final_close.isAccepted()
        reopened = ProjectStore.open(window.store.project_path)[1]
        assert len(reopened.audio_tracks) == 1
        assert reopened.audio_tracks[0].start_time == 2.0
        assert reopened.audio_tracks[0].duration == 3.5
    finally:
        window.audio_panel._recording_path = None
        window.close()
        window.deleteLater()
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_recorded_start_is_used_by_preview_and_export(recording, tmp_path, monkeypatch):
    from neuroedit_desktop.exporter import ExportSettings, ProjectExporter
    from neuroedit_desktop.ui import audio_preview
    from test_audio_preview import FakeOutput, FakePlayer
    from PySide6.QtMultimedia import QMediaPlayer

    path = recording._recording_path
    path.write_bytes(b"recording")
    recording.project.current_time = 7.0
    recording._recording_state_changed(QMediaRecorder.RecorderState.StoppedState)
    recording.project.current_time = 2.5
    monkeypatch.setattr(audio_preview, "QMediaPlayer", FakePlayer)
    monkeypatch.setattr(audio_preview, "QAudioOutput", FakeOutput)
    FakePlayer.MediaStatus = QMediaPlayer.MediaStatus
    FakePlayer.PlaybackState = QMediaPlayer.PlaybackState
    preview = audio_preview.AudioPreview()
    preview.sync(recording.project, True)
    player = next(iter(preview._players.values()))["player"]
    player.load()
    assert player.pos == 500
    exporter = ProjectExporter(recording.project, ExportSettings(output_path=tmp_path / "out.mp4", width=64, height=64, fps=30, crf=23, label="test"))
    monkeypatch.setattr(exporter, "_has_audio_stream", lambda *args: True)
    source, = exporter._audio_sources("ffmpeg")
    assert source.timeline_start == 2.0
    preview.stop()


def test_synchronous_stop_finalizes_once(recording):
    def stop():
        recording.recorder.stop_count += 1
        recording.recorder.state = QMediaRecorder.RecorderState.StoppedState
        recording._recording_state_changed(QMediaRecorder.RecorderState.StoppedState)
    recording.recorder.stop = stop
    recording._stop_recording()
    assert not recording.recording_pending
    assert len(recording.project.audio_tracks) == 1
    assert recording.recorder.stop_count == 1


def test_immediate_record_error_does_not_trap_close(app, tmp_path, monkeypatch):
    project = ProjectState(current_time=2)
    panel = AudioPanel(project, tmp_path)
    panel.recorder = FakeRecorder()
    panel.recorder.state = QMediaRecorder.RecorderState.StoppedState
    panel.recorder.record = lambda: panel._recording_failed(QMediaRecorder.Error.ResourceError, "No input")
    panel.capture_session = SimpleNamespace(setAudioInput=lambda value: None)
    monkeypatch.setattr(audio_panel.QMediaDevices, "defaultAudioInput", lambda: SimpleNamespace(isNull=lambda: False))
    monkeypatch.setattr(audio_panel, "QAudioInput", lambda *args: object())
    monkeypatch.setattr(panel, "_probe_audio_duration", lambda path: pytest.fail("must not probe"))
    panel._start_recording()
    assert not panel.recording_pending
    assert panel.record_btn.isEnabled() and not panel.stop_btn.isEnabled()
    assert not project.audio_tracks
    assert "No input" in panel.status.text() and "recording file at" in panel.status.text()


def test_close_during_duration_probe_is_refused(recording, monkeypatch):
    window = MainWindow.__new__(MainWindow)
    window.project = recording.project
    window.audio_panel = recording
    window.dirty = True
    saves = []
    window.store = SimpleNamespace(save=lambda project: saves.append(project))
    window.statusBar = lambda: SimpleNamespace(showMessage=lambda *args: None)
    ignored = []
    def probe(path):
        assert recording.recording_pending
        window.closeEvent(SimpleNamespace(ignore=lambda: ignored.append(True)))
        return 3.5
    monkeypatch.setattr(recording, "_probe_audio_duration", probe)
    recording._recording_state_changed(QMediaRecorder.RecorderState.StoppedState)
    assert ignored == [True] and not saves
    assert len(recording.project.audio_tracks) == 1
    assert not recording.recording_pending


def test_stopped_signal_before_error_signal_rejects_failed_capture(recording, monkeypatch):
    recording.recorder.error_value = QMediaRecorder.Error.FormatError
    monkeypatch.setattr(recording, "_probe_audio_duration", lambda path: pytest.fail("must not probe"))
    recording._recording_state_changed(QMediaRecorder.RecorderState.StoppedState)
    assert not recording.recording_pending
    assert not recording.project.audio_tracks
    assert "Encoder failed" in recording.status.text()
    recording._recording_failed(QMediaRecorder.Error.FormatError, "Encoder failed")
    assert not recording.project.audio_tracks
