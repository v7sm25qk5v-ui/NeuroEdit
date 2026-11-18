"""NE-030 small lifecycle items (b, f, e, d, a, g, h, c)."""
# ruff: noqa: F811
from types import SimpleNamespace

from test_main_window_headless import _wait_for_import, app, window  # noqa: F401,E402

from neuroedit_desktop.models import ProjectState
from neuroedit_desktop.ui import audio_panel
from neuroedit_desktop.ui.audio_panel import AudioPanel


# ---- b: unique recording names -------------------------------------------------

def test_two_takes_in_same_second_get_distinct_files(app, tmp_path, monkeypatch):
    monkeypatch.setattr(audio_panel.time, "time", lambda: 1_700_000_000.4)
    monkeypatch.setattr(audio_panel.QMediaDevices, "defaultAudioInput", lambda: SimpleNamespace(isNull=lambda: False))
    monkeypatch.setattr(audio_panel, "QAudioInput", lambda *a: object())
    panel = AudioPanel(ProjectState(), tmp_path)
    panel.recorder = SimpleNamespace(setOutputLocation=lambda u: None, record=lambda: None)
    panel.capture_session = SimpleNamespace(setAudioInput=lambda v: None)
    panel._start_recording()
    first = panel._recording_path
    first.write_bytes(b"take one")
    panel._start_recording()
    second = panel._recording_path
    assert first != second
    assert first.read_bytes() == b"take one"
    second.write_bytes(b"x")
    panel._start_recording()
    assert panel._recording_path not in (first, second)


# ---- f: library label is truthful ----------------------------------------------

def test_library_relative_time_uses_modified_label_for_file_mtime():
    import time

    from neuroedit_desktop.ui.project_library import relative_time

    now = time.time()
    assert relative_time(now, "Modified") == "Modified today"
    assert relative_time(now - 3 * 86400, "Modified") == "Modified 3 days ago"
    assert relative_time(now) == "Opened today"  # default kept for other callers


def test_library_card_does_not_claim_opened_for_mtime(app, tmp_path):
    import json

    from PySide6.QtCore import QSettings

    from neuroedit_desktop.ui.main_window import ProjectLibraryDialog

    proj = tmp_path / "A" / "project.json"
    proj.parent.mkdir()
    proj.write_text(json.dumps({"project_name": "A", "clips": []}), encoding="utf-8")
    settings = QSettings("NeuroEdit", "Desktop")
    settings.setValue("recentProjects", [str(proj)])
    dialog = ProjectLibraryDialog()
    try:
        texts = [dialog.list_widget.item(i).text() for i in range(dialog.list_widget.count())]
    finally:
        dialog.close()
    assert texts and all("Modified today" in t and "Opened" not in t for t in texts)


# ---- e: no per-tick filesystem calls --------------------------------------------

class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _count_fs(monkeypatch, target):
    """Count Path.stat / Path.exists calls whose target path equals `target`."""
    import pathlib

    calls = []
    real_stat, real_exists = pathlib.Path.stat, pathlib.Path.exists

    def stat(self, *a, **k):
        if str(self) == str(target):
            calls.append("stat")
        return real_stat(self, *a, **k)

    def exists(self, *a, **k):
        if str(self) == str(target):
            calls.append("exists")
        return real_exists(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "stat", stat)
    monkeypatch.setattr(pathlib.Path, "exists", exists)
    return calls


