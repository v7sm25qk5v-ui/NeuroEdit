# Unsigned alpha build for PyInstaller (cross-platform).
#   macOS:   pyinstaller --clean --noconfirm NeuroEdit.spec  -> dist/NeuroEdit.app
#   Windows: pyinstaller --clean --noconfirm NeuroEdit.spec  -> dist/NeuroEdit/NeuroEdit.exe
# The app source is identical on every platform; only the packaging step below
# branches. Keep feature work in src/ so it carries to all platforms automatically.

import sys
import os
from pathlib import Path

IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"
APP_VERSION = os.environ.get("NEUROEDIT_VERSION", "0.5.8-alpha").removeprefix("v")
APP_BUILD_VERSION = APP_VERSION.removesuffix("-alpha")

ROOT = Path.cwd()
SRC = ROOT / "src"
RESOURCES = SRC / "neuroedit_desktop" / "resources"

# App icon paths — set per platform
if IS_MACOS:
    APP_ICON = str(RESOURCES / "NeuroEdit.icns") if (RESOURCES / "NeuroEdit.icns").exists() else None
elif IS_WINDOWS:
    APP_ICON = str(RESOURCES / "NeuroEdit.ico") if (RESOURCES / "NeuroEdit.ico").exists() else None
else:
    APP_ICON = str(RESOURCES / "icon_256.png") if (RESOURCES / "icon_256.png").exists() else None

datas = []
if RESOURCES.exists():
    datas.append((str(RESOURCES), "neuroedit_desktop/resources"))

# Bundle the imageio-ffmpeg binary so export/probe work without a system ffmpeg
# install. This is what makes the Windows build self-contained (Windows has no
# system ffmpeg); it is harmless and useful on macOS too. The runtime
# imageio_ffmpeg.get_ffmpeg_exe() looks under <pkg>/binaries/, so mirror that path.
binaries = []
try:
    import imageio_ffmpeg

    binaries.append((imageio_ffmpeg.get_ffmpeg_exe(), "imageio_ffmpeg/binaries"))
except Exception as exc:  # pragma: no cover - build-time diagnostic only
    print(f"WARNING: could not locate imageio-ffmpeg binary to bundle: {exc}")

block_cipher = None

a = Analysis(
    ["src/neuroedit_desktop/__main__.py"],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "cv2",
        "numpy",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtWidgets",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Keep the unsigned alpha small and avoid bundling optional SAM/ML stacks.
        "torch",
        "torchvision",
        "transformers",
        "safetensors",
        "huggingface_hub",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NeuroEdit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=APP_ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NeuroEdit",
)

# macOS wraps the collected folder in an .app bundle. On Windows/Linux the
# COLLECT folder (dist/NeuroEdit/) is the distributable; the installer packages it.
if IS_MACOS:
    app = BUNDLE(
        coll,
        name="NeuroEdit.app",
        icon=APP_ICON,
        bundle_identifier="org.neuroedit.alpha",
        info_plist={
            "CFBundleName": "NeuroEdit",
            "CFBundleDisplayName": "NeuroEdit",
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_BUILD_VERSION,
            "NSMicrophoneUsageDescription": "NeuroEdit uses the microphone when you record narration.",
            "NSDocumentsFolderUsageDescription": "NeuroEdit opens and saves video editing projects.",
            "NSDownloadsFolderUsageDescription": "NeuroEdit can import media from Downloads.",
            "NSDesktopFolderUsageDescription": "NeuroEdit can import media from Desktop.",
            "NSCameraUsageDescription": "NeuroEdit does not use the camera.",
        },
    )
