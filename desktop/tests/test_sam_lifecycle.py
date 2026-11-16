"""NE-024: SAM weight cache detection, deletion, model warm-up and mask cleanup.

Everything is stubbed: torch/transformers/huggingface_hub are never imported and
every cache directory lives under tmp_path.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from neuroedit_desktop.models import SamPoint
from neuroedit_desktop.sam_backend import SamBackend, SamCancelled


@pytest.fixture
def hub(tmp_path, monkeypatch) -> Path:
    base = tmp_path / "hub"
    base.mkdir()
    monkeypatch.setenv("HF_HUB_CACHE", str(base))
    return base


def _make_model_cache(hub: Path, name: str, *, weights: bool, incomplete: bool = False) -> Path:
    cache = hub / name
    blobs = cache / "blobs"
    snap = cache / "snapshots" / "abc123"
    blobs.mkdir(parents=True)
    snap.mkdir(parents=True)
    (blobs / "cfg").write_text("{}")
    (snap / "config.json").symlink_to(blobs / "cfg")
    if weights:
        (blobs / "w").write_bytes(b"x")
        (snap / "model.safetensors").symlink_to(blobs / "w")
    if incomplete:
        (blobs / "deadbeef.incomplete").write_bytes(b"partial")
    return cache


# -- is_weights_cached ------------------------------------------------------


def test_config_only_snapshot_is_not_cached(hub):
    _make_model_cache(hub, "models--facebook--sam3", weights=False)
    assert SamBackend().is_weights_cached() is False


def test_complete_weights_are_cached(hub):
    _make_model_cache(hub, "models--facebook--sam3", weights=True)
    assert SamBackend().is_weights_cached() is True


def test_incomplete_blob_means_not_cached(hub):
    _make_model_cache(hub, "models--facebook--sam3", weights=True, incomplete=True)
    assert SamBackend().is_weights_cached() is False


def test_dangling_weight_link_is_not_cached(hub):
    cache = _make_model_cache(hub, "models--facebook--sam3", weights=True)
    (cache / "blobs" / "w").unlink()
    assert SamBackend().is_weights_cached() is False


def test_missing_cache_is_not_cached(hub):
    assert SamBackend().is_weights_cached() is False


# -- delete_weights ----------------------------------------------------------


def test_delete_removes_only_managed_dirs(hub):
    sam3 = _make_model_cache(hub, "models--facebook--sam3", weights=True)
    sam1 = _make_model_cache(hub, "models--facebook--sam-vit-base", weights=True)
    other = _make_model_cache(hub, "models--someone--else", weights=True)
    (hub / "unrelated.txt").write_text("keep")

    removed, failed = SamBackend().delete_weights()

    assert failed == []
    assert set(removed) == {sam3, sam1}
    assert not sam3.exists() and not sam1.exists()
    assert other.exists() and (hub / "unrelated.txt").exists()


def test_delete_never_follows_symlinks_out_of_the_cache(hub, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "precious.txt").write_text("keep")
    cache = _make_model_cache(hub, "models--facebook--sam3", weights=True)
    (cache / "escape").symlink_to(outside, target_is_directory=True)

    removed, failed = SamBackend().delete_weights()

    assert failed == [] and removed == [cache]
    assert (outside / "precious.txt").read_text() == "keep"


def test_delete_of_symlinked_cache_dir_removes_link_only(hub, tmp_path):
    target = tmp_path / "real_cache"
    target.mkdir()
    (target / "precious.txt").write_text("keep")
    (hub / "models--facebook--sam3").symlink_to(target, target_is_directory=True)

    removed, failed = SamBackend().delete_weights()

    assert failed == [] and len(removed) == 1
    assert (target / "precious.txt").exists()
    assert not (hub / "models--facebook--sam3").is_symlink()


def test_delete_reports_failure_truthfully(hub, monkeypatch):
    cache = _make_model_cache(hub, "models--facebook--sam3", weights=True)

    def boom(path, *args, **kwargs):
        raise PermissionError("permission denied")

    monkeypatch.setattr("neuroedit_desktop.sam_backend.shutil.rmtree", boom)
    removed, failed = SamBackend().delete_weights()

    assert removed == []
    assert [p for p, _ in failed] == [cache]
    assert "permission denied" in failed[0][1]
    assert cache.exists()


def test_delete_drops_loaded_models(hub):
    backend = SamBackend()
    backend._sam3_tracker_model = object()
    backend._sam3_video_model = object()
    backend._sam1_model = object()
    backend.delete_weights()
    assert backend._sam3_tracker_model is None
    assert backend._sam3_video_model is None
    assert backend._sam1_model is None


def test_managed_dirs_stay_inside_given_cache_base(hub):
    for path in SamBackend().managed_cache_dirs():
        assert path.parent == hub
        assert path.name.startswith("models--facebook--")


# -- warm-up and loading status ---------------------------------------------


def test_warmup_loads_the_tracker_model_the_first_click_uses(monkeypatch):
    from neuroedit_desktop.sam_backend import SamBackendInfo

    backend = SamBackend()
    monkeypatch.setattr(backend, "probe", lambda: SamBackendInfo("ready", "cpu", "ok"))
    calls = []
    monkeypatch.setattr(backend, "_ensure_sam3_tracker_model", lambda: calls.append("tracker"))
    monkeypatch.setattr(backend, "_ensure_sam3_video_model", lambda: calls.append("video"))
    assert backend.warmup().status == "ready"
    assert calls == ["tracker"]


def test_segment_reports_loading_model_when_not_resident(monkeypatch, tmp_path):
    np = pytest.importorskip("numpy")
    backend = SamBackend()
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    monkeypatch.setattr(backend, "_grab_frame", lambda *_a: frame)
    monkeypatch.setattr(backend, "_run_sam3_on_frame", lambda *_a: (np.ones((4, 4)), 0.9))
    monkeypatch.setattr(backend, "_save_mask_rgba", lambda *_a, **_k: None)
    messages: list[str] = []
    backend.segment_frame(
        tmp_path / "v.mp4", 0.0, [SamPoint(0.5, 0.5)], tmp_path / "m", progress=messages.append
    )
    assert any("Loading SAM3 model" in m for m in messages)
    messages.clear()
    backend._sam3_tracker_model = object()  # now resident: no loading message
    backend.segment_frame(
        tmp_path / "v.mp4", 0.0, [SamPoint(0.5, 0.5)], tmp_path / "m", progress=messages.append
    )
    assert not any("Loading" in m for m in messages)


# -- partial mask cleanup -----------------------------------------------------


def _write_png_stub(self_, mask, shape, path, color=None):
    Path(path).write_bytes(b"png")


def test_sam1_propagation_cleans_up_on_cancel(monkeypatch, tmp_path):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    backend = SamBackend()
    cap = Mock()
    cap.isOpened.return_value = True
    monkeypatch.setattr(cv2, "VideoCapture", lambda _p: cap)
    monkeypatch.setattr(backend, "_ensure_sam1_model", lambda: None)
    monkeypatch.setattr(backend, "_video_duration", lambda _c: 20.0)
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    monkeypatch.setattr(backend, "_read_frame_from_capture", lambda *_a: frame)
    monkeypatch.setattr(backend, "_run_sam1_on_frame", lambda *_a: (np.ones((8, 8)), 0.9))
    monkeypatch.setattr(cv2, "calcOpticalFlowPyrLK", lambda *a, **k: (None, None, None))
    monkeypatch.setattr(SamBackend, "_save_mask_rgba", _write_png_stub)
    state = {"n": 0}

    def cancelled():
        state["n"] += 1
        return state["n"] > 2  # two frames written, then cancel

    with pytest.raises(SamCancelled):
        backend._propagate_video_sam1(
            tmp_path / "c.mp4", 0.0, 3.0, [SamPoint(0.5, 0.5)], tmp_path,
            sample_rate=2.0, cancelled=cancelled, run_id="r",
        )
    assert list(tmp_path.glob("*.png")) == []
    cap.release.assert_called_once()


def test_sam1_propagation_cleans_up_on_failure(monkeypatch, tmp_path):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    backend = SamBackend()
    cap = Mock()
    cap.isOpened.return_value = True
    monkeypatch.setattr(cv2, "VideoCapture", lambda _p: cap)
    monkeypatch.setattr(backend, "_ensure_sam1_model", lambda: None)
    monkeypatch.setattr(backend, "_video_duration", lambda _c: 20.0)
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    monkeypatch.setattr(backend, "_read_frame_from_capture", lambda *_a: frame)
    monkeypatch.setattr(cv2, "calcOpticalFlowPyrLK", lambda *a, **k: (None, None, None))
    monkeypatch.setattr(SamBackend, "_save_mask_rgba", _write_png_stub)
    calls = {"n": 0}

    def flaky(*_a):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("inference blew up")
        return np.ones((8, 8)), 0.9

    monkeypatch.setattr(backend, "_run_sam1_on_frame", flaky)
    with pytest.raises(RuntimeError):
        backend._propagate_video_sam1(
            tmp_path / "c.mp4", 0.0, 3.0, [SamPoint(0.5, 0.5)], tmp_path,
            sample_rate=2.0, run_id="r",
        )
    assert list(tmp_path.glob("*.png")) == []


def test_sam3_failure_removes_partial_masks_before_sam1_fallback(monkeypatch, tmp_path):
    """A SAM3 run that wrote frames then failed must not leave them behind
    when propagate_video falls back to SAM1."""
    backend = SamBackend()
    leftovers_seen_by_fallback: list[list[str]] = []

    def fake_sam3(*_a, mask_dir, **_k):
        written = [mask_dir / "track_sam3_a.png", mask_dir / "track_sam3_b.png"]
        for p in written:
            p.write_bytes(b"png")
        try:
            raise RuntimeError("sam3 died")
        except BaseException:
            backend._unlink_quietly(written)  # what the real method does
            raise

    def fake_sam1(*_a, mask_dir, **_k):
        leftovers_seen_by_fallback.append(sorted(p.name for p in mask_dir.glob("*.png")))
        return "fallback-result"

    monkeypatch.setattr(backend, "_propagate_video_sam3", lambda *a, **k: fake_sam3(*a, mask_dir=a[4], **k))
    monkeypatch.setattr(backend, "_propagate_video_sam1", lambda *a, **k: fake_sam1(*a, mask_dir=a[4], **k))
    out = backend.propagate_video(Path("v.mp4"), 0.0, 1.0, [SamPoint(0.5, 0.5)], tmp_path)
    assert out == "fallback-result"
    assert leftovers_seen_by_fallback == [[]]


def test_sam3_propagation_unlinks_written_frames_on_cancel(monkeypatch, tmp_path):
    """Drive the real _propagate_video_sam3 with fake torch/processor objects."""
    import sys
    import types

    np = pytest.importorskip("numpy")
    fake_torch = types.ModuleType("torch")

    class _NoGrad:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    fake_torch.no_grad = lambda: _NoGrad()
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    backend = SamBackend()
    frames = [np.zeros((4, 4, 3), dtype=np.uint8)] * 3
    times = [0.0, 0.5, 1.0]
    session = SimpleNamespace(video_height=4, video_width=4)
    processor = Mock()
    processor.init_video_session.return_value = session
    processor.post_process_masks.return_value = [np.ones((4, 4))]
    pred = SimpleNamespace(detach=lambda: SimpleNamespace(cpu=lambda: np.ones((1, 4, 4))))
    outputs = [SimpleNamespace(frame_idx=i, pred_masks=pred) for i in range(3)]
    model = Mock()
    model.propagate_in_video_iterator.return_value = iter(outputs)
    monkeypatch.setattr(backend, "_ensure_sam3_video_model", lambda: (model, processor, "cpu", None))
    monkeypatch.setattr(backend, "_load_video_window", lambda *_a: (frames, times, 2.0))
    monkeypatch.setattr(backend, "_first_binary_mask", lambda m: np.ones((4, 4), dtype=np.uint8))
    monkeypatch.setattr(backend, "_score_from_outputs", lambda _o: 0.9)
    monkeypatch.setattr(SamBackend, "_save_mask_rgba", _write_png_stub)
    calls = {"n": 0}

    def cancelled():
        calls["n"] += 1
        return calls["n"] > 2

    with pytest.raises(SamCancelled):
        backend._propagate_video_sam3(
            Path("v.mp4"), 0.0, 1.0, [SamPoint(0.5, 0.5)], tmp_path,
            cancelled=cancelled, run_id="r",
        )
    assert list(tmp_path.glob("*.png")) == []


# -- workflow: Delete Weights ---------------------------------------------------


@pytest.fixture
def workflow(monkeypatch, hub):
    from PySide6.QtWidgets import QApplication, QWidget

    from neuroedit_desktop.ui import sam_workflow

    QApplication.instance() or QApplication([])

    class Workflow(sam_workflow.SamWorkflowMixin, QWidget):
        pass

    monkeypatch.setattr(sam_workflow.diagnostics, "log", lambda *a, **k: None)
    box = SimpleNamespace(
        question=Mock(return_value=sam_workflow.QMessageBox.StandardButton.Yes),
        critical=Mock(),
        information=Mock(),
        StandardButton=sam_workflow.QMessageBox.StandardButton,
    )
    monkeypatch.setattr(sam_workflow, "QMessageBox", box)
    w = Workflow()
    w.sam_backend = SamBackend()
    w.sam_panel = Mock()
    w.statusBar = Mock(return_value=Mock())
    w._box = box
    yield w
    w.close()


def test_workflow_delete_success_updates_panel(workflow, hub):
    _make_model_cache(hub, "models--facebook--sam3", weights=True)
    workflow._delete_sam_weights()
    workflow.sam_panel.set_weights_cached.assert_called_with(False)
    workflow._box.critical.assert_not_called()
    assert not (hub / "models--facebook--sam3").exists()


def test_workflow_delete_failure_is_reported_and_cache_rechecked(workflow, hub, monkeypatch):
    _make_model_cache(hub, "models--facebook--sam3", weights=True)

    def boom(path, *a, **k):
        raise PermissionError("denied")

    monkeypatch.setattr("neuroedit_desktop.sam_backend.shutil.rmtree", boom)
    workflow._delete_sam_weights()
    workflow._box.critical.assert_called_once()
    assert "denied" in workflow._box.critical.call_args.args[2]
    workflow.sam_panel.set_weights_cached.assert_called_with(True)  # still cached
    assert "deleted." not in str(workflow.sam_panel.set_status.call_args)


def test_workflow_delete_blocked_while_job_running(workflow, hub):
    cache = _make_model_cache(hub, "models--facebook--sam3", weights=True)
    workflow._sam_segment_thread = object()
    workflow._delete_sam_weights()
    assert cache.exists()
    workflow._box.question.assert_not_called()
    workflow._box.information.assert_called_once()


def test_workflow_delete_cancelled_by_user_removes_nothing(workflow, hub):
    cache = _make_model_cache(hub, "models--facebook--sam3", weights=True)
    workflow._box.question.return_value = workflow._box.StandardButton.Cancel
    workflow._delete_sam_weights()
    assert cache.exists()


def test_unrelated_bin_file_is_not_model_weights(hub):
    cache = _make_model_cache(hub, "models--facebook--sam3", weights=False)
    (cache / "snapshots" / "abc123" / "vocab.bin").write_bytes(b"vocab")
    assert not SamBackend().is_weights_cached()


def test_unload_releases_mps_cache(monkeypatch):
    import sys

    mps = Mock()
    fake_torch = SimpleNamespace(cuda=Mock(), mps=mps, backends=SimpleNamespace(mps=Mock()))
    fake_torch.cuda.is_available.return_value = False
    fake_torch.backends.mps.is_available.return_value = True
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    SamBackend().unload_models()
    mps.empty_cache.assert_called_once()


def test_workflow_delete_reports_absent_cache(workflow):
    workflow._delete_sam_weights()
    assert "No cached SAM weights" in workflow.sam_panel.set_status.call_args.args[0]
