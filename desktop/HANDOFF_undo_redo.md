# Handoff — Undo/Redo correctness work

Scope: the undo/redo snapshot system in the NeuroEdit desktop app
(`desktop/src/neuroedit_desktop/ui/main_window.py`). Two work items, done in two
sessions. Verify everything with:

```bash
cd desktop && source .venv/bin/activate && python -m pytest tests/ -q
# → 6 passed
```

---

## Background — how undo/redo works here

Undo/redo is **full-state JSON snapshots of `ProjectState`**, not per-field
patches (see `desktop/CLAUDE.md` → "State, persistence, and undo/redo").

- `_snapshot()` serializes the project for the history stack.
- `_push_history()` appends a snapshot (caps: 50 entries and 64 MiB of compact
  serialized bytes) and clears redo.
- `undo()`/`redo()` move snapshots between `_undo_stack` and `_redo_stack` and
  call `_apply_snapshot()`, which rebuilds via `ProjectState.from_dict`.
- `_restoring` guards against undo-during-undo re-pushing history.
- `_mark_dirty(history=True)` is the common write path: it pushes history (unless
  `history=False` or `_restoring`), sets `dirty`, and refreshes.

---

## Session 1 (previous chat) — move/resize as a single undo step

**Problem:** dragging an annotation to move/resize it on the canvas produced
either no undo entry or many tiny ones (one per mouse-move), because the drag
path marked dirty repeatedly.

**Fix:** split "in-progress drag" from "drag committed" in `VideoGraphicsView`:

- `annotation_mutated` signal — emitted continuously **during** a drag.
  Handler `_on_annotation_mutated()` (~`main_window.py:3835`) only sets
  `dirty` + light refresh. **No history push.**
- `edit_committed` signal — emitted **once** when the move/resize drag finishes
  (`mouseReleaseEvent`, ~`main_window.py:987`/`1012`). Handler
  `_commit_canvas_edit()` (~`main_window.py:3840`) calls `_mark_dirty()` →
  exactly one undo snapshot for the whole gesture.

Wiring: `main_window.py:2501-2502`. Drag state lives on
`VideoGraphicsView._drag_start` (`main_window.py:795`).

This session **intentionally did not** address the two issues below — left out of
scope on purpose.

---

## Session 2 (this chat) — exclude transient UI state; fix redo-clobber

### Issue 1 — transient UI state was being snapshotted

`ProjectState` carries view/selection fields (`selected_annotation_id`,
`active_tool`, `active_panel`, `current_time`, `zoom`, `scroll_left`). Because
`_mark_dirty()` / `_set_tool()` / `_set_panel()` all pushed history, merely
selecting an annotation or switching tools/panels created undo entries **and
cleared the redo stack** ("redo clobbering" — navigating after an undo destroyed
the redo future even though no real edit happened).

**Fix:**

- `_snapshot()` (`main_window.py:2773`) now pops the six transient fields before
  returning, so they are excluded from both the stored snapshot and the equality
  check:
  ```python
  for key in ("active_panel", "active_tool", "current_time",
              "scroll_left", "selected_annotation_id", "zoom"):
      snapshot.pop(key, None)
  ```
- `_set_tool` / `_set_panel` (`main_window.py:3564-3570`) call
  `_mark_dirty(history=False)` — still dirty (for autosave), no history.
- Selection handlers `_on_view_selection_changed` /
  `_on_panel_selection_changed` (`main_window.py:3821-3833`) call
  `_mark_dirty(history=False)`.
- `_apply_snapshot()` (`main_window.py:2818`) preserves the **live** view/selection
  across undo/redo: it captures the current transient fields before
  `ProjectState.from_dict(snapshot)` and reapplies them after (selection only
  reapplied if that annotation still exists). So undo restores document content
  without yanking the user's current tool/panel/playhead around.

### Issue 2 — net-zero mutation skipped redo-clear

`_push_history()` did its dedup early-return **before** clearing redo, so a
net-zero edit (e.g. a drag that returns to its start position → identical
snapshot) returned early and left a stale redo future in place.

**Fix:** `_push_history()` (`main_window.py:2786`) now clears redo **first**:
```python
def _push_history(self) -> None:
    snapshot = self._snapshot()
    self._redo_stack.clear()          # moved above the dedup return
    if self._undo_stack and self._undo_stack[-1] == snapshot:
        self._update_history_actions()
        return
    self._undo_stack.append(snapshot)
    ...
```

### Tests added

`desktop/tests/test_undo_history.py` (constructs `MainWindow` via `__new__` with
stub panels/views, so no real Qt event loop):

- `test_tool_panel_and_selection_changes_do_not_create_undo_entries` — after
  `_set_tool` / `_set_panel` / both selection handlers, `_undo_stack` stays
  length 1 and `dirty is True`.
- `test_editing_annotation_creates_undo_entry` — `_update_annotation_label`
  grows the stack to 2 and the new snapshot carries the edited label.
- `test_net_zero_document_mutation_clears_redo_stack` — a `_push_history()` that
  dedups still empties a pre-populated `_redo_stack`.

---

## Status & notes

- All 6 tests pass; verification command above is green.

## 2026-07-01 — cumulative history-size cap

- Snapshot hashing now exposes the already-produced compact JSON payload so its
  byte length can be recorded without a third serialization.
- Undo and redo move byte-size metadata with each snapshot. New edits evict the
  oldest undo states above 64 MiB while retaining at least the current state.
- Focused tests cover byte-cap eviction and undo/redo bookkeeping. The full suite
  now passes 143 tests.
- Pre-existing `ruff` warnings in `main_window.py` (unused imports at lines ~45,
  68–70, 1599, 2045) are **unrelated** to this work and were left untouched.
- No new `ProjectState` fields were added, so old saves / old undo snapshots are
  unaffected. `from_dict` tolerates the popped keys being absent because they all
  have dataclass defaults.

## 2026-07-02 — compact history storage

- Undo and redo stacks now retain the compact JSON bytes already produced for
  hashing instead of duplicate nested dictionaries. Autosave reuse remains a
  dictionary and the on-disk project format is unchanged.
- `_apply_snapshot()` decodes the payload before `ProjectState.from_dict()`;
  close-time orphan-mask cleanup also decodes history before collecting paths.
- Across 50 generated smoothness-fixture edits, traced retained memory fell from
  0.631 MiB to 0.400 MiB (36.6%). Median push time stayed effectively flat at
  0.640 ms before and 0.629 ms after.
