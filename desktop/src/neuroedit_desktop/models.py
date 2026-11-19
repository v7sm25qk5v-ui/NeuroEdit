from __future__ import annotations

import math
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


# Version of the project.json layout this build reads and writes. Bump it only
# when a change would make older builds lose or misread data.
SCHEMA_VERSION = 2

# An inserted slide lands on the nearest clip edge when it is this close
# (seconds, or pixels at the current zoom, whichever is wider), so a slide
# meant to go between two clips never splits one a second from its end.
INSERT_SNAP_SECONDS = 2.0
INSERT_SNAP_PX = 16.0
# Inserting room this close to a clip edge goes to the edge instead of
# splitting off a piece of clip too short to matter.
MIN_SPLIT = 0.05
CLIP_SPEEDS = (0.25, 0.5, 1.0, 1.5, 2.0, 4.0)


def effective_clip_speed(speed: float, media_type: str) -> float:
    if (media_type == "video" and isinstance(speed, (int, float))
            and CLIP_SPEEDS[0] <= speed <= CLIP_SPEEDS[-1]):
        return float(speed)
    return 1.0


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
    speed: float = 1.0  # source seconds per timeline second

    @property
    def effective_speed(self) -> float:
        return effective_clip_speed(self.speed, self.media_type)

    @property
    def display_duration(self) -> float:
        return max(0.0, self.trim_end - self.trim_start) / self.effective_speed

    def source_time_at(self, timeline_time: float) -> float:
        return self.trim_start + (timeline_time - self.start_time) * self.effective_speed

    def timeline_time_at(self, source_time: float) -> float:
        return self.start_time + (source_time - self.trim_start) / self.effective_speed

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
    # A full slide with its own time in the video storyline: the clips after
    # it were pushed later to make room, so no footage is hidden behind it.
    # False with overlay False is a "cover" slide, drawn over the footage.
    insert: bool = False
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


def slide_span(slide: Slide) -> float:
    """Timeline length of a slide, matching the storyline's gap rules."""
    return max(0.1, slide.duration)


def slide_is_inserted(slide: Slide) -> bool:
    return bool(slide.insert) and not slide.overlay


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


def _shift_mask_frames(annotation: Annotation, shift: float) -> None:
    if shift:
        for frame in annotation.mask_frames:
            frame["time"] = float(frame["time"]) + shift


