"""Diagnostics logging: PHI-safe perf log written outside project folders."""
from __future__ import annotations

import pytest

from neuroedit_desktop import diagnostics


@pytest.fixture()
def diag_log(tmp_path, monkeypatch):
    """Redirect the log file to tmp and force-enable for the test."""
    log_file = tmp_path / "diag.log"
    monkeypatch.setattr(diagnostics, "_log_path", log_file)
    monkeypatch.setattr(diagnostics, "_enabled", True)
    monkeypatch.setattr(diagnostics, "_paint_stats", {})
    return log_file


def test_log_writes_timestamped_event(diag_log):
    diagnostics.log("project_load", duration_ms=12.34, clips=3, source="dialog")
    line = diag_log.read_text(encoding="utf-8").strip()
    assert "project_load" in line
    assert "duration_ms=12.3" in line
    assert "clips=3" in line
    assert "source=dialog" in line


def test_log_noop_when_disabled(diag_log, monkeypatch):
    monkeypatch.setattr(diagnostics, "_enabled", False)
    diagnostics.log("event")
    assert not diag_log.exists()


def test_timed_context_manager_records_duration(diag_log):
    with diagnostics.timed("export_start", clips=1):
        pass
    line = diag_log.read_text(encoding="utf-8").strip()
    assert "export_start" in line
    assert "duration_ms=" in line


def test_record_paint_logs_over_budget_immediately(diag_log):
    diagnostics.record_paint("timeline_paint", diagnostics.FRAME_BUDGET_MS + 10.0)
    line = diag_log.read_text(encoding="utf-8")
    assert "timeline_paint" in line
    assert "over_budget=1" in line


def test_record_paint_summarizes_fast_paints(diag_log):
    for _ in range(diagnostics._SUMMARY_EVERY):
        diagnostics.record_paint("canvas_paint", 1.0)
    text = diag_log.read_text(encoding="utf-8")
    assert "canvas_paint_summary" in text
    assert f"count={diagnostics._SUMMARY_EVERY}" in text
    # Fast paints themselves are aggregated, not logged line-by-line.
    assert text.count("\n") == 1


def test_log_dir_is_outside_project_storage():
    log_dir = str(diagnostics.log_dir())
    assert "Autosave" not in log_dir
    assert "NeuroEdit" in log_dir or "neuroedit" in log_dir