def test_audio_preview_does_not_stat_every_tick_but_notices_deletion(app, tmp_path, monkeypatch):
    from PySide6.QtMultimedia import QMediaPlayer

    from neuroedit_desktop.models import AudioTrack
    from neuroedit_desktop.ui import audio_preview

    class P:
        MediaStatus = QMediaPlayer.MediaStatus
        PlaybackState = QMediaPlayer.PlaybackState

        def __init__(self, parent):
            self.mediaStatusChanged = SimpleNamespace(connect=lambda cb: None)
            self.pos = 0

        def setAudioOutput(self, o): pass
        def setSource(self, s): pass
        def mediaStatus(self): return QMediaPlayer.MediaStatus.LoadingMedia
        def position(self): return self.pos
        def setPosition(self, p): self.pos = p
        def setPlaybackRate(self, r): pass
        def playbackState(self): return QMediaPlayer.PlaybackState.StoppedState
        def play(self): pass
        def stop(self): pass
        def deleteLater(self): pass

    class Out:
        def __init__(self, parent): pass
        def setVolume(self, v): pass
        def deleteLater(self): pass

    monkeypatch.setattr(audio_preview, "QMediaPlayer", P)
    monkeypatch.setattr(audio_preview, "QAudioOutput", Out)
    clock = _Clock()
    monkeypatch.setattr(audio_preview.time, "monotonic", clock)
    audio = tmp_path / "n.wav"
    audio.touch()
    project = ProjectState(audio_tracks=[AudioTrack("a", str(audio), "A", start_time=0, duration=100)])
    preview = audio_preview.AudioPreview()
    calls = _count_fs(monkeypatch, audio)
    for _ in range(60):  # ~2 s of 33 ms ticks, but the clock below only moves 0.6 s
        clock.now += 0.01
        project.current_time += 0.01
        preview.sync(project, True)
    assert calls.count("exists") == 1 and "a" in preview._players  # one probe, 60 ticks
    audio.unlink()
    clock.now += 1.1
    preview.sync(project, True)
    assert "a" not in preview._players  # deletion noticed within about a second


def test_audio_preview_seek_rechecks_file_immediately(app, tmp_path, monkeypatch):
    from neuroedit_desktop.models import AudioTrack
    from neuroedit_desktop.ui import audio_preview

    clock = _Clock()
    monkeypatch.setattr(audio_preview.time, "monotonic", clock)
    audio = tmp_path / "n.wav"
    audio.touch()
    preview = audio_preview.AudioPreview()
    track = AudioTrack("a", str(audio), "A", start_time=0, duration=100)
    project = ProjectState(audio_tracks=[track])
    assert preview._file_exists(str(audio), clock.now, fresh=False)
    audio.unlink()
    assert preview._file_exists(str(audio), clock.now + 0.1, fresh=False)  # cached
    assert not preview._file_exists(str(audio), clock.now + 0.1, fresh=True)  # seek
    del project


def test_clip_media_problem_check_stats_once_per_interval(app, tmp_path, monkeypatch):
    from neuroedit_desktop.models import VideoClip
    from neuroedit_desktop.ui import main_window
    from neuroedit_desktop.ui.main_window import MainWindow

    img = tmp_path / "still.png"
    from PySide6.QtGui import QImage

    image = QImage(4, 4, QImage.Format.Format_RGB32)
    image.fill(0)
    assert image.save(str(img))
    clip = VideoClip(id="c1", path=str(img), name="s", media_type="image", duration=3)
    stub = MainWindow.__new__(MainWindow)
    stub._media_problem_cache = {}
    stub._media_stat_cache = {}
    clock = _Clock()
    monkeypatch.setattr(main_window.time, "monotonic", clock)
    calls = _count_fs(monkeypatch, img)
    assert stub._cached_clip_media_problem(clip) is None
    after_first = len(calls)
    for _ in range(100):
        clock.now += 0.005
        assert stub._cached_clip_media_problem(clip) is None
    assert len(calls) == after_first  # no filesystem call on the other 100 ticks
    img.unlink()
    clock.now += 1.1
    assert stub._cached_clip_media_problem(clip) == "file is missing"


