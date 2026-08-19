from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QImage, QPainter, QPen, QPolygonF

from neuroedit_desktop.captions import build_caption_cues, cue_at_time, paint_caption
from neuroedit_desktop.models import Annotation, ProjectState, Slide, VideoClip


ProgressCallback = Callable[[int, str], None]
CancelCallback = Callable[[], bool]


@dataclass(frozen=True)
class ExportSettings:
    output_path: Path
    width: int
    height: int
    fps: int
    crf: int
    label: str
    mute_source_audio: bool = False  # drop original clip audio (may contain spoken PHI)
    burn_captions: bool = False  # burn transcript captions into the video frames
    audio_bitrate_k: int = 192  # AAC bitrate in kbit/s for the mixed audio track


@dataclass(frozen=True)
class AudioSource:
    path: Path
    timeline_start: float
    source_start: float
    duration: float
    volume: float


@dataclass(frozen=True)
class TimelineSegment:
    start: float
    end: float
    kind: Literal["video", "render"]
    clip: VideoClip | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


class ExportCancelled(Exception):
    pass


class ProjectExporter:
    def __init__(
        self,
        project: ProjectState,
        settings: ExportSettings,
        *,
        progress: ProgressCallback | None = None,
        cancelled: CancelCallback | None = None,
    ) -> None:
        self.project = project
        self.settings = settings
        self.progress = progress or (lambda _pct, _msg: None)
        self.cancelled = cancelled or (lambda: False)
        self._captures: dict[str, object] = {}
        self._video_states: dict[str, dict[str, object]] = {}
        self._image_cache: dict[str, np.ndarray] = {}
        self._qt_image_cache: dict[str, QImage] = {}
        self._audio_probe_cache: dict[str, bool] = {}
        self._ffmpeg_encoder_cache: dict[str, bool] = {}
        self._caption_cues = (
            build_caption_cues(project.transcript_segments)
            if settings.burn_captions
            else []
        )

    def export(self) -> list[str]:
        import cv2  # noqa: PLC0415

        warnings: list[str] = []
        try:
            output_path = self.settings.output_path.resolve()
            sources = self._source_media()
            if any(path.resolve() == output_path for _name, path in sources):
                raise RuntimeError("Choose an export path that is not one of the source media files.")
            missing = [name for name, path in sources if not path.is_file()]
            if missing:
                raise RuntimeError(
                    "Cannot export while source media is missing: " + ", ".join(missing[:5])
                )
            duration = self._duration()
            if duration <= 0:
                raise RuntimeError("The project has no timeline content to export.")

            self.settings.output_path.parent.mkdir(parents=True, exist_ok=True)
            ffmpeg = self._find_ffmpeg()

            with tempfile.TemporaryDirectory(prefix="neuroedit_export_") as tmp_dir:
                tmp_video = Path(tmp_dir) / "visual.mp4"
                if ffmpeg:
                    self._encode_timeline_video(tmp_video, ffmpeg, Path(tmp_dir), duration)
                else:
                    self._encode_video_with_opencv(tmp_video, duration, cv2)
                    warnings.append(
                        "FFmpeg was not found, so the export uses OpenCV video encoding without audio."
                    )

                audio_sources = self._audio_sources(ffmpeg) if ffmpeg else []
                if ffmpeg and audio_sources:
                    self.progress(92, "Mixing audio...")
                    self._mux_audio(tmp_video, self.settings.output_path, audio_sources, ffmpeg, duration)
                else:
                    if ffmpeg and self.project.audio_tracks:
                        warnings.append("No readable audio streams were found, so the MP4 is silent.")
                    os.replace(tmp_video, self.settings.output_path)

            self.progress(100, "Export complete.")
            return warnings
        finally:
            self._release_captures()

    def _source_media(self) -> list[tuple[str, Path]]:
        sources = [(clip.name, Path(clip.path)) for clip in self.project.clips]
        sources.extend((track.name, Path(track.path)) for track in self.project.audio_tracks)
        sources.extend(
            (slide.title or "Slide image", Path(slide.image_path))
            for slide in self.project.slides
            if slide.image_path
        )
        return sources

    def _duration(self) -> float:
        # Derived from actual content ends only — project.duration is a display
        # value that can ratchet past the real content (playhead padding) and
        # would add a black/silent tail to the export.
        ends: list[float] = []
        ends.extend(clip.start_time + clip.display_duration for clip in self.project.clips)
        ends.extend(slide.start_time + max(0.1, slide.duration) for slide in self.project.slides)
        ends.extend(track.start_time + max(0.1, track.duration) for track in self.project.audio_tracks)
        return max(0.0, max(ends, default=0.0))

    def _find_ffmpeg(self) -> str | None:
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            return system_ffmpeg
        try:
            import imageio_ffmpeg  # type: ignore[import-not-found]  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            return None
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # noqa: BLE001
            return None

    def _encode_timeline_video(
        self,
        path: Path,
        ffmpeg: str,
        tmp_dir: Path,
        duration: float,
    ) -> None:
        segments = self._build_segments(duration)
        if not segments:
            self._encode_render_segment_with_ffmpeg(
                TimelineSegment(0.0, duration, "render"),
                path,
                ffmpeg,
                0.0,
                1.0,
            )
            return

        segment_paths: list[Path] = []
        total = max(0.01, sum(segment.duration for segment in segments))
        complete = 0.0
        for index, segment in enumerate(segments, start=1):
            if self.cancelled():
                raise ExportCancelled()
            segment_path = tmp_dir / f"segment_{index:05d}.mp4"
            start_pct = complete / total
            end_pct = (complete + segment.duration) / total
            if segment.kind == "video" and segment.clip is not None:
                self.progress(
                    int(start_pct * 88),
                    f"Fast-exporting video segment {index} of {len(segments)}...",
                )
                self._encode_video_segment_with_ffmpeg(segment, segment_path, ffmpeg)
            else:
                self._encode_render_segment_with_ffmpeg(
                    segment,
                    segment_path,
                    ffmpeg,
                    start_pct,
                    end_pct,
                )
            complete += segment.duration
            segment_paths.append(segment_path)

        if len(segment_paths) == 1:
            os.replace(segment_paths[0], path)
            return
        self.progress(89, "Joining timeline segments...")
        self._concat_video_segments(segment_paths, path, ffmpeg, tmp_dir)

    def _build_segments(self, duration: float) -> list[TimelineSegment]:
        boundaries = self._timeline_boundaries(duration)
        segments: list[TimelineSegment] = []
        for start, end in zip(boundaries, boundaries[1:]):
            if end - start < 0.001:
                continue
            mid = (start + end) / 2
            clip = self._clip_at_time(mid)
            if self._segment_needs_render(start, end, clip):
                segments.append(TimelineSegment(start, end, "render", clip))
            else:
                segments.append(TimelineSegment(start, end, "video", clip))
        return self._merge_adjacent_segments(segments)

    def _timeline_boundaries(self, duration: float) -> list[float]:
        boundaries = {0.0, duration}

        def add(value: float) -> None:
            boundaries.add(max(0.0, min(duration, float(value))))

        for clip in self.project.clips:
            start = clip.start_time
            end = clip.start_time + clip.display_duration
            add(start)
            add(end)
            if clip.fade_in > 0:
                add(start + min(clip.fade_in, clip.display_duration))
            if clip.fade_out > 0:
                add(end - min(clip.fade_out, clip.display_duration))

        for slide in self.project.slides:
            add(slide.start_time)
            add(slide.start_time + slide.duration)

        for ann in self.project.annotations:
            add(ann.frame_time)
            ann_end = duration if ann.ann_duration == 0 else ann.frame_time + ann.ann_duration
            add(ann_end)

        for cue in self._caption_cues:
            add(cue.start)
            add(cue.end)

        ordered: list[float] = []
        for value in sorted(boundaries):
            if not ordered or abs(value - ordered[-1]) > 0.001:
                ordered.append(value)
        return ordered

    def _segment_needs_render(
        self,
        start: float,
        end: float,
        clip: VideoClip | None,
    ) -> bool:
        mid = (start + end) / 2
        if clip is None or clip.media_type != "video" or not Path(clip.path).exists():
            return True
        if self._slide_at_time(mid) is not None:
            return True
        if self._has_visible_annotation(mid):
            return True
        if cue_at_time(self._caption_cues, mid) is not None:
            return True
        # Redactions must never be decided by a single midpoint sample: a sub-frame
        # window that the boundary dedup collapsed could otherwise slip past and let
        # the original PHI frame stream-copy through. Force render on ANY interval
        # overlap.
        if self._redaction_overlaps(start, end):
            return True
        clip_end = clip.start_time + clip.display_duration
        in_fade_in = clip.fade_in > 0 and start < clip.start_time + clip.fade_in
        in_fade_out = clip.fade_out > 0 and end > clip_end - clip.fade_out
        return in_fade_in or in_fade_out

    def _has_visible_annotation(self, time_s: float) -> bool:
        return any(ann.is_visible_at(time_s) for ann in self.project.annotations)

    def _redaction_overlaps(self, start: float, end: float) -> bool:
        for ann in self.project.annotations:
            if ann.type != "redact" or not ann.visible:
                continue
            r_start = ann.frame_time
            r_end = math.inf if ann.ann_duration == 0 else ann.frame_time + ann.ann_duration
            if r_start < end and start < r_end:
                return True
        return False

    def _merge_adjacent_segments(self, segments: list[TimelineSegment]) -> list[TimelineSegment]:
        merged: list[TimelineSegment] = []
        for segment in segments:
            if (
                merged
                and segment.kind == merged[-1].kind
                and segment.clip is merged[-1].clip
                and abs(segment.start - merged[-1].end) < 0.001
            ):
                previous = merged[-1]
                merged[-1] = TimelineSegment(
                    previous.start,
                    segment.end,
                    previous.kind,
                    previous.clip,
                )
            else:
                merged.append(segment)
        return merged

    def _encode_video_segment_with_ffmpeg(
        self,
        segment: TimelineSegment,
        path: Path,
        ffmpeg: str,
    ) -> None:
        if segment.clip is None:
            raise RuntimeError("Video segment is missing its source clip.")
        source_start = segment.clip.trim_start + max(0.0, segment.start - segment.clip.start_time)
        vf = (
            f"scale={self.settings.width}:{self.settings.height}:force_original_aspect_ratio=decrease,"
            f"pad={self.settings.width}:{self.settings.height}:(ow-iw)/2:(oh-ih)/2,"
            f"fps={self.settings.fps},format=yuv420p,setpts=PTS-STARTPTS"
        )
        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{source_start:.3f}",
            "-t",
            f"{segment.duration:.3f}",
            "-i",
            segment.clip.path,
            "-map_metadata",
            "-1",
            "-map_chapters",
            "-1",
            "-vf",
            vf,
            "-an",
            *self._encoder_args(ffmpeg),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(path),
        ]
        self._run_ffmpeg(cmd, "FFmpeg video segment export failed")

    def _encode_render_segment_with_ffmpeg(
        self,
        segment: TimelineSegment,
        path: Path,
        ffmpeg: str,
        progress_start: float,
        progress_end: float,
    ) -> None:
        width, height = self.settings.width, self.settings.height
        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{width}x{height}",
            "-r",
            str(self.settings.fps),
            "-i",
            "-",
            "-an",
            *self._encoder_args(ffmpeg),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(path),
        ]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        assert proc.stdin is not None
        frame_count = max(1, int(math.ceil(segment.duration * self.settings.fps)))
        encoder_died = False
        try:
            for index in range(frame_count):
                if self.cancelled():
                    raise ExportCancelled()
                time_s = min(segment.end - 0.000001, segment.start + index / self.settings.fps)
                frame = np.ascontiguousarray(self._render_frame(time_s), dtype=np.uint8)
                try:
                    proc.stdin.write(frame.tobytes())
                except (BrokenPipeError, OSError):
                    # ffmpeg exited early — stop feeding frames and surface its
                    # stderr below instead of crashing on the pipe write.
                    encoder_died = True
                    break
                if index % max(1, self.settings.fps) == 0:
                    ratio = index / frame_count
                    pct = int((progress_start + (progress_end - progress_start) * ratio) * 88)
                    self.progress(pct, f"Rendering segment frame {index + 1} of {frame_count}...")
            try:
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                encoder_died = True
            stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
            ret = proc.wait()
        except ExportCancelled:
            proc.terminate()
            proc.wait()
            raise
        if ret != 0 or encoder_died:
            raise RuntimeError(f"FFmpeg video export failed: {stderr.strip() or 'unknown error'}")

    def _concat_video_segments(
        self,
        segment_paths: list[Path],
        output_path: Path,
        ffmpeg: str,
        tmp_dir: Path,
    ) -> None:
        list_path = tmp_dir / "segments.txt"
        lines = []
        for path in segment_paths:
            escaped = str(path).replace("\\", "\\\\").replace("'", "\\'")
            lines.append(f"file '{escaped}'")
        list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-map_metadata",
            "-1",
            "-map_chapters",
            "-1",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        self._run_ffmpeg(cmd, "FFmpeg timeline join failed")

    def _encoder_args(self, ffmpeg: str) -> list[str]:
        if self._has_encoder(ffmpeg, "h264_videotoolbox"):
            return ["-c:v", "h264_videotoolbox", "-b:v", self._hardware_bitrate(), "-allow_sw", "1"]
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(self.settings.crf)]

    def _hardware_bitrate(self) -> str:
        pixels = self.settings.width * self.settings.height
        if pixels >= 3840 * 2160:
            return "45M"
        if pixels >= 1920 * 1080:
            return "12M"
        return "5M"

    def _has_encoder(self, ffmpeg: str, encoder_name: str) -> bool:
        cached = self._ffmpeg_encoder_cache.get(encoder_name)
        if cached is not None:
            return cached
        try:
            proc = subprocess.run(
                [ffmpeg, "-hide_banner", "-encoders"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self._ffmpeg_encoder_cache[encoder_name] = False
            return False
        available = encoder_name in proc.stdout
        self._ffmpeg_encoder_cache[encoder_name] = available
        return available

    def _run_ffmpeg(self, cmd: list[str], failure_prefix: str) -> None:
        # communicate() drains stdout/stderr while waiting — polling without
        # reading can deadlock once ffmpeg fills the OS pipe buffer.
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                if self.cancelled():
                    proc.terminate()
                    proc.wait()
                    raise ExportCancelled() from None
        if proc.returncode != 0:
            details = (stderr or stdout or "unknown error").strip()
            raise RuntimeError(f"{failure_prefix}: {details}")

    def _encode_video_with_opencv(self, path: Path, duration: float, cv2) -> None:
        writer = None
        for fourcc_name in ("avc1", "H264", "mp4v"):
            fourcc = cv2.VideoWriter_fourcc(*fourcc_name)
            candidate = cv2.VideoWriter(
                str(path),
                fourcc,
                float(self.settings.fps),
                (self.settings.width, self.settings.height),
            )
            if candidate.isOpened():
                writer = candidate
                break
            candidate.release()
        if writer is None:
            raise RuntimeError("Could not open an MP4 video encoder.")

        frame_count = max(1, int(math.ceil(duration * self.settings.fps)))
        try:
            for index in range(frame_count):
                if self.cancelled():
                    raise ExportCancelled()
                time_s = min(duration, index / self.settings.fps)
                rgb = self._render_frame(time_s)
                writer.write(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
                if index % max(1, self.settings.fps) == 0:
                    pct = int((index / frame_count) * 88)
                    self.progress(pct, f"Rendering frame {index + 1} of {frame_count}...")
        finally:
            writer.release()

    def _render_frame(self, time_s: float) -> np.ndarray:
        frame = np.zeros((self.settings.height, self.settings.width, 3), dtype=np.uint8)
        slide = self._slide_at_time(time_s)
        if slide is not None and not slide.overlay:
            return self._paint_qt(frame, time_s, slide=slide, include_annotations=False)

        clip = self._clip_at_time(time_s)
        if clip is not None:
            clip_frame = self._frame_for_clip(clip, time_s)
            if clip_frame is None:
                raise RuntimeError(f"Could not render source media for clip: {clip.name}")
            frame = self._fit_frame(clip_frame)

        return self._paint_qt(frame, time_s, slide=slide, include_annotations=True)

    def _frame_for_clip(self, clip: VideoClip, time_s: float) -> np.ndarray | None:
        import cv2  # noqa: PLC0415

        if clip.media_type == "image":
            cached = self._image_cache.get(clip.path)
            if cached is None:
                image = cv2.imread(clip.path, cv2.IMREAD_COLOR)
                if image is None:
                    return None
                cached = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                self._image_cache[clip.path] = cached
            return cached

        cap = self._captures.get(clip.path)
        if cap is None:
            cap = cv2.VideoCapture(clip.path)
            self._captures[clip.path] = cap
            self._video_states[clip.path] = {
                "last_time_s": None,
                "last_frame": None,
            }

        state = self._video_states[clip.path]
        local_s = max(0.0, clip.trim_start + max(0.0, time_s - clip.start_time))
        if state["last_time_s"] == local_s and state["last_frame"] is not None:
            return state["last_frame"]  # type: ignore[return-value]
        # Frame indices derived from an average FPS select the wrong source frame
        # for VFR recordings. Seek by the media timestamp for every rendered frame.
        cap.set(cv2.CAP_PROP_POS_MSEC, local_s * 1000.0)
        ok, frame_bgr = cap.read()
        if not ok or frame_bgr is None:
            cached = state.get("last_frame")
            return cached if isinstance(cached, np.ndarray) else None
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        state["last_time_s"] = local_s
        state["last_frame"] = rgb
        return rgb

    def _fit_frame(self, frame: np.ndarray) -> np.ndarray:
        import cv2  # noqa: PLC0415

        src_h, src_w = frame.shape[:2]
        if src_w <= 0 or src_h <= 0:
            return np.zeros((self.settings.height, self.settings.width, 3), dtype=np.uint8)
        scale = min(self.settings.width / src_w, self.settings.height / src_h)
        out_w = max(1, int(round(src_w * scale)))
        out_h = max(1, int(round(src_h * scale)))
        resized = cv2.resize(frame, (out_w, out_h), interpolation=cv2.INTER_AREA)
        canvas = np.zeros((self.settings.height, self.settings.width, 3), dtype=np.uint8)
        x = (self.settings.width - out_w) // 2
        y = (self.settings.height - out_h) // 2
        canvas[y:y + out_h, x:x + out_w] = resized
        return canvas

    def _paint_qt(
        self,
        frame: np.ndarray,
        time_s: float,
        *,
        slide: Slide | None,
        include_annotations: bool,
    ) -> np.ndarray:
        height, width = frame.shape[:2]
        qimage = QImage(
            frame.data,
            width,
            height,
            int(frame.strides[0]),
            QImage.Format.Format_RGB888,
        ).copy()
        painter = QPainter(qimage)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if slide is not None:
            self._paint_slide(painter, slide, width, height)
        if include_annotations:
            self._paint_annotations(painter, time_s, width, height)
            self._paint_fade(painter, time_s, width, height)
        # Captions paint over slides too (narration continues across them), but
        # under redactions so a redaction can never be covered by caption text.
        self._paint_captions(painter, time_s, width, height)
        # Redactions burn last and unconditionally — even behind a full-frame slide —
        # so a redaction placed over slide/still content is never skipped.
        self._paint_redactions(painter, time_s, width, height)

        painter.end()
        bits = qimage.bits()
        arr = np.frombuffer(bits, dtype=np.uint8).reshape((height, qimage.bytesPerLine()))
        return arr[:, : width * 3].reshape((height, width, 3)).copy()

    def _paint_slide(self, painter: QPainter, slide: Slide, w: int, h: int) -> None:
        if not slide.overlay:
            painter.fillRect(QRectF(0, 0, w, h), QColor(slide.background))

        image_path = getattr(slide, "image_path", None)
        if image_path:
            image = self._qt_image_cache.get(image_path)
            if image is None:
                image = QImage(image_path)
                if not image.isNull():
                    self._qt_image_cache[image_path] = image
            if image is not None and not image.isNull():
                painter.drawImage(QRectF(0, 0, w, h), image)

        family = slide.font_family or painter.font().family()
        title_rect = QRectF(slide.title_x * w, slide.title_y * h, slide.title_w * w, slide.title_h * h)
        body_rect = QRectF(slide.body_x * w, slide.body_y * h, slide.body_w * w, slide.body_h * h)

        scale = h / 1080.0
        title_font = QFont(family)
        title_font.setBold(slide.bold)
        title_font.setItalic(slide.italic)
        title_font.setPointSize(
            self._fit_slide_font_size(
                slide.title, title_rect, int((slide.font_size + 10) * scale),
                bold=slide.bold, italic=slide.italic, family=family, min_size=10, max_size=72,
            )
        )
        painter.setFont(title_font)
        painter.setPen(QColor(slide.text_color))
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom | Qt.TextFlag.TextWordWrap,
            slide.title,
        )

        body_font = QFont(family)
        body_font.setItalic(slide.italic)
        body_font.setPointSize(
            self._fit_slide_font_size(
                slide.content, body_rect, int(slide.font_size * scale),
                bold=False, italic=slide.italic, family=family, min_size=8, max_size=54,
            )
        )
        painter.setFont(body_font)
        painter.drawText(
            body_rect,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            slide.content,
        )

    def _fit_slide_font_size(
        self,
        text: str,
        rect: QRectF,
        desired: int,
        *,
        bold: bool,
        italic: bool,
        family: str,
        min_size: int,
        max_size: int,
    ) -> int:
        if not text or rect.width() <= 0 or rect.height() <= 0:
            return max(min_size, min(desired, max_size))
        size = max(min_size, min(desired, max_size))
        while size > min_size:
            font = QFont(family)
            font.setBold(bold)
            font.setItalic(italic)
            font.setPointSize(size)
            metrics = QFontMetricsF(font)
            bounds = metrics.boundingRect(
                rect,
                int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignHCenter),
                text,
            )
            if bounds.width() <= rect.width() and bounds.height() <= rect.height():
                return size
            size -= 1
        return min_size

    def _paint_annotations(self, painter: QPainter, time_s: float, w: int, h: int) -> None:
        for ann in self.project.annotations:
            if not ann.is_visible_at(time_s):
                continue
            if ann.type == "redact":
                continue  # burned opaque in _paint_redactions, last and on top
            mask_path = ann.mask_path_at(time_s)
            if ann.type in ("mask", "tracked-mask") and mask_path:
                mask = QImage(mask_path)
                if not mask.isNull():
                    painter.save()
                    painter.setOpacity(max(0.05, min(1.0, ann.opacity)))
                    painter.drawImage(QRectF(0, 0, w, h), mask)
                    painter.restore()
                continue
            self._paint_annotation_shape(painter, ann, w, h)

    def _paint_annotation_shape(self, painter: QPainter, ann: Annotation, w: int, h: int) -> None:
        color = QColor(ann.color)
        color.setAlphaF(max(0.05, min(1.0, ann.opacity)))
        pen_width = max(1, int(float(ann.geometry.get("width_px", self.project.draw_width))))
        pen = QPen(color, pen_width)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if ann.type == "rect":
            painter.drawRect(self._annotation_rect(ann, w, h))
        elif ann.type == "ellipse":
            painter.drawEllipse(self._annotation_rect(ann, w, h))
        elif ann.type == "arrow":
            self._paint_arrow(painter, ann, w, h, color)
        elif ann.type == "text":
            self._paint_text_label(painter, ann, w, h, color)
        if ann.type in ("rect", "ellipse", "arrow"):
            self._paint_attached_label(painter, ann, w, h, color)

    def _annotation_rect(self, ann: Annotation, w: int, h: int) -> QRectF:
        return QRectF(
            float(ann.geometry.get("x", 0.0)) * w,
            float(ann.geometry.get("y", 0.0)) * h,
            float(ann.geometry.get("width", 0.0)) * w,
            float(ann.geometry.get("height", 0.0)) * h,
        )

    def _paint_arrow(self, painter: QPainter, ann: Annotation, w: int, h: int, color: QColor) -> None:
        start = QPointF(float(ann.geometry.get("x1", 0.0)) * w, float(ann.geometry.get("y1", 0.0)) * h)
        end = QPointF(float(ann.geometry.get("x2", 0.0)) * w, float(ann.geometry.get("y2", 0.0)) * h)
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = math.hypot(dx, dy)
        if length < 2:
            return
        painter.drawLine(start, end)
        angle = math.atan2(dy, dx)
        head_len = min(28.0, max(12.0, length * 0.18))
        spread = math.radians(28)
        left = QPointF(end.x() - head_len * math.cos(angle - spread), end.y() - head_len * math.sin(angle - spread))
        right = QPointF(end.x() - head_len * math.cos(angle + spread), end.y() - head_len * math.sin(angle + spread))
        painter.setBrush(QBrush(color))
        painter.drawPolygon(QPolygonF([end, left, right]))

    def _label_should_show(self, ann: Annotation) -> bool:
        if not getattr(ann, "show_label", True):
            return False
        label = ann.label.strip()
        if not label:
            return False
        return label.lower() != ann.type

    def _attached_label_rect(self, ann: Annotation, w: int, h: int) -> QRectF | None:
        if ann.type not in ("rect", "ellipse", "arrow") or not self._label_should_show(ann):
            return None
        label = ann.label.strip()
        font = QFont()
        font.setBold(True)
        font.setPointSize(max(8, int(ann.font_size)))
        metrics = QFontMetricsF(font)
        text_rect = QRectF(metrics.boundingRect(label).adjusted(-8, -5, 8, 5))
        if ann.type == "arrow":
            anchor = QPointF(
                float(ann.geometry.get("x1", 0.0)) * w + 10,
                float(ann.geometry.get("y1", 0.0)) * h - text_rect.height() - 8,
            )
            if anchor.y() < 0:
                anchor.setY(float(ann.geometry.get("y1", 0.0)) * h + 8)
        else:
            bounds = self._annotation_rect(ann, w, h)
            anchor = bounds.topLeft() + QPointF(0, -text_rect.height() - 8)
            if anchor.y() < 0:
                anchor = bounds.bottomLeft() + QPointF(0, 8)
        anchor += QPointF(
            float(ann.geometry.get("label_dx", 0.0)) * w,
            float(ann.geometry.get("label_dy", 0.0)) * h,
        )
        text_rect.moveTopLeft(anchor)
        return text_rect

    def _paint_attached_label(self, painter: QPainter, ann: Annotation, w: int, h: int, color: QColor) -> None:
        label = ann.label.strip()
        text_rect = self._attached_label_rect(ann, w, h)
        if text_rect is None:
            return
        font = QFont(painter.font())
        font.setBold(True)
        font.setPointSize(max(8, int(ann.font_size)))
        painter.setFont(font)
        bg = QColor("#000000")
        bg.setAlpha(170)
        painter.setPen(QPen(color, 1))
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(text_rect, 6, 6)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)

    def _paint_text_label(self, painter: QPainter, ann: Annotation, w: int, h: int, color: QColor) -> None:
        label = ann.label or "Text"
        x = float(ann.geometry.get("x", 0.5)) * w
        y = float(ann.geometry.get("y", 0.5)) * h
        font = QFont(painter.font())
        font.setPointSize(max(8, int(ann.font_size)))
        font.setBold(True)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        text_rect = metrics.boundingRect(label).adjusted(-10, -6, 10, 6)
        text_rect.moveTopLeft(QPointF(x, y))
        bg = QColor("#000000")
        bg.setAlpha(160)
        painter.setPen(QPen(color, 1))
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(text_rect, 6, 6)
        painter.setPen(color)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, label)

    def _paint_captions(self, painter: QPainter, time_s: float, w: int, h: int) -> None:
        cue = cue_at_time(self._caption_cues, time_s)
        if cue is None:
            return
        paint_caption(
            painter,
            cue,
            w,
            h,
            size=self.project.caption_size,
            position=self.project.caption_position,
            background=self.project.caption_background,
        )

    def _paint_redactions(self, painter: QPainter, time_s: float, w: int, h: int) -> None:
        """Burn every visible redaction as a fully opaque black box, last and on
        top, so the underlying PHI is irrecoverable in the exported file."""
        painter.save()
        painter.setOpacity(1.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#000000")))
        for ann in self.project.annotations:
            if ann.type != "redact" or not ann.is_visible_at(time_s):
                continue
            painter.drawRect(self._annotation_rect(ann, w, h))
        painter.restore()

    def _paint_fade(self, painter: QPainter, time_s: float, w: int, h: int) -> None:
        clip = self._clip_at_time(time_s)
        if clip is None:
            return
        start = clip.start_time
        end = clip.start_time + clip.display_duration
        alpha = 0.0
        if clip.fade_in > 0 and time_s < start + clip.fade_in:
            alpha = max(alpha, 1.0 - (time_s - start) / clip.fade_in)
        if clip.fade_out > 0 and time_s > end - clip.fade_out:
            alpha = max(alpha, 1.0 - (end - time_s) / clip.fade_out)
        if alpha <= 0:
            return
        color = QColor(clip.fade_color or "#000000")
        color.setAlphaF(max(0.0, min(1.0, alpha)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawRect(QRectF(0, 0, w, h))

    def _clip_at_time(self, time_s: float) -> VideoClip | None:
        for clip in self.project.clips:
            if clip.start_time <= time_s < clip.start_time + clip.display_duration:
                return clip
        return None

    def _slide_at_time(self, time_s: float) -> Slide | None:
        for slide in reversed(self.project.slides):
            if slide.start_time <= time_s < slide.start_time + slide.duration:
                return slide
        return None

    def _audio_sources(self, ffmpeg: str | None) -> list[AudioSource]:
        if not ffmpeg:
            return []
        sources: list[AudioSource] = []
        source_volume = 0.0 if self.project.is_muted else max(0.0, min(1.0, self.project.volume))
        if source_volume > 0 and not self.settings.mute_source_audio:
            for clip in self.project.clips:
                path = Path(clip.path)
                if (
                    clip.media_type == "video"
                    and clip.display_duration > 0
                    and path.exists()
                    and self._has_audio_stream(path, ffmpeg)
                ):
                    sources.append(
                        AudioSource(
                            path=path,
                            timeline_start=clip.start_time,
                            source_start=clip.trim_start,
                            duration=clip.display_duration,
                            volume=source_volume,
                        )
                    )
        for track in self.project.audio_tracks:
            path = Path(track.path)
            if track.duration <= 0 or track.volume <= 0 or not path.exists():
                continue
            if not self._has_audio_stream(path, ffmpeg):
                continue
            sources.append(
                AudioSource(
                    path=path,
                    timeline_start=track.start_time,
                    source_start=0.0,
                    duration=track.duration,
                    volume=max(0.0, min(2.0, track.volume)),
                )
            )
        return sources

    def _has_audio_stream(self, path: Path, ffmpeg: str) -> bool:
        key = str(path)
        cached = self._audio_probe_cache.get(key)
        if cached is not None:
            return cached
        try:
            proc = subprocess.run(
                [ffmpeg, "-hide_banner", "-i", str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self._audio_probe_cache[key] = False
            return False
        has_audio = "Audio:" in proc.stderr
        self._audio_probe_cache[key] = has_audio
        return has_audio

    def _mux_audio(
        self,
        tmp_video: Path,
        output_path: Path,
        audio_sources: list[AudioSource],
        ffmpeg: str,
        duration: float,
    ) -> None:
        staged_output = tmp_video.with_name("muxed.mp4")
        cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp_video)]
        for source in audio_sources:
            cmd.extend(["-i", str(source.path)])

        chains: list[str] = []
        labels: list[str] = []
        for idx, source in enumerate(audio_sources):
            label = f"a{idx}"
            delay_ms = max(0, int(round(source.timeline_start * 1000)))
            source_start = max(0.0, source.source_start)
            source_duration = max(0.01, min(source.duration, max(0.01, duration - source.timeline_start)))
            chains.append(
                f"[{idx + 1}:a:0]atrim=start={source_start:.3f}:duration={source_duration:.3f},"
                f"asetpts=PTS-STARTPTS,volume={source.volume:.3f},"
                f"adelay={delay_ms}:all=1[{label}]"
            )
            labels.append(f"[{label}]")
        if not labels:
            os.replace(tmp_video, output_path)
            return

        chains.append(
            "".join(labels)
            + f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
            + f"atrim=0:{duration:.3f}[mix]"
        )
        filter_complex = ";".join(chains)
        cmd.extend(
            [
                "-filter_complex",
                filter_complex,
                "-map",
                "0:v:0",
                "-map",
                "[mix]",
                "-map_metadata",
                "-1",
                "-map_chapters",
                "-1",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                f"{max(64, int(self.settings.audio_bitrate_k))}k",
                "-t",
                f"{duration:.3f}",
                "-movflags",
                "+faststart",
                str(staged_output),
            ]
        )
        self._run_ffmpeg(cmd, "Audio mux failed")
        os.replace(staged_output, output_path)

    def _release_captures(self) -> None:
        for cap in self._captures.values():
            try:
                cap.release()
            except Exception:  # noqa: BLE001
                pass
        self._captures.clear()
        self._video_states.clear()
