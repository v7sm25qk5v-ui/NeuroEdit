from __future__ import annotations

import datetime
import sys
import time
from pathlib import Path

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QDialog, QMessageBox

from neuroedit_desktop import diagnostics
from neuroedit_desktop.models import Annotation, SamPoint, new_id
from neuroedit_desktop.ui.dialogs import SamSetupDialog
from neuroedit_desktop.ui.main_window_utils import (
    MASK_PALETTE,
    format_time,
    hex_to_rgb,
    propagation_window_s,
)
from neuroedit_desktop.ui.sam_workers import (
    SamDownloadWorker,
    SamProbeWorker,
    SamPropagationWorker,
    SamSegmentWorker,
)


class SamWorkflowMixin:
    def _clear_sam_points(self) -> None:
        self.project.sam_points.clear()
        self._mark_dirty()

    def _undo_sam_point(self) -> None:
        if self.project.sam_points:
            self.project.sam_points.pop()
            self._mark_dirty()

    def _set_sam_points_enabled(self, enabled: bool) -> None:
        self.project.sam_points_enabled = enabled
        self._mark_dirty()

    def _start_sam_heartbeat(self, stage: str) -> None:
        self._sam_stage = stage
        self._sam_stage_start = time.monotonic()
        self.sam_panel.set_status(f"{stage} (0s)")
        if not hasattr(self, "_sam_heartbeat_timer"):
            self._sam_heartbeat_timer = QTimer(self)
            self._sam_heartbeat_timer.setInterval(500)
            self._sam_heartbeat_timer.timeout.connect(self._tick_sam_heartbeat)
        self._sam_heartbeat_timer.start()

    def _tick_sam_heartbeat(self) -> None:
        elapsed = int(time.monotonic() - self._sam_stage_start)
        self.sam_panel.set_status(f"{self._sam_stage} ({elapsed}s)")

    def _stop_sam_heartbeat(self) -> None:
        if hasattr(self, "_sam_heartbeat_timer"):
            self._sam_heartbeat_timer.stop()

    def _set_sam_mode(self, mode: str) -> None:
        if mode not in ("positive", "negative"):
            return
        self.project.sam_mode = mode  # type: ignore[assignment]
        self._mark_dirty()

    def _cancel_sam_jobs(self) -> None:
        """Cooperative cancel of whichever SAM worker is running. The download
        worker has no cancel hook (HF transfer is not interruptible), hence the
        getattr guard."""
        for worker_attr in (
            "_sam_segment_worker",
            "_sam_propagation_worker",
            "_sam_probe_worker",
            "_sam_download_worker",
        ):
            worker = getattr(self, worker_attr, None)
            cancel = getattr(worker, "cancel", None)
            if worker is not None and callable(cancel):
                cancel()
                self.statusBar().showMessage("SAM: cancel requested…", 3000)

    def _load_sam_backend(self) -> None:
        # Guard against double-calls while a probe is already in flight
        if getattr(self, "_sam_probe_thread", None) is not None:
            return
        self.sam_panel.set_status("Loading SAM backend… (importing PyTorch)")
        self.sam_panel.set_busy(True)
        self.statusBar().showMessage("Loading SAM backend…")
        diagnostics.log("sam_job", job="probe", state="started")

        self._sam_probe_thread = QThread(self)
        self._sam_probe_worker = SamProbeWorker(self.sam_backend)
        self._sam_probe_worker.moveToThread(self._sam_probe_thread)
        self._sam_probe_thread.started.connect(self._sam_probe_worker.run)
        self._sam_probe_worker.progress.connect(self._on_sam_probe_progress)
        self._sam_probe_worker.finished.connect(self._on_sam_probe_finished)
        self._sam_probe_worker.finished.connect(self._sam_probe_thread.quit)
        self._sam_probe_thread.finished.connect(self._sam_probe_worker.deleteLater)
        self._sam_probe_thread.finished.connect(self._sam_probe_thread.deleteLater)
        self._sam_probe_thread.start()

    def _on_sam_probe_progress(self, message: str) -> None:
        self._start_sam_heartbeat(message)
        self.statusBar().showMessage(f"SAM: {message}")

    def _on_sam_probe_finished(self, info) -> None:  # type: ignore[no-untyped-def]
        self._stop_sam_heartbeat()
        self._sam_probe_thread = None
        self._sam_probe_worker = None
        diagnostics.log("sam_job", job="probe", state="finished", status=info.status)
        cached = self.sam_backend.is_weights_cached()
        self.sam_panel.set_weights_cached(cached)
        if info.status == "missing":
            # Torch / transformers not importable: explain SAM instead of only
            # showing the raw import error.
            self.sam_panel.show_backend_explainer(deps_missing=True)
        elif info.status == "ready" and not cached:
            self.sam_panel.show_backend_explainer(deps_missing=False)
        else:
            self.sam_panel.show_backend_ready()
        if info.status == "ready" and not cached:
            # The inline explainer (with its Download Weights button) is the
            # single setup entry point; auto-opening SamSetupDialog on top of
            # it produced two competing prompts for the same action.
            self.sam_panel.set_status(
                "SAM3 weights not downloaded yet — use Download Weights below."
            )
            self.sam_panel.set_busy(False)
            self.statusBar().showMessage("SAM3 weights not downloaded", 4000)
            return
        label = {
            "ready": info.message or f"SAM ready ({info.device})",
            "unsupported": f"SAM on CPU — {info.message}",
            "missing": f"SAM unavailable — {info.message}",
        }.get(info.status, info.message)
        self.sam_panel.set_status(label)
        self.sam_panel.set_busy(False)
        self.statusBar().showMessage(f"SAM backend: {info.status}", 4000)

    def _show_sam_install_help(self) -> None:
        if getattr(sys, "frozen", False):
            QMessageBox.information(
                self,
                "SAM unavailable in this alpha",
                "This installer is an editor-only alpha and does not include the "
                "optional SAM/PyTorch runtime. Use a SAM-enabled source build for "
                "segmentation and tracking.",
            )
            return
        # There is no in-app installer for the optional SAM stack; point source
        # users at the documented one-line install instead.
        QMessageBox.information(
            self,
            "Install SAM dependencies",
            "The AI components SAM needs (PyTorch + Transformers) are not "
            "installed in this copy of NeuroEdit.\n\n"
            "From a terminal, run:\n\n"
            '    pip install -e ".[sam]"\n\n'
            "from the NeuroEdit desktop folder, then restart NeuroEdit and "
            "reopen the SAM panel.",
        )

    def _show_sam_setup(self) -> None:
        dlg = SamSetupDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.sam_panel.set_status("SAM3 setup cancelled. Reopen the SAM panel to try again.")
            return
        self._start_sam_download(dlg.token())

    def _start_sam_download(self, token: str) -> None:
        self.sam_panel.set_status("Downloading SAM3 weights…")
        self.sam_panel.set_busy(True)
        self.statusBar().showMessage("SAM3: downloading weights…")
        diagnostics.log("sam_job", job="download", state="started")
        self._sam_download_thread = QThread(self)
        self._sam_download_worker = SamDownloadWorker(self.sam_backend, token)
        self._sam_download_worker.moveToThread(self._sam_download_thread)
        self._sam_download_thread.started.connect(self._sam_download_worker.run)
        self._sam_download_worker.progress.connect(self._on_sam_probe_progress)
        self._sam_download_worker.finished.connect(self._on_sam_download_finished)
        self._sam_download_worker.finished.connect(self._sam_download_thread.quit)
        self._sam_download_thread.finished.connect(self._sam_download_worker.deleteLater)
        self._sam_download_thread.finished.connect(self._sam_download_thread.deleteLater)
        self._sam_download_thread.start()

    def _on_sam_download_finished(self, info) -> None:  # type: ignore[no-untyped-def]
        self._stop_sam_heartbeat()
        self._sam_download_thread = None
        self._sam_download_worker = None
        diagnostics.log("sam_job", job="download", state="finished", status=info.status)
        cached = self.sam_backend.is_weights_cached()
        self.sam_panel.set_weights_cached(cached)
        if info.status == "ready":
            self.sam_panel.show_backend_ready()
            self.sam_panel.set_status(info.message or f"SAM3 ready ({info.device})")
            self.statusBar().showMessage("SAM3 ready", 4000)
        else:
            self.sam_panel.set_status(f"Download failed: {info.message}")
            self.statusBar().showMessage("SAM3 download failed", 5000)
        self.sam_panel.set_busy(False)

    def _delete_sam_weights(self) -> None:
        import shutil
        cache = self.sam_backend.weights_cache_dir()
        reply = QMessageBox.question(
            self,
            "Delete SAM3 weights?",
            "This will permanently delete ~3.2 GB of cached SAM3 model weights.\n\n"
            "SAM3 features will stop working until you re-download them.\n\n"
            "Delete the weights?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            shutil.rmtree(cache, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Delete failed", str(exc))
            return
        self.sam_panel.set_weights_cached(False)
        self.sam_panel.set_status("SAM3 weights deleted. Re-open the SAM panel to set up again.")
        self.statusBar().showMessage("SAM3 weights deleted", 4000)

    def _run_segmentation(self) -> None:
        clip = self.project.active_clip
        if not clip:
            QMessageBox.information(self, "No video", "Import a video before running SAM.")
            return
        if not self.project.sam_points:
            QMessageBox.information(
                self, "No prompt points",
                "Place at least one SAM point on the video before running segmentation.",
            )
            return
        if getattr(self, "_sam_segment_thread", None) is not None:
            return

        self.sam_panel.set_status("Running SAM segmentation…")
        self.sam_panel.set_busy(True)
        self.statusBar().showMessage("SAM: running segmentation…")
        self._sam_run_started_iso = datetime.datetime.now().isoformat(timespec="seconds")
        self._sam_run_start_monotonic = time.monotonic()
        diagnostics.log(
            "sam_job", job="segment", state="started",
            points=len(self.project.sam_points),
        )

        mask_dir = self.store.project_path.parent / "masks"
        self._pending_mask_color = self._next_mask_color()
        self._pending_prompt_points = self._current_prompt_points()
        self._sam_job_context = {
            "project": self.project,
            "time_s": self.project.current_time,
            "mask_color": self._pending_mask_color,
            "prompt_points": list(self._pending_prompt_points),
        }
        self._sam_segment_thread = QThread(self)
        self._sam_segment_worker = SamSegmentWorker(
            self.sam_backend,
            Path(clip.path),
            self.project.current_time,
            list(self.project.sam_points),
            mask_dir,
            mask_color=hex_to_rgb(self._pending_mask_color),
        )
        self._sam_segment_worker.moveToThread(self._sam_segment_thread)
        self._sam_segment_thread.started.connect(self._sam_segment_worker.run)
        self._sam_segment_worker.progress.connect(self._on_segment_progress)
        self._sam_segment_worker.finished.connect(self._on_segment_finished)
        self._sam_segment_worker.finished.connect(self._sam_segment_thread.quit)
        self._sam_segment_thread.finished.connect(self._sam_segment_worker.deleteLater)
        self._sam_segment_thread.finished.connect(self._sam_segment_thread.deleteLater)
        self._sam_segment_thread.start()

    def _on_segment_progress(self, message: str) -> None:
        self._start_sam_heartbeat(message)
        self.statusBar().showMessage(f"SAM: {message}")

    def _on_segment_finished(self, result, error) -> None:  # type: ignore[no-untyped-def]
        self._stop_sam_heartbeat()
        self._sam_segment_thread = None
        self._sam_segment_worker = None
        self.sam_panel.set_busy(False)
        context = getattr(self, "_sam_job_context", None) or {}
        if context.get("project", self.project) is not self.project:
            self._discard_sam_result(result)
            self.sam_panel.set_status("Segmentation result discarded after project changed.")
            return
        if error:
            # Single-frame runs stamp sam_last_run just like propagation, so
            # the SAM panel's "Last run" row reflects whichever ran last.
            self.project.sam_last_run = self._sam_run_record("error", 0, "", str(error))
            diagnostics.log("sam_job", job="segment", state="finished", ok=0)
            self.sam_panel.set_status(f"Segmentation failed: {error}")
            self.statusBar().showMessage("SAM: segmentation failed", 5000)
            self._mark_dirty(history=False)
            QMessageBox.critical(self, "SAM segmentation failed", str(error))
            return
        if result is None:
            diagnostics.log("sam_job", job="segment", state="finished", ok=0)
            return
        annotation = Annotation(
            id=new_id(),
            frame_time=float(context.get("time_s", self.project.current_time)),
            ann_duration=0.0,
            type="mask",
            label=self.project.draw_label or f"Mask {self._mask_count() + 1}",
            color=str(context.get("mask_color", self.project.draw_color)),
            visible=True,
            opacity=0.55,
            geometry={},
            mask_path=str(result.mask_path),
            score=float(result.score),
            prompt_points=list(context.get("prompt_points", [])),
        )
        self.project.annotations.append(annotation)
        self.project.sam_last_run = self._sam_run_record("success", 1, result.backend, "")
        diagnostics.log("sam_job", job="segment", state="finished", ok=1)
        self.video_view.annotation_item.invalidate_mask_cache()
        self.sam_panel.set_status(f"{result.backend} mask saved (score {result.score:.2f})")
        self.statusBar().showMessage(
            f"SAM: {result.backend} mask saved (score {result.score:.2f})",
            4000,
        )
        self._mark_dirty(review_relevant=True)

    @staticmethod
    def _discard_sam_result(result) -> None:  # type: ignore[no-untyped-def]
        if result is None:
            return
        paths = []
        mask_path = getattr(result, "mask_path", None)
        if mask_path:
            paths.append(Path(mask_path))
        for frame in getattr(result, "mask_frames", []) or []:
            if path := frame.get("mask_path"):
                paths.append(Path(str(path)))
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _mask_count(self) -> int:
        return sum(1 for a in self.project.annotations if a.type in ("mask", "tracked-mask"))

    def _next_mask_color(self) -> str:
        return MASK_PALETTE[self._mask_count() % len(MASK_PALETTE)]

    def _current_prompt_points(self) -> list[dict]:
        return [
            {"x": float(p.x), "y": float(p.y), "type": p.type}
            for p in self.project.sam_points
        ]

    def _run_propagation(self) -> None:
        clip = self.project.active_clip
        if not clip:
            QMessageBox.information(self, "No video", "Import a video before running propagation.")
            return
        if not self.project.sam_points:
            QMessageBox.information(
                self, "No prompt points",
                "Place at least one SAM point on the video before running propagation.",
            )
            return
        if getattr(self, "_sam_propagation_thread", None) is not None:
            return

        remaining = clip.start_time + clip.display_duration - self.project.current_time
        duration_s = propagation_window_s(
            remaining,
            self.sam_panel.track_to_end_check.isChecked(),
            float(self.sam_panel.track_window_spin.value()),
        )
        self._retrack_target_id = None
        self._pending_prompt_points = self._current_prompt_points()
        self._start_propagation(
            Path(clip.path),
            self.project.current_time,
            duration_s,
            list(self.project.sam_points),
            self._next_mask_color(),
        )

    def _retrack_mask(self, annotation_id: str) -> None:
        """Explicit re-run of propagation for an existing tracked mask, replacing
        its frames in place. Never triggered automatically."""
        ann = self._find_annotation(annotation_id)
        if ann is None or ann.type != "tracked-mask":
            return
        if not ann.prompt_points:
            QMessageBox.information(
                self, "Re-track unavailable",
                "This mask was created before NeuroEdit saved prompt points with "
                "masks, so it cannot be re-tracked. Place new SAM points and run "
                "Video Propagation instead.",
            )
            return
        clip = self.project.active_clip
        if not clip:
            QMessageBox.information(self, "No video", "Import a video before re-tracking.")
            return
        if getattr(self, "_sam_propagation_thread", None) is not None:
            return
        points = [
            SamPoint(
                x=float(p.get("x", 0.0)),
                y=float(p.get("y", 0.0)),
                type="negative" if p.get("type") == "negative" else "positive",
            )
            for p in ann.prompt_points
        ]
        self._retrack_target_id = ann.id
        self._pending_prompt_points = list(ann.prompt_points)
        self._start_propagation(
            Path(clip.path),
            ann.frame_time,
            max(1.0, ann.ann_duration or 5.0),
            points,
            ann.color,
        )

    def _start_propagation(
        self,
        video_path: Path,
        start_time_s: float,
        duration_s: float,
        points: list[SamPoint],
        mask_color_hex: str,
    ) -> None:
        self._pending_mask_color = mask_color_hex
        self._sam_job_context = {
            "project": self.project,
            "retrack_id": getattr(self, "_retrack_target_id", None),
            "prompt_points": list(getattr(self, "_pending_prompt_points", [])),
            "mask_color": mask_color_hex,
        }
        self._sam_run_started_iso = datetime.datetime.now().isoformat(timespec="seconds")
        self._sam_run_start_monotonic = time.monotonic()
        self.sam_panel.set_status(
            f"Tracking {format_time(start_time_s)} → {format_time(start_time_s + duration_s)}…"
        )
        self.sam_panel.set_busy(True)
        self.statusBar().showMessage("SAM: running video propagation…")
        diagnostics.log(
            "sam_job", job="propagate", state="started",
            window_s=f"{duration_s:.1f}",
        )

        mask_dir = self.store.project_path.parent / "masks"
        self._sam_propagation_thread = QThread(self)
        self._sam_propagation_worker = SamPropagationWorker(
            self.sam_backend,
            video_path,
            start_time_s,
            duration_s=duration_s,
            points=points,
            mask_dir=mask_dir,
            sample_rate=2.0,
            mask_color=hex_to_rgb(mask_color_hex),
        )
        self._sam_propagation_worker.moveToThread(self._sam_propagation_thread)
        self._sam_propagation_thread.started.connect(self._sam_propagation_worker.run)
        self._sam_propagation_worker.progress.connect(self._on_propagation_progress)
        self._sam_propagation_worker.finished.connect(self._on_propagation_finished)
        self._sam_propagation_worker.finished.connect(self._sam_propagation_thread.quit)
        self._sam_propagation_thread.finished.connect(self._sam_propagation_worker.deleteLater)
        self._sam_propagation_thread.finished.connect(self._sam_propagation_thread.deleteLater)
        self._sam_propagation_thread.start()

    def _on_propagation_progress(self, message: str) -> None:
        self._start_sam_heartbeat(message)
        self.statusBar().showMessage(f"SAM: {message}")

    def _sam_run_record(self, result: str, frames: int, backend: str, message: str) -> dict:
        elapsed = time.monotonic() - getattr(self, "_sam_run_start_monotonic", time.monotonic())
        return {
            "started_iso": getattr(self, "_sam_run_started_iso", ""),
            "duration_s": round(elapsed, 1),
            "frames": frames,
            "result": result,
            "backend": backend,
            "message": message,
        }

    def _on_propagation_finished(self, result, error) -> None:  # type: ignore[no-untyped-def]
        self._stop_sam_heartbeat()
        self._sam_propagation_thread = None
        self._sam_propagation_worker = None
        self.sam_panel.set_busy(False)
        context = getattr(self, "_sam_job_context", None) or {}
        if context.get("project", self.project) is not self.project:
            self._discard_sam_result(result)
            self.sam_panel.set_status("Propagation result discarded after project changed.")
            return
        diagnostics.log(
            "sam_job", job="propagate", state="finished",
            ok=int(error is None and result is not None and bool(result.mask_frames)),
        )
        retrack_id = context.get("retrack_id")
        self._retrack_target_id = None

        if error:
            self.project.sam_last_run = self._sam_run_record("error", 0, "", str(error))
            self.sam_panel.set_status(f"Propagation failed: {error}")
            self.statusBar().showMessage("SAM: propagation failed", 5000)
            self._mark_dirty(history=False)
            QMessageBox.critical(self, "SAM propagation failed", str(error))
            return
        if result is None or not result.mask_frames:
            self.project.sam_last_run = self._sam_run_record(
                "canceled", 0, "", "Propagation canceled."
            )
            self._mark_dirty(history=False)
            return

        first_time = float(result.mask_frames[0]["time"])
        last_time = float(result.mask_frames[-1]["time"])
        frame_step = 1.0 / result.sample_rate
        ann_duration = max(frame_step, last_time - first_time + frame_step)
        target = self._find_annotation(retrack_id) if retrack_id else None
        if target is not None:
            # Re-track: regenerate the existing annotation's frames in place,
            # keeping its id, label, and color.
            target.frame_time = first_time
            target.ann_duration = ann_duration
            target.mask_path = str(result.mask_frames[0]["mask_path"])
            target.mask_frames = result.mask_frames
            target.score = float(result.score)
            target.sample_rate = float(result.sample_rate)
        else:
            annotation = Annotation(
                id=new_id(),
                frame_time=first_time,
                ann_duration=ann_duration,
                type="tracked-mask",
                label=self.project.draw_label or f"Mask {self._mask_count() + 1}",
                color=str(context.get("mask_color", self.project.draw_color)),
                visible=True,
                opacity=0.55,
                geometry={},
                mask_path=str(result.mask_frames[0]["mask_path"]),
                mask_frames=result.mask_frames,
                score=float(result.score),
                sample_rate=float(result.sample_rate),
                prompt_points=list(context.get("prompt_points", [])),
            )
            self.project.annotations.append(annotation)
            self.project.sam_points.clear()
            self.project.active_panel = "labels"
        self.project.sam_last_run = self._sam_run_record(
            "success", len(result.mask_frames), result.backend, ""
        )
        self.video_view.annotation_item.invalidate_mask_cache()
        self.sam_panel.set_status(
            f"{result.backend} propagation saved {len(result.mask_frames)} frames "
            f"(score {result.score:.2f})"
        )
        self.statusBar().showMessage(
            f"SAM: {result.backend} propagation saved {len(result.mask_frames)} frames",
            4000,
        )
        self._mark_dirty(review_relevant=True)
