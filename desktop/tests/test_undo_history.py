from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402

from neuroedit_desktop.models import Annotation, ProjectState, Slide, VideoClip  # noqa: E402
from neuroedit_desktop.ui import main_window as main_window_module  # noqa: E402
from neuroedit_desktop.ui.canvas import AnnotationGraphicsItem  # noqa: E402
from neuroedit_desktop.ui.main_window import MainWindow  # noqa: E402


class _StubPanel:
    def __init__(self) -> None:
        self.selected_annotation_id: str | None = None

    def set_selected_annotation(self, annotation_id: str | None) -> None:
        self.selected_annotation_id = annotation_id


class _StubView:
    class _VisibleItem:
        def isVisible(self) -> bool:
            return True

    video_item = _VisibleItem()

    def __init__(self) -> None:
        self.annotation_updates: list[tuple[float, float] | None] = []

    def update_annotations(self) -> None:
        self.annotation_updates.append(None)

    def update_annotations_for_time(self, previous_time: float, current_time: float) -> None:
        self.annotation_updates.append((previous_time, current_time))


class _StubTimeline:
    def __init__(self) -> None:
        self.refresh_count = 0

    def refresh(self) -> None:
        self.refresh_count += 1


class _StubPlayer:
    def __init__(
        self,
        state: QMediaPlayer.PlaybackState = QMediaPlayer.PlaybackState.StoppedState,
    ) -> None:
        self.pause_count = 0
        self.play_count = 0
        self.state = state

    def pause(self) -> None:
        self.pause_count += 1

    def playbackState(self) -> QMediaPlayer.PlaybackState:
        return self.state

    def play(self) -> None:
        self.play_count += 1

    def position(self) -> int:
        return 2_000

    def source(self) -> QUrl:
        return QUrl.fromLocalFile("/tmp/clip.mp4")


class _StubTimer:
    def __init__(self) -> None:
        self.stop_count = 0

    def stop(self) -> None:
        self.stop_count += 1


class _StubButton:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, value: str) -> None:
        self.text = value


class _StubLabel:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, value: str) -> None:
        self.text = value


class _StubStatusBar:
    def showMessage(self, *_args: object) -> None:
        pass


class _StubStore:
    def __init__(self) -> None:
        self.project_path = "project.json"
        self.saved_project: ProjectState | None = None
        self.saved_data: dict | None = None

    def save(self, project: ProjectState) -> None:
        self.saved_project = project

    def save_data(self, data: dict) -> None:
        self.saved_data = data


