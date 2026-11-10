import pytest
from PySide6.QtWidgets import QApplication

from PySide6.QtMultimedia import QMediaPlayer, QMediaRecorder

from neuroedit_desktop.models import AudioTrack, ProjectState
from neuroedit_desktop.ui.audio_panel import AudioPanel
from neuroedit_desktop.ui import audio_preview


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


class Signal:
    def connect(self, callback):
        self.callback = callback


class FakePlayer:
    def __init__(self, parent):
        self.mediaStatusChanged = Signal()
        self.status = QMediaPlayer.MediaStatus.LoadingMedia
        self.pos = 0
        self.playing = False
        self.stopped = False

    def setAudioOutput(self, output): self.output = output
    def setSource(self, source): self.source = source
    def mediaStatus(self): return self.status
    def position(self): return self.pos
    def setPosition(self, pos): self.pos = pos
    def setPlaybackRate(self, rate): self.rate = rate
    def playbackState(self):
        return (QMediaPlayer.PlaybackState.PlayingState if self.playing
                else QMediaPlayer.PlaybackState.StoppedState)
    def play(self): self.playing = True
    def stop(self):
        self.playing = False
        self.stopped = True
    def deleteLater(self): pass
    def load(self):
        self.status = QMediaPlayer.MediaStatus.LoadedMedia
        self.mediaStatusChanged.callback(self.status)


class FakeOutput:
    def __init__(self, parent): pass
    def setVolume(self, volume): self.volume = volume
    def deleteLater(self): pass


def test_preview_tracks_clock_overlap_and_lifecycle(app, tmp_path, monkeypatch):
    monkeypatch.setattr(audio_preview, 'QMediaPlayer', FakePlayer)
    monkeypatch.setattr(audio_preview, 'QAudioOutput', FakeOutput)
    # Retain Qt enum values on the test double.
    FakePlayer.MediaStatus = QMediaPlayer.MediaStatus
    FakePlayer.PlaybackState = QMediaPlayer.PlaybackState
    path = tmp_path / 'audio.wav'
    path.touch()
    project = ProjectState(audio_tracks=[
        AudioTrack('a', str(path), 'A', start_time=1, duration=3, volume=.5),
        AudioTrack('b', str(path), 'B', start_time=2, duration=2),
        AudioTrack('silent', str(path), 'Silent', duration=10, volume=0),
    ], current_time=2.5, playback_rate=1.5, is_muted=True)
    preview = audio_preview.AudioPreview()
    preview.sync(project, True)
    a, b = (preview._players[key]['player'] for key in ('a', 'b'))
    assert not a.playing
    project.current_time = 2.8
    preview.sync(project, True)
    a.load()
    b.load()
    assert (a.pos, b.pos, a.rate) == (1800, 800, 1.5)
    assert a.output.volume == .5
    project.current_time = 3.4
    preview.sync(project, True, seek=True)
    assert a.pos == 2400
    project.audio_tracks.pop(0)
    preview.sync(project, True)
    assert a.stopped and b.playing
    preview.sync(project, False)  # paused or held while video loads
    assert b.stopped and not preview._players
    preview.sync(project, True)
    old = preview._players['b']['player']
    preview.sync(ProjectState(), True)  # undo/project replacement
    assert old.stopped and not preview._players


def test_failed_import_and_recording_probe_do_not_add_track(app, tmp_path, monkeypatch):
    project = ProjectState()
    panel = AudioPanel(project, tmp_path)
    path = tmp_path / 'broken.mp3'
    path.write_text('bad audio')
    monkeypatch.setattr('neuroedit_desktop.ui.audio_panel.QFileDialog.getOpenFileName',
                        lambda *args: (str(path), ''))
    monkeypatch.setattr(panel, '_ffmpeg_audio_duration', lambda path: 0)
    panel._import_audio()
    assert not project.audio_tracks
    assert 'Could not read audio duration' in panel.status.text()
    panel._recording_path = path
    panel._recording_project = project
    panel._recording_state_changed(QMediaRecorder.RecorderState.StoppedState)
    assert not project.audio_tracks
    assert panel._recording_path is None
    assert panel.record_btn.isEnabled()
    assert path.exists()


def test_probe_validation_with_real_wav_and_compressed_audio(app, tmp_path):
    import subprocess
    import wave
    import imageio_ffmpeg

    panel = AudioPanel(ProjectState(), tmp_path)
    wav_path = tmp_path / 'tone.wav'
    with wave.open(str(wav_path), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b'\0\0' * 4000)
    assert panel._probe_audio_duration(wav_path) == .5
    mp3_path = tmp_path / 'tone.mp3'
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-y', '-i',
                    str(wav_path), str(mp3_path)], check=True)
    assert .4 < panel._probe_audio_duration(mp3_path) < .7


@pytest.mark.parametrize('duration', [float('nan'), float('inf'), 0, -1])
def test_probe_rejects_nonfinite_or_nonpositive(app, tmp_path, monkeypatch, duration):
    panel = AudioPanel(ProjectState(), tmp_path)
    monkeypatch.setattr(panel, '_ffmpeg_audio_duration', lambda path: duration)
    assert panel._probe_audio_duration(tmp_path / 'test.mp3') == 0


def test_ffmpeg_probe_rejects_timeout_and_video_only(app, tmp_path, monkeypatch):
    import subprocess
    from types import SimpleNamespace

    panel = AudioPanel(ProjectState(), tmp_path)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('ffmpeg', 10)
    monkeypatch.setattr(subprocess, 'run', timeout)
    assert panel._ffmpeg_audio_duration(tmp_path / 'file.mp4') == 0
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(
        stderr='Duration: 00:00:04.00\nStream #0:0: Video: h264'))
    assert panel._ffmpeg_audio_duration(tmp_path / 'file.mp4') == 0


def test_invalid_preview_reports_once(app, tmp_path, monkeypatch):
    monkeypatch.setattr(audio_preview, 'QMediaPlayer', FakePlayer)
    monkeypatch.setattr(audio_preview, 'QAudioOutput', FakeOutput)
    FakePlayer.MediaStatus = QMediaPlayer.MediaStatus
    FakePlayer.PlaybackState = QMediaPlayer.PlaybackState
    path = tmp_path / 'broken.wav'
    path.touch()
    project = ProjectState(audio_tracks=[AudioTrack('a', str(path), 'A', duration=3)])
    preview = audio_preview.AudioPreview()
    errors = []
    preview.error.connect(errors.append)
    preview.sync(project, True)
    player = preview._players['a']['player']
    player.mediaStatusChanged.callback(QMediaPlayer.MediaStatus.InvalidMedia)
    preview.sync(project, True)
    assert len(errors) == 1 and not player.playing
    assert preview._players['a']['player'] is player