def test_split_clips_share_source_validation(app, tmp_path, monkeypatch):
    from neuroedit_desktop.models import VideoClip
    from neuroedit_desktop.ui import main_window

    source = tmp_path / "shared.mp4"
    source.write_bytes(b"original")
    clips = [
        VideoClip(id=str(i), path=str(source), name="Part", duration=10,
                  start_time=i, trim_start=i, trim_end=i + 1)
        for i in range(3)
    ]
    stub = main_window.MainWindow.__new__(main_window.MainWindow)
    stub._media_problem_cache = {}
    stub._media_stat_cache = {}
    clock = _Clock()
    probes = []

    def probe(path):
        probes.append(path)
        return (10, 160, 90) if path.read_bytes() == b"original" else (0, 0, 0)

    monkeypatch.setattr(main_window.time, "monotonic", clock)
    monkeypatch.setattr(main_window, "probe_video", probe)
    for clip in clips:
        assert stub._cached_clip_media_problem(clip) is None
    assert probes == [source]
    source.write_bytes(b"replacement")
    clock.now += 1.1
    for clip in clips:
        assert stub._cached_clip_media_problem(clip) == "video could not be read"
    assert probes == [source, source]


# ---- d: import progress dialog is window-modal ----------------------------------

def test_import_progress_dialog_is_window_modal_and_cancel_works(window, tmp_path, monkeypatch):
    import threading
    import time

    from PySide6.QtCore import Qt

    from neuroedit_desktop.ui import main_window as main_window_module

    started = threading.Event()

    def probe(_path):
        started.set()
        time.sleep(0.2)
        return (1.0, 100, 100)

    monkeypatch.setattr(main_window_module, "probe_video", probe)
    window._import_media_files([tmp_path / "a.mov"])
    assert window._import_progress.windowModality() == Qt.WindowModality.WindowModal
    assert started.wait(2)
    window._import_progress.canceled.emit()  # the dialog's Cancel button
    _wait_for_import(window)
    assert not window.project.clips


# ---- a: Save As keeps undo history and reloads the frame ------------------------

def test_save_as_keeps_history_migrates_snapshot_assets_and_reloads_frame(window, tmp_path, monkeypatch):
    from pathlib import Path

    from neuroedit_desktop.models import Annotation
    from neuroedit_desktop.ui import main_window as mw

    monkeypatch.setattr(window, "_sync_player_to_timeline", lambda **_k: None)
    old_root = window.store.project_path.parent
    (old_root / "masks").mkdir(parents=True, exist_ok=True)
    mask = old_root / "masks" / "m.png"
    mask.write_bytes(b"mask")
    window.project.annotations.append(Annotation(
        id="a1", frame_time=0.0, ann_duration=1.0, type="mask", label="Mask",
        color="#fff", mask_path=str(mask)))
    window._mark_dirty()
    window.project.project_name = "Before"
    window._mark_dirty()  # second undo step
    depth = len(window._undo_stack)
    assert depth >= 3 and window.undo_action.isEnabled()

    reloaded = []
    monkeypatch.setattr(window, "_load_active_clip", lambda: reloaded.append(True))
    dest = tmp_path / "Saved"
    dest.mkdir()
    monkeypatch.setattr(mw.QInputDialog, "getText", lambda *a, **k: ("Copy", True))
    monkeypatch.setattr(mw.QFileDialog, "getExistingDirectory", lambda *a: str(dest))
    window._save_project_as()

    new_root = dest / "Copy"
    assert (new_root / "project.json").exists()
    assert len(window._undo_stack) == depth and window.undo_action.isEnabled()
    assert reloaded, "frame must be reloaded after Save As"
    assert mask.exists(), "original assets are never deleted"
    window.undo()
    restored = window.project.annotations[0].mask_path
    assert Path(restored) == new_root / "masks" / "m.png" and Path(restored).exists()
    window.undo()
    assert not window.project.annotations
    window.redo()
    assert window.project.annotations[0].mask_path == restored
    assert window.project.project_name == "Copy"


# ---- g: project schema version ---------------------------------------------------

def test_schema_version_written_and_old_files_load_as_v1(tmp_path):
    import json

    from neuroedit_desktop.project_store import ProjectStore

    store = ProjectStore.create(tmp_path / "p")
    store.save(ProjectState(project_name="X"))
    data = json.loads(store.project_path.read_text())
    assert data["schema_version"] == 1
    del data["schema_version"]  # a file from before the field existed
    loaded = ProjectState.from_dict(data)
    assert loaded.loaded_schema_version == loaded.schema_version == 1
    assert ProjectState.from_dict(loaded.to_dict()).to_dict() == loaded.to_dict()
    assert ProjectState.from_dict({"schema_version": "junk"}).loaded_schema_version == 1


