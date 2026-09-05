from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

VideoType = Literal[
    "educational",
    "case-study",
    "surgical-report",
    "conference",
    "training",
    "research",
]

ToolType = Literal["select", "sam", "rect", "ellipse", "arrow", "text", "brush", "redact"]
PanelType = Literal["sam", "labels", "tips", "slides", "audio"]
AnnotationType = Literal[
    "rect", "ellipse", "arrow", "text", "brush", "mask", "tracked-mask", "redact"
]
SamPointType = Literal["positive", "negative"]


def new_id() -> str:
    return str(uuid4())


def _from_dict_tolerant(cls, data: dict[str, Any]):
    """Build a dataclass from a dict, dropping unknown keys so projects saved by
    a newer app version still open here. Missing fields without defaults still
    raise — that contract (loud failure) is intentional."""
    fields = cls.__dataclass_fields__
    return cls(**{key: value for key, value in data.items() if key in fields})


@dataclass
class SamPoint:
    x: float
    y: float
    type: SamPointType = "positive"


@dataclass
class VideoClip:
    id: str
    path: str
    name: str
    duration: float = 0.0
    start_time: float = 0.0
    trim_start: float = 0.0
    trim_end: float = 0.0
    source_in_limit: float | None = None
    source_out_limit: float | None = None
    width: int = 1920
    height: int = 1080
    thumbnail_path: str | None = None
    media_type: Literal["video", "image"] = "video"
    fade_in: float = 0.0   # seconds; 0 disables
    fade_out: float = 0.0
    fade_color: str = "#000000"  # color to fade to/from

    @property
    def display_duration(self) -> float:
        return max(0.0, self.trim_end - self.trim_start)

    @property
    def effective_source_in_limit(self) -> float:
        return max(0.0, self.source_in_limit or 0.0)

    @property
    def effective_source_out_limit(self) -> float:
        limit = self.duration if self.source_out_limit is None else self.source_out_limit
        if self.duration > 0:
            limit = min(limit, self.duration)
        return max(self.effective_source_in_limit, limit)


@dataclass
class AudioTrack:
    id: str
    path: str
    name: str
    start_time: float = 0.0
    duration: float = 0.0
    type: Literal["voice", "music"] = "voice"
    volume: float = 1.0


@dataclass
class TranscriptSegment:
    id: str
    audio_track_id: str | None
    start_time: float
    end_time: float
    text: str
    speaker: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end_time - self.start_time)


@dataclass
class Slide:
    id: str
    title: str
    content: str = ""
    image_path: str | None = None
    duration: float = 3.0
    start_time: float = 0.0
    background: str = "#000000"
    text_color: str = "#ffffff"
    font_size: int = 16
    overlay: bool = False
    font_family: str = ""
    bold: bool = True
    italic: bool = False
    # Normalized rectangles (0..1) for the title and body text regions.
    title_x: float = 0.05
    title_y: float = 0.07
    title_w: float = 0.90
    title_h: float = 0.40
    body_x: float = 0.07
    body_y: float = 0.50
    body_w: float = 0.86
    body_h: float = 0.43


@dataclass
class TimelineMarker:
    id: str
    time: float
    label: str
    color: str = "#f59e0b"


@dataclass
class Annotation:
    id: str
    frame_time: float
    ann_duration: float
    type: AnnotationType
    label: str
    color: str
    visible: bool = True
    opacity: float = 0.6
    geometry: dict[str, float | list[float] | list[list[float]] | str] = field(
        default_factory=dict
    )
    mask_path: str | None = None
    mask_frames: list[dict[str, float | str]] = field(default_factory=list)
    score: float | None = None
    sample_rate: float | None = None
    font_size: int = 15
    show_label: bool = True
    # SAM prompt points used to create a mask/tracked-mask, as
    # [{"x": float, "y": float, "type": "positive"|"negative"}] — lets Re-track
    # regenerate the mask later. Empty for masks made before this field existed.
    prompt_points: list[dict] = field(default_factory=list)

    def is_visible_at(self, time_s: float) -> bool:
        if not self.visible:
            return False
        if time_s < self.frame_time:
            return False
        return self.ann_duration == 0 or time_s <= self.frame_time + self.ann_duration

    def mask_path_at(self, time_s: float) -> str | None:
        if self.type != "tracked-mask" or not self.mask_frames:
            return self.mask_path

        current = self.mask_frames[0]
        for frame in self.mask_frames:
            if float(frame.get("time", 0.0)) <= time_s:
                current = frame
            else:
                break
        path = current.get("mask_path")
        return str(path) if path else self.mask_path


