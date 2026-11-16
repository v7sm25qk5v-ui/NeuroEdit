"""Exported overlays sit on the letterboxed source, as in the preview (NE-012).

The preview paints labels, shapes, and masks in the source's own pixel space.
The exporter fits the source into the output frame, so overlays must be mapped
onto that fitted rectangle (position, stroke weight, and text size) instead of
being stretched across the whole output frame.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from neuroedit_desktop.exporter import ExportSettings, ProjectExporter  # noqa: E402
from neuroedit_desktop.models import Annotation, ProjectState, Slide, new_id  # noqa: E402

RED = "#ff0000"


@pytest.fixture(scope="module", autouse=True)
def qt_app():
    return QApplication.instance() or QApplication([])


def _annotation(kind: str, geometry: dict, **fields) -> Annotation:
    return Annotation(
        id=new_id(), frame_time=0.0, ann_duration=0.0, type=kind,
        label=fields.pop("label", kind), color=RED, opacity=1.0,
        geometry=geometry, **fields,
    )


def _render(tmp_path, source: tuple[int, int] | None, output: tuple[int, int],
            *annotations: Annotation, slide: Slide | None = None) -> np.ndarray:
    """Render one frame of a white image clip of `source` size (width, height)."""
    project = ProjectState()
    if source is not None:
        width, height = source
        path = tmp_path / f"white-{width}x{height}.png"
        cv2.imwrite(str(path), np.full((height, width, 3), 255, dtype=np.uint8))
        project.add_image_clip(path, width, height, display_duration=5.0)
    if slide is not None:
        project.slides.append(slide)
    project.annotations.extend(annotations)
    exporter = ProjectExporter(
        project, ExportSettings(tmp_path / "out.mp4", output[0], output[1], 30, 20, "test")
    )
    try:
        return exporter._render_frame(1.0)
    finally:
        exporter._release_captures()


def _fitted(source: tuple[int, int], output: tuple[int, int]) -> tuple[int, int, int, int]:
    scale = min(output[0] / source[0], output[1] / source[1])
    width, height = round(source[0] * scale), round(source[1] * scale)
    return (output[0] - width) // 2, (output[1] - height) // 2, width, height


def _red(frame: np.ndarray) -> np.ndarray:
    r, g, b = (frame[..., i].astype(int) for i in range(3))
    return (r > 180) & (g < 90) & (b < 90)


def _bounds(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    assert xs.size, "nothing was painted"
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


FULL_FRAME = {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0, "width_px": 4}

SOURCES = [
    pytest.param((100, 100), (200, 100), id="square-in-wide"),
    pytest.param((80, 160), (200, 100), id="portrait-in-wide"),
    pytest.param((400, 100), (200, 200), id="wide-in-square"),
    pytest.param((160, 120), (320, 180), id="4x3-in-16x9"),
]


@pytest.mark.parametrize("source, output", SOURCES)
def test_shape_is_drawn_on_the_fitted_source_not_the_whole_frame(tmp_path, source, output):
    frame = _render(tmp_path, source, output, _annotation("rect", dict(FULL_FRAME)))

    x, y, width, height = _fitted(source, output)
    left, top, right, bottom = _bounds(_red(frame))
    # A full-frame rectangle outlines the fitted picture: it reaches each edge
    # (within the stroke) and never crosses into the letterbox bars.
    assert left == pytest.approx(x, abs=4) and right == pytest.approx(x + width - 1, abs=4)
    assert top == pytest.approx(y, abs=4) and bottom == pytest.approx(y + height - 1, abs=4)
    assert left >= x - 3 and right <= x + width + 2
    assert top >= y - 3 and bottom <= y + height + 2


@pytest.mark.parametrize("source, output", SOURCES)
def test_mask_is_drawn_on_the_fitted_source(tmp_path, source, output):
    mask_path = tmp_path / "mask.png"
    mask = np.zeros((source[1], source[0], 4), dtype=np.uint8)
    mask[..., 2] = 255  # BGRA: opaque red over the whole source
    mask[..., 3] = 255
    cv2.imwrite(str(mask_path), mask)

    frame = _render(
        tmp_path, source, output, _annotation("mask", {}, mask_path=str(mask_path)),
    )

    x, y, width, height = _fitted(source, output)
    red = _red(frame)
    assert red[y + 2:y + height - 2, x + 2:x + width - 2].all()
    outside = red.copy()
    outside[max(0, y - 1):y + height + 1, max(0, x - 1):x + width + 1] = False
    assert not outside.any(), "mask must not spill into the letterbox bars"


def test_arrow_and_text_follow_the_fitted_source(tmp_path):
    source, output = (100, 100), (200, 100)
    arrow = _annotation(
        "arrow", {"x1": 0.25, "y1": 0.5, "x2": 0.75, "y2": 0.5, "width_px": 2},
        show_label=False,
    )
    frame = _render(tmp_path, source, output, arrow)
    left, _top, right, _bottom = _bounds(_red(frame))
    assert left == pytest.approx(50 + 25, abs=3)
    assert right == pytest.approx(50 + 75, abs=3)

    text = _annotation("text", {"x": 0.5, "y": 0.5}, label="X", font_size=12)
    frame = _render(tmp_path, source, output, text)
    picture = frame[:, 50:150]  # the fitted source, without the black bars
    left, top, _right, _bottom = _bounds(picture.max(axis=2) < 200)  # the label's backing box
    assert left == pytest.approx(50, abs=3)    # half-way across the picture
    assert top == pytest.approx(50, abs=3)


@pytest.mark.parametrize("output_height, expected", [(100, 5), (200, 10), (400, 20), (800, 40)])
def test_stroke_weight_scales_with_the_exported_picture(tmp_path, output_height, expected):
    """A 20 px stroke on a 400 px-high source is 5% of the picture height in the
    preview, so it must stay 5% at every export size."""
    rect = _annotation(
        "rect", {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5, "width_px": 20},
        show_label=False,
    )
    frame = _render(tmp_path, (400, 400), (output_height, output_height), rect)

    middle_row = _red(frame)[output_height // 2]
    left_edge = middle_row[: output_height // 2]
    assert int(left_edge.sum()) == pytest.approx(expected, abs=2)


def test_label_text_scales_with_the_exported_picture(tmp_path):
    def label_box(output_height: int) -> tuple[int, int]:
        text = _annotation("text", {"x": 0.1, "y": 0.1}, label="Tumor margin", font_size=40)
        frame = _render(tmp_path, (800, 800), (output_height, output_height), text)
        left, top, right, bottom = _bounds(frame.max(axis=2) < 200)
        return right - left + 1, bottom - top + 1

    native, half = label_box(800), label_box(400)

    assert half[0] == pytest.approx(native[0] / 2, abs=4)
    assert half[1] == pytest.approx(native[1] / 2, abs=3)


def test_same_size_export_matches_output_space_painting(tmp_path):
    """With no scaling or letterbox, source space and output space are the same
    thing, so a clip and a blank frame of that size place the shape identically."""
    rect = {"x": 0.2, "y": 0.3, "width": 0.4, "height": 0.5, "width_px": 6}
    on_clip = _render(tmp_path, (200, 100), (200, 100), _annotation("rect", dict(rect), show_label=False))
    on_blank = _render(tmp_path, None, (200, 100), _annotation("rect", dict(rect), show_label=False))

    assert np.array_equal(_red(on_clip), _red(on_blank))


def test_full_frame_slide_and_empty_timeline_keep_output_coordinates(tmp_path):
    slide = Slide(id="slide", title="", duration=5, start_time=0, background="#ffffff")
    for kwargs in ({"slide": slide}, {}):
        frame = _render(tmp_path, None, (200, 100), _annotation("rect", dict(FULL_FRAME)), **kwargs)
        left, top, right, bottom = _bounds(_red(frame))
        assert (left, top) == (0, 0)
        assert right >= 197 and bottom >= 97


def test_overlay_slide_over_a_clip_still_uses_the_clip_fit(tmp_path):
    overlay = Slide(id="overlay", title="", duration=5, start_time=0, overlay=True)
    frame = _render(tmp_path, (100, 100), (200, 100), _annotation("rect", dict(FULL_FRAME)), slide=overlay)

    left, _top, right, _bottom = _bounds(_red(frame))
    assert left >= 47 and right <= 152


# --- Review follow-ups ------------------------------------------------------


@pytest.mark.parametrize("kind, geometry", [
    ("ellipse", {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5, "width_px": 2}),
    ("brush", {"points": [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]], "width_px": 2}),
])
def test_ellipse_and_brush_follow_the_fitted_source(tmp_path, kind, geometry):
    frame = _render(tmp_path, (100, 100), (200, 100), _annotation(kind, geometry, show_label=False))

    left, top, right, bottom = _bounds(_red(frame))
    assert (left, right) == (pytest.approx(75, abs=3), pytest.approx(125, abs=3))
    assert (top, bottom) == (pytest.approx(25, abs=3), pytest.approx(75, abs=3))


def test_overlay_fit_follows_the_decoded_picture_not_stale_clip_metadata(tmp_path):
    project = ProjectState()
    path = tmp_path / "square.png"
    cv2.imwrite(str(path), np.full((100, 100, 3), 255, dtype=np.uint8))
    clip = project.add_image_clip(path, 100, 100, display_duration=5.0)
    clip.width, clip.height = 1920, 1080  # wrong on purpose
    project.annotations.append(_annotation("rect", dict(FULL_FRAME)))
    exporter = ProjectExporter(project, ExportSettings(tmp_path / "out.mp4", 200, 100, 30, 20, "test"))
    try:
        frame = exporter._render_frame(1.0)
    finally:
        exporter._release_captures()

    left, _top, right, _bottom = _bounds(_red(frame))
    assert left == pytest.approx(50, abs=4) and right == pytest.approx(149, abs=4)


def test_overlay_mapping_does_not_move_redactions_or_captions(tmp_path):
    """The source-space mapping applies to overlays only; whatever is painted
    after them (fade, captions, redactions) keeps its own coordinates."""
    redaction = Annotation(
        id=new_id(), frame_time=0.0, ann_duration=0.0, type="redact", label="Redacted",
        color="#000000", opacity=1.0, geometry={"x": 0.0, "y": 0.0, "width": 0.25, "height": 1.0},
    )
    alone = _render(tmp_path, (100, 100), (200, 100), redaction)
    with_overlay = _render(
        tmp_path, (100, 100), (200, 100),
        _annotation("rect", {"x": 0.6, "y": 0.6, "width": 0.3, "height": 0.3, "width_px": 2},
                    show_label=False),
        redaction,
    )

    black = lambda frame: frame.max(axis=2) == 0  # noqa: E731
    assert np.array_equal(black(alone), black(with_overlay))
    assert black(with_overlay)[:, 50:75].all()        # left quarter of the picture
    assert not black(with_overlay)[:, 80:150].any()