def test_newer_schema_opens_with_warning_and_older_does_not(window, tmp_path, monkeypatch):
    from neuroedit_desktop.models import SCHEMA_VERSION
    from neuroedit_desktop.project_store import ProjectStore
    from neuroedit_desktop.ui import main_window as mw

    warnings = []
    monkeypatch.setattr(mw.QMessageBox, "warning", lambda *a: warnings.append(a[1:]))
    newer = ProjectState.from_dict({"schema_version": SCHEMA_VERSION + 1, "project_name": "Future"})
    assert newer.loaded_schema_version == SCHEMA_VERSION + 1
    window._activate_project(ProjectStore.create(tmp_path / "n"), newer)
    assert window.project is newer and window.project.project_name == "Future"
    assert len(warnings) == 1
    assert "newer version" in warnings[0][0].lower() and "lose" in warnings[0][1]
    window._activate_project(ProjectStore.create(tmp_path / "o"), ProjectState.from_dict({}))
    assert len(warnings) == 1  # a v1/legacy file does not warn


# ---- h: sys.excepthook ----------------------------------------------------------

def test_excepthook_logs_without_message_shows_once_per_burst_and_never_raises(tmp_path, monkeypatch):
    from neuroedit_desktop import __main__ as entry
    from neuroedit_desktop import diagnostics

    monkeypatch.setattr(diagnostics, "log_dir", lambda: tmp_path)
    monkeypatch.setattr(entry, "_last_error_time", None)
    clock = _Clock()
    shown = []

    SECRET = "/".join(["", "Users", "jane", "Patient Smith", "case.mp4"])

    def boom():
        raise ValueError(SECRET)

    try:
        boom()
    except ValueError as exc:
        info = (type(exc), exc, exc.__traceback__)
    entry.handle_unhandled_exception(*info, show=lambda: shown.append(1), now=clock)
    clock.now += 2
    entry.handle_unhandled_exception(*info, show=lambda: shown.append(1), now=clock)
    assert shown == [1]  # one box for the burst
    clock.now += 60
    entry.handle_unhandled_exception(*info, show=lambda: shown.append(1), now=clock)
    assert shown == [1, 1]
    log = (tmp_path / "crash.log").read_text()
    assert "ValueError" in log and "boom" in log
    assert SECRET not in log and "Smith" not in log

    def bad_show():
        raise RuntimeError("dialog failed")

    clock.now += 60
    entry.handle_unhandled_exception(*info, show=bad_show, now=clock)  # must not raise
    entry.handle_unhandled_exception(None, None, None)  # garbage input must not raise


def test_error_box_text_has_no_paths(monkeypatch):
    from neuroedit_desktop import __main__ as entry

    seen = []
    monkeypatch.setattr(entry.QMessageBox, "warning", lambda *a: seen.append(a[2]))
    entry._show_error_box()
    assert seen and "/" not in seen[0] and "\\" not in seen[0]


def test_error_box_from_a_worker_thread_is_shown_on_the_gui_thread(monkeypatch):
    """Widgets may only be used on the GUI thread; a slot that raises on an
    export, SAM, or import worker must not open the message box there."""
    import threading

    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication, QMessageBox

    from neuroedit_desktop import __main__ as entry

    app = QApplication.instance() or QApplication([])
    shown_on = []
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda *a, **k: shown_on.append(QThread.currentThread() is app.thread())),
    )

    worker = threading.Thread(target=entry._show_error_box)
    worker.start()
    worker.join()
    assert shown_on == [], "nothing may be shown from the worker thread itself"

    for _ in range(50):
        app.processEvents()
        if shown_on:
            break
    assert shown_on == [True]
