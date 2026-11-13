"""Apply the suite's settings isolation to these repros however they are run.

`tests/conftest.py` only covers files under `tests/`. Without this file a bare
`pytest` from `desktop/` built MainWindow against the user's native NeuroEdit
preferences.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parents[3] / "tests"
# test_window.py reuses the suite's `app` and `window` fixtures.
sys.path.insert(0, str(_TESTS))

_spec = importlib.util.spec_from_file_location("neuroedit_suite_conftest", _TESTS / "conftest.py")
_suite = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_suite)
isolated_app_settings = _suite.isolated_app_settings
