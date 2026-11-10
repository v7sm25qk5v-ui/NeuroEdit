#!/usr/bin/env python3
"""Capture baseline UI screenshots before/after brand changes (plan P1.1/P5).

Renders the app offscreen and grabs PNGs of: the full window, header, timeline,
all five right panels, the SAM missing-backend explainer, and every dialog on
the visual-QA checklist (project library, export, export checklist, export
history, PHI review stepper, storage location, SAM setup).

Settings and project storage are isolated in a temporary directory.

Usage:
    python scripts/capture_baseline_screenshots.py [--output DIR]

Default output: desktop/qa/screenshots/<UTC timestamp>/ (gitignored).
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QEventLoop, QSettings, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton, QWidget  # noqa: E402

from neuroedit_desktop.models import (  # noqa: E402
    AudioTrack,
    ProjectState,
    Slide,
    VideoClip,
    new_id,
)
from neuroedit_desktop.sam_backend import SamBackend, SamBackendInfo  # noqa: E402

DEFAULT_OUTPUT = (
    Path(__file__).resolve().parent.parent
    / "qa"
    / "screenshots"
    / datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
)

def _demo_project() -> ProjectState:
    project = ProjectState(project_name="Baseline Capture")
    project.clips.append(
        VideoClip(id=new_id(), path="/tmp/demo.mp4", name="Demo clip", duration=10.0,
                  start_time=0.0, trim_start=0.0, trim_end=10.0)
    )
    project.slides.append(Slide(id=new_id(), title="Demo slide", start_time=10.0))
    project.audio_tracks.append(
        AudioTrack(id=new_id(), path="/tmp/demo.m4a", name="Narration",
                   start_time=0.0, duration=8.0)
    )
    return project


def _grab(widget: QWidget, output: Path, name: str) -> None:
    pixmap = widget.grab()
    target = output / f"{name}.png"
    if pixmap.save(str(target)):
        print(f"  {target.name}  ({pixmap.width()}x{pixmap.height()})")
    else:
        raise RuntimeError(f"Failed to save {target}")


def _settle() -> None:
    loop = QEventLoop()
    QTimer.singleShot(100, loop.quit)
    loop.exec()


def capture(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    tmp_dir = tempfile.TemporaryDirectory(prefix="neuroedit_baseline_")
    tmp_root = tmp_dir.name
    original_settings_init = QSettings.__init__

    def isolated_settings_init(settings, *args, **kwargs):
        if args == ("NeuroEdit", "Desktop"):
            original_settings_init(settings, str(Path(tmp_root) / "settings.ini"),
                                   QSettings.Format.IniFormat, **kwargs)
        else:
            original_settings_init(settings, *args, **kwargs)

    original_probe = SamBackend.probe
    app = None
    settings = None
    window = None
    try:
        QSettings.__init__ = isolated_settings_init
        app = QApplication.instance() or QApplication([])
        SamBackend.probe = lambda self: SamBackendInfo("missing", "none", "stubbed")  # type: ignore[method-assign]
        settings = QSettings("NeuroEdit", "Desktop")
        if Path(settings.fileName()) != Path(tmp_root) / "settings.ini":
            raise RuntimeError("Capture settings are not isolated")
        settings.setValue("storage/projectRoot", str(Path(tmp_root) / "Autosave"))
        settings.setValue("storage/promptShown", True)
        settings.setValue("tutorial/seen", True)
        settings.setValue("recentProjects", [])

        from neuroedit_desktop.ui.styles import apply_app_style

        apply_app_style(app)
        from neuroedit_desktop.ui.main_window import (
            ExportChecklistDialog,
            ExportDialog,
            ExportHistoryDialog,
            MainWindow,
            PhiReviewDialog,
            ProjectLibraryDialog,
            SamSetupDialog,
            StorageLocationDialog,
        )

        window = MainWindow()
        window.resize(1440, 900)
        window.show()
        _settle()

        print(f"Writing screenshots to {output}")
        _grab(window, output, "window_1440x900")
        _grab(window._header_widget, output, "header")
        _grab(window.timeline, output, "timeline")
        window.resize(window.minimumSize())
        _settle()
        _grab(window, output, "window_minimum")
        for label, name in (("Add Video Files…", "media_minimum_add"),
                            ("Link Video Folder…", "media_minimum_link")):
            button = next(button for button in window.media_panel.findChildren(QPushButton)
                          if button.text() == label)
            window.media_scroll.ensureWidgetVisible(button)
            _settle()
            _grab(window.media_scroll, output, name)
        window.media_scroll.verticalScrollBar().setValue(0)
        window.resize(1440, 900)
        _settle()

        for panel in ("sam", "labels", "tips", "slides", "audio"):
            window._set_panel(panel)
            _settle()
            expected = getattr(window, f"{panel}_panel")
            if window.project.active_panel != panel or window.panels.currentWidget() is not expected or not expected.isVisible():
                raise RuntimeError(f"Panel did not settle: {panel}")
            _grab(window.panel_scroll, output, f"panel_{panel}")

        window._set_panel("sam")
        window.sam_panel.show_backend_explainer(deps_missing=True)
        _settle()
        if (window.panels.currentWidget() is not window.sam_panel
                or not window.sam_panel.isVisible() or not window.sam_panel._explainer.isVisible()):
            raise RuntimeError("SAM panel did not settle")
        _grab(window.panel_scroll, output, "panel_sam_missing_backend")
        window.sam_panel.show_backend_ready()

        demo = _demo_project()
        dialogs = [
            ("dialog_project_library", ProjectLibraryDialog(window)),
            ("dialog_export", ExportDialog(demo, window)),
            (
                "dialog_export_checklist",
                ExportChecklistDialog(
                    demo, export_includes_audio=True,
                    keeps_source_audio=True, parent=window,
                ),
            ),
            ("dialog_export_history", ExportHistoryDialog(lambda _p: None, window)),
            ("dialog_phi_review", PhiReviewDialog(demo, window)),
            ("dialog_storage_location", StorageLocationDialog(window)),
            ("dialog_sam_setup", SamSetupDialog(window)),
        ]
        for name, dialog in dialogs:
            dialog.show()
            _settle()
            if not dialog.isVisible():
                raise RuntimeError(f"Dialog did not open: {name}")
            _grab(dialog, output, name)
            dialog.close()
            app.processEvents()

    finally:
        try:
            if window is not None:
                probe_thread = getattr(window, "_sam_probe_thread", None)
                if probe_thread is not None:
                    probe_thread.quit()
                    probe_thread.wait(5_000)
                window.close()
                app.processEvents()
            if settings is not None:
                settings.sync()
        finally:
            SamBackend.probe = original_probe
            QSettings.__init__ = original_settings_init
            tmp_dir.cleanup()
    print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    capture(args.output)


if __name__ == "__main__":
    main()
