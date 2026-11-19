"""Exercise export control through real Qt worker-thread signal delivery."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton

from neuroedit_desktop.exporter import ExportCancelled, ExportSettings, ProjectExporter
from neuroedit_desktop.models import ProjectState
from neuroedit_desktop.ui.export_workflow import ExportWorkflowMixin


def test_main_window_import_keeps_exporter_lazy():
    result = subprocess.run(
        [sys.executable, "-c", (
            "import sys; import neuroedit_desktop.ui.main_window; "
            "assert 'neuroedit_desktop.exporter' not in sys.modules"
        )],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_cancel_reaches_export_while_worker_is_busy(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    entered = threading.Event()
    canceled = threading.Event()

    def export(exporter):
        entered.set()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if exporter.cancelled():
                canceled.set()
                raise ExportCancelled()
            time.sleep(0.005)
        return []

    class ExportWindow(ExportWorkflowMixin, QMainWindow):
        def __init__(self):
            super().__init__()
            self.project = ProjectState()
            self.export_btn = QPushButton("Export", self)

    monkeypatch.setattr(ProjectExporter, "export", export)
    window = ExportWindow()
    window._start_export(ExportSettings(
        output_path=tmp_path / "out.mp4", width=64, height=64, fps=30, crf=23, label="Test",
    ))
    thread = window._export_thread
    try:
        assert entered.wait(2.0), "Export worker never started"
        assert window.export_btn.text().startswith("Exporting")
        # A click while exporting opens a menu instead of starting another export.
        window._export_button_clicked()
        window._export_menu.actions()[0].trigger()
        deadline = time.monotonic() + 3.0
        while window._export_thread is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        assert canceled.is_set(), "Cancel was queued behind the running export"
        assert window._export_thread is None
        assert window.statusBar().currentMessage() == "Export canceled."
        assert window.export_btn.text() == "Export"
    finally:
        if window._export_thread is not None:
            thread.quit()
            thread.wait(3000)
        window.close()
        window.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