def _ripple_redaction(annotation: Annotation, anchor: float, delta: float) -> None:
    """Ripple one redaction so it still covers the footage it covered.

    Covering extra footage is acceptable; exposing covered footage is not.
    `ann_duration == 0` means "to the end of the timeline", so a finite
    window is never allowed to collapse to zero.
    """
    eps = 1e-9
    start = annotation.frame_time
    finite = annotation.ann_duration > 0
    end = start + annotation.ann_duration
    if delta > 0:
        # Footage is revealed at `anchor`. A redaction strictly after it
        # follows its footage; one that touches or spans the edit point
        # keeps its start and grows over the revealed footage.
        if start > anchor + eps:
            annotation.frame_time = start + delta
        elif finite and end >= anchor - eps:
            annotation.ann_duration += delta
        return

    # delta < 0: timeline [cut_start, anchor) was removed.
    cut_start = max(0.0, anchor + delta)
    if finite and start >= cut_start - eps and end <= anchor + eps:
        return  # only covered removed footage: stays put, over-covering

    def moved(time_s: float) -> float:
        if time_s >= anchor - eps:
            return max(0.0, time_s + delta)
        return min(time_s, cut_start)

    new_start = moved(start)
    if finite:
        new_duration = moved(end) - new_start
        if new_duration > eps:
            annotation.ann_duration = new_duration
    annotation.frame_time = new_start


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
    # Last export-sheet choices: {quality, mute_source_audio, burn_captions, fps}.
    export_preferences: dict = field(default_factory=dict)

    # Not a dataclass field (no annotation): the version recorded in the file
    # this state was loaded from. Greater than SCHEMA_VERSION means a newer
    # build wrote it and saving here would drop fields this build does not know.
    loaded_schema_version = SCHEMA_VERSION

    @property
    def schema_version(self) -> int:
        # Older builds misread retimed footage and its redactions. Version 2
        # lets them warn while ordinary projects remain compatible with v1.
        return 2 if any(clip.effective_speed != 1.0 for clip in self.clips) else 1

    @property
    def has_case_notes(self) -> bool:
        return any((
            self.storyboard_objective, self.storyboard_case_context,
            self.storyboard_key_anatomy, self.storyboard_steps,
            self.storyboard_decision_points, self.storyboard_teaching_pearl,
            self.storyboard_final_point, self.intended_audience, self.edit_disclosure,
        ))

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
        """Keep the primary video storyline compact and ordered.

        Empty time between video clips is removed. A gap that is completely
        occupied by one or more full-frame slides is retained because it is
        visible project content (Take Still uses this form).
        """
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
        positions = self.compact_clip_positions(ordered)
        for clip in ordered:
            clip.start_time = positions[clip.id]
        self.clips = ordered

    def compact_clip_positions(self, ordered: list[VideoClip] | None = None) -> dict[str, float]:
        """Return magnetic storyline positions without mutating the project."""
        original = sorted(self.clips, key=lambda clip: clip.start_time)
        reserved_gaps: list[tuple[float, float]] = []
        full_frame_slides = sorted(
            (slide for slide in self.slides if not slide.overlay),
            key=lambda slide: slide.start_time,
        )
        # The time before the first clip counts too: an inserted title slide
        # at 0:00 keeps the first clip after it.
        gaps = [(0.0, original[0].start_time)] if original else []
        gaps.extend(
            (left.start_time + left.display_duration, right.start_time)
            for left, right in zip(original, original[1:])
        )
        for gap_start, gap_end in gaps:
            if gap_end <= gap_start + 1e-9:
                continue
            covered_until = gap_start
            for slide in full_frame_slides:
                slide_start = slide.start_time
                slide_end = slide.start_time + max(0.1, slide.duration)
                if slide_end <= covered_until + 1e-9:
                    continue
                if slide_start > covered_until + 1e-9:
                    break
                covered_until = max(covered_until, slide_end)
                if covered_until >= gap_end - 1e-9:
                    reserved_gaps.append((gap_start, gap_end))
                    break
        ordered = original if ordered is None else ordered
        cursor = 0.0
        positions: dict[str, float] = {}
        for clip in ordered:
            for gap_start, gap_end in reserved_gaps:
                if gap_start - 1e-9 <= cursor < gap_end - 1e-9:
                    cursor = gap_end
            positions[clip.id] = cursor
            cursor += clip.display_duration
        return positions

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
            old_start = annotation.frame_time
            if annotation.type == "redact":
                _ripple_redaction(annotation, anchor, delta)
            elif annotation.frame_time >= threshold:
                annotation.frame_time = max(0.0, annotation.frame_time + delta)
            _shift_mask_frames(annotation, annotation.frame_time - old_start)

    def set_clip_speed(self, clip: VideoClip, speed: float) -> bool:
        """Change the clip's duration while keeping timed edits on their footage."""
        if (clip.media_type != "video" or not isinstance(speed, (int, float))
                or not CLIP_SPEEDS[0] <= speed <= CLIP_SPEEDS[-1]
                or speed == clip.effective_speed):
            return False

        start = clip.start_time
        old_duration = clip.display_duration
        old_end = start + old_duration
        clip.speed = speed
        new_duration = clip.display_duration
        new_end = start + new_duration

        def retime(time_s: float) -> float:
            if time_s <= start:
                return time_s
            if time_s >= old_end:
                return new_end + (time_s - old_end)
            return start + (time_s - start) / old_duration * new_duration

        for other in self.clips:
            if other is not clip and other.start_time >= old_end - 1e-9:
                other.start_time = new_end + max(0.0, other.start_time - old_end)
        for slide in self.slides:
            if not slide_is_inserted(slide):
                slide.duration = retime(slide.start_time + slide.duration) - retime(slide.start_time)
            slide.start_time = retime(slide.start_time)
        audio_shifts = {}
        for track in self.audio_tracks:
            new_start = retime(track.start_time)
            audio_shifts[track.id] = new_start - track.start_time
            track.start_time = new_start
        for segment in self.transcript_segments:
            if segment.audio_track_id in audio_shifts:
                shift = audio_shifts[segment.audio_track_id]
                segment.start_time += shift
                segment.end_time += shift
            else:
                segment.start_time, segment.end_time = retime(segment.start_time), retime(segment.end_time)
        for marker in self.markers:
            marker.time = retime(marker.time)
        for annotation in self.annotations:
            new_start = retime(annotation.frame_time)
            if annotation.ann_duration > 0:
                new_end_time = retime(annotation.frame_time + annotation.ann_duration)
                annotation.ann_duration = max(math.ulp(new_end_time), new_end_time - new_start)
            annotation.frame_time = new_start
            for frame in annotation.mask_frames:
                frame["time"] = retime(float(frame["time"]))
        self.current_time = retime(self.current_time)
        return True

    def move_redactions_with_clips(self, old_spans: dict[str, tuple[float, float]]) -> None:
        """Re-place redactions after clips were reordered.

        `old_spans` maps clip id to its (start, end) on the timeline before
        the reorder. Each redaction moves to the smallest single window that
        still holds every piece of footage it covered; time that was not over
        a clip stays where it was. A redaction spanning clips that are no
        longer adjacent therefore widens rather than exposing either piece.
        """
        moves = sorted(
            (old_spans[clip.id][0], old_spans[clip.id][1], clip.start_time - old_spans[clip.id][0])
            for clip in self.clips
            if clip.id in old_spans
        )
        if all(abs(shift) < 1e-9 for _start, _end, shift in moves):
            return
        for annotation in self.annotations:
            if annotation.type != "redact":
                continue
            start = annotation.frame_time
            finite = annotation.ann_duration > 0
            end = start + annotation.ann_duration if finite else math.inf
            pieces: list[tuple[float, float]] = []
            cursor = start
            for clip_start, clip_end, shift in moves:
                if clip_end <= start + 1e-9 or clip_start >= end - 1e-9:
                    continue
                if clip_start > cursor + 1e-9:
                    pieces.append((cursor, clip_start))
                pieces.append((max(start, clip_start) + shift, min(end, clip_end) + shift))
                cursor = max(cursor, clip_end)
            if cursor < end - 1e-9:
                pieces.append((cursor, end))
            new_start = max(0.0, min(piece[0] for piece in pieces))
            if finite:
                annotation.ann_duration = max(piece[1] for piece in pieces) - new_start
            annotation.frame_time = new_start
            _shift_mask_frames(annotation, new_start - start)

    def timeline_positions(self) -> list[tuple[Any, dict[str, Any]]]:
        """Capture every value a trim and its ripple can change, so a live
        drag can be re-applied from its starting state on each mouse move."""
        saved: list[tuple[Any, dict[str, Any]]] = []
        for clip in self.clips:
            saved.append((clip, {
                "start_time": clip.start_time,
                "trim_start": clip.trim_start,
                "trim_end": clip.trim_end,
            }))
        for item in (*self.slides, *self.audio_tracks):
            saved.append((item, {"start_time": item.start_time}))
        for segment in self.transcript_segments:
            saved.append((segment, {
                "start_time": segment.start_time,
                "end_time": segment.end_time,
            }))
        for marker in self.markers:
            saved.append((marker, {"time": marker.time}))
        for annotation in self.annotations:
            saved.append((annotation, {
                "frame_time": annotation.frame_time,
                "ann_duration": annotation.ann_duration,
                "mask_frame_times": [frame["time"] for frame in annotation.mask_frames],
            }))
        return saved

    def restore_timeline_positions(self, saved: list[tuple[Any, dict[str, Any]]]) -> None:
        for item, values in saved:
            for name, value in values.items():
                if name == "mask_frame_times":
                    for frame, time_s in zip(item.mask_frames, value):
                        frame["time"] = time_s
                else:
                    setattr(item, name, value)

    def insert_gap(self, time_s: float, duration: float, *, split_suffix: str = "(after still)") -> float:
        """Make `duration` seconds of room at `time_s`: everything from there
        on moves later, and a clip under that point is split around the room.
        Returns the point actually used: one within MIN_SPLIT of a clip edge
        moves to the edge, since a split there would leave a sliver of clip
        under whatever fills the room."""
        splits_clip = False
        for clip in self.clips:
            start = clip.start_time
            end = start + clip.display_duration
            if start < time_s < end:
                if time_s - start < MIN_SPLIT:
                    time_s = start
                elif end - time_s < MIN_SPLIT:
                    time_s = end
                else:
                    splits_clip = True
                break
        # At a clip edge, a redaction that ends exactly at the point stops
        # there instead of growing over the new room (its inclusive end frame
        # is the next clip's first frame, which it was never drawn for).
        # Inside a clip it still grows: the frame at its end is the same
        # footage, resumed after the room.
        ends_at_point = [] if splits_clip else [
            (ann, ann.ann_duration)
            for ann in self.annotations
            if ann.type == "redact"
            and ann.ann_duration > 0
            and ann.frame_time < time_s - 1e-9
            and abs(ann.frame_time + ann.ann_duration - time_s) <= 1e-9
        ]
        # A redaction that starts exactly at the insertion point moves after
        # the gap (whatever fills the gap already shows that frame);
        # ripple_after would keep its start and grow it instead.
        at_point = [
            (ann, ann.frame_time, ann.ann_duration)
            for ann in self.annotations
            if ann.type == "redact" and time_s <= ann.frame_time <= time_s + 1e-9
        ]
        # Everything downstream (clips, slides, audio, captions, markers,
        # annotations and their mask frames) shifts in one place. Clips that
        # span the insertion point keep their start and are split below.
        self.ripple_after(time_s, duration)
        for ann, start, length in at_point:
            _shift_mask_frames(ann, start + duration - ann.frame_time)
            ann.frame_time = start + duration
            ann.ann_duration = length
        for ann, length in ends_at_point:
            ann.ann_duration = length

        for clip in list(self.clips):
            start = clip.start_time
            if start < time_s < start + clip.display_duration:
                self.split_clip_for_gap(clip, time_s, duration, suffix=split_suffix)

        for ann in self.annotations:
            # Cap normal labels so they don't bleed through the gap. Redactions
            # were already extended by ripple_after, unlimited ones stay so.
            if ann.type != "redact" and ann.frame_time < time_s and ann.is_visible_at(time_s):
                ann.ann_duration = time_s - ann.frame_time
        return time_s

    def split_clip_for_gap(
        self, clip: VideoClip, time_s: float, gap_duration: float, *, suffix: str = "(after still)",
    ) -> None:
        left_duration = time_s - clip.start_time
        split_trim = clip.source_time_at(time_s)
        right_duration = (clip.trim_end - split_trim) / clip.effective_speed
        if left_duration < MIN_SPLIT:
            clip.start_time += gap_duration
            return
        if right_duration < MIN_SPLIT:
            return

        original_trim_end = clip.trim_end
        original_source_out_limit = clip.source_out_limit
        clip.trim_end = split_trim
        clip.source_out_limit = split_trim
        right = VideoClip(
            id=new_id(),
            path=clip.path,
            name=f"{clip.name} {suffix}",
            duration=clip.duration,
            start_time=time_s + gap_duration,
            trim_start=split_trim,
            trim_end=original_trim_end,
            source_in_limit=split_trim,
            source_out_limit=original_source_out_limit,
            width=clip.width,
            height=clip.height,
            thumbnail_path=clip.thumbnail_path,
            media_type=clip.media_type,
            fade_in=clip.fade_in,
            fade_out=clip.fade_out,
            fade_color=clip.fade_color,
            speed=clip.speed,
        )
        idx = self.clips.index(clip)
        self.clips.insert(idx + 1, right)

    def slide_insert_point(
        self,
        time_s: float,
        *,
        boundaries_only: bool = False,
        exclude_id: str | None = None,
    ) -> float:
        """Where an inserted slide aimed at `time_s` should go.

        Edges are the timeline start, every clip's start and end, and the
        edges of other inserted slides. A point inside another inserted slide
        moves to its nearer edge, and a point past the end of the video goes
        to the end. Otherwise the nearest edge wins when it is within
        INSERT_SNAP_SECONDS (or INSERT_SNAP_PX at the current zoom); a point
        further inside a clip stays put and splits that clip. With
        `boundaries_only` (dragging on the timeline) the nearest edge always wins.
        """
        eps = 1e-9
        time_s = max(0.0, time_s)
        edges = [0.0]
        for clip in self.clips:
            edges.extend((clip.start_time, clip.start_time + clip.display_duration))
        for slide in self.slides:
            if slide.id == exclude_id or not slide_is_inserted(slide):
                continue
            start = slide.start_time
            end = start + slide_span(slide)
            if start + eps < time_s < end - eps:
                return start if time_s - start <= end - time_s else end
            edges.extend((start, end))
        storyline_end = max(edges)
        if time_s >= storyline_end:
            return storyline_end
        nearest = min(edges, key=lambda edge: (abs(edge - time_s), edge))
        threshold = max(INSERT_SNAP_SECONDS, INSERT_SNAP_PX / max(1.0, self.zoom))
        if boundaries_only or abs(nearest - time_s) <= threshold:
            return nearest
        return time_s

    def insert_slide(self, slide: Slide, time_s: float) -> None:
        """Give a full slide its own time at `time_s` (a point from
        slide_insert_point): what follows moves later by the slide's length."""
        time_s = self.insert_gap(time_s, slide_span(slide), split_suffix="(after slide)")
        slide.start_time = time_s
        slide.overlay = False
        slide.insert = True

    def remove_slide_gap(self, slide: Slide) -> bool:
        """Stop a slide being inserted and close the time it had, pulling
        what follows back. If footage now fills that time, nothing moves.
        Returns whether the time was closed."""
        if not slide_is_inserted(slide):
            # Includes a file with overlay and insert both set: an overlay
            # never had time of its own, so there is nothing to close.
            slide.insert = False
            return False
        slide.insert = False
        start = slide.start_time
        end = start + slide_span(slide)
        eps = 1e-6
        if any(
            clip.start_time < end - eps and clip.start_time + clip.display_duration > start + eps
            for clip in self.clips
        ):
            return False
        self.ripple_after(end, start - end)
        return True

    def outside_inserted_slides(self, time_s: float) -> float:
        """`time_s`, or the nearer edge of the inserted slide it falls inside."""
        for slide in self.slides:
            if not slide_is_inserted(slide):
                continue
            start = slide.start_time
            end = start + slide_span(slide)
            if start < time_s < end:
                return start if time_s - start <= end - time_s else end
        return time_s

    def move_inserted_slide(self, slide: Slide, time_s: float) -> None:
        """Take an inserted slide out of the storyline and insert it again at
        the clip edge nearest `time_s`, read with the slide already removed."""
        if not slide_is_inserted(slide):
            return
        origin = self.timeline_positions()
        old_start = slide.start_time
        self.remove_slide_gap(slide)
        point = self.slide_insert_point(time_s, boundaries_only=True, exclude_id=slide.id)
        if abs(point - old_start) < 1e-6:
            # Same place: put everything back exactly, including items that
            # start inside the slide's time, which a close-and-reopen would move.
            self.restore_timeline_positions(origin)
            slide.insert = True
            return
        self.insert_slide(slide, point)

    def place_inserted_slide(self, slide: Slide, time_s: float) -> None:
        """Move an inserted slide to the playhead at `time_s` (current
        timeline coordinates). Unlike a drag, a point well inside a clip
        splits it there; near a clip edge it goes to the edge."""
        if not slide_is_inserted(slide):
            return
        start = slide.start_time
        end = start + slide_span(slide)
        if start - 1e-9 <= time_s <= end + 1e-9:
            return
        origin = self.timeline_positions()
        clips = list(self.clips)
        if self.remove_slide_gap(slide) and time_s > end:
            time_s -= end - start
        point = self.slide_insert_point(time_s, exclude_id=slide.id)
        if abs(point - start) < 1e-6:
            self.clips = clips
            self.restore_timeline_positions(origin)
            slide.insert = True
            return
        self.insert_slide(slide, point)

    def resize_inserted_slide(self, slide: Slide, duration: float) -> None:
        """Set a slide's duration; an inserted slide pushes or pulls what follows."""
        old_span = slide_span(slide)
        slide.duration = duration
        if not slide_is_inserted(slide):
            return
        delta = slide_span(slide) - old_span
        old_end = slide.start_time + old_span
        if delta > 1e-9:
            self.insert_gap(old_end, delta, split_suffix="(after slide)")
        elif delta < -1e-9:
            self.ripple_after(old_end, delta)

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
        return {"schema_version": self.schema_version, **asdict(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectState:
        try:
            loaded_version = int(data.get("schema_version", 1))
        except (TypeError, ValueError):
            loaded_version = 1
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
            export_preferences=data.get("export_preferences", {}) or {},
        )
        project.loaded_schema_version = loaded_version
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
        # JSON accepts NaN/Infinity, but timeline geometry and frame arithmetic
        # require finite times. Reject invalid documents instead of normalizing
        # their timing and potentially detaching privacy coverage.
        values = [project.duration, project.current_time, project.zoom, project.scroll_left]
        for clip in project.clips:
            if (not isinstance(clip.speed, (int, float))
                    or not CLIP_SPEEDS[0] <= clip.speed <= CLIP_SPEEDS[-1]):
                raise ValueError("Clip speeds must be between 0.25× and 4×.")
            values.extend((clip.duration, clip.start_time, clip.trim_start, clip.trim_end,
                           clip.start_time + clip.display_duration))
        for track in project.audio_tracks:
            values.extend((track.start_time, track.duration, track.start_time + track.duration))
        for slide in project.slides:
            values.extend((slide.start_time, slide.duration, slide.start_time + slide.duration))
        for ann in project.annotations:
            values.extend((ann.frame_time, ann.ann_duration, ann.frame_time + ann.ann_duration))
        values.extend(marker.time for marker in project.markers)
        for segment in project.transcript_segments:
            values.extend((segment.start_time, segment.end_time))
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
            raise ValueError("Project timeline values must be finite numbers.")
        return project
