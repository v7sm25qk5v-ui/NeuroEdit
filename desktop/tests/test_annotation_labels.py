from __future__ import annotations

import pytest
from PySide6.QtCore import QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter
from PySide6.QtWidgets import QApplication

from neuroedit_desktop.annotation_label import annotation_label_layout
from neuroedit_desktop.exporter import ExportSettings, ProjectExporter
from neuroedit_desktop.models import Annotation, ProjectState
from neuroedit_desktop.ui.canvas import VideoGraphicsView


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _label(kind="rect", **fields):
    return Annotation(
        id="label", frame_time=0, ann_duration=0, type=kind, color="#ffffff",
        label=fields.pop("label", "Resection cavity"), opacity=1.0,
        geometry={"x": 0.93, "y": 0.96, "width": 0.04, "height": 0.03}, **fields,
    )


@pytest.mark.parametrize("kind", ["rect", "text"])
def test_fitted_label_inside_frame_has_matching_preview_and_export(app, tmp_path, kind):
    w, h = 400, 200
    label = _label(kind, font_size=28)
    project = ProjectState(annotations=[label])
    view = VideoGraphicsView(project)
    view.annotation_item.set_size(QSizeF(w, h))
    exporter = ProjectExporter(project, ExportSettings(tmp_path / "unused.mp4", w, h, 30, 20, "test"))
    layout = annotation_label_layout(label, w, h)
    assert layout is not None
    assert layout.frame_shift.x() < 0
    assert QRectF(0, 0, w, h).contains(layout.box)
    assert layout.font.pixelSize() > 0
    assert layout.text_box.width() > label.geometry["width"] * w
    assert layout.text_box.contains(
        QFontMetricsF(layout.font).boundingRect(layout.text_box, layout.flags, label.label)
    )

    def render(font_family, paint):
        target = QImage(w, h, QImage.Format.Format_RGB32)
        target.fill(QColor("#654321"))
        painter = QPainter(target)
        painter.setFont(QFont(font_family, 48))
        paint(painter, label, w, h)
        painter.end()
        return target

    def preview(painter, label, width, height):
        view.annotation_item._paint_shape(painter, label, width, height, preview=False)

    preview_image = render("Monospace", preview)
    export_image = render("Sans Serif", exporter._paint_annotation_shape)
    assert preview_image == export_image

    # Verify the whole reference lettering appears inside the box whether the
    # local font fits on one line or wraps. Outside this interior, white may be
    # the shape or border.
    reference = QImage(w, h, QImage.Format.Format_RGB32)
    reference.fill(QColor("#000000"))
    painter = QPainter(reference)
    painter.setFont(layout.font)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(layout.text_box, layout.flags | int(Qt.TextFlag.TextDontClip), label.label)
    painter.end()
    interior = layout.text_box.toAlignedRect()
    lettering = {
        (x, y) for y in range(interior.top(), interior.bottom() + 1)
        for x in range(interior.left(), interior.right() + 1)
        if reference.pixelColor(x, y).red() > 220
    }
    assert lettering
    assert all(preview_image.pixelColor(x, y).red() > 220 for x, y in lettering)


def test_oversized_label_wraps_and_shrinks_without_dropping_text(app):
    label = _label(label="LongUnbrokenLabelResectionCavity Landmark\nNext line", font_size=96)
    layout = annotation_label_layout(label, 160, 80)
    assert layout is not None
    assert layout.text == label.label
    assert 0 < layout.font.pixelSize() < 96 * QFontMetricsF(layout.font).fontDpi() / 72
    metrics = QFontMetricsF(layout.font)
    assert layout.text_box.height() > metrics.height() * 2
    assert layout.text_box.contains(metrics.boundingRect(layout.text_box, layout.flags, layout.text))


def test_drag_starts_at_the_fitted_label_box(app):
    label = _label(font_size=24)
    project = ProjectState(annotations=[label], selected_annotation_id=label.id)
    view = VideoGraphicsView(project)
    w, h = 800, 400
    view.annotation_item.set_size(QSizeF(w, h))
    before = view.annotation_item.attached_label_rect(label, w, h)
    x, y = before.center().x() / w, before.center().y() / h

    view._select_press((x, y))
    view._select_drag((x - 0.05, y))

    assert view._select_mode == "label"
    assert label.geometry["x"] == 0.93  # the shape stays in place
    after = view.annotation_item.attached_label_rect(label, w, h)
    assert after.left() == pytest.approx(before.left() - 0.05 * w)
