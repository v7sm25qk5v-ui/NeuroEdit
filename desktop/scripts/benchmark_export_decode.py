#!/usr/bin/env python3
"""Compare the existing sequential decoder with the prior seek-per-frame path.

Uses only temporary synthetic media; the measured operation is a complete,
software-encoded 1080p export with a redaction active for the entire clip.
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import tempfile
import time
from pathlib import Path

import cv2
from PySide6.QtWidgets import QApplication

from neuroedit_desktop.exporter import ExportSettings, ProjectExporter, require_ffmpeg
from neuroedit_desktop.models import Annotation, ProjectState, new_id


def main() -> None:
    app = QApplication.instance() or QApplication([])
    ffmpeg = require_ffmpeg()
    with tempfile.TemporaryDirectory(prefix="neuroedit-benchmark-") as temp:
        root = Path(temp)
        source = root / "long-gop.mp4"
        subprocess.run([
            ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
            "testsrc2=size=1920x1080:rate=30:duration=6", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "28", "-g", "180", "-keyint_min", "180",
            "-sc_threshold", "0", "-pix_fmt", "yuv420p", str(source),
        ], check=True)
        project = ProjectState()
        project.add_clip(source, 6.0, 1920, 1080)
        project.annotations.append(Annotation(
            id=new_id(), frame_time=0.0, ann_duration=6.0, type="redact",
            label="Redacted", color="#000000",
            geometry={"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
        ))
        results = {}
        hashes = {}
        for mode in ("seek_per_frame", "sequential"):
            exp = ProjectExporter(project, ExportSettings(root / f"{mode}.mp4", 1920, 1080, 30, 20, "benchmark"))
            exp._encoder_args = lambda _: ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
            if mode == "seek_per_frame":
                def seek_frame(clip, time_s):
                    cap = exp._captures.get(clip.path)
                    if cap is None:
                        cap = cv2.VideoCapture(clip.path)
                        exp._captures[clip.path] = cap
                    local_s = max(0.0, clip.trim_start + max(0.0, time_s - clip.start_time))
                    cap.set(cv2.CAP_PROP_POS_MSEC, local_s * 1000.0)
                    ok, frame = cap.read()
                    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) if ok else None
                exp._frame_for_clip = seek_frame
            render = exp._render_frame
            frame_hashes = []
            def checked_render(time_s):
                frame = render(time_s)
                frame_hashes.append(hashlib.sha256(frame.tobytes()).hexdigest())
                return frame
            exp._render_frame = checked_render
            started = time.perf_counter()
            exp.export()
            seconds = time.perf_counter() - started
            hashes[mode] = frame_hashes
            results[mode] = {"seconds": round(seconds, 3), "frames": len(frame_hashes),
                             "fps": round(len(frame_hashes) / seconds, 2)}
        result = {"platform": platform.platform(), "opencv": cv2.__version__,
                  "fixture": "synthetic testsrc2, 1920x1080, 30 fps, 6 s, H.264 GOP 180; redaction active throughout covering 20% x 20%",
                  "encoder": "libx264 veryfast CRF 20", "runs": results,
                  "rendered_frame_hashes_identical": hashes["seek_per_frame"] == hashes["sequential"]}
        print(json.dumps(result, indent=2))
        if not result["rendered_frame_hashes_identical"] or len(hashes["sequential"]) != 180:
            raise SystemExit("Frame comparison failed")
    app.quit()


if __name__ == "__main__":
    main()
