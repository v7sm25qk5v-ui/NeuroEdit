from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox, QProgressDialog

from neuroedit_desktop import diagnostics
from neuroedit_desktop.exporter import ExportSettings
from neuroedit_desktop.models import ProjectState
from neuroedit_desktop.ui.dialogs import (
    ExportChecklistDialog,
    ExportDialog,
    ExportHistoryDialog,
    record_export_history,
)
from neuroedit_desktop.ui.editor_panels import project_preflight_warnings
from neuroedit_desktop.ui.export_worker import ExportWorker
from neuroedit_desktop.ui.main_window_utils import format_time


class ExportWorkflowMixin:
    def _export_project(self) -> None:
        self.project.duration = self._project_end_time()
        if self.project.duration <= 0 or (not self.project.clips and not self.project.slides):
            QMessageBox.information(self, "Export", "Add at least one clip or slide before exporting.")
            return

        preflight_warnings = project_preflight_warnings(self.project)
        if preflight_warnings:
            message = (
                "NeuroEdit found operative-video preflight issues:\n\n"
                + "\n".join(f"- {warning}" for warning in preflight_warnings[:10])
            )
            if len(preflight_warnings) > 10:
                message += f"\n- ...and {len(preflight_warnings) - 10} more"
            message += "\n\nContinue export anyway?"
            reply = QMessageBox.question(
                self,
                "Export Preflight",
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                self.project.active_panel = "tips"
                self.refresh()
                return

        dialog = ExportDialog(self.project, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        keeps_source_audio = not dialog.mute_source_audio_check.isChecked() and any(
            clip.media_type == "video" for clip in self.project.clips
        )
        includes_audio = keeps_source_audio or bool(self.project.audio_tracks)
        checklist = ExportChecklistDialog(
            self.project,
            export_includes_audio=includes_audio,
            keeps_source_audio=keeps_source_audio,
            parent=self,
        )
        if checklist.exec() != QDialog.DialogCode.Accepted:
            if checklist.guided_review_requested:
                self._start_phi_review()
            return
        checklist.apply_to_project(self.project)
        self._mark_dirty(history=False)
        self.refresh()

        default_name = self._safe_export_name(self.project.project_name)
        default_path = Path.home() / "Movies" / f"{default_name}.mp4"
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save MP4 Export",
            str(default_path),
            "MP4 Video (*.mp4)",
        )
        if not path_str:
            return
        output_path = Path(path_str)
        if output_path.suffix.lower() != ".mp4":
            output_path = output_path.with_suffix(".mp4")
        settings = dialog.export_settings(output_path)
        self._start_export(settings)

    def _show_export_history(self) -> None:
        ExportHistoryDialog(self._reveal_path, self).exec()

    def _export_captions(self) -> None:
        from neuroedit_desktop.captions import build_caption_cues, cues_to_srt, cues_to_vtt

        if not self.project.transcript_segments:
            QMessageBox.information(
                self,
                "Export Captions",
                "No transcript segments yet. Add or import a transcript on the "
                "Audio panel first.",
            )
            return
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

    def _start_export(self, settings: ExportSettings) -> None:
        if getattr(self, "_export_thread", None) is not None:
            QMessageBox.information(self, "Export", "An export is already running.")
            return
        project_snapshot = ProjectState.from_dict(self.project.to_dict())
        self._export_report_project = project_snapshot
        progress = QProgressDialog("Preparing export...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Exporting MP4")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        thread = QThread(self)
        worker = ExportWorker(project_snapshot, settings)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._export_progress)
        worker.finished.connect(self._export_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: setattr(self, "_export_thread", None))
        progress.canceled.connect(worker.cancel)

        self._export_progress_dialog = progress
        self._export_thread = thread
        self._export_worker = worker
        self._export_worker_settings = settings
        self._export_started_perf = time.perf_counter()
        self._export_first_progress_logged = False
        diagnostics.log(
            "export_start",
            width=settings.width, height=settings.height,
            fps=settings.fps, crf=settings.crf,
            clips=len(project_snapshot.clips),
        )
        self.export_btn.setEnabled(False)
        self.statusBar().showMessage("Export started...")
        thread.start()

    def _export_progress(self, value: int, message: str) -> None:
        if value > 0 and not getattr(self, "_export_first_progress_logged", True):
            # Export startup latency: time until the pipeline first reports.
            self._export_first_progress_logged = True
            diagnostics.log(
                "export_first_progress",
                duration_ms=(time.perf_counter() - self._export_started_perf) * 1000.0,
            )
        progress = getattr(self, "_export_progress_dialog", None)
        if progress is not None:
            progress.setLabelText(message)
            progress.setValue(max(0, min(100, int(value))))
        self.statusBar().showMessage(message)

    def _export_finished(self, output_path, error, warnings) -> None:
        progress = getattr(self, "_export_progress_dialog", None)
        if progress is not None:
            progress.close()
        self._export_progress_dialog = None
        self._export_worker = None
        self.export_btn.setEnabled(True)
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
            QMessageBox.critical(self, "Export failed", str(error))
            self.statusBar().showMessage("Export failed.", 5000)
            return

        warning_text = ""
        if warnings:
            warning_text = "\n\nNotes:\n" + "\n".join(f"- {warning}" for warning in warnings)
        report_path = self._write_export_report(Path(output_path), warnings)
        if report_path is not None:
            warning_text += f"\n\nExport report:\n{report_path}"
        record_export_history(
            {
                "path": str(output_path),
                "report": str(report_path) if report_path else "",
                "label": getattr(getattr(self, "_export_worker_settings", None), "label", "")
                or self.project.project_name,
                "time": time.time(),
            }
        )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Export complete")
        box.setText(f"Saved MP4 export:\n{output_path}{warning_text}")
        reveal_mp4_btn = box.addButton("Reveal MP4", QMessageBox.ButtonRole.ActionRole)
        reveal_report_btn = None
        if report_path is not None:
            reveal_report_btn = box.addButton(
                "Reveal Report", QMessageBox.ButtonRole.ActionRole
            )
        box.addButton(QMessageBox.StandardButton.Ok)
        box.setDefaultButton(QMessageBox.StandardButton.Ok)
        box.exec()
        clicked = box.clickedButton()
        if clicked is reveal_mp4_btn:
            self._reveal_path(Path(output_path))
        elif reveal_report_btn is not None and clicked is reveal_report_btn:
            self._reveal_path(report_path)
        self.statusBar().showMessage(f"Exported {output_path}", 5000)

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
        report_path = output_path.with_suffix(".export-report.txt")
        preflight = project_preflight_warnings(project)
        lines = [
            f"NeuroEdit Export Report: {project.project_name}",
            f"Video goal: {project.video_goal}",
            f"Audience: {project.intended_audience or 'Not specified'}",
            f"Timeline duration: {format_time(project.duration)}",
            "",
            "Storyboard",
            f"Objective: {project.storyboard_objective or 'Not specified'}",
            f"Case context: {project.storyboard_case_context or 'Not specified'}",
            f"Key anatomy: {project.storyboard_key_anatomy or 'Not specified'}",
            f"Operative steps: {project.storyboard_steps or 'Not specified'}",
            f"Decision points: {project.storyboard_decision_points or 'Not specified'}",
            f"Pearl/pitfall: {project.storyboard_teaching_pearl or 'Not specified'}",
            f"Final point: {project.storyboard_final_point or 'Not specified'}",
            "",
            "Privacy / distribution",
            f"Consent/authorization confirmed: {project.consent_confirmed}",
            f"Staff notice/consent addressed: {project.staff_notice_confirmed}",
            f"De-identified: {project.deidentified_confirmed}",
            f"PHI review completed: {project.phi_review_confirmed}",
            f"Audio reviewed for spoken PHI: {project.audio_reviewed_for_phi}",
            f"Edit disclosure: {project.edit_disclosure or 'Not specified'}",
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
            report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            return None
        return report_path
