"""User-initiated, verified release downloads; never launches installers."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from neuroedit_desktop import __version__
from neuroedit_desktop.update_release import _version, is_newer_version, parse_release

API_URL = "https://api.github.com/repos/v7sm25qk5v-ui/NeuroEdit/releases/latest"
MAX_METADATA = 2 * 1024 * 1024


def installed_release_tag():
    """Return the packaged tag when it matches the installed numeric version."""
    try:
        path = Path(__file__).parent / "resources" / "build_info.json"
        tag = json.loads(path.read_text(encoding="utf-8"))["tag"]
        if isinstance(tag, str) and _version(tag)[0] == _version(__version__)[0]:
            return tag
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return __version__


class UpdateService(QObject):
    checking = Signal()
    available = Signal(object)
    up_to_date = Signal()
    progress = Signal(int, int)
    downloaded = Signal(str, object)
    error = Signal(str)
    cancelled = Signal()

    def __init__(self, current_version=None, parent=None, *, platform=None):
        super().__init__(parent)
        self._platform = platform or sys.platform
        self._current_version = current_version or installed_release_tag()
        self._manager = QNetworkAccessManager(self)
        self._reply = None
        self._disposed = False
        self._starting = False
        self._directory = None
        self._file = None
        self._release = None
        self._buffer = bytearray()
        self._count = 0
        self._hash = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._timed_out)

    def _request(self, url):
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", b"NeuroEdit-Updater")
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        request.setTransferTimeout(30000)
        self._reply = self._manager.get(request)
        reply = self._reply
        reply.readyRead.connect(lambda: self._read(reply))
        reply.finished.connect(lambda: self._finished(reply))
        self._timer.start(10 * 60 * 1000)

    def check_for_updates(self):
        if self._disposed or self._reply or self._starting:
            return
        self._release = None
        self._buffer.clear()
        self._starting = True
        try:
            self.checking.emit()
            if not self._disposed:
                self._request(API_URL)
        finally:
            self._starting = False

    def download_update(self, release):
        if self._disposed or self._reply or self._starting:
            return
        # Revalidate even if a caller constructs its own dataclass.
        try:
            asset = release.asset
            payload = {"tag_name": release.tag_name, "html_url": release.html_url,
                       "body": release.body, "assets": [{"name": asset.name,
                       "browser_download_url": asset.url, "size": asset.size,
                       "digest": "sha256:" + asset.sha256}]}
            self._release = parse_release(payload, self._platform, self._current_version)
            if not is_newer_version(self._release.tag_name, self._current_version):
                raise ValueError("The selected release is not newer than this installation")
            self._directory = tempfile.mkdtemp(prefix="neuroedit-update-")
            path = Path(self._directory) / asset.name
            self._file = open(path, "xb")
            self._count = 0
            self._hash = hashlib.sha256()
            self._request(asset.url)
        except (ValueError, AttributeError, TypeError):
            self._cleanup()
            self.error.emit("This update is invalid or is not newer than the installed version.")
        except OSError:
            self._cleanup()
            self.error.emit("Could not save the update. Check available storage and try again.")

    def _read(self, reply):
        if reply is not self._reply:
            return
        while self._reply is reply and reply.bytesAvailable():
            data = bytes(reply.read(65536))
            if not data:
                break
            if self._release is None:
                self._buffer.extend(data)
                if len(self._buffer) > MAX_METADATA:
                    self._fail("The release information is too large to use.")
                    return
            else:
                self._count += len(data)
                if self._count > self._release.asset.size:
                    self._fail("The update download exceeded its expected size.")
                    return
                try:
                    self._file.write(data)
                except OSError:
                    self._fail("Could not save the update. Check available storage and try again.")
                    return
                self._hash.update(data)
                self.progress.emit(self._count, self._release.asset.size)

    def _finished(self, reply):
        if reply is not self._reply:
            return
        self._read(reply)
        if self._reply is not reply:
            return
        reply = self._reply
        self._reply = None
        self._timer.stop()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        network_error = reply.error()
        reply.deleteLater()
        if network_error != QNetworkReply.NetworkError.NoError or status != 200:
            self._cleanup()
            if status in (403, 429):
                self.error.emit("GitHub refused the update request or its rate limit was reached. Please try again later.")
            else:
                self.error.emit("Could not reach GitHub for the update. Check your connection and try again.")
            return
        if self._release is None:
            try:
                payload = json.loads(self._buffer)
                release = parse_release(payload, self._platform, self._current_version)
                if is_newer_version(release.tag_name, self._current_version):
                    self.available.emit(release)
                else:
                    self.up_to_date.emit()
            except (ValueError, UnicodeDecodeError):
                self.error.emit("The latest release information is invalid or does not include a verified download for this platform.")
        else:
            release = self._release
            if self._count != release.asset.size or self._hash.hexdigest() != release.asset.sha256:
                self._cleanup()
                self.error.emit("The update download could not be verified. Please try again.")
                return
            try:
                self._file.close()
            except OSError:
                self._cleanup()
                self.error.emit("Could not save the update. Check available storage and try again.")
                return
            self._file = None
            path = os.path.join(self._directory, release.asset.name)
            self._directory = None  # Caller owns the verified file and its directory.
            self._release = None
            self.downloaded.emit(path, release)

    def _cleanup(self):
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None
        if self._directory:
            shutil.rmtree(self._directory, ignore_errors=True)
            self._directory = None
        self._release = None

    def _stop(self):
        reply, self._reply = self._reply, None
        self._timer.stop()
        if reply is not None:
            reply.abort()
            reply.deleteLater()
        self._cleanup()

    def _fail(self, message):
        self._stop()
        if not self._disposed:
            self.error.emit(message)

    def _timed_out(self):
        self._fail("Update request timed out")

    def cancel(self):
        if self._reply is not None:
            self._stop()
            if not self._disposed:
                self.cancelled.emit()

    def dispose(self):
        self._disposed = True
        self._stop()
