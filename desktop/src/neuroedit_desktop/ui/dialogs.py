from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from neuroedit_desktop import export_plan
from neuroedit_desktop.captions import build_caption_cues
from neuroedit_desktop.export_plan import (
    DEFAULT_EXPORT_NAME,
    QUALITY_PRESETS,
    STANDARD_FPS,
    QualityPreset,
    automatic_fps,
    estimate_encode_seconds,
    estimate_output_bytes,
    format_time_estimate,
    preset_for_key,
    readable_export_name,
    unique_export_path,
)
from neuroedit_desktop.models import ProjectState
from neuroedit_desktop.project_copy import format_bytes
from neuroedit_desktop.ui.editor_panels import (
    project_has_active_audio_tracks,
    project_preflight_warnings,
)
from neuroedit_desktop.ui.project_library import relative_time
from neuroedit_desktop.ui.styles import ACCENT_AMBER, TEXT_MUTED
from neuroedit_desktop.ui.timeline_utils import fmt_time as format_time
from neuroedit_desktop.ui.timeline_utils import project_end_time

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
    storage prompt / File menu; defaults to the local app-support location so
    first-run autosaves do not silently enter cloud-synced Documents folders."""
    stored = QSettings("NeuroEdit", "Desktop").value("storage/projectRoot", "")
    if stored:
        return Path(str(stored))
    return recommended_project_root()


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


# Key in project.phi_review_progress for "caption text was read for PHI". It is
# cleared with the rest of the progress whenever review-relevant content changes.
TRANSCRIPT_REVIEW_KEY = "transcript"


def project_has_transcript_text(project: ProjectState) -> bool:
    return any(segment.text.strip() for segment in project.transcript_segments)


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
        self.item_label.setTextFormat(Qt.TextFormat.PlainText)
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
        if project_has_transcript_text(project):
            text = "\n".join(cue.text for cue in build_caption_cues(project.transcript_segments))
            if len(text) > 800:
                text = text[:800] + "…\n(Only the start is shown here. Read the rest on the Audio panel.)"
            first = min(
                (s.start_time for s in project.transcript_segments if s.text.strip()),
                default=0.0,
            )
            stops.append(
                (
                    TRANSCRIPT_REVIEW_KEY,
                    f"Caption text:\n{text}",
                    "Read the caption text for patient names, MRNs, or dates. "
                    "Captions can be burned into the video or saved as SRT/VTT "
                    "files; edit the text on the Audio panel if needed.",
                    first,
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


EXPORT_FOLDER_KEY = "export/lastFolder"
EXPORT_PIXEL_RATE_KEY = "export/pixelRate"

# Preflight warnings the sheet's privacy gate already covers. Everything else
# in project_preflight_warnings() is shown as a quiet "suggestions" list.
_GATE_WARNING_PREFIXES = (
    "Confirm patient consent",
    "Confirm de-identification",
    "Complete a PHI review",
    "Audio has not been reviewed",
)


def export_suggestions(project: ProjectState) -> list[str]:
    return [
        warning for warning in project_preflight_warnings(project)
        if not warning.startswith(_GATE_WARNING_PREFIXES)
    ]


def default_export_folder() -> Path:
    """The folder used last time, else ~/Movies, else the home folder."""
    remembered = str(QSettings("NeuroEdit", "Desktop").value(EXPORT_FOLDER_KEY, "") or "")
    for candidate in (
        Path(remembered) if remembered else None,
        Path.home() / "Movies",
        Path.home(),
    ):
        if candidate is not None and candidate.is_dir():
            return candidate
    return Path.home()


def _link_button(text: str) -> QPushButton:
    """A borderless text button (the app style gives every QPushButton a frame)."""
    button = QPushButton(text)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet(
        "QPushButton { border: none; background: transparent; text-align: left;"
        " padding: 2px 0px; }"
    )
    return button


class ExportDialog(QDialog):
    """The one export sheet: quality, audio, name and place, and the privacy
    gate, all inline. Export stays disabled until the required confirmations
    hold and the name and folder are usable."""

    def __init__(
        self,
        project: ProjectState | None = None,
        parent: QWidget | None = None,
        *,
        fps_probe=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export")
        self.setMinimumWidth(600)
        project = project if project is not None else ProjectState()
        self._project = project
        prefs = dict(project.export_preferences or {})
        self.guided_review_requested = False
        self._details_open = False

        settings = QSettings("NeuroEdit", "Desktop")
        try:
            self._pixel_rate = float(settings.value(EXPORT_PIXEL_RATE_KEY, 0.0, type=float))
        except (TypeError, ValueError):
            self._pixel_rate = 0.0
        self._duration = project.duration if project.duration > 0 else project_end_time(project)

        # Header
        title = QLabel(project.project_name or DEFAULT_EXPORT_NAME)
        title.setProperty("role", "title")
        title.setWordWrap(True)
        length = QLabel(format_time(self._duration))
        length.setProperty("role", "muted")
        header = QHBoxLayout()
        header.addWidget(title, 1)
        header.addWidget(length, 0, Qt.AlignmentFlag.AlignTop)

        # Quality
        recommended_key, reason = recommended_preset_key(project)
        self._recommended_key = recommended_key
        self._recommended_reason = reason
        chosen_key = prefs.get("quality")
        if chosen_key not in {preset.key for preset in QUALITY_PRESETS}:
            chosen_key = recommended_key
        self.preset_group = QButtonGroup(self)
        self.preset_buttons: dict[str, QRadioButton] = {}
        quality_box = QVBoxLayout()
        quality_box.setSpacing(4)
        for preset in QUALITY_PRESETS:
            button = QRadioButton(preset.label)
            button.setToolTip(preset.help)
            self.preset_group.addButton(button)
            self.preset_buttons[preset.key] = button
            quality_box.addWidget(button)
        self.preset_buttons[chosen_key].setChecked(True)
        self.help_label = QLabel()
        self.help_label.setProperty("role", "muted")
        self.estimate_label = QLabel()
        self.estimate_label.setWordWrap(True)
        quality_box.addWidget(self.help_label)
        quality_box.addWidget(self.estimate_label)

        # Audio and captions
        self.mute_source_audio_check = QCheckBox("Remove original clip audio")
        # Safe default for a clinical tool: drop the original operating-room audio,
        # which can contain spoken identifiers. Narration added on the Audio panel
        # is always kept. The user must deliberately opt in to retaining it.
        self.mute_source_audio_check.setChecked(bool(prefs.get("mute_source_audio", True)))
        self.mute_source_audio_check.setToolTip(
            "Drops the audio recorded with your video clips from the export. "
            "Narration or music you added on the Audio panel is kept."
        )
        privacy_explanation = QLabel(
            "Original audio may contain spoken PHI. Added narration and music are kept."
        )
        privacy_explanation.setProperty("role", "muted")
        privacy_explanation.setWordWrap(True)
        audio_box = QVBoxLayout()
        audio_box.setSpacing(2)
        audio_box.addWidget(self.mute_source_audio_check)
        audio_box.addWidget(privacy_explanation)

        self.burn_captions_check = QCheckBox("Burn in captions (from transcript)")
        if project.transcript_segments:
            self.burn_captions_check.setChecked(
                bool(prefs.get("burn_captions", project.captions_enabled))
            )
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

        # More options (collapsed)
        probe = fps_probe or (lambda path: export_plan.source_fps(path))
        self._auto_fps = automatic_fps(project, probe=probe)
        self.fps_combo = QComboBox()
        self.fps_combo.addItem(f"Automatic (matches your video: {self._auto_fps} fps)", "auto")
        for fps_value in STANDARD_FPS:
            self.fps_combo.addItem(f"{fps_value} fps", fps_value)
        index = self.fps_combo.findData(prefs.get("fps", "auto"))
        self.fps_combo.setCurrentIndex(index if index >= 0 else 0)
        self.audio_bitrate_combo = QComboBox()
        for kbps in (128, 192, 256):
            self.audio_bitrate_combo.addItem(f"{kbps} kbit/s", kbps)
        self.audio_bitrate_combo.setCurrentIndex(1)  # 192k, the long-standing default
        more_form = QFormLayout()
        more_form.setContentsMargins(0, 0, 0, 0)
        more_form.addRow("Frame rate", self.fps_combo)
        more_form.addRow("Audio quality", self.audio_bitrate_combo)
        self.more_widget = QWidget()
        self.more_widget.setLayout(more_form)
        self.more_widget.setVisible(False)
        self.more_toggle = _link_button("More options ▸")
        self.more_toggle.clicked.connect(lambda *_: self._toggle_more())

        # Save as / Where
        self._folder = default_export_folder()
        self._name_is_default = True
        self.name_edit = QLineEdit()
        self.name_edit.setText(self._default_name())
        self.name_edit.textEdited.connect(self._name_edited)
        self.name_edit.textChanged.connect(self._refresh_destination)
        self.replace_note = QLabel("Replaces the existing file")
        self.replace_note.setStyleSheet(f"color: {ACCENT_AMBER};")
        self.folder_label = QLabel()
        self.folder_button = QPushButton("Change…")
        self.folder_button.clicked.connect(self._choose_folder)
        where_row = QHBoxLayout()
        where_row.addWidget(self.folder_label, 1)
        where_row.addWidget(self.folder_button)
        save_box = QVBoxLayout()
        save_box.setSpacing(4)
        save_box.addWidget(self.name_edit)
        save_box.addWidget(self.replace_note)

        # A grid, not a QFormLayout: it sizes wrapped labels correctly.
        form = QGridLayout()
        form.setVerticalSpacing(10)
        form.setColumnStretch(1, 1)
        rows = (
            ("Quality", quality_box), ("Audio", audio_box),
            ("Captions", self.burn_captions_check), ("", self.more_toggle),
            ("", self.more_widget), ("Save as", save_box), ("Where", where_row),
        )
        for row, (caption, content) in enumerate(rows):
            if caption:
                form.addWidget(QLabel(caption), row, 0, Qt.AlignmentFlag.AlignTop)
            if isinstance(content, QWidget):
                form.addWidget(content, row, 1)
            else:
                form.addLayout(content, row, 1)

        # Privacy gate
        privacy_title = QLabel("Privacy")
        privacy_title.setProperty("role", "muted")
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.review_btn = _link_button("Review…")
        self.review_btn.clicked.connect(self._open_details)
        self.privacy_summary = QWidget()
        summary_row = QHBoxLayout(self.privacy_summary)
        summary_row.setContentsMargins(0, 0, 0, 0)
        summary_row.addWidget(self.summary_label, 1)
        summary_row.addWidget(self.review_btn)

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
        self.guided_btn.clicked.connect(self._request_guided_review)
        # Burned-in caption text cannot be covered after export, and it is shown
        # even when the export has no audio.
        self.caption_check = QCheckBox(
            "The caption text was checked for patient information\n"
            "(names, MRNs, dates)"
        )
        self.caption_check.setChecked(
            bool((project.phi_review_progress or {}).get(TRANSCRIPT_REVIEW_KEY))
        )
        self.privacy_details = QWidget()
        details = QVBoxLayout(self.privacy_details)
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(8)
        for widget in (
            self.phi_check, self.guided_btn, self.deid_check, self.consent_check,
            self.caption_check,
        ):
            details.addWidget(widget)

        # The audio item warns but never blocks, so it stays visible whenever the
        # export carries audio, even when the three required items are collapsed.
        self.audio_check = QCheckBox("The audio was reviewed for spoken PHI")
        self.audio_check.setChecked(project.audio_reviewed_for_phi)
        self.audio_warning = QLabel()
        self.audio_warning.setWordWrap(True)
        self.audio_group = QWidget()
        audio_gate = QVBoxLayout(self.audio_group)
        audio_gate.setContentsMargins(0, 0, 0, 0)
        audio_gate.setSpacing(4)
        audio_gate.addWidget(self.audio_warning)
        audio_gate.addWidget(self.audio_check)

        for check in (
            self.phi_check, self.deid_check, self.consent_check, self.caption_check,
        ):
            check.toggled.connect(self._refresh_privacy)
        self.audio_check.toggled.connect(self._refresh_privacy)
        self.mute_source_audio_check.toggled.connect(self._refresh_privacy)
        self.burn_captions_check.toggled.connect(self._refresh_privacy)
        self.preset_group.buttonToggled.connect(lambda *_: self._refresh_estimate())
        self.mute_source_audio_check.toggled.connect(lambda *_: self._refresh_estimate())
        self.fps_combo.currentIndexChanged.connect(lambda *_: self._refresh_estimate())
        self.audio_bitrate_combo.currentIndexChanged.connect(lambda *_: self._refresh_estimate())

        # Suggestions (never blocking)
        self._suggestions = export_suggestions(project)
        count = len(self._suggestions)
        self._suggestions_title = f"{count} suggestion{'s' if count != 1 else ''}"
        self.suggestions_toggle = _link_button(f"{self._suggestions_title} ▸")
        self.suggestions_toggle.setVisible(bool(self._suggestions))
        self.suggestions_toggle.clicked.connect(lambda *_: self._toggle_suggestions())
        self.suggestions_label = QLabel("\n".join(f"• {item}" for item in self._suggestions))
        self.suggestions_label.setProperty("role", "muted")
        self.suggestions_label.setWordWrap(True)
        self.suggestions_label.setVisible(False)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        self.export_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.export_button.setText("Export")
        self.export_button.setDefault(True)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addLayout(form)
        layout.addWidget(privacy_title)
        layout.addWidget(self.privacy_summary)
        layout.addWidget(self.privacy_details)
        layout.addWidget(self.audio_group)
        layout.addWidget(self.suggestions_toggle)
        layout.addWidget(self.suggestions_label)
        layout.addWidget(self.buttons)

        self._refresh_destination()
        self._refresh_estimate()
        self._refresh_privacy()

    # ── choices ──────────────────────────────────────────────────────────

    def selected_preset(self) -> QualityPreset:
        for key, button in self.preset_buttons.items():
            if button.isChecked():
                return preset_for_key(key)
        return preset_for_key(None)

    def selected_fps(self) -> int:
        data = self.fps_combo.currentData()
        return self._auto_fps if data == "auto" else int(data)

    def export_settings(self, output_path: Path | None = None) -> ExportSettings:
        from neuroedit_desktop.exporter import ExportSettings

        preset = self.selected_preset()
        return ExportSettings(
            output_path=output_path if output_path is not None else self.output_path(),
            width=preset.width,
            height=preset.height,
            fps=self.selected_fps(),
            crf=preset.crf,
            label=preset.label,
            mute_source_audio=self.mute_source_audio_check.isChecked(),
            burn_captions=self.burn_captions_check.isChecked(),
            audio_bitrate_k=int(self.audio_bitrate_combo.currentData()),
        )

    def save_preferences(self, project: ProjectState) -> None:
        """Remember this sheet's choices on the project (no undo step)."""
        prefs = dict(project.export_preferences or {})
        prefs["quality"] = self.selected_preset().key
        prefs["mute_source_audio"] = self.mute_source_audio_check.isChecked()
        if self.burn_captions_check.isEnabled():
            prefs["burn_captions"] = self.burn_captions_check.isChecked()
        prefs["fps"] = self.fps_combo.currentData()
        project.export_preferences = prefs

    def remember_folder(self) -> None:
        QSettings("NeuroEdit", "Desktop").setValue(EXPORT_FOLDER_KEY, str(self._folder))

    # ── name and place ───────────────────────────────────────────────────

    def _default_name(self) -> str:
        return unique_export_path(
            self._folder, readable_export_name(self._project.project_name)
        ).stem

    def _name_edited(self, _text: str) -> None:
        self._name_is_default = False

    def _typed_name(self) -> str:
        text = self.name_edit.text().strip()
        if text.lower().endswith(".mp4"):
            text = text[:-4]
        return text.strip(" .")

    def output_path(self) -> Path | None:
        name = self._typed_name()
        if not name:
            return None
        return self._folder / f"{readable_export_name(name)}.mp4"

    def _folder_usable(self) -> bool:
        return self._folder.is_dir() and os.access(self._folder, os.W_OK)

    def _choose_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose Export Folder", str(self._folder)
        )
        if not chosen:
            return
        self._folder = Path(chosen)
        if self._name_is_default:
            self.name_edit.setText(self._default_name())
        self._refresh_destination()

    def _refresh_destination(self, *_args) -> None:
        name = self._folder.name or str(self._folder)
        self.folder_label.setText(name)
        self.folder_label.setToolTip(str(self._folder))
        path = self.output_path()
        self.replace_note.setVisible(path is not None and path.exists())
        self._update_export_enabled()

    # ── estimate ─────────────────────────────────────────────────────────

    def _refresh_estimate(self) -> None:
        preset = self.selected_preset()
        note = f"{preset.width} x {preset.height}"
        if preset.key == self._recommended_key:
            note += " · Recommended for this project"
        self.help_label.setText(note)
        self.help_label.setToolTip(f"{preset.help}\n{self._recommended_reason}")
        if self._duration <= 0:
            self.estimate_label.setText("")
            return
        audio_kbps = int(self.audio_bitrate_combo.currentData()) if self._includes_audio() else None
        size = estimate_output_bytes(
            preset.width, preset.height, self._duration, audio_kbps=audio_kbps
        )
        seconds = estimate_encode_seconds(
            preset.width, preset.height, self.selected_fps(), self._duration,
            pixel_rate=self._pixel_rate or None,
        )
        where = "this Mac" if sys.platform == "darwin" else "this computer"
        self.estimate_label.setText(
            f"About {format_bytes(size)} · {format_time_estimate(seconds)} on {where}"
        )

    def _toggle_more(self) -> None:
        opened = self.more_widget.isHidden()
        self.more_widget.setVisible(opened)
        self.more_toggle.setText("More options ▾" if opened else "More options ▸")
        self.adjustSize()

    def _toggle_suggestions(self) -> None:
        checked = self.suggestions_label.isHidden()
        self.suggestions_label.setVisible(checked)
        self.suggestions_toggle.setText(
            f"{self._suggestions_title} {'▾' if checked else '▸'}"
        )
        self.adjustSize()

    # ── privacy gate ─────────────────────────────────────────────────────

    def _keeps_source_audio(self) -> bool:
        return not self.mute_source_audio_check.isChecked() and any(
            clip.media_type == "video" for clip in self._project.clips
        )

    def _includes_audio(self) -> bool:
        return self._keeps_source_audio() or project_has_active_audio_tracks(self._project)

    def _reviews_captions(self) -> bool:
        return self.burn_captions_check.isChecked() and project_has_transcript_text(
            self._project
        )

    def required_confirmed(self) -> bool:
        return (
            self.phi_check.isChecked()
            and self.deid_check.isChecked()
            and self.consent_check.isChecked()
            and (not self._reviews_captions() or self.caption_check.isChecked())
        )

    def can_export(self) -> bool:
        return (
            self.required_confirmed()
            and bool(self._typed_name())
            and self._folder_usable()
        )

    def _open_details(self) -> None:
        self._details_open = True
        self._refresh_privacy()

    def _request_guided_review(self) -> None:
        # Keep the choices made so far; the caller restarts the sheet afterwards.
        self.save_preferences(self._project)
        self.guided_review_requested = True
        self.reject()

    def _refresh_privacy(self, *_args) -> None:
        reviews_captions = self._reviews_captions()
        self.caption_check.setVisible(reviews_captions)
        if not self.required_confirmed():
            self._details_open = True  # never hide an unchecked required item
        self.privacy_details.setVisible(self._details_open)
        self.privacy_summary.setVisible(not self._details_open)
        self.summary_label.setText(
            "✓ PHI review, de-identification, consent and caption text confirmed"
            if reviews_captions
            else "✓ PHI review, de-identification and consent confirmed"
        )
        includes_audio = self._includes_audio()
        self.audio_group.setVisible(includes_audio)
        note = (
            "This export includes audio. Spoken identifiers (patient name, MRN, "
            "date of birth) are not covered by the Redact tool."
        )
        if self._keeps_source_audio():
            note += " Original operating-room clip audio is being kept."
        self.audio_warning.setText(note)
        # Reviewed audio doesn't need the amber warning anymore.
        colour = TEXT_MUTED if self.audio_check.isChecked() else ACCENT_AMBER
        self.audio_warning.setStyleSheet(f"color: {colour};")
        self._refresh_estimate()
        self._update_export_enabled()

    def _update_export_enabled(self) -> None:
        # Called while the widgets are still being built.
        if hasattr(self, "export_button") and hasattr(self, "audio_group"):
            self.export_button.setEnabled(self.can_export())

    def accept(self) -> None:
        if self.can_export():
            super().accept()

    def apply_to_project(self, project: ProjectState) -> None:
        project.phi_review_confirmed = self.phi_check.isChecked()
        project.deidentified_confirmed = self.deid_check.isChecked()
        project.consent_confirmed = self.consent_check.isChecked()
        if self._includes_audio():
            project.audio_reviewed_for_phi = self.audio_check.isChecked()
        if self._reviews_captions():
            progress = dict(project.phi_review_progress or {})
            if self.caption_check.isChecked():
                progress[TRANSCRIPT_REVIEW_KEY] = True
            else:
                progress.pop(TRANSCRIPT_REVIEW_KEY, None)
            project.phi_review_progress = progress


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
