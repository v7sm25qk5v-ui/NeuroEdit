from __future__ import annotations

from neuroedit_desktop.models import ProjectState


def fmt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes = int(seconds // 60)
    remainder = seconds % 60
    return f"{minutes}:{remainder:04.1f}"


def project_end_time(project: ProjectState) -> float:
    # Content ends only. Feeding project.duration or current_time back in here
    # let the timeline end ratchet upward one second per seek-to-end (the seek
    # clamp uses this value), which then padded exports with a black tail.
    ends: list[float] = []
    ends.extend(clip.start_time + clip.display_duration for clip in project.clips)
    ends.extend(track.start_time + max(0.1, track.duration) for track in project.audio_tracks)
    ends.extend(slide.start_time + max(0.1, slide.duration) for slide in project.slides)
    ends.extend(marker.time + 1.0 for marker in project.markers)
    return max(1.0, max(ends, default=1.0))
