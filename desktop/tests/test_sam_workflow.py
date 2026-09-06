from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from neuroedit_desktop.models import Annotation, ProjectState, SamPoint  # noqa: E402
from neuroedit_desktop.sam_backend import SamBackend  # noqa: E402
from neuroedit_desktop.ui import main_window_utils  # noqa: E402
from neuroedit_desktop.ui.main_window import (  # noqa: E402
    MASK_PALETTE,
    SamPanel,
    delete_orphan_masks,
    hex_to_rgb,
    propagation_window_s,
    referenced_mask_paths,
)


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _mask_annotation(
    ann_id: str,
    label: str = "Mask",
    type_: str = "mask",
    frames: int = 0,
) -> Annotation:
    ann = Annotation(
        id=ann_id,
        frame_time=0.0,
        ann_duration=1.0,
        type=type_,  # type: ignore[arg-type]
        label=label,
        color="#22d3ee",
    )
    if frames:
        ann.mask_frames = [
            {"time": float(i), "mask_path": f"/tmp/{ann_id}_{i}.png"} for i in range(frames)
        ]
    return ann


# ── Models round-trip ─────────────────────────────────────────────────────


def test_round_trip_preserves_sam_last_run_and_prompt_points() -> None:
    project = ProjectState()
    project.sam_last_run = {
        "started_iso": "2026-06-10T14:02:00",
        "duration_s": 41.0,
        "frames": 24,
        "result": "success",
        "backend": "SAM3",
        "message": "",
    }
    ann = _mask_annotation("m1", "Mask 1")
    ann.prompt_points = [{"x": 0.5, "y": 0.25, "type": "positive"}]
    project.annotations.append(ann)

    restored = ProjectState.from_dict(project.to_dict())

    assert restored.sam_last_run == project.sam_last_run
    assert restored.annotations[0].prompt_points == [{"x": 0.5, "y": 0.25, "type": "positive"}]


def test_old_dicts_without_new_keys_still_load() -> None:
    data = ProjectState().to_dict()
    data.pop("sam_last_run")
    data["annotations"] = [
        {
            "id": "a1",
            "frame_time": 0.0,
            "ann_duration": 0.0,
            "type": "mask",
            "label": "old mask",
            "color": "#22d3ee",
        }
    ]

    restored = ProjectState.from_dict(data)

    assert restored.sam_last_run == {}
    assert restored.annotations[0].prompt_points == []


# ── Orphan mask cleanup ───────────────────────────────────────────────────


def test_main_window_utility_re_exports_are_stable() -> None:
    assert MASK_PALETTE is main_window_utils.MASK_PALETTE
    assert hex_to_rgb is main_window_utils.hex_to_rgb
    assert propagation_window_s is main_window_utils.propagation_window_s
    assert referenced_mask_paths is main_window_utils.referenced_mask_paths
    assert delete_orphan_masks is main_window_utils.delete_orphan_masks


def test_orphan_mask_cleanup(tmp_path) -> None:
    masks_dir = tmp_path / "masks"
    masks_dir.mkdir()
    kept_current = masks_dir / "current.png"
    kept_snapshot = masks_dir / "snapshot.png"
    orphan = masks_dir / "orphan.png"
    for path in (kept_current, kept_snapshot, orphan):
        path.write_bytes(b"png")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"png")

    current_project = {"annotations": [{"mask_path": str(kept_current), "mask_frames": []}]}
    undo_snapshot = {
        "annotations": [
            {
                "mask_path": None,
                "mask_frames": [{"time": 0.0, "mask_path": str(kept_snapshot)}],
            }
        ]
    }
    referencing_outside = {"annotations": [{"mask_path": str(outside)}]}

    referenced = referenced_mask_paths([current_project, undo_snapshot, referencing_outside])
    removed = delete_orphan_masks(masks_dir, referenced)

    assert removed == 1
    assert kept_current.exists()
    assert kept_snapshot.exists()
    assert not orphan.exists()
    # Files outside the masks dir are never touched, referenced or not.
    assert outside.exists()


