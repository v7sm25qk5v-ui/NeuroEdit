import json
from pathlib import Path
import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from PySide6.QtNetwork import QNetworkReply
from neuroedit_desktop.update_release import parse_release
from neuroedit_desktop.update_service import UpdateService
from test_update_release import payload


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


class Reply(QObject):
    readyRead = Signal()
    finished = Signal()

    def __init__(self, data):
        super().__init__()
        self.data = data
        self.aborted = False

    def bytesAvailable(self):
        return len(self.data)

    def read(self, size):
        data, self.data = self.data[:size], self.data[size:]
        return data

    def attribute(self, _attribute):
        return 200

    def error(self):
        return QNetworkReply.NetworkError.NoError

    def errorString(self):
        return ""

    def abort(self):
        self.aborted = True
        self.finished.emit()


def test_check_download_and_verify(qapp, monkeypatch):
    service = UpdateService(platform="darwin", current_version="0.5.18")
    replies = []
    def request(_url):
        reply = Reply(json.dumps(payload()).encode() if not replies else b"abc")
        replies.append(reply)
        service._reply = reply
        reply.readyRead.connect(lambda: service._read(reply))
        reply.finished.connect(lambda: service._finished(reply))
    monkeypatch.setattr(service, "_request", request)
    releases, downloaded = [], []
    service.available.connect(releases.append)
    service.downloaded.connect(lambda path, release: downloaded.append((path, release)))
    service.check_for_updates()
    replies[-1].finished.emit()
    assert len(releases) == 1
    service.download_update(releases[0])
    replies[-1].finished.emit()
    assert Path(downloaded[0][0]).read_bytes() == b"abc"
    Path(downloaded[0][0]).unlink()
    Path(downloaded[0][0]).parent.rmdir()


def test_bad_hash_and_cancellation(qapp, monkeypatch):
    service = UpdateService(platform="darwin", current_version="0.5.18")
    replies, errors, cancelled = [], [], []
    def request(_url):
        reply = Reply(b"xyz")
        replies.append(reply)
        service._reply = reply
        reply.readyRead.connect(lambda: service._read(reply))
        reply.finished.connect(lambda: service._finished(reply))
    monkeypatch.setattr(service, "_request", request)
    service.error.connect(errors.append)
    service.cancelled.connect(lambda: cancelled.append(True))
    release = parse_release(payload(), "darwin", "0.5.18")
    service.download_update(release)
    directory = service._directory
    replies[-1].finished.emit()
    assert errors and not Path(directory).exists()
    service.download_update(release)
    directory = service._directory
    service.cancel()
    assert replies[-1].aborted and cancelled and not Path(directory).exists()
    service.dispose()
    replies[-1].finished.emit()
    assert len(errors) == 1


def test_old_reply_cannot_affect_retry(qapp, monkeypatch):
    service = UpdateService(platform="darwin", current_version="0.5.18")
    replies, errors = [], []
    def request(_url):
        reply = Reply(b"abc")
        replies.append(reply)
        service._reply = reply
        reply.readyRead.connect(lambda: service._read(reply))
        reply.finished.connect(lambda: service._finished(reply))
    monkeypatch.setattr(service, "_request", request)
    service.error.connect(errors.append)
    release = parse_release(payload(), "darwin", "0.5.18")
    service.download_update(release)
    old = replies[-1]
    service.cancel()
    service.download_update(release)
    new = replies[-1]
    old.readyRead.emit()
    old.finished.emit()
    assert service._reply is new and new.bytesAvailable() == 3 and not errors
    service.cancel()


def test_same_version_download_rejected(qapp):
    service = UpdateService(platform="darwin", current_version="0.5.19")
    errors = []
    service.error.connect(errors.append)
    service.download_update(parse_release(payload(), "darwin", "0.5.19"))
    assert errors and service._reply is None


@pytest.mark.parametrize("data", [b"ab", b"abcd", b"xyz"])
def test_invalid_download_is_removed(qapp, monkeypatch, data):
    service = UpdateService("0.5.18", platform="darwin")
    errors = []
    service.error.connect(errors.append)
    def request(_url):
        reply = Reply(data)
        service._reply = reply
        reply.finished.connect(lambda: service._finished(reply))
    monkeypatch.setattr(service, "_request", request)
    service.download_update(parse_release(payload(), "darwin", "0.5.18"))
    directory = service._directory
    service._reply.finished.emit()
    assert errors and not Path(directory).exists()


@pytest.mark.parametrize("status,data", [(403, b""), (429, b""), (200, b"bad json")])
def test_failed_checks_are_clear(qapp, monkeypatch, status, data):
    service = UpdateService("0.5.18", platform="darwin")
    errors = []
    service.error.connect(errors.append)
    def request(_url):
        reply = Reply(data)
        reply.attribute = lambda _: status
        service._reply = reply
        reply.finished.connect(lambda: service._finished(reply))
    monkeypatch.setattr(service, "_request", request)
    service.check_for_updates()
    service._reply.finished.emit()
    assert len(errors) == 1
    if status != 200:
        assert "rate limit" in errors[0]


def test_timeout_dispose_and_up_to_date(qapp, monkeypatch):
    service = UpdateService("0.5.19", platform="darwin")
    replies, errors, up_to_date = [], [], []
    def request(_url):
        reply = Reply(json.dumps(payload()).encode())
        replies.append(reply)
        service._reply = reply
        reply.finished.connect(lambda: service._finished(reply))
    monkeypatch.setattr(service, "_request", request)
    service.error.connect(errors.append)
    service.up_to_date.connect(lambda: up_to_date.append(True))
    service.check_for_updates()
    replies[-1].finished.emit()
    assert up_to_date
    service.check_for_updates()
    service._timed_out()
    assert errors and replies[-1].aborted
    service.check_for_updates()
    service.dispose()
    replies[-1].finished.emit()
    assert len(errors) == 1 and len(up_to_date) == 1


def test_dispose_from_progress_does_not_emit_completion(qapp, monkeypatch):
    service = UpdateService("0.5.18", platform="darwin")
    results = []
    def request(_url):
        reply = Reply(b"abc")
        service._reply = reply
        reply.finished.connect(lambda: service._finished(reply))
    monkeypatch.setattr(service, "_request", request)
    service.progress.connect(lambda *_: service.dispose())
    service.downloaded.connect(lambda *_: results.append("downloaded"))
    service.error.connect(lambda *_: results.append("error"))
    service.download_update(parse_release(payload(), "darwin", "0.5.18"))
    directory = service._directory
    service._reply.finished.emit()
    assert not results and not Path(directory).exists()


def test_installed_release_tag(tmp_path, monkeypatch):
    from neuroedit_desktop import update_service
    resources = tmp_path / "resources"
    resources.mkdir()
    monkeypatch.setattr(update_service, "__file__", str(tmp_path / "update_service.py"))
    monkeypatch.setattr(update_service, "__version__", "0.5.19")
    info = resources / "build_info.json"
    info.write_text('{"tag":"v0.5.19-alpha.2"}')
    assert update_service.installed_release_tag() == "v0.5.19-alpha.2"
    info.write_text('{"tag":"v0.5.20-alpha"}')
    assert update_service.installed_release_tag() == "0.5.19"
    info.write_text("not json")
    assert update_service.installed_release_tag() == "0.5.19"
