from __future__ import annotations

import wave
from threading import Event

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtTest import QTest

from neuroedit_desktop.models import ProjectState
from neuroedit_desktop.ui.audio_panel import AudioPanel
from test_main_window_headless import app  # noqa: F401


def _dispose(panel):
    """Destroy the panel now, on the GUI thread. Left to the garbage collector,
    its native audio objects were torn down at an arbitrary later moment (often
    while the next test's worker thread was running), which crashed the process
    intermittently."""
    panel.shutdown_audio_import()
    panel.close()
    panel.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _wait_for(predicate):
    for _ in range(2000):
        if predicate():
            return
        QTest.qWait(10)
    pytest.fail("audio import did not finish")


@pytest.mark.parametrize("outcome", ["success", "playback", "cancel", "replace", "edit", "close"])
def test_background_audio_import(app, tmp_path, monkeypatch, outcome):  # noqa: F811
    project = ProjectState()
    panel = AudioPanel(project, tmp_path)
    path = tmp_path / "audio.mp3"
    path.write_bytes(b"audio")
    entered, release = Event(), Event()

    def probe(_path):
        entered.set()
        release.wait(3)
        return 4.0

    monkeypatch.setattr(panel, "_probe_audio_duration", probe)
    monkeypatch.setattr(
        "neuroedit_desktop.ui.audio_panel.QFileDialog.getOpenFileName",
        lambda *args: (str(path), ""),
    )
    try:
        project.current_time = 2.0
        panel._import_audio()
        _wait_for(entered.is_set)
        heartbeat = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        _wait_for(lambda: heartbeat)
        if outcome == "cancel":
            panel._audio_import_progress.canceled.emit()
        elif outcome == "replace":
            panel.set_project(ProjectState())
        elif outcome == "edit":
            project.project_name = "Changed while importing"
        elif outcome == "playback":
            project.current_time = 4.0
            project.active_clip_id = "other"
        elif outcome == "close":
            panel.shutdown_audio_import()
        release.set()
        if outcome == "close":
            _wait_for(lambda: panel._audio_import_future.done())
            QTest.qWait(50)
        else:
            _wait_for(lambda: panel._audio_import_future is None)
        assert len(project.audio_tracks) == (1 if outcome in {"success", "playback"} else 0)
        if project.audio_tracks:
            assert project.audio_tracks[0].start_time == 2.0
    finally:
        release.set()
        _dispose(panel)


@pytest.mark.parametrize("valid", [True, False])
def test_real_audio_import(app, tmp_path, monkeypatch, valid):  # noqa: F811
    panel = AudioPanel(ProjectState(), tmp_path)
    path = tmp_path / "audio.wav"
    if valid:
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(8000)
            wav.writeframes(b"\0\0" * 4000)
    else:
        path.write_bytes(b"not audio")
    monkeypatch.setattr(
        "neuroedit_desktop.ui.audio_panel.QFileDialog.getOpenFileName",
        lambda *args: (str(path), ""),
    )
    try:
        panel._import_audio()
        _wait_for(lambda: panel._audio_import_future is None)
        assert len(panel.project.audio_tracks) == int(valid)
        if valid:
            assert panel.project.audio_tracks[0].duration == pytest.approx(0.5)
        else:
            assert "Could not read audio duration" in panel.status.text()
    finally:
        _dispose(panel)


def test_cancelled_probe_blocks_retry_until_it_finishes(app, tmp_path, monkeypatch):  # noqa: F811
    panel = AudioPanel(ProjectState(), tmp_path)
    path = tmp_path / "audio.mp3"
    path.write_bytes(b"audio")
    entered, release = Event(), Event()
    calls = []

    def probe(_path):
        calls.append(1)
        entered.set()
        release.wait(3)
        return 4.0

    monkeypatch.setattr(panel, "_probe_audio_duration", probe)
    monkeypatch.setattr(
        "neuroedit_desktop.ui.audio_panel.QFileDialog.getOpenFileName",
        lambda *args: (str(path), ""),
    )
    try:
        panel._import_audio()
        _wait_for(entered.is_set)
        panel._audio_import_progress.canceled.emit()
        panel._import_audio()
        assert len(calls) == 1
        release.set()
        _wait_for(lambda: panel._audio_import_future is None)
        assert not panel.project.audio_tracks
        panel._import_audio()
        _wait_for(lambda: panel._audio_import_future is None)
        assert len(calls) == 2
        assert len(panel.project.audio_tracks) == 1
    finally:
        release.set()
        _dispose(panel)