def test_orphan_cleanup_never_leaves_masks_dir(tmp_path) -> None:
    masks_dir = tmp_path / "masks"
    masks_dir.mkdir()
    stray = tmp_path / "stray.png"  # unreferenced, but outside masks dir
    stray.write_bytes(b"png")

    removed = delete_orphan_masks(masks_dir, set())

    assert removed == 0
    assert stray.exists()


# ── Mask PNG color threading ──────────────────────────────────────────────


def test_save_mask_rgba_uses_custom_color(tmp_path) -> None:
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")

    mask = np.zeros((4, 4), dtype=bool)
    mask[1, 2] = True
    out = tmp_path / "mask.png"

    SamBackend()._save_mask_rgba(mask, (4, 4), out, color=(250, 100, 20))

    img = cv2.imread(str(out), cv2.IMREAD_UNCHANGED)  # BGRA channel order
    assert img.shape == (4, 4, 4)
    b, g, r, a = img[1, 2]
    assert (int(r), int(g), int(b)) == (250, 100, 20)
    assert int(a) == 200
    assert int(img[0, 0][3]) == 0  # unmasked pixels stay transparent

    SamBackend()._save_mask_rgba(mask, (4, 4), out)  # default stays cyan
    img = cv2.imread(str(out), cv2.IMREAD_UNCHANGED)
    b, g, r, _a = img[1, 2]
    assert (int(r), int(g), int(b)) == (34, 211, 238)


def test_segment_frame_never_reuses_an_existing_mask_filename(tmp_path, monkeypatch) -> None:
    np = pytest.importorskip("numpy")
    backend = SamBackend()
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    mask = np.ones((4, 4), dtype=bool)
    monkeypatch.setattr(backend, "_grab_frame", lambda *_args: frame)
    monkeypatch.setattr(backend, "_run_sam3_on_frame", lambda *_args: (mask, 0.9))

    first = backend.segment_frame(
        tmp_path / "video.mp4", 1.0, [SamPoint(0.5, 0.5)], tmp_path / "masks"
    )
    first.mask_path.write_bytes(b"original")
    second = backend.segment_frame(
        tmp_path / "video.mp4", 1.0, [SamPoint(0.5, 0.5)], tmp_path / "masks"
    )

    assert first.mask_path != second.mask_path
    assert first.mask_path.read_bytes() == b"original"
    assert second.mask_path.exists()


# ── SamPanel mask list ────────────────────────────────────────────────────


def test_sam_panel_lists_masks_and_emits_signals(app) -> None:
    project = ProjectState()
    project.annotations.append(_mask_annotation("m1", "Mask 1"))
    project.annotations.append(_mask_annotation("m2", "Mask 2", type_="tracked-mask", frames=3))
    project.annotations.append(
        Annotation(
            id="r1", frame_time=0.0, ann_duration=0.0, type="rect", label="box", color="#fff"
        )
    )

    panel = SamPanel(project)
    panel.refresh()

    assert panel.masks_list.count() == 2  # rect annotation excluded
    assert panel.masks_list.item(0).text() == "Mask 1"
    assert "· 3 frames" in panel.masks_list.item(1).text()

    visibility_events: list[tuple[str, bool]] = []
    panel.mask_visibility_changed.connect(
        lambda ann_id, visible: visibility_events.append((ann_id, visible))
    )
    panel.masks_list.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert visibility_events == [("m1", False)]
    assert project.annotations[0].visible is False

    rename_events: list[tuple[str, str]] = []
    panel.mask_renamed.connect(lambda ann_id, label: rename_events.append((ann_id, label)))
    panel.masks_list.item(1).setText("Carotid · 3 frames")
    assert rename_events == [("m2", "Carotid")]
    assert project.annotations[1].label == "Carotid"


def test_sam_panel_refresh_preserves_selection(app) -> None:
    project = ProjectState()
    project.annotations.append(_mask_annotation("m1", "Mask 1"))
    project.annotations.append(_mask_annotation("m2", "Mask 2"))
    panel = SamPanel(project)
    panel.refresh()
    panel.masks_list.setCurrentRow(1)
    project.selected_annotation_id = "m2"

    panel.refresh()

    item = panel.masks_list.currentItem()
    assert item is not None
    assert item.data(Qt.ItemDataRole.UserRole) == "m2"


