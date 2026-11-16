#!/usr/bin/env python3
"""Time repeated 1080p static renders and a full-frame-copy lower bound."""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtWidgets import QApplication

from neuroedit_desktop.exporter import ExportSettings, ProjectExporter
from neuroedit_desktop.models import ProjectState, Slide, new_id


def main() -> None:
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="neuroedit-static-benchmark-") as temp:
        root = Path(temp)
        image = root / "image.png"
        pixels = np.random.default_rng(0).integers(0, 256, (1080, 1920, 3), dtype=np.uint8)
        if not cv2.imwrite(str(image), pixels):
            raise RuntimeError("Could not create fixture")
        for kind in ("image", "slide"):
            project = ProjectState()
            if kind == "image":
                project.add_image_clip(image, 1920, 1080, display_duration=6)
            else:
                project.slides.append(Slide(
                    id=new_id(), title="A representative static title",
                    content="A representative teaching slide with a few lines of text.",
                    duration=6, start_time=0,
                ))
            exporter = ProjectExporter(project, ExportSettings(root / "o.mp4", 1920, 1080, 30, 20, "test"))
            frame = exporter._render_frame(0)  # warm caches and fonts
            count = 180
            started = time.perf_counter()
            for index in range(count):
                exporter._render_frame(index / 30)
            render_seconds = time.perf_counter() - started
            started = time.perf_counter()
            for _ in range(count):
                frame.copy()
            copy_seconds = time.perf_counter() - started
            print(f"{kind}: {count} renders {render_seconds:.3f}s; copies {copy_seconds:.3f}s")
    app.quit()


if __name__ == "__main__":
    main()
