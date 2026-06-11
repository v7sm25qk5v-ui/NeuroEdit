"""Caption generation from transcript segments, SRT/WebVTT serialization, and
the shared canvas/export caption painter.

Conventions follow accessibility guidance for caption styling: ~42 chars per
line, max 2 lines per cue, white sans-serif text on a semi-opaque dark box,
positioned inside a safe-area margin so platform UI doesn't cover it.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPen

from neuroedit_desktop.models import TranscriptSegment

MAX_CHARS_PER_LINE = 42
MAX_LINES_PER_CUE = 2
MIN_CUE_SECONDS = 0.8

# Fraction of frame height used for the caption font size.
FONT_SCALE = {"small": 0.035, "medium": 0.045, "large": 0.058}
SAFE_MARGIN_FRACTION = 0.05  # keep captions inside a 5% safe area


@dataclass(frozen=True)
class CaptionCue:
    start: float
    end: float
    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def wrap_caption_text(text: str, max_chars: int = MAX_CHARS_PER_LINE) -> list[str]:
    """Greedy word wrap. Words longer than max_chars stay on their own line."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def build_caption_cues(
    segments: list[TranscriptSegment],
    *,
    max_chars: int = MAX_CHARS_PER_LINE,
    max_lines: int = MAX_LINES_PER_CUE,
) -> list[CaptionCue]:
    """Turn transcript segments into display-sized caption cues. A segment whose
    text wraps past max_lines is split into several sequential cues, each given
    a share of the segment's time proportional to its character count."""
    cues: list[CaptionCue] = []
    for segment in sorted(segments, key=lambda s: s.start_time):
        text = segment.text.strip()
        if not text:
            continue
        if segment.speaker.strip():
            text = f"{segment.speaker.strip()}: {text}"
        lines = wrap_caption_text(text, max_chars)
        chunks = [
            tuple(lines[i : i + max_lines]) for i in range(0, len(lines), max_lines)
        ]
        duration = max(MIN_CUE_SECONDS, segment.end_time - segment.start_time)
        total_chars = sum(len(line) for chunk in chunks for line in chunk) or 1
        cursor = segment.start_time
        for index, chunk in enumerate(chunks):
            chunk_chars = sum(len(line) for line in chunk)
            if index == len(chunks) - 1:
                end = segment.start_time + duration
            else:
                end = cursor + duration * (chunk_chars / total_chars)
            cues.append(CaptionCue(start=cursor, end=max(cursor + 0.1, end), lines=chunk))
            cursor = end
    return cues


def cue_at_time(cues: list[CaptionCue], time_s: float) -> CaptionCue | None:
    for cue in cues:
        if cue.start <= time_s < cue.end:
            return cue
    return None


def _srt_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _vtt_timestamp(seconds: float) -> str:
    return _srt_timestamp(seconds).replace(",", ".")


def cues_to_srt(cues: list[CaptionCue]) -> str:
    blocks = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            f"{index}\n{_srt_timestamp(cue.start)} --> {_srt_timestamp(cue.end)}\n"
            + "\n".join(cue.lines)
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def cues_to_vtt(cues: list[CaptionCue]) -> str:
    blocks = ["WEBVTT"]
    for cue in cues:
        blocks.append(
            f"{_vtt_timestamp(cue.start)} --> {_vtt_timestamp(cue.end)}\n"
            + "\n".join(cue.lines)
        )
    return "\n\n".join(blocks) + "\n"


def paint_caption(
    painter: QPainter,
    cue: CaptionCue,
    width: float,
    height: float,
    *,
    size: str = "medium",
    position: str = "bottom",
    background: bool = True,
) -> None:
    """Paint one cue centered near the bottom (or top) of the frame. Shared by
    the live canvas and the exporter so preview and output match exactly."""
    if not cue.lines or width <= 0 or height <= 0:
        return
    font = QFont()
    font.setPixelSize(max(10, int(height * FONT_SCALE.get(size, FONT_SCALE["medium"]))))
    font.setBold(True)
    painter.setFont(font)
    metrics = QFontMetricsF(font)
    line_height = metrics.height()
    pad_x = line_height * 0.45
    pad_y = line_height * 0.18
    margin = height * SAFE_MARGIN_FRACTION

    block_height = line_height * len(cue.lines) + pad_y * 2
    if position == "top":
        block_top = margin
    else:
        block_top = height - margin - block_height

    widest = max(metrics.horizontalAdvance(line) for line in cue.lines)
    block_width = widest + pad_x * 2
    block_left = (width - block_width) / 2
    block = QRectF(block_left, block_top, block_width, block_height)

    painter.save()
    if background:
        bg = QColor("#000000")
        bg.setAlpha(165)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(block, 6, 6)
    painter.setPen(QPen(QColor("#ffffff")))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    y = block_top + pad_y
    for line in cue.lines:
        line_rect = QRectF(0, y, width, line_height)
        painter.drawText(line_rect, Qt.AlignmentFlag.AlignHCenter, line)
        y += line_height
    painter.restore()
