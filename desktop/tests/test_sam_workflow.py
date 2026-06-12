from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from neuroedit_desktop.models import Annotation, ProjectState  # noqa: E402
from neuroedit_desktop.sam_backend import SamBackend  # noqa: E402
from neuroedit_desktop.ui.main_window import (  # noqa: E402
    SamPanel,
    delete_orphan_masks,
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
