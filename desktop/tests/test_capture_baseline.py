from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_capture_preserves_native_settings_and_cleans_temporary_files(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "capture_baseline_screenshots.py"
    code = '''
import importlib.util
import sys
from pathlib import Path
from PySide6.QtCore import QSettings
settings = QSettings(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, "NeuroEdit", "Desktop")
def snapshot():
    settings.sync()
    return {key: settings.value(key) for key in settings.allKeys()}
before = snapshot()
spec = importlib.util.spec_from_file_location("capture", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
def fail(*args):
    raise RuntimeError("injected capture failure")
original_probe = module.SamBackend.probe
module.capture(Path(sys.argv[2]) / "success")
assert snapshot() == before
module._grab = fail
try:
    module.capture(Path(sys.argv[2]))
except RuntimeError as exc:
    assert str(exc) == "injected capture failure"
else:
    raise AssertionError("capture failure was hidden")
assert module.SamBackend.probe is original_probe
assert snapshot() == before
'''
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", TMPDIR=str(tmp_path))
    proc = subprocess.run(
        [sys.executable, "-c", code, str(script), str(tmp_path / "output")],
        env=env, capture_output=True, text=True, timeout=30, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert not list(tmp_path.glob("neuroedit_baseline_*"))
