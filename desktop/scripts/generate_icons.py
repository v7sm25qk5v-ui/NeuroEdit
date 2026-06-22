#!/usr/bin/env python3
"""Regenerate the OS app-icon rasters (PNG/.icns/.ico) from the aperture-mark
SVGs that live in `src/neuroedit_desktop/resources/`.

The header and About lockups render the `neuroedit-mark-{light,dark}.svg` files
directly via QSvgRenderer, so they need no rasters. This script only produces
the OS-level icon set:
  - resources/icon_{16,32,64,128,256,512}.png  (dock/taskbar/window icon)
  - resources/NeuroEdit.icns                    (macOS bundle, via iconutil)
  - resources/NeuroEdit.iconset/*               (the .icns source layout)
  - resources/NeuroEdit.ico                     (Windows exe/installer)

Source of truth: resources/neuroedit-appicon.svg (dark tile + dark mark).

Dependencies: PySide6 (project dep), Pillow (for .ico), iconutil (macOS, for
.icns). Run from the `desktop/` folder:  python scripts/generate_icons.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

RESOURCES = Path(__file__).resolve().parent.parent / "src" / "neuroedit_desktop" / "resources"
APPICON_SVG = RESOURCES / "neuroedit-appicon.svg"
ICON_PNG_SIZES = (16, 32, 64, 128, 256, 512)
ICO_SIZES = (16, 32, 48, 64, 128, 256)
# (size, iconset filename) per Apple's .iconset spec.
ICNS_SPECS = [
    (16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png"),
]


def rasterize(svg_path: Path, size: int, out_path: Path) -> None:
    renderer = QSvgRenderer(str(svg_path))
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter)
    painter.end()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path), "PNG")
    try:
        shown: Path | str = out_path.relative_to(RESOURCES.parent)
    except ValueError:
        shown = out_path.name  # temp scratch (e.g. .ico staging) lives outside the tree
    print(f"  {shown}  ({size}px)")


def build_icns(tmp_iconset: Path) -> None:
    for size, name in ICNS_SPECS:
        rasterize(APPICON_SVG, size, tmp_iconset / name)
    if sys.platform == "darwin":
        out = RESOURCES / "NeuroEdit.icns"
        subprocess.run(["iconutil", "-c", "icns", str(tmp_iconset), "-o", str(out)], check=True)
        print(f"  built {out.relative_to(RESOURCES.parent)}")
    else:
        print("  (skipped .icns: iconutil is macOS-only)")


def build_ico(tmp_dir: Path) -> None:
    try:
        from PIL import Image
    except ImportError:
        print("  (skipped .ico: pip install pillow to enable)")
        return
    for s in ICO_SIZES:
        rasterize(APPICON_SVG, s, tmp_dir / f"{s}.png")
    imgs = [Image.open(tmp_dir / f"{s}.png").convert("RGBA") for s in ICO_SIZES]
    out = RESOURCES / "NeuroEdit.ico"
    # Save from the LARGEST image and embed every rendered size via
    # append_images. Saving from the smallest (a common bug) yields an .ico
    # that contains only the 16px entry.
    imgs[-1].save(out, format="ICO", sizes=[(s, s) for s in ICO_SIZES], append_images=imgs[:-1])
    print(f"  built {out.relative_to(RESOURCES.parent)}")


def main() -> None:
    QGuiApplication(sys.argv)  # required for QImage/QPainter
    if not APPICON_SVG.exists():
        raise SystemExit(f"missing source SVG: {APPICON_SVG}")

    print("App-icon PNGs:")
    for s in ICON_PNG_SIZES:
        rasterize(APPICON_SVG, s, RESOURCES / f"icon_{s}.png")
    rasterize(APPICON_SVG, 512, RESOURCES / "icon.png")

    print("macOS .icns:")
    build_icns(RESOURCES / "NeuroEdit.iconset")

    print("Windows .ico:")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        build_ico(Path(tmp))

    print("\nDone. Rasters written to resources/.")


if __name__ == "__main__":
    main()