def _annotation(annotation_id: str = "ann-1", label: str = "Tumor") -> Annotation:
    return Annotation(
        id=annotation_id,
        frame_time=0.0,
        ann_duration=1.0,
        type="rect",
        label=label,
        color="#22d3ee",
        geometry={"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
    )


def _window(project: ProjectState | None = None) -> MainWindow:
    window = MainWindow.__new__(MainWindow)
    window.project = project or ProjectState()
    window.dirty = False
    snapshot = window._snapshot()
    window._undo_stack = [snapshot]
    window._redo_stack = []
    window._undo_hashes = [window._snapshot_hash(snapshot)]
    window._redo_hashes = []
    window._undo_sizes = [len(window._snapshot_payload(snapshot))]
    window._redo_sizes = []
    window._autosave_snapshot = None
    window._history_limit = 50
    window._history_bytes_limit = 64 * 1024 * 1024
    window._restoring = False
    window._project_end_time_cache = None
    window._pending_seek_ms = None
    window._pending_play = False
    window.labels_panel = _StubPanel()
    window.video_view = _StubView()
    window.timeline = _StubTimeline()
    window.store = _StubStore()
    window.statusBar = lambda: _StubStatusBar()
    window.refresh = lambda: None
    window._update_title = lambda: None
    window._update_history_actions = lambda: None
    return window


def _annotation_item(project: ProjectState) -> AnnotationGraphicsItem:
    item = AnnotationGraphicsItem.__new__(AnnotationGraphicsItem)
    item.project = project
    item._caption_cues = []
    item._caption_fingerprint = None
    return item


def test_canvas_time_state_is_stable_between_overlay_boundaries() -> None:
    project = ProjectState()
    project.annotations.append(_annotation())
    item = _annotation_item(project)

    assert item.time_state(0.25) == item.time_state(0.5)
    assert item.time_state(0.5) != item.time_state(1.1)


def test_canvas_time_state_changes_during_clip_fade() -> None:
    project = ProjectState()
    project.clips.append(
        VideoClip(
            id="clip-1",
            path="clip.mp4",
            name="Clip",
            duration=10.0,
            trim_end=10.0,
            fade_in=1.0,
        )
    )
    item = _annotation_item(project)

    assert item.time_state(0.25) != item.time_state(0.5)


def test_tool_panel_and_selection_changes_do_not_create_undo_entries() -> None:
    project = ProjectState()
    project.annotations.append(_annotation())
    window = _window(project)

    window._set_tool("rect")
    window._set_panel("labels")
    window._on_view_selection_changed("ann-1")
    window._on_panel_selection_changed(None)

    assert len(window._undo_stack) == 1
    assert window.dirty is True


def test_editing_annotation_creates_undo_entry() -> None:
    project = ProjectState()
    project.annotations.append(_annotation())
    window = _window(project)

    window._update_annotation_label("ann-1", "Updated")

    assert len(window._undo_stack) == 2
    assert window._undo_stack[-1]["annotations"][0]["label"] == "Updated"
    assert window.dirty is True


def test_net_zero_document_mutation_clears_redo_stack() -> None:
    project = ProjectState()
    project.annotations.append(_annotation())
    window = _window(project)
    window._redo_stack = [{"annotations": [{"label": "future"}]}]
    window._redo_hashes = ["future"]
    window._redo_sizes = [100]

    window._push_history()

    assert len(window._undo_stack) == 1
    assert window._redo_stack == []
    assert window._redo_hashes == []
    assert window._redo_sizes == []


def test_history_dedup_uses_snapshot_hash() -> None:
    project = ProjectState()
    project.annotations.append(_annotation())
    window = _window(project)

    window._push_history()

    assert len(window._undo_stack) == 1
    assert len(window._undo_hashes) == 1


def test_history_evicts_oldest_snapshots_over_byte_limit() -> None:
    project = ProjectState()
    project.annotations.append(_annotation(label="Initial"))
    window = _window(project)
    window._history_bytes_limit = window._undo_sizes[0] * 2 + 50

    window._update_annotation_label("ann-1", "A" * 100)
    window._update_annotation_label("ann-1", "B" * 100)

    assert len(window._undo_stack) == 1
    assert window._undo_stack[-1]["annotations"][0]["label"] == "B" * 100
    assert len(window._undo_hashes) == len(window._undo_stack)
    assert len(window._undo_sizes) == len(window._undo_stack)


def test_undo_redo_moves_snapshot_size_bookkeeping() -> None:
    project = ProjectState()
    project.annotations.append(_annotation(label="Initial"))
    window = _window(project)
    window._update_annotation_label("ann-1", "Updated")
    updated_size = window._undo_sizes[-1]

    window.undo()

    assert window._redo_sizes == [updated_size]
    assert len(window._undo_sizes) == len(window._undo_stack)

    window.redo()

    assert window._redo_sizes == []
    assert window._undo_sizes[-1] == updated_size


def test_autosave_reuses_snapshot_from_history_push() -> None:
    project = ProjectState()
    project.annotations.append(_annotation())
    window = _window(project)

    window._update_annotation_label("ann-1", "Updated")
    window._autosave()

    assert window.store.saved_project is None
    assert window.store.saved_data is not None
    assert window.store.saved_data["annotations"][0]["label"] == "Updated"
    assert window._autosave_snapshot is None
    assert window.dirty is False


def test_ui_only_dirty_invalidates_cached_autosave_snapshot() -> None:
    project = ProjectState()
    project.annotations.append(_annotation())
    window = _window(project)

    window._update_annotation_label("ann-1", "Updated")
    assert window._autosave_snapshot is not None

    window._set_tool("rect")
    window._autosave()

    assert window.store.saved_data is None
    assert window.store.saved_project is project


def test_project_end_time_cache_reused_until_dirty(monkeypatch: pytest.MonkeyPatch) -> None:
    project = ProjectState()
    project.clips.append(
        VideoClip(
            id="clip-1",
            path="clip.mp4",
            name="Clip",
            duration=10.0,
            trim_end=10.0,
        )
    )
    calls = 0

    def fake_project_end_time(_project: ProjectState) -> float:
        nonlocal calls
        calls += 1
        return 10.0

    monkeypatch.setattr(main_window_module, "project_end_time", fake_project_end_time)
    window = _window(project)

    assert window._project_end_time() == 10.0
    assert window._project_end_time() == 10.0
    assert calls == 1

    window._mark_dirty(history=False)

    assert window._project_end_time() == 10.0
    assert calls == 2


def test_apply_snapshot_invalidates_project_end_time_cache() -> None:
    project = ProjectState()
    project.clips.append(
        VideoClip(
            id="clip-1",
            path="clip.mp4",
            name="Clip",
            duration=10.0,
            trim_end=10.0,
        )
    )
    window = _window(project)
    restored = window._snapshot()
    project.clips[0].trim_end = 5.0

    assert window._project_end_time() == 5.0

    window._apply_snapshot(restored)

    assert window._project_end_time() == 10.0


def test_open_recent_project_invalidates_end_time_before_loading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "project.json"
    path.touch()
    window = _window()
    window._project_end_time_cache = 10.0
    opened_project = ProjectState()

    monkeypatch.setattr(
        main_window_module.ProjectStore,
        "open",
        lambda _path: (_StubStore(), opened_project),
    )
    window._add_to_recent = lambda _path: None

    def validate_loaded_project_media(_context: str) -> None:
        assert window._project_end_time_cache is None

    window._validate_loaded_project_media = validate_loaded_project_media
    window._load_active_clip = lambda: None
    window._log_project_load = lambda _start, _source: None
    window._mark_dirty = lambda: None

    window._open_recent_project(str(path))

    assert window.project is opened_project
    assert window._project_end_time_cache is None


def test_timeline_playback_reuses_cached_project_end_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = ProjectState(playback_rate=1.0)
    project.clips.append(
        VideoClip(
            id="clip-1",
            path="clip.mp4",
            name="Clip",
            duration=10.0,
            trim_end=10.0,
        )
    )
    calls = 0

    def fake_project_end_time(_project: ProjectState) -> float:
        nonlocal calls
        calls += 1
        return 10.0

    monotonic_values = iter([1.0, 1.1])
    monkeypatch.setattr(main_window_module, "project_end_time", fake_project_end_time)
    monkeypatch.setattr(main_window_module.time, "monotonic", lambda: next(monotonic_values))
    window = _window(project)
    window._timeline_playing = True
    window._last_timeline_tick = 0.0
    window.player = _StubPlayer()
    window.timeline_clock = _StubTimer()
    window.play_button = _StubButton()
    window.time_label = _StubLabel()
    window._sync_player_to_timeline = lambda *, play: None

    window._tick_timeline_playback()
    window._tick_timeline_playback()

    assert calls == 1
    assert window.timeline.refresh_count == 2


def test_timeline_clock_advances_while_variable_frame_rate_video_is_playing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = ProjectState(current_time=2.0, playback_rate=1.0)
    clip = VideoClip(
        id="clip-1",
        path="clip.mp4",
        name="Clip",
        duration=10.0,
        trim_end=10.0,
    )
    project.clips.append(clip)
    project.active_clip_id = clip.id
    window = _window(project)
    window._timeline_playing = True
    window._last_timeline_tick = 1.0
    window.player = _StubPlayer(QMediaPlayer.PlaybackState.PlayingState)
    window.timeline_clock = _StubTimer()
    window.play_button = _StubButton()
    window.time_label = _StubLabel()
    sync_calls: list[bool] = []
    window._sync_player_to_timeline = lambda *, play: sync_calls.append(play)
    monkeypatch.setattr(main_window_module.time, "monotonic", lambda: 1.033)

    # Sparse VFR frame timestamps must not drive or reset the timeline.
    window._position_changed(5000)
    window._tick_timeline_playback()

    assert project.current_time == pytest.approx(2.033)
    assert window.timeline.refresh_count == 1
    assert sync_calls == []


def test_sync_keeps_video_playing_under_overlay_slide() -> None:
    project = ProjectState(current_time=2.0)
    clip = VideoClip(
        id="clip-1",
        path="clip.mp4",
        name="Clip",
        duration=10.0,
        trim_end=10.0,
    )
    project.clips.append(clip)
    project.active_clip_id = clip.id
    project.slides.append(Slide(id="slide-1", title="Overlay", overlay=True, duration=5.0))
    window = _window(project)
    window.player = _StubPlayer()
    window._cached_clip_media_problem = lambda _clip: None

    window._sync_player_to_timeline(play=True)

    assert window.player.pause_count == 0
    assert window.player.play_count == 1


def test_timeline_does_not_resync_playing_video_under_overlay_slide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = ProjectState(current_time=2.0, playback_rate=1.0)
    clip = VideoClip(
        id="clip-1",
        path="clip.mp4",
        name="Clip",
        duration=10.0,
        trim_end=10.0,
    )
    project.clips.append(clip)
    project.active_clip_id = clip.id
    project.slides.append(Slide(id="slide-1", title="Overlay", overlay=True, duration=5.0))
    window = _window(project)
    window._timeline_playing = True
    window._last_timeline_tick = 1.0
    window.player = _StubPlayer(QMediaPlayer.PlaybackState.PlayingState)
    window.timeline_clock = _StubTimer()
    window.play_button = _StubButton()
    window.time_label = _StubLabel()
    sync_calls: list[bool] = []
    window._sync_player_to_timeline = lambda *, play: sync_calls.append(play)
    monkeypatch.setattr(main_window_module.time, "monotonic", lambda: 1.033)

    window._tick_timeline_playback()

    assert project.current_time == pytest.approx(2.033)
    assert sync_calls == []
