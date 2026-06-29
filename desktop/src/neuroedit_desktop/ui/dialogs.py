from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from neuroedit_desktop.models import ProjectState
from neuroedit_desktop.ui.project_library import relative_time
from neuroedit_desktop.ui.styles import TEXT_MUTED
from neuroedit_desktop.ui.timeline_utils import fmt_time as format_time

if TYPE_CHECKING:
    from neuroedit_desktop.exporter import ExportSettings


def legacy_project_root() -> Path:
    return Path.home() / "Documents" / "NeuroEdit" / "Autosave"


def recommended_project_root() -> Path:
    """A per-user location that cloud-sync services do not mirror by default.
    ~/Documents can be auto-uploaded by iCloud ("Desktop & Documents Folders")
    or OneDrive, which would silently push PHI in masks/stills of an unsaved
    scratch project to a personal cloud account."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "NeuroEdit" / "Autosave"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "NeuroEdit" / "Autosave"
        return Path.home() / "AppData" / "Local" / "NeuroEdit" / "Autosave"
    return Path.home() / ".local" / "share" / "neuroedit" / "Autosave"


def default_project_root() -> Path:
    """Where unsaved scratch projects autosave. Configurable via the one-time
    storage prompt / File menu; defaults to the legacy Documents location for
    existing users who never chose."""
    stored = QSettings("NeuroEdit", "Desktop").value("storage/projectRoot", "")
    if stored:
        return Path(str(stored))
    return legacy_project_root()


def migrate_storage_root(old_root: Path, new_root: Path) -> str | None:
    """Copy the autosave tree from old_root into new_root. Copy, never move:
    the originals are the user's safety net until they verify the new location.
    Returns an error string on failure, None on success."""
    import shutil

    try:
        shutil.copytree(old_root, new_root, dirs_exist_ok=True)
    except OSError as exc:
        return str(exc)
    return None


EXPORT_HISTORY_LIMIT = 20


def load_export_history() -> list[dict]:
    """Recent exports, newest first: {path, report, label, time(epoch s)}."""
    raw = QSettings("NeuroEdit", "Desktop").value("exportHistory", "")
    try:
        data = json.loads(str(raw))
        if isinstance(data, list):
            return [entry for entry in data if isinstance(entry, dict) and entry.get("path")]
    except (ValueError, TypeError):
        pass
    return []


def record_export_history(entry: dict) -> None:
    history = [
        existing for existing in load_export_history()
        if existing.get("path") != entry.get("path")
    ]
    history.insert(0, entry)
    QSettings("NeuroEdit", "Desktop").setValue(
        "exportHistory", json.dumps(history[:EXPORT_HISTORY_LIMIT])
    )



class SamSetupDialog(QDialog):
    """Shown when SAM3 stack is installed but weights are not yet downloaded."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Set Up SAM3")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        intro = QLabel(
            "SAM3 requires a one-time download of <b>~3.2 GB</b> from Meta / HuggingFace.<br><br>"
            "1. <a href='https://huggingface.co/facebook/sam3'>Accept the SAM3 license</a> "
            "&nbsp;(free HuggingFace account required).<br>"
            "2. <a href='https://huggingface.co/settings/tokens'>Create a read token</a> "
            "and paste it below."
        )
        intro.setOpenExternalLinks(True)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        token_label = QLabel("HuggingFace token:")
        self._token_edit = QLineEdit()
        self._token_edit.setPlaceholderText("hf_…")
        # The token is a credential — mask it like a password field.
        self._token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        try:
            from huggingface_hub import get_token
            saved = get_token()
            if saved:
                self._token_edit.setText(saved)
        except Exception:  # noqa: BLE001
            pass
        layout.addWidget(token_label)
        layout.addWidget(self._token_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Download")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def token(self) -> str:
        return self._token_edit.text().strip()


class StorageLocationDialog(QDialog):
    """One-time / on-demand chooser for where unsaved scratch projects autosave.
    Exists because ~/Documents (the legacy default) is cloud-synced on many
    machines, which can silently upload PHI before the user ever hits Save As."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Where NeuroEdit Stores Projects")
        self.setMinimumWidth(520)

        title = QLabel("Where should NeuroEdit store unsaved projects?")
        title.setProperty("role", "title")
        title.setWordWrap(True)
        intro = QLabel(
            "Until you choose Save As, new projects autosave here — including any "
            "video stills and masks, which may contain patient information. "
            "Folders synced to iCloud or OneDrive (often ~/Documents) can upload "
            "that content to a personal cloud account automatically."
        )
        intro.setProperty("role", "muted")
        intro.setWordWrap(True)

        recommended = recommended_project_root()
        legacy = legacy_project_root()
        current = default_project_root()

        self.recommended_radio = QRadioButton(
            f"Recommended — local app folder (not cloud-synced)\n{recommended}"
        )
        self.legacy_radio = QRadioButton(
            f"Documents folder (may be iCloud/OneDrive synced)\n{legacy}"
        )
        self.custom_radio = QRadioButton("Choose a folder…")
        self.custom_path_label = QLabel("")
        self.custom_path_label.setProperty("role", "muted")
        self.custom_path_label.setWordWrap(True)
        self._custom_path: Path | None = None

        if current == recommended:
            self.recommended_radio.setChecked(True)
        elif current == legacy:
            self.recommended_radio.setChecked(True)  # nudge toward the safe choice
        else:
            self.custom_radio.setChecked(True)
            self._custom_path = current
            self.custom_path_label.setText(str(current))

        self.custom_radio.toggled.connect(self._pick_custom)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Use This Location")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addWidget(self.recommended_radio)
        layout.addWidget(self.legacy_radio)
        layout.addWidget(self.custom_radio)
        layout.addWidget(self.custom_path_label)
        layout.addWidget(buttons)

    def _pick_custom(self, checked: bool) -> None:
        if not checked or self._custom_path is not None:
            return
        folder = QFileDialog.getExistingDirectory(
            self, "Choose Project Storage Folder", str(Path.home())
        )
        if folder:
            self._custom_path = Path(folder) / "NeuroEdit" / "Autosave"
            self.custom_path_label.setText(str(self._custom_path))
        else:
            self.recommended_radio.setChecked(True)

    def chosen_root(self) -> Path:
        if self.custom_radio.isChecked() and self._custom_path is not None:
            return self._custom_path
        if self.legacy_radio.isChecked():
            return legacy_project_root()
        return recommended_project_root()


class PhiReviewDialog(QDialog):
    """Guided PHI review: steps the playhead through each timeline item that
    needs human eyes (clips, stills/slides, audio) with a what-to-look-for hint.
    Marking every stop reviewed sets project.phi_review_confirmed."""

    review_completed = Signal()
    seek_requested = Signal(float)

    def __init__(self, project: ProjectState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Guided PHI Review")
        self.setMinimumWidth(460)
        self.stops = self._build_stops(project)
        # Stops are keyed by item id so saved progress survives reordering and
        # newly added media simply appears as an unreviewed stop.
        stop_keys = {key for key, *_rest in self.stops}
        self._reviewed: set[str] = {
            key for key, done in (project.phi_review_progress or {}).items()
            if done and key in stop_keys
        }
        # Resume at the first stop not yet reviewed.
        self._index = 0
        for position, (key, *_rest) in enumerate(self.stops):
            if key not in self._reviewed:
                self._index = position
                break

        self.progress_label = QLabel()
        self.progress_label.setProperty("role", "title")
        self.item_label = QLabel()
        self.item_label.setWordWrap(True)
        self.hint_label = QLabel()
        self.hint_label.setProperty("role", "muted")
        self.hint_label.setWordWrap(True)

        self.back_btn = QPushButton("◀ Back")
        self.back_btn.clicked.connect(self._go_back)
        self.skip_btn = QPushButton("Skip")
        self.skip_btn.setToolTip("Move on without marking this section reviewed.")
        self.skip_btn.clicked.connect(self._go_next)
        self.mark_btn = QPushButton("Mark Reviewed, Next ▶")
        self.mark_btn.setProperty("variant", "cyan")
        self.mark_btn.clicked.connect(self._mark_and_next)

        nav = QHBoxLayout()
        nav.addWidget(self.back_btn)
        nav.addStretch(1)
        nav.addWidget(self.skip_btn)
        nav.addWidget(self.mark_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.item_label)
        layout.addWidget(self.hint_label)
        layout.addLayout(nav)
        self._show_stop()

    @staticmethod
    def _build_stops(project: ProjectState) -> list[tuple[str, str, str, float]]:
        """(item_id, label, hint, seek_time) per timeline item needing review."""
        stops: list[tuple[str, str, str, float]] = []
        clip_hint = (
            "Scrub through this clip. Look for burned-in patient banners, names, "
            "MRNs, dates, faces, tattoos, or room displays. Cover anything found "
            "with the Redact tool."
        )
        for clip in sorted(project.clips, key=lambda c: c.start_time):
            span = (
                f"{format_time(clip.start_time)}–"
                f"{format_time(clip.start_time + clip.display_duration)}"
            )
            kind = "Still image" if clip.media_type == "image" else "Video clip"
            stops.append(
                (clip.id, f"{kind} “{clip.name}” ({span})", clip_hint, clip.start_time)
            )
        slide_hint = (
            "Read every line of slide text and any slide image for patient "
            "identifiers, case numbers, or dates."
        )
        for slide in sorted(project.slides, key=lambda s: s.start_time):
            stops.append(
                (
                    slide.id,
                    f"Slide “{slide.title or 'Untitled'}” ({format_time(slide.start_time)})",
                    slide_hint,
                    slide.start_time,
                )
            )
        audio_hint = (
            "Listen to the narration/audio for spoken identifiers — patient name, "
            "MRN, date of birth, staff full names. The Redact tool does not cover "
            "audio; re-record or remove the track if needed."
        )
        for track in sorted(project.audio_tracks, key=lambda t: t.start_time):
            stops.append(
                (
                    track.id,
                    f"Audio track “{track.name}” ({format_time(track.start_time)})",
                    audio_hint,
                    track.start_time,
                )
            )
        return stops

    def progress_dict(self) -> dict:
        """Per-stop progress to persist on the project, complete or not."""
        return {key: True for key in self._reviewed}

    def _show_stop(self) -> None:
        total = len(self.stops)
        if total == 0:
            self.progress_label.setText("Nothing to review")
            self.item_label.setText("This project has no clips, slides, or audio yet.")
            self.hint_label.setText("")
            self.mark_btn.setEnabled(False)
            self.skip_btn.setEnabled(False)
            self.back_btn.setEnabled(False)
            return
        if self._index >= total:
            self._finish()
            return
        key, label, hint, seek_time = self.stops[self._index]
        reviewed = " ✓ reviewed" if key in self._reviewed else ""
        self.progress_label.setText(f"Section {self._index + 1} of {total}{reviewed}")
        self.item_label.setText(label)
        self.hint_label.setText(hint)
        self.back_btn.setEnabled(self._index > 0)
        self.seek_requested.emit(seek_time)

    def _go_back(self) -> None:
        if self._index > 0:
            self._index -= 1
            self._show_stop()

    def _go_next(self) -> None:
        self._index += 1
        self._show_stop()

    def _mark_and_next(self) -> None:
        if self._index < len(self.stops):
            self._reviewed.add(self.stops[self._index][0])
        self._go_next()

    def _finish(self) -> None:
        # No extra pop-up here: the caller surfaces the outcome in the status
        # bar, and stacking a second modal on dialog close trains users to
        # click through (confirmation fatigue).
        total = len(self.stops)
        if total > 0 and all(key in self._reviewed for key, *_rest in self.stops):
            self.review_completed.emit()
            self.accept()
        else:
            self.reject()


class ExportChecklistDialog(QDialog):
    """Pre-export attestation: one concise dialog (not a chain of pop-ups) that
    requires the three trust-critical confirmations before the export job starts.
    The audio item warns but never blocks. State is pre-filled from the project
    so re-exports don't re-ask what was already confirmed."""

    def __init__(
        self,
        project: ProjectState,
        *,
        export_includes_audio: bool,
        keeps_source_audio: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Before You Export")
        self.setMinimumWidth(500)

        title = QLabel("Confirm before exporting")
        title.setProperty("role", "title")
        intro = QLabel(
            "These confirmations are saved with the project and written into the "
            "export report next to the MP4."
        )
        intro.setProperty("role", "muted")
        intro.setWordWrap(True)

        self.phi_check = QCheckBox(
            "I reviewed the full timeline for on-screen PHI\n"
            "(names, MRNs, dates, faces, monitors, paperwork)"
        )
        self.phi_check.setChecked(project.phi_review_confirmed)
        self.deid_check = QCheckBox(
            "De-identification is complete — redactions cover\nany identifiers found"
        )
        self.deid_check.setChecked(project.deidentified_confirmed)
        self.consent_check = QCheckBox(
            "Patient consent or institutional authorization\nis in place for this use"
        )
        self.consent_check.setChecked(project.consent_confirmed)

        self.guided_btn = QPushButton("Run Guided PHI Review…")
        self.guided_btn.setVisible(not project.phi_review_confirmed)
        self.guided_review_requested = False
        self.guided_btn.clicked.connect(self._request_guided_review)

        self.audio_check = QCheckBox("The audio was reviewed for spoken PHI")
        self.audio_check.setChecked(project.audio_reviewed_for_phi)
        self.audio_warning = QLabel()
        self.audio_warning.setWordWrap(True)
        self.audio_warning.setStyleSheet("color: #f59e0b;")
        audio_note = (
            "This export includes audio. Spoken identifiers (patient name, MRN, "
            "date of birth) are not covered by the Redact tool."
        )
        if keeps_source_audio:
            audio_note += " Original operating-room clip audio is being kept."
        self.audio_warning.setText(audio_note)
        self._export_includes_audio = export_includes_audio
        self.audio_check.setVisible(export_includes_audio)
        self.audio_warning.setVisible(export_includes_audio)
        self.audio_check.toggled.connect(self._update_audio_warning)
        self._update_audio_warning()

        for check in (self.phi_check, self.deid_check, self.consent_check):
            check.toggled.connect(self._update_ok_enabled)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Continue to Export")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addWidget(self.phi_check)
        layout.addWidget(self.guided_btn)
        layout.addWidget(self.deid_check)
        layout.addWidget(self.consent_check)
        layout.addWidget(self.audio_warning)
        layout.addWidget(self.audio_check)
        layout.addWidget(self.buttons)
        self._update_ok_enabled()

    def _request_guided_review(self) -> None:
        self.guided_review_requested = True
        self.reject()

    def _update_ok_enabled(self) -> None:
        required_ok = (
            self.phi_check.isChecked()
            and self.deid_check.isChecked()
            and self.consent_check.isChecked()
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(required_ok)

    def _update_audio_warning(self) -> None:
        # Reviewed audio doesn't need the amber warning anymore.
        if self.audio_check.isChecked():
            self.audio_warning.setStyleSheet(f"color: {TEXT_MUTED};")
        else:
            self.audio_warning.setStyleSheet("color: #f59e0b;")

    def apply_to_project(self, project: ProjectState) -> None:
        project.phi_review_confirmed = self.phi_check.isChecked()
        project.deidentified_confirmed = self.deid_check.isChecked()
        project.consent_confirmed = self.consent_check.isChecked()
        if self._export_includes_audio:
            project.audio_reviewed_for_phi = self.audio_check.isChecked()


def recommended_preset_key(project: ProjectState | None) -> tuple[str, str]:
    """(preset_key, reason) for the export dialog's default selection, from
    source resolution and intended use. Never recommends upscaling, and only
    recommends 4K when the video goal actually targets a big screen."""
    if project is None or not project.clips:
        return "1080p", "the standard choice when no source video is loaded"
    max_height = max((clip.height or 0) for clip in project.clips)
    if 0 < max_height < 1080:
        return "720p", "matches your source resolution (upscaling adds size, not quality)"
    if max_height >= 2160 and project.video_goal in (
        "standalone-publication", "conference",
    ):
        return "4k", "your source is 4K and this video targets a large screen"
    return "1080p", "the best balance for teaching and sharing at your source resolution"


class ExportDialog(QDialog):
    PRESETS = [
        (
            "1080p",
            "Recommended: 1080p MP4",
            "Best default for teaching videos, conference screens, and general sharing.",
            1920,
            1080,
            30,
            20,
        ),
        (
            "720p",
            "Small screen: 720p MP4",
            "Smaller files for quick review, email, or mobile-first viewing.",
            1280,
            720,
            30,
            23,
        ),
        (
            "4k",
            "Big screen / high quality: 4K MP4",
            "Use for large displays or when you want the cleanest export.",
            3840,
            2160,
            30,
            18,
        ),
    ]

    def __init__(self, project: ProjectState | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export Video")
        self.setMinimumWidth(440)
        self._project = project

        title = QLabel("Where will this video be watched?")
        title.setProperty("role", "title")
        title.setWordWrap(True)
        intro = QLabel(
            "Choose the viewing target. NeuroEdit will keep the format simple: "
            "MP4 for the best Mac and Windows compatibility."
        )
        intro.setProperty("role", "muted")
        intro.setWordWrap(True)

        self.preset_combo = QComboBox()
        for key, label, help_text, width, height, fps, crf in self.PRESETS:
            self.preset_combo.addItem(label, (key, width, height, fps, crf, help_text))
        self.preset_combo.currentIndexChanged.connect(self._preset_changed)

        self.help_label = QLabel()
        self.help_label.setProperty("role", "muted")
        self.help_label.setWordWrap(True)

        recommended_key, reason = recommended_preset_key(project)
        recommended_label = next(
            (label for key, label, *_rest in self.PRESETS if key == recommended_key),
            "",
        )
        self.recommend_label = QLabel(
            f"★ Recommended for this project: {recommended_label} — {reason}."
        )
        self.recommend_label.setProperty("role", "muted")
        self.recommend_label.setWordWrap(True)
        self._recommended_key = recommended_key

        self.file_type = QComboBox()
        self.file_type.addItem("MP4 video (.mp4) - highest compatibility", "mp4")
        self.file_type.setEnabled(False)

        self.mute_source_audio_check = QCheckBox(
            "Remove original clip audio (may contain spoken PHI)"
        )
        # Safe default for a clinical tool: drop the original operating-room audio,
        # which can contain spoken identifiers. Narration added on the Audio panel
        # is always kept. The user must deliberately opt in to retaining it.
        self.mute_source_audio_check.setChecked(True)
        self.mute_source_audio_check.setToolTip(
            "Drops the audio recorded with your video clips from the export. "
            "Narration or music you added on the Audio panel is kept."
        )

        self.burn_captions_check = QCheckBox("Burn captions into the video (from transcript)")
        has_transcript = bool(project and project.transcript_segments)
        if has_transcript:
            self.burn_captions_check.setChecked(bool(project and project.captions_enabled))
            self.burn_captions_check.setToolTip(
                "Renders the transcript as open captions in the exported frames. "
                "For toggleable captions, use File → Export Captions (SRT/VTT) "
                "and ship the sidecar file instead."
            )
        else:
            self.burn_captions_check.setChecked(False)
            self.burn_captions_check.setEnabled(False)
            self.burn_captions_check.setToolTip(
                "Add transcript segments on the Audio panel to enable captions."
            )

        form = QFormLayout()
        form.addRow("Viewing target", self.preset_combo)
        form.addRow("File type", self.file_type)
        form.addRow("Privacy", self.mute_source_audio_check)
        form.addRow("Captions", self.burn_captions_check)

        # Advanced settings stay collapsed: presets are the primary interface,
        # and the fields below re-glue to the preset whenever it changes.
        self.advanced_toggle = QPushButton("Advanced settings ▸")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setFlat(True)
        self.advanced_toggle.setStyleSheet("text-align: left; padding: 2px;")
        self.advanced_toggle.toggled.connect(self._toggle_advanced)

        self.crf_spin = QSpinBox()
        self.crf_spin.setRange(12, 32)
        self.crf_spin.setToolTip(
            "Constant Rate Factor: lower = higher quality and bigger files. "
            "18–23 is the practical range for most exports."
        )
        self.fps_combo = QComboBox()
        for fps_value in (24, 25, 30, 50, 60):
            self.fps_combo.addItem(f"{fps_value} fps", fps_value)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(320, 4096)
        self.width_spin.setSingleStep(2)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(240, 2160)
        self.height_spin.setSingleStep(2)
        self.audio_bitrate_combo = QComboBox()
        for kbps in (128, 192, 256):
            self.audio_bitrate_combo.addItem(f"AAC {kbps} kbit/s", kbps)
        self.audio_bitrate_combo.setCurrentIndex(1)  # 192k, the long-standing default

        advanced_form = QFormLayout()
        advanced_form.addRow("Quality (CRF)", self.crf_spin)
        advanced_form.addRow("Frame rate", self.fps_combo)
        advanced_form.addRow("Width", self.width_spin)
        advanced_form.addRow("Height", self.height_spin)
        advanced_form.addRow("Audio", self.audio_bitrate_combo)
        self.advanced_widget = QWidget()
        self.advanced_widget.setLayout(advanced_form)
        self.advanced_widget.setVisible(False)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Choose Save Location")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(intro)
        layout.addWidget(self.recommend_label)
        layout.addLayout(form)
        layout.addWidget(self.help_label)
        layout.addWidget(self.advanced_toggle)
        layout.addWidget(self.advanced_widget)
        layout.addWidget(buttons)
        # Preselect the recommendation; the user can still pick any preset.
        for index in range(self.preset_combo.count()):
            if self.preset_combo.itemData(index)[0] == recommended_key:
                self.preset_combo.setCurrentIndex(index)
                break
        self._preset_changed()

    def export_settings(self, output_path: Path) -> ExportSettings:
        from neuroedit_desktop.exporter import ExportSettings

        return ExportSettings(
            output_path=output_path,
            width=int(self.width_spin.value()),
            height=int(self.height_spin.value()),
            fps=int(self.fps_combo.currentData()),
            crf=int(self.crf_spin.value()),
            label=self.preset_combo.currentText(),
            mute_source_audio=self.mute_source_audio_check.isChecked(),
            burn_captions=self.burn_captions_check.isChecked(),
            audio_bitrate_k=int(self.audio_bitrate_combo.currentData()),
        )

    def _toggle_advanced(self, checked: bool) -> None:
        self.advanced_widget.setVisible(checked)
        self.advanced_toggle.setText(
            "Advanced settings ▾" if checked else "Advanced settings ▸"
        )
        self.adjustSize()

    def _preset_changed(self) -> None:
        _key, width, height, fps, crf, help_text = self.preset_combo.currentData()
        self.help_label.setText(f"{help_text} Output: {width} x {height}, {fps} fps.")
        # Re-glue the advanced fields to the preset so a preset switch always
        # produces exactly the preset, even after manual tweaks.
        self.crf_spin.setValue(int(crf))
        index = self.fps_combo.findData(int(fps))
        self.fps_combo.setCurrentIndex(index if index >= 0 else 2)
        self.width_spin.setValue(int(width))
        self.height_spin.setValue(int(height))


class ExportHistoryDialog(QDialog):
    """Answers "where did my export go?" — recent output files with one-click
    Reveal for the MP4 and its export report."""

    def __init__(self, reveal, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export History")
        self.setMinimumSize(560, 360)
        self._reveal = reveal

        intro = QLabel("Your most recent exports, newest first.")
        intro.setProperty("role", "muted")

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._reveal_selected)

        self.reveal_btn = QPushButton("Reveal File")
        self.reveal_btn.clicked.connect(self._reveal_selected)
        self.reveal_report_btn = QPushButton("Reveal Report")
        self.reveal_report_btn.clicked.connect(self._reveal_report)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addWidget(self.reveal_btn)
        buttons.addWidget(self.reveal_report_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.addWidget(intro)
        layout.addWidget(self.list_widget, 1)
        layout.addLayout(buttons)
        self._populate()

    def _populate(self) -> None:
        self.list_widget.clear()
        for entry in load_export_history():
            path = Path(str(entry.get("path")))
            when = relative_time(float(entry.get("time", 0.0))).replace("Opened", "Exported")
            label = str(entry.get("label", "")).strip()
            missing = "" if path.exists() else "  —  file missing"
            item = QListWidgetItem(f"{path.name}{missing}\n{when}  •  {label}\n{path.parent}")
            item.setData(Qt.ItemDataRole.UserRole, entry)
            if missing:
                item.setForeground(QColor(TEXT_MUTED))
            self.list_widget.addItem(item)
        has_items = self.list_widget.count() > 0
        self.reveal_btn.setEnabled(has_items)
        self.reveal_report_btn.setEnabled(has_items)
        if not has_items:
            self.list_widget.addItem("No exports yet — finished exports will appear here.")

    def _selected_entry(self) -> dict | None:
        item = self.list_widget.currentItem()
        data = item.data(Qt.ItemDataRole.UserRole) if item else None
        return data if isinstance(data, dict) else None

    def _reveal_selected(self, *_args) -> None:
        entry = self._selected_entry()
        if entry and Path(str(entry["path"])).exists():
            self._reveal(Path(str(entry["path"])))

    def _reveal_report(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        report = entry.get("report")
        if report and Path(str(report)).exists():
            self._reveal(Path(str(report)))
