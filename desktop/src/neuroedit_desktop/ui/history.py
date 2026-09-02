from __future__ import annotations

import hashlib
import json

from PySide6.QtCore import QTimer

from neuroedit_desktop.models import ProjectState


class HistoryMixin:
    """Undo/redo and autosave controller methods for MainWindow."""

    # Transient UI state: excluded from undo snapshots and carried across
    # snapshot restores. draw_* are tool settings, not document content.
    _TRANSIENT_SNAPSHOT_KEYS = (
        "active_panel",
        "active_tool",
        "current_time",
        "scroll_left",
        "selected_annotation_id",
        "zoom",
        "draw_color",
        "draw_width",
        "draw_opacity",
        "draw_label",
    )

    def _build_autosave(self) -> None:
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(2000)
        self.autosave_timer.timeout.connect(self._autosave)
        self.autosave_timer.start()

    def _mark_dirty(self, *, history: bool = True, review_relevant: bool = False) -> None:
        if review_relevant:
            self._invalidate_review_attestations()
        self._invalidate_project_end_time()
        if history and not self._restoring:
            self._push_history()
        elif not history:
            self._autosave_snapshot = None
        self.dirty = True
        self.refresh()
        self._update_title()

    def _mark_project_dirty(self) -> None:
        self._invalidate_project_end_time()
        end_time = self._project_end_time()
        if self.project.current_time > end_time:
            self.project.current_time = end_time
            if self._timeline_playing:
                self._timeline_playing = False
                self.timeline_clock.stop()
                self.player.pause()
                self.play_button.setText("▶")
        if not self._restoring:
            self._push_history()
        else:
            self._autosave_snapshot = None
        self.dirty = True
        self._update_title()
        self.video_view.set_project(self.project)
        # Re-point the player at whatever is under the playhead now. A timeline
        # edit can change (or remove) the clip there.
        self._sync_player_to_timeline(play=self._timeline_playing)
        self.video_view.update_annotations()
        self.timeline.refresh()
        self.media_panel.refresh()

    def _mark_review_relevant_project_dirty(self) -> None:
        self._invalidate_review_attestations()
        self._mark_project_dirty()

    def _seed_history(self) -> None:
        """Start a new undo session for the current project document."""
        snapshot_payload = self._snapshot_payload(self._snapshot())
        self._undo_stack = [snapshot_payload]
        self._redo_stack = []
        self._undo_hashes = [self._payload_hash(snapshot_payload)]
        self._redo_hashes = []
        self._undo_sizes = [len(snapshot_payload)]
        self._redo_sizes = []
        self._autosave_snapshot = None
        self._update_history_actions()

    def _snapshot(self, project_data: dict | None = None) -> dict:
        snapshot = dict(project_data if project_data is not None else self.project.to_dict())
        for key in self._TRANSIENT_SNAPSHOT_KEYS:
            snapshot.pop(key, None)
        return snapshot

    def _snapshot_payload(self, snapshot: dict) -> bytes:
        return json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def _payload_hash(self, payload: bytes) -> str:
        return hashlib.blake2b(payload, digest_size=16).hexdigest()

    def _snapshot_hash(self, snapshot: dict) -> str:
        return self._payload_hash(self._snapshot_payload(snapshot))

    def _push_history(self) -> None:
        project_data = self.project.to_dict()
        if (
            self._autosave_snapshot is not None
            and project_data == self._autosave_snapshot
        ):
            self._autosave_snapshot = project_data
            self._redo_stack.clear()
            self._redo_hashes.clear()
            self._redo_sizes.clear()
            self._update_history_actions()
            return
        snapshot = self._snapshot(project_data)
        snapshot_payload = self._snapshot_payload(snapshot)
        snapshot_hash = self._payload_hash(snapshot_payload)
        self._autosave_snapshot = project_data
        self._redo_stack.clear()
        self._redo_hashes.clear()
        self._redo_sizes.clear()
        if self._undo_hashes and self._undo_hashes[-1] == snapshot_hash:
            self._update_history_actions()
            return
        self._undo_stack.append(snapshot_payload)
        self._undo_hashes.append(snapshot_hash)
        self._undo_sizes.append(len(snapshot_payload))
        while len(self._undo_stack) > 1 and (
            len(self._undo_stack) > self._history_limit
            or sum(self._undo_sizes) > self._history_bytes_limit
        ):
            self._undo_stack.pop(0)
            self._undo_hashes.pop(0)
            self._undo_sizes.pop(0)
        self._update_history_actions()

    def _update_history_actions(self) -> None:
        self.undo_action.setEnabled(len(self._undo_stack) > 1)
        self.redo_action.setEnabled(bool(self._redo_stack))

    def undo(self) -> None:
        if len(self._undo_stack) <= 1:
            return
        current = self._undo_stack.pop()
        current_hash = self._undo_hashes.pop()
        current_size = self._undo_sizes.pop()
        self._redo_stack.append(current)
        self._redo_hashes.append(current_hash)
        self._redo_sizes.append(current_size)
        previous = self._undo_stack[-1]
        self._apply_snapshot(previous)
        self._update_history_actions()

    def redo(self) -> None:
        if not self._redo_stack:
            return
        snapshot = self._redo_stack.pop()
        snapshot_hash = (
            self._redo_hashes.pop()
            if self._redo_hashes
            else self._payload_hash(snapshot)
        )
        snapshot_size = (
            self._redo_sizes.pop()
            if self._redo_sizes
            else len(snapshot)
        )
        self._undo_stack.append(snapshot)
        self._undo_hashes.append(snapshot_hash)
        self._undo_sizes.append(snapshot_size)
        self._apply_snapshot(snapshot)
        self._update_history_actions()

    def _apply_snapshot(self, snapshot: bytes) -> None:
        self._restoring = True
        try:
            transient = {
                key: getattr(self.project, key) for key in self._TRANSIENT_SNAPSHOT_KEYS
            }
            old_clip = self.project.active_clip
            old_path = old_clip.path if old_clip else None
            self.project = ProjectState.from_dict(json.loads(snapshot))
            self._autosave_snapshot = None
            self._project_end_time_cache = None
            for key, value in transient.items():
                if key == "selected_annotation_id":
                    if any(ann.id == value for ann in self.project.annotations):
                        self.project.selected_annotation_id = value
                    continue
                setattr(self.project, key, value)
            self.dirty = True
            new_clip = self.project.active_clip
            new_path = new_clip.path if new_clip else None
            if old_path != new_path:
                self._load_active_clip()
            self.refresh()
        finally:
            self._restoring = False

    def _autosave(self) -> None:
        if not self.dirty:
            return
        try:
            if self._autosave_snapshot is not None:
                self.store.save_data(self._autosave_snapshot)
            else:
                self.store.save(self.project)
            self.statusBar().showMessage(f"Autosaved {self.store.project_path}", 2500)
            self.dirty = False
            self._autosave_snapshot = None
            self._update_title()
        except Exception as exc:
            self.statusBar().showMessage(f"Autosave failed: {exc}", 5000)
