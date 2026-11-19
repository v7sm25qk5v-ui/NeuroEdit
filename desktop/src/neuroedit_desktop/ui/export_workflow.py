from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QSettings, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QWidget,
)

from neuroedit_desktop import diagnostics
from neuroedit_desktop.models import ProjectState
from neuroedit_desktop.ui import styles as ui_styles
from neuroedit_desktop.ui.dialogs import (
    EXPORT_PIXEL_RATE_KEY,
    TRANSCRIPT_REVIEW_KEY,
    ExportDialog,
    ExportHistoryDialog,
    project_has_transcript_text,
    record_export_history,
)
from neuroedit_desktop.ui.editor_panels import (
    project_has_active_audio_tracks,
    project_preflight_warnings,
)
from neuroedit_desktop.ui.export_worker import ExportWorker
from neuroedit_desktop.ui.main_window_utils import format_time

if TYPE_CHECKING:
    from neuroedit_desktop.exporter import ExportSettings


def project_export_includes_audio(project: ProjectState, *, keeps_source_audio: bool) -> bool:
    return keeps_source_audio or project_has_active_audio_tracks(project)


EXPORT_TOAST_MS = 10_000


class ExportToast(QWidget):
    """Non-modal "Exported ‘name’ · Show in Finder" note that lives in the status
    bar for a few seconds. Never takes focus, never blocks editing."""

    show_requested = Signal()
    dismissed = Signal()

    def __init__(self, file_name: str, notes: list[str] | None = None) -> None:
        super().__init__()
        self.setObjectName("exportToast")
        text = f"Exported “{file_name}”"
        if notes:
            text += f" · {len(notes)} note{'s' if len(notes) != 1 else ''} in the export report"
        self.label = QLabel(text)
        if notes:
            self.label.setToolTip("\n".join(notes))
        self.show_button = QPushButton("Show in Finder" if sys.platform == "darwin" else "Show in folder")
        self.show_button.setFlat(True)
        self.show_button.clicked.connect(self.show_requested)
        self.close_button = QPushButton("×")
        self.close_button.setFlat(True)
        self.close_button.setFixedWidth(24)
        self.close_button.setToolTip("Dismiss")
        self.close_button.clicked.connect(self.dismissed)
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(self.label)
        row.addWidget(self.show_button)
        row.addWidget(self.close_button)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismissed)
        self._timer.start(EXPORT_TOAST_MS)


