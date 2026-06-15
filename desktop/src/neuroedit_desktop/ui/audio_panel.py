from __future__ import annotations

import re
import subprocess
import time
import wave
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtMultimedia import (
    QAudioInput,
    QMediaCaptureSession,
    QMediaDevices,
    QMediaRecorder,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from neuroedit_desktop.models import AudioTrack, ProjectState, TranscriptSegment, new_id
from neuroedit_desktop.ui.styles import TEXT_PRIMARY
from neuroedit_desktop.ui.timeline_utils import fmt_time, project_end_time


class AudioPanel(QWidget):
    project_changed = Signal()
    seek_requested = Signal(float)
    export_captions_requested = Signal()

    def __init__(self, project: ProjectState, audio_dir: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.audio_dir = audio_dir
        self._refreshing = False
        self._recording_path: Path | None = None
        self._recording_started = 0.0
        self.capture_session = QMediaCaptureSession(self)
        self.recorder = QMediaRecorder(self)
        self.capture_session.setRecorder(self.recorder)
        self.audio_input: QAudioInput | None = None

        title = QLabel("Voice Recorder")
        title.setProperty("role", "title")
        self.status = QLabel("Ready")
        self.status.setProperty("role", "muted")
        self.timer_label = QLabel("0:00.0")
        self.timer_label.setStyleSheet(f"font-size: 24px; font-weight: 800; color: {TEXT_PRIMARY};")

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Recording name...")
        self.record_btn = QPushButton("Record")
        self.record_btn.setProperty("variant", "danger")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.import_btn = QPushButton("Import Audio")
        self.import_btn.setProperty("variant", "cyan")
        self.record_btn.clicked.connect(self._start_recording)
        self.stop_btn.clicked.connect(self._stop_recording)
        self.import_btn.clicked.connect(self._import_audio)

        controls = QHBoxLayout()
        controls.addWidget(self.record_btn)
        controls.addWidget(self.stop_btn)
        controls.addWidget(self.import_btn)

        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._selection_changed)
        self.track_name = QLineEdit()
        self.track_name.textChanged.connect(self._apply_track_fields)
        self.start_input = QDoubleSpinBox()
        self.start_input.setRange(0.0, 24 * 60 * 60)
        self.start_input.setSingleStep(0.5)
        self.start_input.setSuffix(" s")
        self.duration_input = QDoubleSpinBox()
        self.duration_input.setRange(0.1, 24 * 60 * 60)
        self.duration_input.setSingleStep(0.5)
        self.duration_input.setSuffix(" s")
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.start_input.valueChanged.connect(self._apply_track_fields)
        self.duration_input.valueChanged.connect(self._apply_track_fields)
        self.volume_slider.valueChanged.connect(self._apply_track_fields)
        delete_btn = QPushButton("Delete Track")
        delete_btn.setProperty("variant", "danger")
        delete_btn.clicked.connect(self._delete_selected)

        self.audio_phi_check = QCheckBox("Audio reviewed for spoken PHI")
        self.audio_phi_check.setToolTip(
            "Confirm you listened to the narration/audio for spoken identifiers "
            "(patient name, MRN, date of birth). Recorded in the export report; "
            "exports with audio warn when this is unchecked."
        )
        self.audio_phi_check.toggled.connect(self._apply_audio_phi_flag)

        form = QFormLayout()
        form.addRow("Name", self.track_name)
        form.addRow("Start", self.start_input)
        form.addRow("Duration", self.duration_input)
        form.addRow("Volume", self.volume_slider)

        transcript_title = QLabel("Transcript Editing")
        transcript_title.setProperty("role", "title")
        transcript_hint = QLabel(
            "Import or write timestamped transcript segments, then jump the timeline from text."
        )
        transcript_hint.setProperty("role", "muted")
        transcript_hint.setWordWrap(True)

        self.transcript_search = QLineEdit()
        self.transcript_search.setPlaceholderText("Search transcript...")
        self.transcript_search.textChanged.connect(self.refresh_transcript)

        self.transcript_list = QListWidget()
        self.transcript_list.currentItemChanged.connect(self._transcript_selection_changed)
        self.transcript_list.itemDoubleClicked.connect(self._transcript_item_activated)

        import_transcript_btn = QPushButton("Import Transcript")
        import_transcript_btn.setProperty("variant", "cyan")
        add_segment_btn = QPushButton("Add Segment")
        add_segment_btn.clicked.connect(self._add_transcript_segment)
        import_transcript_btn.clicked.connect(self._import_transcript)

        self.segment_start = QDoubleSpinBox()
        self.segment_start.setRange(0.0, 24 * 60 * 60)
        self.segment_start.setSingleStep(0.5)
        self.segment_start.setSuffix(" s")
        self.segment_end = QDoubleSpinBox()
        self.segment_end.setRange(0.0, 24 * 60 * 60)
        self.segment_end.setSingleStep(0.5)
        self.segment_end.setSuffix(" s")
        self.segment_speaker = QLineEdit()
        self.segment_speaker.setPlaceholderText("Narrator, surgeon...")
        self.segment_text = QTextEdit()
        self.segment_text.setAcceptRichText(False)
        self.segment_text.setPlaceholderText("Transcript text...")
        self.segment_text.setFixedHeight(72)
        self.segment_start.valueChanged.connect(self._apply_transcript_fields)
        self.segment_end.valueChanged.connect(self._apply_transcript_fields)
        self.segment_speaker.textChanged.connect(self._apply_transcript_fields)
        self.segment_text.textChanged.connect(self._apply_transcript_fields)

        seek_segment_btn = QPushButton("Jump to Segment")
        seek_segment_btn.clicked.connect(self._seek_selected_transcript)
        delete_segment_btn = QPushButton("Delete Segment")
        delete_segment_btn.setProperty("variant", "danger")
        delete_segment_btn.clicked.connect(self._delete_transcript_segment)

        transcript_buttons = QHBoxLayout()
        transcript_buttons.addWidget(import_transcript_btn)
        transcript_buttons.addWidget(add_segment_btn)

        transcript_actions = QHBoxLayout()
        transcript_actions.addWidget(seek_segment_btn)
        transcript_actions.addWidget(delete_segment_btn)

        transcript_form = QFormLayout()
        transcript_form.addRow("Start", self.segment_start)
        transcript_form.addRow("End", self.segment_end)
        transcript_form.addRow("Speaker", self.segment_speaker)
        transcript_form.addRow("Text", self.segment_text)

        captions_title = QLabel("Captions")
        captions_title.setProperty("role", "title")
        captions_hint = QLabel(
            "Captions are generated from the transcript segments above. Preview "
            "them on the canvas, burn them in at export, or save an SRT/VTT file."
        )
        captions_hint.setProperty("role", "muted")
        captions_hint.setWordWrap(True)

        self.captions_enabled_check = QCheckBox("Show captions on the video")
        self.captions_enabled_check.toggled.connect(self._apply_caption_fields)
        self.caption_size_combo = QComboBox()
        for key, label in (("small", "Small"), ("medium", "Medium"), ("large", "Large")):
            self.caption_size_combo.addItem(label, key)
        self.caption_size_combo.currentIndexChanged.connect(self._apply_caption_fields)
        self.caption_position_combo = QComboBox()
        for key, label in (("bottom", "Bottom"), ("top", "Top")):
            self.caption_position_combo.addItem(label, key)
        self.caption_position_combo.currentIndexChanged.connect(self._apply_caption_fields)
        self.caption_background_check = QCheckBox("Dark background box")
        self.caption_background_check.toggled.connect(self._apply_caption_fields)
        export_captions_btn = QPushButton("Export Captions (SRT/VTT)…")
        export_captions_btn.setProperty("variant", "cyan")
        export_captions_btn.clicked.connect(self.export_captions_requested.emit)

        captions_form = QFormLayout()
        captions_form.addRow("Size", self.caption_size_combo)
        captions_form.addRow("Position", self.caption_position_combo)

        self.clock = QTimer(self)
        self.clock.setInterval(100)
        self.clock.timeout.connect(self._tick_recording)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(self.status)
        layout.addWidget(self.timer_label)
        layout.addWidget(self.name_input)
        layout.addLayout(controls)
        layout.addWidget(QLabel("Audio Tracks"))
        layout.addWidget(self.list_widget, 1)
        layout.addLayout(form)
        layout.addWidget(delete_btn)
        layout.addWidget(self.audio_phi_check)
        layout.addWidget(transcript_title)
        layout.addWidget(transcript_hint)
        layout.addWidget(self.transcript_search)
        layout.addWidget(self.transcript_list, 1)
        layout.addLayout(transcript_buttons)
        layout.addLayout(transcript_form)
        layout.addLayout(transcript_actions)
        layout.addWidget(captions_title)
        layout.addWidget(captions_hint)
        layout.addWidget(self.captions_enabled_check)
        layout.addLayout(captions_form)
        layout.addWidget(self.caption_background_check)
        layout.addWidget(export_captions_btn)
        self.refresh()

    def set_project(self, project: ProjectState, audio_dir: Path | None = None) -> None:
        self.project = project
        if audio_dir is not None:
            self.audio_dir = audio_dir
        self.refresh()

    def select_track(self, track_id: str) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item and str(item.data(Qt.ItemDataRole.UserRole)) == track_id:
                self.list_widget.setCurrentItem(item)
                break

    def _apply_audio_phi_flag(self, checked: bool) -> None:
        if self._refreshing:
            return
        self.project.audio_reviewed_for_phi = checked
        self.project_changed.emit()

    def _apply_caption_fields(self) -> None:
        if self._refreshing:
            return
        self.project.captions_enabled = self.captions_enabled_check.isChecked()
        self.project.caption_size = str(self.caption_size_combo.currentData())
        self.project.caption_position = str(self.caption_position_combo.currentData())
        self.project.caption_background = self.caption_background_check.isChecked()
        self.project_changed.emit()

    def refresh(self) -> None:
        self._refreshing = True
        current_id = self._selected_id()
        self.audio_phi_check.setChecked(self.project.audio_reviewed_for_phi)
        self.captions_enabled_check.setChecked(self.project.captions_enabled)
        size_index = self.caption_size_combo.findData(self.project.caption_size)
        self.caption_size_combo.setCurrentIndex(size_index if size_index >= 0 else 1)
        pos_index = self.caption_position_combo.findData(self.project.caption_position)
        self.caption_position_combo.setCurrentIndex(pos_index if pos_index >= 0 else 0)
        self.caption_background_check.setChecked(self.project.caption_background)
        self.list_widget.clear()
        for track in self.project.audio_tracks:
            item = QListWidgetItem(
                f"{track.name}  |  {fmt_time(track.start_time)}  |  {fmt_time(track.duration)}"
            )
            item.setData(Qt.ItemDataRole.UserRole, track.id)
            self.list_widget.addItem(item)
            if track.id == current_id:
                self.list_widget.setCurrentItem(item)
        if self.list_widget.currentItem() is None and self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
        self._refreshing = False
        self._load_selected_track()
        self.refresh_transcript()

    def _selected_id(self) -> str | None:
        item = self.list_widget.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _selected_track(self) -> AudioTrack | None:
        track_id = self._selected_id()
        if track_id is None:
            return None
        return next((track for track in self.project.audio_tracks if track.id == track_id), None)

    def _selected_transcript_id(self) -> str | None:
        item = self.transcript_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _selected_transcript(self) -> TranscriptSegment | None:
        segment_id = self._selected_transcript_id()
        if segment_id is None:
            return None
        return next(
            (segment for segment in self.project.transcript_segments if segment.id == segment_id),
            None,
        )

    def _selection_changed(self) -> None:
        if not self._refreshing:
            self._load_selected_track()

    def _load_selected_track(self) -> None:
        track = self._selected_track()
        self._refreshing = True
        enabled = track is not None
        self.track_name.setEnabled(enabled)
        self.start_input.setEnabled(enabled)
        self.duration_input.setEnabled(enabled)
        self.volume_slider.setEnabled(enabled)
        if track is None:
            self.track_name.clear()
            self.start_input.setValue(0.0)
            self.duration_input.setValue(0.1)
            self.volume_slider.setValue(100)
        else:
            self.track_name.setText(track.name)
            self.start_input.setValue(track.start_time)
            self.duration_input.setValue(max(0.1, track.duration))
            self.volume_slider.setValue(int(max(0.0, min(1.0, track.volume)) * 100))
        self._refreshing = False
        self.refresh_transcript()

    def _start_recording(self) -> None:
        default_input = QMediaDevices.defaultAudioInput()
        if default_input.isNull():
            self.status.setText("No microphone available.")
            return
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self._recording_path = self.audio_dir / f"voice_{int(time.time())}.m4a"
        self.audio_input = QAudioInput(default_input, self)
        self.capture_session.setAudioInput(self.audio_input)
        self.recorder.setOutputLocation(QUrl.fromLocalFile(str(self._recording_path)))
        self.recorder.record()
        self._recording_started = time.monotonic()
        self.clock.start()
        self.record_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status.setText("Recording...")

    def _stop_recording(self) -> None:
        self.recorder.stop()
        self.clock.stop()
        elapsed = max(0.1, time.monotonic() - self._recording_started)
        path = self._recording_path
        self._recording_path = None
        self.record_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if path is None:
            return
        name = self.name_input.text().strip() or f"Voice {time.strftime('%H:%M:%S')}"
        self.project.audio_tracks.append(
            AudioTrack(
                id=new_id(),
                path=str(path),
                name=name,
                start_time=self.project.current_time,
                duration=elapsed,
                type="voice",
                volume=1.0,
            )
        )
        self.name_input.clear()
        self.project.duration = project_end_time(self.project)
        self.status.setText(f"Saved {name}")
        self.project_changed.emit()
        self.refresh()

    def _tick_recording(self) -> None:
        elapsed = max(0.0, time.monotonic() - self._recording_started)
        self.timer_label.setText(fmt_time(elapsed))

    def _import_audio(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Import Audio",
            str(Path.home()),
            "Audio Files (*.wav *.m4a *.mp3 *.aac *.aiff *.caf);;All Files (*)",
        )
        if not path_str:
            return
        path = Path(path_str)
        duration = self._probe_audio_duration(path)
        self.project.audio_tracks.append(
            AudioTrack(
                id=new_id(),
                path=str(path),
                name=path.stem,
                start_time=self.project.current_time,
                duration=duration,
                type="music",
                volume=1.0,
            )
        )
        self.project.duration = project_end_time(self.project)
        self.project_changed.emit()
        self.refresh()

    def _probe_audio_duration(self, path: Path) -> float:
        if path.suffix.lower() == ".wav":
            try:
                with wave.open(str(path), "rb") as wav:
                    return max(0.1, wav.getnframes() / float(wav.getframerate()))
            except Exception:  # noqa: BLE001
                pass
        # Non-wav (m4a/mp3/aac): probe with the bundled ffmpeg. Falling back to
        # a guessed 5.0 s silently truncated imported audio in the export mix.
        duration = self._ffmpeg_audio_duration(path)
        return duration if duration > 0 else 5.0

    def _ffmpeg_audio_duration(self, path: Path) -> float:
        try:
            import imageio_ffmpeg  # noqa: PLC0415

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            proc = subprocess.run(
                [ffmpeg, "-hide_banner", "-i", str(path)],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            match = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", proc.stderr)
            if match:
                hours, minutes, seconds = match.groups()
                return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        except Exception:  # noqa: BLE001
            pass
        return 0.0

    def _apply_track_fields(self) -> None:
        if self._refreshing:
            return
        track = self._selected_track()
        if track is None:
            return
        track.name = self.track_name.text()
        track.start_time = float(self.start_input.value())
        track.duration = float(self.duration_input.value())
        track.volume = self.volume_slider.value() / 100.0
        self.project.duration = project_end_time(self.project)
        self.project_changed.emit()
        self._refresh_list_labels()

    def _refresh_list_labels(self) -> None:
        for row, track in enumerate(self.project.audio_tracks):
            item = self.list_widget.item(row)
            if item is not None:
                item.setText(f"{track.name}  |  {fmt_time(track.start_time)}  |  {fmt_time(track.duration)}")
                item.setData(Qt.ItemDataRole.UserRole, track.id)

    def refresh_transcript(self) -> None:
        if not hasattr(self, "transcript_list"):
            return
        current_id = self._selected_transcript_id()
        query = self.transcript_search.text().strip().lower()
        selected_track_id = self._selected_id()
        segments = sorted(self.project.transcript_segments, key=lambda segment: segment.start_time)
        self._refreshing = True
        self.transcript_list.clear()
        for segment in segments:
            if selected_track_id and segment.audio_track_id not in (None, selected_track_id):
                continue
            haystack = f"{segment.speaker} {segment.text}".lower()
            if query and query not in haystack:
                continue
            speaker = f"{segment.speaker}: " if segment.speaker else ""
            item = QListWidgetItem(
                f"{fmt_time(segment.start_time)} - {fmt_time(segment.end_time)}\n"
                f"{speaker}{segment.text}"
            )
            item.setData(Qt.ItemDataRole.UserRole, segment.id)
            self.transcript_list.addItem(item)
            if segment.id == current_id:
                self.transcript_list.setCurrentItem(item)
        if self.transcript_list.currentItem() is None and self.transcript_list.count() > 0:
            self.transcript_list.setCurrentRow(0)
        self._refreshing = False
        self._load_selected_transcript()

    def _transcript_selection_changed(self) -> None:
        if not self._refreshing:
            self._load_selected_transcript()

    def _load_selected_transcript(self) -> None:
        segment = self._selected_transcript()
        self._refreshing = True
        enabled = segment is not None
        self.segment_start.setEnabled(enabled)
        self.segment_end.setEnabled(enabled)
        self.segment_speaker.setEnabled(enabled)
        self.segment_text.setEnabled(enabled)
        if segment is None:
            self.segment_start.setValue(0.0)
            self.segment_end.setValue(0.5)
            self.segment_speaker.clear()
            self.segment_text.clear()
        else:
            self.segment_start.setValue(segment.start_time)
            self.segment_end.setValue(max(segment.start_time + 0.1, segment.end_time))
            self.segment_speaker.setText(segment.speaker)
            self.segment_text.setPlainText(segment.text)
        self._refreshing = False

    def _apply_transcript_fields(self) -> None:
        if self._refreshing:
            return
        segment = self._selected_transcript()
        if segment is None:
            return
        segment.start_time = float(self.segment_start.value())
        segment.end_time = max(segment.start_time + 0.1, float(self.segment_end.value()))
        segment.speaker = self.segment_speaker.text()
        segment.text = self.segment_text.toPlainText()
        self.project_changed.emit()
        self._refresh_transcript_list_labels()

    def _refresh_transcript_list_labels(self) -> None:
        for row in range(self.transcript_list.count()):
            item = self.transcript_list.item(row)
            if item is None:
                continue
            segment_id = str(item.data(Qt.ItemDataRole.UserRole))
            segment = next(
                (candidate for candidate in self.project.transcript_segments if candidate.id == segment_id),
                None,
            )
            if segment is None:
                continue
            speaker = f"{segment.speaker}: " if segment.speaker else ""
            item.setText(
                f"{fmt_time(segment.start_time)} - {fmt_time(segment.end_time)}\n"
                f"{speaker}{segment.text}"
            )

    def _add_transcript_segment(self) -> None:
        track = self._selected_track()
        start = track.start_time if track else self.project.current_time
        end = start + 3.0
        if track is not None:
            end = min(track.start_time + max(0.1, track.duration), end)
        segment = TranscriptSegment(
            id=new_id(),
            audio_track_id=track.id if track else None,
            start_time=start,
            end_time=max(start + 0.1, end),
            text="New transcript segment",
        )
        self.project.transcript_segments.append(segment)
        self.project_changed.emit()
        self.refresh_transcript()
        self._select_transcript_segment(segment.id)

    def _select_transcript_segment(self, segment_id: str) -> None:
        for row in range(self.transcript_list.count()):
            item = self.transcript_list.item(row)
            if item and str(item.data(Qt.ItemDataRole.UserRole)) == segment_id:
                self.transcript_list.setCurrentItem(item)
                break

    def _import_transcript(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Import Transcript",
            str(Path.home()),
            "Transcript Files (*.srt *.vtt *.txt);;All Files (*)",
        )
        if not path_str:
            return
        path = Path(path_str)
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            text = path.read_text(encoding="latin-1")
        segments = self._parse_transcript_text(text)
        if not segments:
            self.status.setText("No timestamped transcript segments found.")
            return
        track = self._selected_track()
        track_id = track.id if track else None
        offset = track.start_time if track else 0.0
        imported = [
            TranscriptSegment(
                id=new_id(),
                audio_track_id=track_id,
                start_time=offset + start,
                end_time=offset + max(start + 0.1, end),
                text=segment_text,
                speaker=speaker,
            )
            for start, end, speaker, segment_text in segments
        ]
        self.project.transcript_segments.extend(imported)
        self.status.setText(f"Imported {len(imported)} transcript segment(s).")
        self.project_changed.emit()
        self.refresh_transcript()

    def _parse_transcript_text(self, text: str) -> list[tuple[float, float, str, str]]:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        segments = self._parse_srt_like_transcript(normalized)
        if segments:
            return segments
        return self._parse_line_transcript(normalized)

    def _parse_srt_like_transcript(self, text: str) -> list[tuple[float, float, str, str]]:
        blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
        segments: list[tuple[float, float, str, str]] = []
        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if lines and lines[0].isdigit():
                lines = lines[1:]
            if len(lines) < 2 or "-->" not in lines[0]:
                continue
            start_raw, end_raw = [part.strip() for part in lines[0].split("-->", 1)]
            start = self._parse_timestamp(start_raw)
            end = self._parse_timestamp(end_raw.split()[0])
            if start is None or end is None:
                continue
            speaker, content = self._split_speaker(" ".join(lines[1:]))
            segments.append((start, max(start + 0.1, end), speaker, content))
        return segments

    def _parse_line_transcript(self, text: str) -> list[tuple[float, float, str, str]]:
        segments: list[tuple[float, float, str, str]] = []
        pattern = re.compile(
            r"^\s*(?:\[)?(?P<start>\d{1,2}:\d{2}(?::\d{2})?(?:[\.,]\d+)?)"
            r"(?:\s*(?:-->|-|–|to)\s*"
            r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?(?:[\.,]\d+)?))?"
            r"(?:\])?\s*(?P<text>.*)$"
        )
        pending: list[tuple[float, str, str]] = []
        for line in text.splitlines():
            match = pattern.match(line)
            if match is None:
                continue
            start = self._parse_timestamp(match.group("start"))
            if start is None:
                continue
            end = self._parse_timestamp(match.group("end") or "")
            speaker, content = self._split_speaker(match.group("text").strip())
            if end is not None:
                segments.append((start, max(start + 0.1, end), speaker, content))
            else:
                pending.append((start, speaker, content))
        for index, (start, speaker, content) in enumerate(pending):
            next_start = pending[index + 1][0] if index + 1 < len(pending) else start + 3.0
            segments.append((start, max(start + 0.1, next_start), speaker, content))
        return sorted(segments, key=lambda segment: segment[0])

    def _parse_timestamp(self, value: str) -> float | None:
        if not value:
            return None
        clean = value.strip().replace(",", ".")
        parts = clean.split(":")
        try:
            if len(parts) == 2:
                minutes, seconds = parts
                return int(minutes) * 60 + float(seconds)
            if len(parts) == 3:
                hours, minutes, seconds = parts
                return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        except ValueError:
            return None
        return None

    def _split_speaker(self, text: str) -> tuple[str, str]:
        if ":" not in text:
            return "", text
        speaker, content = text.split(":", 1)
        if len(speaker.split()) <= 3:
            return speaker.strip(), content.strip()
        return "", text

    def _seek_selected_transcript(self) -> None:
        segment = self._selected_transcript()
        if segment is not None:
            self.seek_requested.emit(segment.start_time)

    def _transcript_item_activated(self, item: QListWidgetItem) -> None:
        segment_id = str(item.data(Qt.ItemDataRole.UserRole))
        segment = next(
            (candidate for candidate in self.project.transcript_segments if candidate.id == segment_id),
            None,
        )
        if segment is not None:
            self.seek_requested.emit(segment.start_time)

    def _delete_transcript_segment(self) -> None:
        segment_id = self._selected_transcript_id()
        if segment_id is None:
            return
        self.project.transcript_segments = [
            segment for segment in self.project.transcript_segments if segment.id != segment_id
        ]
        self.project_changed.emit()
        self.refresh_transcript()

    def _delete_selected(self) -> None:
        track_id = self._selected_id()
        if track_id is None:
            return
        self.project.audio_tracks = [track for track in self.project.audio_tracks if track.id != track_id]
        # Keep unattached segments (audio_track_id is None); only drop the
        # deleted track's own segments.
        self.project.transcript_segments = [
            segment for segment in self.project.transcript_segments
            if segment.audio_track_id != track_id
        ]
        self.project.duration = project_end_time(self.project)
        self.project_changed.emit()
        self.refresh()