# ── Busy state / track-window prefs ───────────────────────────────────────


def test_busy_disables_mask_list_and_shows_cancel(app) -> None:
    project = ProjectState()
    project.annotations.append(_mask_annotation("m1", "Mask 1"))
    panel = SamPanel(project)
    panel.refresh()

    panel.set_busy(True)
    assert not panel.masks_list.isEnabled()
    assert not panel.cancel_button.isHidden()
    assert not panel.segment_button.isEnabled()

    panel.set_busy(False)
    assert panel.masks_list.isEnabled()
    assert panel.cancel_button.isHidden()


def test_track_window_prefs_persist_across_panels(app) -> None:
    from PySide6.QtCore import QSettings

    settings = QSettings("NeuroEdit", "Desktop")
    original_to_end = settings.value("sam/trackToEnd", True, type=bool)
    original_window = settings.value("sam/trackWindowS", 5.0)
    try:
        panel = SamPanel(ProjectState())
        panel.track_to_end_check.setChecked(False)
        panel.track_window_spin.setValue(12.0)

        fresh = SamPanel(ProjectState())
        assert fresh.track_to_end_check.isChecked() is False
        assert fresh.track_window_spin.value() == 12.0
        assert fresh.track_window_spin.isEnabled()
    finally:
        settings.setValue("sam/trackToEnd", original_to_end)
        settings.setValue("sam/trackWindowS", original_window)


# ── Propagation window math ───────────────────────────────────────────────


def test_propagation_window_math() -> None:
    assert propagation_window_s(30.0, True, 5.0) == 30.0
    assert propagation_window_s(0.2, True, 5.0) == 1.0  # clamped up to 1 s
    assert propagation_window_s(30.0, False, 5.0) == 5.0
    assert propagation_window_s(3.0, False, 5.0) == 3.0  # clamped to clip end
    assert propagation_window_s(0.5, False, 5.0) == 1.0