class ExportWorkflowMixin:
    def _export_is_running(self) -> bool:
        return getattr(self, "_export_worker", None) is not None

    def _export_project(self) -> None:
        if self._export_is_running():
            self.statusBar().showMessage("An export is already running.", 4000)
            return
        self._flush_pending_edits()  # an open slider/text edit belongs in this export's history
        self.project.duration = self._project_end_time()
        if self.project.duration <= 0 or (not self.project.clips and not self.project.slides):
            QMessageBox.information(self, "Export", "Add at least one clip or slide before exporting.")
            return

        while True:
            dialog = ExportDialog(self.project, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                break
            if not dialog.guided_review_requested:
                return
            # The guided review replaces the sheet; come back to it afterwards.
            self._mark_dirty(history=False)  # the sheet saved its choices on the project
            self._start_phi_review()

        dialog.apply_to_project(self.project)
        dialog.save_preferences(self.project)
        dialog.remember_folder()
        self._mark_dirty(history=False)
        self.refresh()
        self._start_export(dialog.export_settings())

    def _show_export_history(self) -> None:
        ExportHistoryDialog(self._reveal_path, self).exec()

    def _export_captions(self) -> None:
        from neuroedit_desktop.captions import build_caption_cues, cues_to_srt, cues_to_vtt

        self._flush_pending_edits()

        if not self.project.transcript_segments:
            QMessageBox.information(
                self,
                "Export Captions",
                "No transcript segments yet. Add or import a transcript on the "
                "Audio panel first.",
            )
            return
        if project_has_transcript_text(self.project) and not (
            self.project.phi_review_progress or {}
        ).get(TRANSCRIPT_REVIEW_KEY):
            reply = QMessageBox.question(
                self,
                "Export Captions",
                "Caption files contain the full transcript text.\n\n"
                "Have you checked it for patient names, MRNs, and dates?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self.project.phi_review_progress = {
                **(self.project.phi_review_progress or {}),
                TRANSCRIPT_REVIEW_KEY: True,
            }
            self._mark_dirty(history=False)
        default_name = self._safe_export_name(self.project.project_name)
        default_path = Path.home() / "Movies" / f"{default_name}.srt"
        path_str, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Captions",
            str(default_path),
            "SubRip captions (*.srt);;WebVTT captions (*.vtt)",
        )
        if not path_str:
            return
        output_path = Path(path_str)
        wants_vtt = "WebVTT" in selected_filter or output_path.suffix.lower() == ".vtt"
        if output_path.suffix.lower() not in (".srt", ".vtt"):
            output_path = output_path.with_suffix(".vtt" if wants_vtt else ".srt")
        cues = build_caption_cues(self.project.transcript_segments)
        content = cues_to_vtt(cues) if wants_vtt else cues_to_srt(cues)
        try:
            output_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Export Captions failed", str(exc))
            return
        self.statusBar().showMessage(f"Captions saved to {output_path}", 5000)

    def _safe_export_name(self, value: str) -> str:
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_", " ") else "_" for ch in value)
        safe = "_".join(safe.strip().split())
        return safe or "NeuroEdit_Export"

    def _clear_export_thread(self, thread: QThread) -> None:
        if getattr(self, "_export_thread", None) is thread:
            self._export_thread = None

    def _start_export(
        self, settings: ExportSettings, project_snapshot: ProjectState | None = None,
    ) -> None:
        if self._export_is_running():
            self.statusBar().showMessage("An export is already running.", 4000)
            return
        previous = getattr(self, "_export_thread", None)
        if previous is not None:
            # The last run already reported; let its thread finish winding down.
            previous.quit()
            previous.wait(3000)
            self._clear_export_thread(previous)
        source = project_snapshot if project_snapshot is not None else self.project
        project_snapshot = ProjectState.from_dict(source.to_dict())
        self._export_report_project = project_snapshot

        thread = QThread(self)
        worker = ExportWorker(project_snapshot, settings)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._export_progress)
        worker.finished.connect(self._export_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._clear_export_thread(t))

        self._export_thread = thread
        self._export_worker = worker
        self._export_worker_settings = settings
        self._export_started_perf = time.perf_counter()
        self._export_first_progress_logged = False
        self._export_canceling = False
        self._export_eta_s = None
        self._export_percent = 0
        diagnostics.log_ffmpeg()
        diagnostics.log(
            "export_start",
            width=settings.width, height=settings.height,
            fps=settings.fps, crf=settings.crf,
            clips=len(project_snapshot.clips),
        )
        self._set_export_button("Exporting…", 0)
        self.statusBar().showMessage("Export started...")
        thread.start()

    # ── toolbar progress pill ─────────────────────────────────────────────

    def _set_export_button(self, text: str, percent: int | None) -> None:
        """The Export button doubles as the progress indicator while exporting."""
        button = self.export_btn
        button.setText(text)
        if percent is None:
            button.setStyleSheet("")
            button.setMinimumWidth(0)
            button.setToolTip("")
            return
        fraction = max(0.0, min(1.0, percent / 100))
        accent = QColor(ui_styles.ACCENT_EMERALD)

        def rgba(alpha: int) -> str:
            return f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, {alpha})"

        fill, rest = rgba(90), rgba(30)
        edge = min(1.0, fraction + 0.002)
        rule = (
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 {fill}, stop:{fraction:.3f} {fill}, stop:{edge:.3f} {rest}, stop:1 {rest}); "
            f"border-color: {rgba(115)}; color: {accent.name()};"
        )
        button.setStyleSheet(f"QPushButton, QPushButton:hover {{ {rule} }}")
        button.setMinimumWidth(210)
        button.setToolTip("Click for options")

    @staticmethod
    def _format_time_left(seconds: float) -> str:
        if seconds < 45:
            return "less than a minute left"
        minutes = max(1, round(seconds / 60))
        if minutes < 60:
            return f"{minutes} min left"
        hours, rest = divmod(minutes, 60)
        return f"{hours} h {rest} min left" if rest else f"{hours} h left"

    def _export_progress(self, value: int, message: str) -> None:
        now = time.perf_counter()
        elapsed = now - getattr(self, "_export_started_perf", now)
        if value > 0 and not getattr(self, "_export_first_progress_logged", True):
            # Export startup latency: time until the pipeline first reports.
            self._export_first_progress_logged = True
            diagnostics.log("export_first_progress", duration_ms=elapsed * 1000.0)
        percent = max(0, min(100, int(value)))
        self._export_percent = percent
        if getattr(self, "_export_canceling", False):
            self.statusBar().showMessage("Canceling export…")
            return
        text = "Exporting…"
        if percent >= 3:
            raw = elapsed * (100 - percent) / percent
            previous = getattr(self, "_export_eta_s", None)
            if previous is None:
                smoothed = raw
            else:
                # Blend the new estimate into the previous one, counted down by the
                # time that passed, so the label does not jump between reports.
                since = now - self._export_eta_at
                smoothed = 0.3 * raw + 0.7 * max(0.0, previous - since)
            self._export_eta_s, self._export_eta_at = smoothed, now
            text = f"Exporting {percent}% · {self._format_time_left(smoothed)}"
        self._set_export_button(text, percent)
        self.statusBar().showMessage(message)

    def _export_button_clicked(self, *_args) -> None:
        if not self._export_is_running():
            self._export_project()
            return
        menu = getattr(self, "_export_menu", None)
        if menu is None:
            menu = QMenu(self.export_btn)
            self._export_cancel_action = menu.addAction("Cancel Export")
            self._export_cancel_action.triggered.connect(lambda *_: self._cancel_export())
            self._export_menu = menu
        self._export_cancel_action.setEnabled(not getattr(self, "_export_canceling", False))
        menu.popup(self.export_btn.mapToGlobal(self.export_btn.rect().bottomLeft()))

    def _cancel_export(self) -> None:
        worker = getattr(self, "_export_worker", None)
        if worker is None or getattr(self, "_export_canceling", False):
            return
        self._export_canceling = True
        worker.cancel()  # only sets a flag, so it is safe from the GUI thread
        self._set_export_button("Canceling…", getattr(self, "_export_percent", 0))
        self.statusBar().showMessage("Canceling export…")

    # ── finishing ─────────────────────────────────────────────────────────

    def _export_finished(self, output_path, error, warnings, details="") -> None:
        self._export_worker = None
        self._export_canceling = False
        self._set_export_button("Export", None)
        started_perf = getattr(self, "_export_started_perf", None)
        diagnostics.log(
            "export_finished",
            duration_ms=(
                (time.perf_counter() - started_perf) * 1000.0 if started_perf else 0.0
            ),
            ok=int(error is None),
        )

        if error:
            if str(error) == "Export canceled.":
                self.statusBar().showMessage("Export canceled.", 3000)
                return
            self.statusBar().showMessage("Export failed.", 5000)
            if self._show_export_failure(str(error), str(details or "")):
                self._start_export(
                    self._export_worker_settings,
                    getattr(self, "_export_report_project", None),
                )
            return

        report_path = self._write_export_report(Path(output_path), warnings)
        record_export_history(
            {
                "path": str(output_path),
                "report": str(report_path) if report_path else "",
                "label": getattr(getattr(self, "_export_worker_settings", None), "label", "")
                or self.project.project_name,
                "time": time.time(),
            }
        )
        self._record_export_speed()
        self.statusBar().clearMessage()
        self._show_export_toast(Path(output_path), list(warnings or []))
        QApplication.alert(self)  # bounce the Dock icon if another app is in front

    def _record_export_speed(self) -> None:
        """Remember how fast this Mac exported, so the next estimate is honest."""
        settings = getattr(self, "_export_worker_settings", None)
        project = getattr(self, "_export_report_project", None)
        started = getattr(self, "_export_started_perf", None)
        if settings is None or project is None or not started:
            return
        wall = time.perf_counter() - started
        if wall < 1.0 or project.duration <= 0:
            return
        rate = settings.width * settings.height * settings.fps * project.duration / wall
        QSettings("NeuroEdit", "Desktop").setValue(EXPORT_PIXEL_RATE_KEY, rate)

    def _show_export_failure(self, message: str, details: str) -> bool:
        """One plain message (raw text under Details). True when the user asks to retry."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Export failed")
        box.setText(message)
        if details.strip():
            box.setDetailedText(details)
        retry = box.addButton("Try Again", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.setDefaultButton(retry)
        box.exec()
        return box.clickedButton() is retry

    def _show_export_toast(self, output_path: Path, notes: list[str]) -> None:
        self._dismiss_export_toast()
        toast = ExportToast(output_path.name, notes)
        toast.show_requested.connect(lambda: self._reveal_path(output_path))
        toast.dismissed.connect(self._dismiss_export_toast)
        self.statusBar().addPermanentWidget(toast)
        self._export_toast = toast

    def _dismiss_export_toast(self) -> None:
        toast = getattr(self, "_export_toast", None)
        self._export_toast = None
        if toast is not None:
            self.statusBar().removeWidget(toast)
            toast.deleteLater()

    @staticmethod
    def _reveal_path(path: Path) -> None:
        """Show the file selected in Finder/Explorer; fall back to opening the
        enclosing folder where selection isn't supported."""
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", "-R", str(path)], check=False)
                return
            if sys.platform == "win32":
                subprocess.run(["explorer", f"/select,{path}"], check=False)
                return
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _write_export_report(self, output_path: Path, export_warnings: list[str]) -> Path | None:
        project = getattr(self, "_export_report_project", None)
        if project is None:
            return None
        # The report may hold case notes, so it stays with the project, never next
        # to the MP4 that people share.
        store = getattr(self, "store", None)
        project_path = getattr(store, "project_path", None)
        if project_path is None:
            return None
        report_path = Path(project_path).parent / "Export Reports" / f"{output_path.stem}.export-report.txt"
        preflight = project_preflight_warnings(project)
        lines = [
            "NOTE: This report may contain case notes and is not de-identified. "
            "Review it before sharing it outside your team.",
            "NeuroEdit Export Report",
            f"Timeline duration: {format_time(project.duration)}",
            "Free-text fields (project name, video goal, audience, storyboard, "
            "edit disclosure) are not included.",
            "",
            "Privacy / distribution",
            f"Consent/authorization confirmed: {project.consent_confirmed}",
            f"Staff notice/consent addressed: {project.staff_notice_confirmed}",
            f"De-identified: {project.deidentified_confirmed}",
            f"PHI review completed: {project.phi_review_confirmed}",
            f"Audio reviewed for spoken PHI: {project.audio_reviewed_for_phi}",
            "",
            "Timeline counts",
            f"Video/image clips: {len(project.clips)}",
            f"Audio tracks: {len(project.audio_tracks)}",
            f"Slides/stills: {len(project.slides)}",
            f"Markers: {len(project.markers)}",
            f"Annotations: {len(project.annotations)}",
            "",
            "Preflight issues at export",
        ]
        lines.extend(f"- {warning}" for warning in preflight or ["None"])
        if export_warnings:
            lines.append("")
            lines.append("Renderer warnings")
            lines.extend(f"- {warning}" for warning in export_warnings)
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            return None
        return report_path