@dataclass
class ProjectState:
    project_name: str = "Untitled Case"
    video_type: VideoType = "educational"
    video_goal: str = "talk-adjunct"
    target_presentation_minutes: float = 10.0
    storyboard_objective: str = ""
    storyboard_case_context: str = ""
    storyboard_key_anatomy: str = ""
    storyboard_steps: str = ""
    storyboard_decision_points: str = ""
    storyboard_teaching_pearl: str = ""
    storyboard_final_point: str = ""
    intended_audience: str = ""
    consent_confirmed: bool = False
    staff_notice_confirmed: bool = False
    deidentified_confirmed: bool = False
    phi_review_confirmed: bool = False
    audio_reviewed_for_phi: bool = False
    edit_disclosure: str = ""
    clips: list[VideoClip] = field(default_factory=list)
    audio_tracks: list[AudioTrack] = field(default_factory=list)
    transcript_segments: list[TranscriptSegment] = field(default_factory=list)
    slides: list[Slide] = field(default_factory=list)
    markers: list[TimelineMarker] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)
    current_time: float = 0.0
    duration: float = 0.0
    playback_rate: float = 1.0
    volume: float = 1.0
    is_muted: bool = False
    active_clip_id: str | None = None
    zoom: float = 80.0
    scroll_left: float = 0.0
    active_tool: ToolType = "select"
    active_panel: PanelType = "tips"
    selected_annotation_id: str | None = None
    sam_points: list[SamPoint] = field(default_factory=list)
    sam_mode: SamPointType = "positive"
    sam_points_enabled: bool = True
    draw_color: str = "#00e5ff"
    draw_width: int = 6
    draw_opacity: float = 0.85
    draw_label: str = ""
    # Caption preview/burn-in style (export-safe by construction: white text,
    # optional dark box, safe-area margins; only size/position/background vary).
    captions_enabled: bool = False
    caption_size: str = "medium"  # small | medium | large
    caption_position: str = "bottom"  # bottom | top
    caption_background: bool = True
    # Last SAM propagation run, persisted so the status survives reopening.
    # Keys: started_iso, duration_s, frames, result ("success"|"error"|"canceled"),
    # backend, message.
    sam_last_run: dict = field(default_factory=dict)
    # Guided PHI review progress per stop: {item_id: True} for clips, slides,
    # and audio tracks already marked reviewed. Lets a paused review resume
    # where it left off; phi_review_confirmed stays the single completion flag.
    phi_review_progress: dict = field(default_factory=dict)

    @property
    def active_clip(self) -> VideoClip | None:
        if self.active_clip_id:
            for clip in self.clips:
                if clip.id == self.active_clip_id:
                    return clip
        return self.clips[0] if self.clips else None

    def arrange_clips_without_overlap(
        self,
        preferred_id: str | None = None,
        insert_anchor: float | None = None,
        insert_direction: Literal["left", "right"] | None = None,
    ) -> None:
        """Keep the primary video track sequential when clips are moved or resized."""
        if preferred_id is None:
            ordered = sorted(self.clips, key=lambda clip: clip.start_time)
        else:
            moving = next((clip for clip in self.clips if clip.id == preferred_id), None)
            if moving is None:
                ordered = sorted(self.clips, key=lambda clip: clip.start_time)
            else:
                ordered = self._clip_order_with_insert(
                    moving,
                    insert_anchor,
                    insert_direction,
                )
        cursor = 0.0
        for clip in ordered:
            if clip.start_time < cursor:
                clip.start_time = cursor
            cursor = clip.start_time + clip.display_duration
        self.clips = ordered

    def ripple_after(
        self,
        anchor: float,
        delta: float,
        *,
        excluded_clip_id: str | None = None,
    ) -> None:
        """Shift timeline items after a primary-track edit without closing
        unrelated gaps elsewhere in the project."""
        if abs(delta) < 1e-9:
            return
        threshold = anchor - 1e-9
        for clip in self.clips:
            if clip.id != excluded_clip_id and clip.start_time >= threshold:
                clip.start_time = max(0.0, clip.start_time + delta)
        for slide in self.slides:
            if slide.start_time >= threshold:
                slide.start_time = max(0.0, slide.start_time + delta)
        audio_shifts = {}
        for track in self.audio_tracks:
            old_start = track.start_time
            if track.start_time >= threshold:
                track.start_time = max(0.0, track.start_time + delta)
            audio_shifts[track.id] = track.start_time - old_start
        for segment in self.transcript_segments:
            # Linked captions follow their narration, including an unmoved
            # track spanning the edit. Independent captions follow the timeline.
            shift = audio_shifts.get(
                segment.audio_track_id,
                delta if segment.start_time >= threshold else 0.0,
            )
            new_start = max(0.0, segment.start_time + shift)
            segment.end_time += new_start - segment.start_time
            segment.start_time = new_start
        for marker in self.markers:
            if marker.time >= threshold:
                marker.time = max(0.0, marker.time + delta)
        for annotation in self.annotations:
            if annotation.frame_time >= threshold:
                old_start = annotation.frame_time
                annotation.frame_time = max(0.0, annotation.frame_time + delta)
                for frame in annotation.mask_frames:
                    frame["time"] = float(frame["time"]) + annotation.frame_time - old_start

    def _clip_order_with_insert(
        self,
        moving: VideoClip,
        insert_anchor: float | None = None,
        insert_direction: Literal["left", "right"] | None = None,
    ) -> list[VideoClip]:
        others = sorted(
            (clip for clip in self.clips if clip.id != moving.id),
            key=lambda clip: clip.start_time,
        )
        anchor = (
            moving.start_time + moving.display_duration / 2
            if insert_anchor is None
            else insert_anchor
        )
        edge_margin = 2.0
        if insert_direction == "left":
            for index, clip in enumerate(others):
                threshold = (
                    clip.start_time
                    + clip.display_duration
                    - min(edge_margin, clip.display_duration / 2)
                )
                if anchor < threshold:
                    return others[:index] + [moving] + others[index:]
            return others + [moving]

        if insert_direction == "right":
            insert_at = 0
            for index, clip in enumerate(others):
                threshold = clip.start_time + min(edge_margin, clip.display_duration / 2)
                if anchor >= threshold:
                    insert_at = index + 1
                else:
                    break
            return others[:insert_at] + [moving] + others[insert_at:]

        insert_at = 0
        for index, clip in enumerate(others):
            clip_midpoint = clip.start_time + clip.display_duration / 2
            if anchor >= clip_midpoint:
                insert_at = index + 1
            else:
                break
        return others[:insert_at] + [moving] + others[insert_at:]

    def add_clip(self, path: Path, duration: float, width: int, height: int) -> VideoClip:
        start_time = max(
            (clip.start_time + clip.display_duration for clip in self.clips),
            default=0.0,
        )
        clip = VideoClip(
            id=new_id(),
            path=str(path),
            name=path.stem,
            duration=duration,
            start_time=start_time,
            trim_start=0.0,
            trim_end=duration,
            width=width,
            height=height,
        )
        self.clips.append(clip)
        self.active_clip_id = self.active_clip_id or clip.id
        self.duration = max(self.duration, clip.start_time + clip.display_duration)
        return clip

    def add_image_clip(
        self,
        path: Path,
        width: int,
        height: int,
        display_duration: float = 5.0,
    ) -> VideoClip:
        start_time = max(
            (clip.start_time + clip.display_duration for clip in self.clips),
            default=0.0,
        )
        clip = VideoClip(
            id=new_id(),
            path=str(path),
            name=path.stem,
            duration=3600.0,  # arbitrary cap; images aren't time-bounded
            start_time=start_time,
            trim_start=0.0,
            trim_end=display_duration,
            width=width,
            height=height,
            media_type="image",
        )
        self.clips.append(clip)
        self.active_clip_id = self.active_clip_id or clip.id
        self.duration = max(self.duration, clip.start_time + clip.display_duration)
        return clip

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectState:
        project = cls(
            project_name=data.get("project_name", "Untitled Case"),
            video_type=data.get("video_type", "educational"),
            video_goal=data.get("video_goal", "talk-adjunct"),
            target_presentation_minutes=float(data.get("target_presentation_minutes", 10.0)),
            storyboard_objective=data.get("storyboard_objective", ""),
            storyboard_case_context=data.get("storyboard_case_context", ""),
            storyboard_key_anatomy=data.get("storyboard_key_anatomy", ""),
            storyboard_steps=data.get("storyboard_steps", ""),
            storyboard_decision_points=data.get("storyboard_decision_points", ""),
            storyboard_teaching_pearl=data.get("storyboard_teaching_pearl", ""),
            storyboard_final_point=data.get("storyboard_final_point", ""),
            intended_audience=data.get("intended_audience", ""),
            consent_confirmed=bool(data.get("consent_confirmed", False)),
            staff_notice_confirmed=bool(data.get("staff_notice_confirmed", False)),
            deidentified_confirmed=bool(data.get("deidentified_confirmed", False)),
            phi_review_confirmed=bool(data.get("phi_review_confirmed", False)),
            audio_reviewed_for_phi=bool(data.get("audio_reviewed_for_phi", False)),
            edit_disclosure=data.get("edit_disclosure", ""),
            current_time=float(data.get("current_time", 0.0)),
            duration=float(data.get("duration", 0.0)),
            playback_rate=float(data.get("playback_rate", 1.0)),
            volume=float(data.get("volume", 1.0)),
            is_muted=bool(data.get("is_muted", False)),
            active_clip_id=data.get("active_clip_id"),
            zoom=float(data.get("zoom", 80.0)),
            scroll_left=float(data.get("scroll_left", 0.0)),
            active_tool=data.get("active_tool", "select"),
            active_panel=data.get("active_panel", "tips"),
            selected_annotation_id=data.get("selected_annotation_id"),
            sam_mode=data.get("sam_mode", "positive"),
            sam_points_enabled=bool(data.get("sam_points_enabled", True)),
            draw_color=data.get("draw_color", "#00e5ff"),
            draw_width=int(data.get("draw_width", 6)),
            draw_opacity=float(data.get("draw_opacity", 0.85)),
            draw_label=data.get("draw_label", ""),
            captions_enabled=bool(data.get("captions_enabled", False)),
            caption_size=data.get("caption_size", "medium"),
            caption_position=data.get("caption_position", "bottom"),
            caption_background=bool(data.get("caption_background", True)),
            sam_last_run=data.get("sam_last_run", {}) or {},
            phi_review_progress=data.get("phi_review_progress", {}) or {},
        )
        project.clips = [_from_dict_tolerant(VideoClip, clip) for clip in data.get("clips", [])]
        project.audio_tracks = [
            _from_dict_tolerant(AudioTrack, track) for track in data.get("audio_tracks", [])
        ]
        project.transcript_segments = [
            _from_dict_tolerant(TranscriptSegment, segment)
            for segment in data.get("transcript_segments", [])
        ]
        project.slides = [_from_dict_tolerant(Slide, slide) for slide in data.get("slides", [])]
        project.markers = [
            _from_dict_tolerant(TimelineMarker, marker) for marker in data.get("markers", [])
        ]
        project.annotations = [
            _from_dict_tolerant(Annotation, annotation) for annotation in data.get("annotations", [])
        ]
        project.sam_points = [
            _from_dict_tolerant(SamPoint, point) for point in data.get("sam_points", [])
        ]
        return project
