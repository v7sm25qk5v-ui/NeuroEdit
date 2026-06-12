#!/usr/bin/env python3
"""Build the repeatable "smoothness fixture" QA project (plan P1.3).

Creates a NeuroEdit project containing every timeline element type so QA can
compare cold launch, project open, scrubbing, annotation dragging, panel
switching, and export startup across builds:

- one 10 s 1080p clip and one 6 s 4K clip (synthesized with the bundled
  ffmpeg — no patient content, safe to share),
- one clip whose source file is deliberately missing,
- annotations: rect, ellipse, arrow, text, redact, and a SAM-style mask PNG,
- two slides (one overlay), three markers,
- a sine-tone narration track with transcript segments and captions enabled.

Usage:
    python scripts/make_smoothness_fixture.py [--output DIR] [--register]

--register adds the fixture to the app's Recent Projects list.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from neuroedit_desktop.models import (  # noqa: E402
    Annotation,
    AudioTrack,
    ProjectState,
    Slide,
    TimelineMarker,
    TranscriptSegment,
    new_id,
)
from neuroedit_desktop.project_store import ProjectStore  # noqa: E402

DEFAULT_OUTPUT = Path.home() / "Documents" / "NeuroEdit" / "Fixtures" / "Smoothness"


def _ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _synthesize_clip(ffmpeg: str, path: Path, size: str, seconds: int) -> None:
    if path.exists():
        print(f"  exists, skipping: {path.name}")
        return
    print(f"  encoding {path.name} ({size}, {seconds}s)…")
    subprocess.run(
        [
            ffmpeg, "-y",
            "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=30:duration={seconds}",
            "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "28",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _synthesize_audio(ffmpeg: str, path: Path, seconds: int) -> None:
    if path.exists():
        print(f"  exists, skipping: {path.name}")
        return
    print(f"  encoding {path.name} (sine tone, {seconds}s)…")
    subprocess.run(
        [
            ffmpeg, "-y",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:a", "aac",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _synthesize_mask(path: Path) -> bool:
    """Soft-edged ellipse RGBA mask PNG, like a SAM segmentation output."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        print("  cv2/numpy unavailable — skipping mask annotation")
        return False
    height, width = 1080, 1920
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.ellipse(mask, (960, 540), (300, 180), 0.0, 0.0, 360.0, 255, -1)
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    rgba[mask > 0] = (238, 211, 34, 200)  # BGRA cyan, matching SAM output style
    cv2.imwrite(str(path), rgba)
    return True


def build_fixture(output: Path, register: bool) -> Path:
    media_dir = output / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    store = ProjectStore.create(output)

    ffmpeg = _ffmpeg()
    clip_1080 = media_dir / "fixture_1080p.mp4"
    clip_4k = media_dir / "fixture_4k.mp4"
    narration = media_dir / "fixture_narration.m4a"
    _synthesize_clip(ffmpeg, clip_1080, "1920x1080", 10)
    _synthesize_clip(ffmpeg, clip_4k, "3840x2160", 6)
    _synthesize_audio(ffmpeg, narration, 8)

    project = ProjectState(project_name="Smoothness Fixture")
    project.add_clip(clip_1080, duration=10.0, width=1920, height=1080)
    project.add_clip(clip_4k, duration=6.0, width=3840, height=2160)
    # Missing-media case: a clip whose source was "lost" after import.
    missing = project.add_clip(
        media_dir / "fixture_missing.mp4", duration=5.0, width=1920, height=1080
    )
    missing.name = "Missing source (intentional)"

    project.slides.append(
        Slide(
            id=new_id(), title="Fixture Title Slide",
            content="Synthetic QA content — no patient data.",
            duration=4.0, start_time=21.0, background="#0d1b2a",
            text_color="#ffffff", font_size=20,
        )
    )
    project.slides.append(
        Slide(
            id=new_id(), title="Overlay label", content="Overlay slide over video",
            duration=3.0, start_time=2.0, overlay=True,
            background="#000000", text_color="#ffffff", font_size=18,
        )
    )

    for at, label in ((1.0, "Exposure"), (8.0, "Key step"), (15.0, "Closure")):
        project.markers.append(
            TimelineMarker(id=new_id(), time=at, label=label)
        )

    def _annotation(type_: str, label: str, t: float, geometry: dict) -> Annotation:
        return Annotation(
            id=new_id(), frame_time=t, ann_duration=4.0, type=type_,  # type: ignore[arg-type]
            label=label, color="#00e5ff", geometry=geometry,
        )

    project.annotations.extend(
        [
            _annotation("rect", "Rect", 1.0, {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}),
            _annotation("ellipse", "Ellipse", 2.0, {"x": 0.4, "y": 0.2, "w": 0.2, "h": 0.25}),
            _annotation("arrow", "Arrow", 3.0, {"x1": 0.2, "y1": 0.7, "x2": 0.45, "y2": 0.5}),
            _annotation("text", "Text label", 4.0, {"x": 0.6, "y": 0.65}),
        ]
    )
    redact = _annotation("redact", "Redaction", 0.0, {"x": 0.7, "y": 0.05, "w": 0.25, "h": 0.12})
    redact.ann_duration = 0.0  # whole-timeline, the redact default
    project.annotations.append(redact)

    mask_path = output / "masks" / "fixture_mask.png"
    if _synthesize_mask(mask_path):
        mask = Annotation(
            id=new_id(), frame_time=0.0, ann_duration=5.0, type="mask",
            label="Fixture mask", color="#22d3ee", opacity=0.55,
            mask_path=str(mask_path), score=0.97,
            prompt_points=[{"x": 0.5, "y": 0.5, "type": "positive"}],
        )
        project.annotations.append(mask)

    project.audio_tracks.append(
        AudioTrack(
            id=new_id(), path=str(narration), name="Fixture narration",
            start_time=0.0, duration=8.0, type="voice",
        )
    )
    track_id = project.audio_tracks[0].id
    for start, end, text in (
        (0.0, 2.5, "This is the smoothness fixture."),
        (2.5, 5.0, "Captions are enabled for paint testing."),
        (5.0, 8.0, "No patient content appears anywhere."),
    ):
        project.transcript_segments.append(
            TranscriptSegment(
                id=new_id(), audio_track_id=track_id,
                start_time=start, end_time=end, text=text, speaker="QA",
            )
        )
    project.captions_enabled = True

    store.save(project)
    print(f"Fixture project written to {store.project_path}")

    if register:
        from PySide6.QtCore import QSettings

        settings = QSettings("NeuroEdit", "Desktop")
        recents: list[str] = settings.value("recentProjects", []) or []
        path_str = str(store.project_path)
        if path_str in recents:
            recents.remove(path_str)
        recents.insert(0, path_str)
        settings.setValue("recentProjects", recents[:8])
        print("Registered in Recent Projects.")

    return store.project_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--register", action="store_true",
        help="add the fixture to the app's Recent Projects list",
    )
    args = parser.parse_args()
    build_fixture(args.output, args.register)
    print(
        "\nQA loop: cold launch → open fixture → scrub timeline → drag an "
        "annotation → switch all five panels → start an export. Compare "
        "timings across builds with Help → Performance Diagnostics enabled."
    )


if __name__ == "__main__":
    main()
