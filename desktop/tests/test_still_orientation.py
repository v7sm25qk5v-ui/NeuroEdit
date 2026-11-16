"""NE-031: EXIF orientation is applied in the preview exactly as the exporter's cv2.imread does."""
from __future__ import annotations

import struct

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from neuroedit_desktop.models import ProjectState
from neuroedit_desktop.ui.canvas import VideoGraphicsView


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _exif_segment(orientation: int) -> bytes:
    # Minimal big-endian TIFF with one IFD0 entry: Orientation (0x0112, SHORT).
    tiff = b"MM\x00\x2a" + struct.pack(">I", 8)
    tiff += struct.pack(">H", 1) + struct.pack(">HHI", 0x0112, 3, 1)
    tiff += struct.pack(">HH", orientation, 0) + struct.pack(">I", 0)
    body = b"Exif\x00\x00" + tiff
    return b"\xff\xe1" + struct.pack(">H", len(body) + 2) + body


def _write_jpeg(path, orientation: int) -> None:
    # 200x100 stored image, red top-left quadrant on a blue field.
    img = np.zeros((100, 200, 3), np.uint8)
    img[:] = (255, 0, 0)  # BGR blue
    img[:50, :100] = (0, 0, 255)  # red
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 100])
    assert ok
    data = buf.tobytes()
    path.write_bytes(data[:2] + _exif_segment(orientation) + data[2:])


def _red_quadrant(width: int, height: int, is_red) -> tuple[str, str]:
    ys, xs = np.nonzero(is_red)
    return ("top" if ys.mean() < height / 2 else "bottom",
            "left" if xs.mean() < width / 2 else "right")


@pytest.mark.parametrize("orientation", [1, 3, 6, 8])
def test_preview_still_matches_exporter_orientation(app, tmp_path, orientation):
    path = tmp_path / f"still_{orientation}.jpg"
    _write_jpeg(path, orientation)
    expected = cv2.imread(str(path), cv2.IMREAD_COLOR)
    exp_h, exp_w = expected.shape[:2]
    if orientation in (6, 8):
        assert (exp_w, exp_h) == (100, 200)  # the helper's tag really is honoured

    view = VideoGraphicsView(ProjectState())
    view.set_image(str(path))
    pix = view.image_item.pixmap()
    assert (pix.width(), pix.height()) == (exp_w, exp_h)
    rect = view.video_item.boundingRect()
    assert (rect.width(), rect.height()) == (exp_w, exp_h)
    assert view.annotation_item.boundingRect().size() == rect.size()

    exp_red = (expected[:, :, 2] > 200) & (expected[:, :, 0] < 60)
    img = pix.toImage().convertToFormat(pix.toImage().Format.Format_RGB32)
    arr = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)
    arr = arr[:, :img.width()]
    prev_red = (arr[:, :, 2] > 200) & (arr[:, :, 0] < 60)
    assert _red_quadrant(exp_w, exp_h, exp_red) == _red_quadrant(exp_w, exp_h, prev_red)


@pytest.mark.parametrize("orientation, expected", [(1, (200, 100)), (6, (100, 200)), (8, (100, 200))])
def test_imported_still_records_its_upright_size(tmp_path, orientation, expected):
    """The clip's recorded size must describe the picture as preview and export show it."""
    from neuroedit_desktop.ui.main_window import _read_upright_image

    path = tmp_path / f"o{orientation}.jpg"
    _write_jpeg(path, orientation)
    image = _read_upright_image(path)
    upright = cv2.imread(str(path), cv2.IMREAD_COLOR)

    assert (image.width(), image.height()) == expected
    assert (image.width(), image.height()) == (upright.shape[1], upright.shape[0])


def _png_with_orientation(path, orientation: int) -> None:
    """PNG carrying an eXIf chunk. OpenCV honours it, Qt does not, which is why
    preview and export must share one decoder rather than each trust its own."""
    import zlib

    img = np.zeros((100, 200, 3), np.uint8)
    img[:] = (255, 0, 0)
    img[:50, :100] = (0, 0, 255)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    data = buf.tobytes()
    tiff = _exif_segment(orientation)[10:]  # drop the APP1 marker, length and "Exif\0\0"
    chunk = b"eXIf" + tiff
    exif = struct.pack(">I", len(tiff)) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
    ihdr_end = 8 + 8 + 13 + 4  # signature + IHDR chunk
    path.write_bytes(data[:ihdr_end] + exif + data[ihdr_end:])


@pytest.mark.parametrize("suffix", ["jpg", "png"])
@pytest.mark.parametrize("orientation", [1, 2, 3, 4, 5, 6, 7, 8])
def test_exported_still_is_the_picture_the_preview_shows(app, tmp_path, suffix, orientation):
    from neuroedit_desktop.exporter import ExportSettings, ProjectExporter

    path = tmp_path / f"o{orientation}.{suffix}"
    if suffix == "jpg":
        _write_jpeg(path, orientation)
    else:
        _png_with_orientation(path, orientation)

    project = ProjectState()
    view = VideoGraphicsView(project)
    view.set_image(str(path))
    shown = view.image_item.pixmap().toImage()

    clip = project.add_image_clip(path, shown.width(), shown.height(), display_duration=5.0)
    exporter = ProjectExporter(project, ExportSettings(tmp_path / "o.mp4", 64, 64, 30, 20, "t"))
    frame = exporter._frame_for_clip(clip, 0.0)

    assert (frame.shape[1], frame.shape[0]) == (shown.width(), shown.height())
    for x, y in [(5, 5), (shown.width() - 6, 5), (5, shown.height() - 6),
                 (shown.width() - 6, shown.height() - 6)]:
        pixel = shown.pixelColor(x, y)
        preview_is_red = pixel.red() > 150 and pixel.blue() < 100
        r, _g, b = (int(v) for v in frame[y, x])
        assert (r > 150 and b < 100) == preview_is_red, (x, y)