@pytest.fixture
def workflow(app, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from PySide6.QtWidgets import QWidget

    from neuroedit_desktop.models import VideoClip
    from neuroedit_desktop.ui import sam_workflow
    from neuroedit_desktop.ui.main_window import MainWindow

    class Workflow(sam_workflow.SamWorkflowMixin, QWidget):
        _clip_at_time = MainWindow._clip_at_time
        _slide_at_time = MainWindow._slide_at_time

        def _find_annotation(self, annotation_id):
            return next((a for a in self.project.annotations if a.id == annotation_id), None)

    # Exercise real worker construction without running the optional SAM stack.
    monkeypatch.setattr(sam_workflow.QThread, "start", lambda _self: None)
    monkeypatch.setattr(sam_workflow.QMessageBox, "information", Mock())
    window = Workflow()
    window.project = ProjectState()
    clip = VideoClip(
        id="trimmed", name="Trimmed", path="/tmp/trimmed.mp4", duration=20.0,
        start_time=10.0, trim_start=4.0, trim_end=8.0,
    )
    window.project.clips = [clip]
    window.project.active_clip_id = clip.id
    window.project.current_time = 12.0
    window.project.sam_points = [SamPoint(0.5, 0.5)]
    window.sam_backend = SamBackend()
    window.sam_panel = Mock()
    window.sam_panel.track_to_end_check.isChecked.return_value = True
    window.sam_panel.track_window_spin.value.return_value = 5.0
    window.statusBar = Mock(return_value=Mock())
    window.store = SimpleNamespace(project_path=tmp_path / "project.json")
    window.video_view = Mock()
    window._mark_dirty = Mock()
    yield window
    window.close()


def test_segmentation_decodes_source_time_but_keeps_timeline_time(workflow):
    from neuroedit_desktop.sam_backend import SamSegmentResult

    workflow._run_segmentation()
    assert workflow._sam_segment_worker.time_s == pytest.approx(6.0)
    workflow.project.current_time = 13.0
    workflow._on_segment_finished(SamSegmentResult("/tmp/mask.png", 0.9, "test"), None)
    assert workflow.project.annotations[0].frame_time == pytest.approx(12.0)


def test_segmentation_discards_result_after_same_project_edit(workflow):
    from neuroedit_desktop.sam_backend import SamSegmentResult

    workflow._run_segmentation()
    mask_path = workflow.store.project_path.parent / "stale-mask.png"
    mask_path.write_bytes(b"stale")
    workflow.project.clips[0].trim_end = 6.0

    workflow._on_segment_finished(SamSegmentResult(mask_path, 0.9, "test"), None)

    assert workflow.project.annotations == []
    assert not mask_path.exists()
    workflow.sam_panel.set_status.assert_called_with(
        "Segmentation result discarded after project changed."
    )


def test_propagation_translates_source_samples_and_stops_at_clip_end(workflow):
    from neuroedit_desktop.sam_backend import SamPropagationResult

    workflow.project.current_time = 13.8
    workflow._run_propagation()
    assert workflow._sam_propagation_worker.start_time_s == pytest.approx(7.8)
    assert workflow._sam_propagation_worker.duration_s == pytest.approx(0.2)
    result = SamPropagationResult(
        mask_frames=[
            {"time": 7.8, "mask_path": "/tmp/seed.png"},
            {"time": 8.0, "mask_path": "/tmp/outside.png"},
        ],
        score=0.9, sample_rate=2.0, backend="test",
    )
    workflow._on_propagation_finished(result, None)
    annotation = workflow.project.annotations[0]
    assert annotation.frame_time == pytest.approx(13.8)
    assert annotation.ann_duration == pytest.approx(0.2)
    assert [frame["time"] for frame in annotation.mask_frames] == pytest.approx([13.8])
    assert annotation.mask_path_at(13.9) == "/tmp/seed.png"


def test_propagation_discards_result_after_same_project_edit(workflow):
    from neuroedit_desktop.sam_backend import SamPropagationResult

    workflow._run_propagation()
    mask_path = workflow.store.project_path.parent / "stale-frame.png"
    mask_path.write_bytes(b"stale")
    workflow.project.clips[0].trim_start = 5.0
    result = SamPropagationResult(
        mask_frames=[{"time": 6.0, "mask_path": str(mask_path)}],
        score=0.9, sample_rate=2.0, backend="test",
    )

    workflow._on_propagation_finished(result, None)

    assert workflow.project.annotations == []
    assert not mask_path.exists()
    workflow.sam_panel.set_status.assert_called_with(
        "Propagation result discarded after project changed."
    )


def test_retrack_uses_annotation_clip_and_clamps_window(workflow):
    from neuroedit_desktop.models import VideoClip

    unrelated = VideoClip(
        id="other", name="Other", path="/tmp/other.mp4", duration=10.0,
        start_time=20.0, trim_end=10.0,
    )
    workflow.project.clips.append(unrelated)
    workflow.project.active_clip_id = unrelated.id
    annotation = _mask_annotation("tracked", type_="tracked-mask")
    annotation.frame_time = 13.8
    annotation.ann_duration = 5.0
    annotation.prompt_points = [{"x": 0.5, "y": 0.5, "type": "positive"}]
    workflow.project.annotations = [annotation]
    workflow._retrack_mask(annotation.id)
    worker = workflow._sam_propagation_worker
    assert str(worker.video_path) == "/tmp/trimmed.mp4"
    assert worker.start_time_s == pytest.approx(7.8)
    assert worker.duration_s == pytest.approx(0.2)


def test_propagation_keeps_vfr_seed_frame_visible_at_requested_start(workflow):
    from neuroedit_desktop.sam_backend import SamPropagationResult

    workflow.project.current_time = 12.123456
    workflow._run_propagation()
    seed = str(workflow.store.project_path.parent / "seed.png")
    # Seeking to 6.123456 can return the frame presented since source time 6.1.
    result = SamPropagationResult(
        mask_frames=[{"time": 6.1, "mask_path": seed}],
        score=0.9, sample_rate=2.0, backend="test",
    )
    workflow._on_propagation_finished(result, None)
    annotation = workflow.project.annotations[0]
    assert annotation.frame_time == pytest.approx(12.123456)
    assert annotation.mask_path_at(12.123456) == seed


@pytest.mark.parametrize("time_s", [9.0, 14.0])
def test_sam_cannot_decode_selected_clip_outside_its_timeline_span(workflow, time_s):
    workflow.project.current_time = time_s
    workflow._run_segmentation()
    workflow._run_propagation()
    assert getattr(workflow, "_sam_segment_worker", None) is None
    assert getattr(workflow, "_sam_propagation_worker", None) is None


@pytest.mark.parametrize("overlay", [False, True])
def test_sam_seed_requires_visible_underlying_clip(workflow, overlay):
    from neuroedit_desktop.models import Slide

    workflow.project.slides = [
        Slide(id="title", title="Title", start_time=10.0, duration=4.0, overlay=overlay)
    ]
    workflow._run_segmentation()
    assert (getattr(workflow, "_sam_segment_worker", None) is not None) is overlay
    # These jobs normally cannot overlap; isolate the two entry-point checks.
    workflow._sam_segment_thread = None
    workflow._run_propagation()
    assert (getattr(workflow, "_sam_propagation_worker", None) is not None) is overlay


def test_sam3_frame_window_preserves_sub_tenth_second_bounds(monkeypatch, tmp_path):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    from unittest.mock import Mock

    cap = Mock()
    cap.isOpened.return_value = True
    cap.get.side_effect = lambda prop: 20.0 if prop == cv2.CAP_PROP_FPS else cap.timestamp * 1000.0
    frames = iter([0.0, 0.05, 0.1, 0.15])

    def read():
        cap.timestamp = next(frames)
        return True, np.zeros((2, 2, 3), dtype=np.uint8)

    cap.read.side_effect = read
    monkeypatch.setattr(cv2, "VideoCapture", lambda _path: cap)
    _frames, times, _rate = SamBackend()._load_video_window(tmp_path / "clip.mp4", 0.0, 0.02)
    assert times == [0.0]
    cap.release.assert_called_once()


def test_sam1_keeps_exact_seed_time_and_sub_tenth_second_bounds(monkeypatch, tmp_path):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    from unittest.mock import Mock

    backend = SamBackend()
    cap = Mock()
    cap.isOpened.return_value = True
    monkeypatch.setattr(cv2, "VideoCapture", lambda _path: cap)
    monkeypatch.setattr(backend, "_ensure_sam1_model", lambda: None)
    monkeypatch.setattr(backend, "_video_duration", lambda _cap: 20.0)
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    monkeypatch.setattr(backend, "_read_frame_from_capture", lambda *_args: frame)
    monkeypatch.setattr(backend, "_run_sam1_on_frame", lambda *_args: (np.ones((8, 8)), 0.9))
    monkeypatch.setattr(backend, "_save_mask_rgba", lambda *_args, **_kwargs: None)
    start = 6.123456
    result = backend._propagate_video_sam1(
        tmp_path / "clip.mp4", start, 0.02, [SamPoint(0.5, 0.5)], tmp_path,
        sample_rate=20.0,
    )
    assert [frame["time"] for frame in result.mask_frames] == [start]
    cap.release.assert_called_once()


def test_empty_bounded_propagation_records_failure(workflow):
    from neuroedit_desktop.sam_backend import SamPropagationResult

    workflow._run_propagation()
    workflow.project.sam_last_run = {"result": "success"}
    result = SamPropagationResult(
        mask_frames=[{"time": 8.0, "mask_path": str(workflow.store.project_path.parent / "outside.png")}],
        score=0.9, sample_rate=2.0, backend="test",
    )
    workflow._on_propagation_finished(result, None)
    assert workflow.project.annotations == []
    assert workflow.project.sam_last_run["result"] == "error"
    assert workflow.project.sam_last_run["frames"] == 0
