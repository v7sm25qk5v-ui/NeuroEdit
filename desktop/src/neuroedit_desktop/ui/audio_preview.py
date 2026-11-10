from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from neuroedit_desktop.models import ProjectState


class AudioPreview(QObject):
    """Keep narration players aligned with the editor's timeline clock."""

    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._players = {}
        self._project = None

    def stop(self) -> None:
        for entry in self._players.values():
            entry["player"].stop()
            entry["player"].deleteLater()
            entry["output"].deleteLater()
        self._players.clear()

    def sync(self, project: ProjectState, playing: bool, *, seek: bool = False) -> None:
        if self._project is not project:
            self.stop()
            self._project = project
        active = (
            {
                track.id: track
                for track in project.audio_tracks
                if track.duration > 0
                and track.volume > 0
                and Path(track.path).exists()
                and track.start_time <= project.current_time < track.start_time + track.duration
            }
            if playing
            else {}
        )
        for track_id, entry in list(self._players.items()):
            track = active.get(track_id)
            if track is None or track.path != entry["path"]:
                entry["player"].stop()
                entry["player"].deleteLater()
                entry["output"].deleteLater()
                del self._players[track_id]
        for track_id, track in active.items():
            entry = self._players.get(track_id)
            if entry is None:
                player = QMediaPlayer(self)
                output = QAudioOutput(self)
                player.setAudioOutput(output)
                entry = {
                    "player": player,
                    "output": output,
                    "path": track.path,
                    "pending": True,
                    "failed": False,
                    "target": max(0, round((project.current_time - track.start_time) * 1000)),
                }
                self._players[track_id] = entry
                player.mediaStatusChanged.connect(lambda status, e=entry: self._loaded(e, status))
                player.setSource(QUrl.fromLocalFile(track.path))
            if entry["failed"]:
                continue
            player = entry["player"]
            entry["target"] = max(0, round((project.current_time - track.start_time) * 1000))
            # QAudioOutput accepts 0..1, while export can amplify up to 2.
            entry["output"].setVolume(min(1.0, max(0.0, track.volume)))
            player.setPlaybackRate(project.playback_rate)
            if entry["pending"]:
                self._loaded(entry, player.mediaStatus())
            elif seek or abs(player.position() - entry["target"]) > 300:
                player.setPosition(entry["target"])
            if (
                not entry["pending"]
                and player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
            ):
                player.play()

    def _loaded(self, entry: dict, status: QMediaPlayer.MediaStatus) -> None:
        if entry not in self._players.values() or not entry["pending"]:
            return
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            entry["pending"] = False
            entry["failed"] = True
            self.error.emit(f"Cannot preview audio: {Path(entry['path']).name}")
        elif status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            entry["pending"] = False
            entry["player"].setPosition(entry["target"])
            entry["player"].play()
