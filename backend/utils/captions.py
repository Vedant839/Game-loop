"""SRT and WebVTT parsing and transcript timing validation."""

from __future__ import annotations

import html
import re
import warnings
from collections.abc import Sequence

from backend.schemas.lecture import TranscriptSegment


class CaptionParseError(ValueError):
    """Raised when a caption cue has invalid timing or structure."""


class TranscriptValidationError(ValueError):
    """Raised when transcript segments are out of order or overlap."""


class TranscriptGapWarning(UserWarning):
    """Warns about a large gap between adjacent transcript segments."""


_TIMESTAMP = re.compile(
    r"^(?:(?P<hours>\d+):)?(?P<minutes>\d{2}):(?P<seconds>\d{2})"
    r"(?:[,.](?P<milliseconds>\d{1,3}))?$"
)
_TIMING_LINE = re.compile(r"^\s*(\S+)\s+-->\s+(\S+)(?:\s+.*)?$")
_VTT_TAG = re.compile(r"<[^>]*>")


def _timestamp_seconds(value: str, *, format_name: str, cue_number: int) -> float:
    match = _TIMESTAMP.fullmatch(value)
    if not match:
        raise CaptionParseError(
            f"{format_name} cue {cue_number}: invalid timestamp {value!r}; "
            "expected MM:SS.mmm or HH:MM:SS.mmm"
        )
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes"))
    seconds = int(match.group("seconds"))
    if minutes >= 60 or seconds >= 60:
        raise CaptionParseError(
            f"{format_name} cue {cue_number}: minutes and seconds must be below 60"
        )
    milliseconds_text = match.group("milliseconds") or "0"
    milliseconds = int(milliseconds_text.ljust(3, "0"))
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000


def _parse_blocks(
    content: str,
    *,
    format_name: str,
    gap_warning_seconds: float | None,
) -> list[TranscriptSegment]:
    normalized = content.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n[ \t]*\n+", normalized.strip()) if normalized.strip() else []
    segments: list[TranscriptSegment] = []
    cue_number = 0

    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        if format_name == "WebVTT":
            first = lines[0].upper()
            if first.startswith("WEBVTT") or first.startswith(("NOTE", "STYLE", "REGION")):
                continue

        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            raise CaptionParseError(
                f"{format_name} cue {cue_number + 1}: missing timing line"
            )
        timing_match = _TIMING_LINE.fullmatch(lines[timing_index])
        cue_number += 1
        if not timing_match:
            raise CaptionParseError(f"{format_name} cue {cue_number}: malformed timing line")

        start = _timestamp_seconds(
            timing_match.group(1), format_name=format_name, cue_number=cue_number
        )
        end = _timestamp_seconds(
            timing_match.group(2), format_name=format_name, cue_number=cue_number
        )
        if start >= end:
            raise CaptionParseError(
                f"{format_name} cue {cue_number}: start time must be before end time"
            )
        cue_text = "\n".join(lines[timing_index + 1 :])
        cue_text = html.unescape(_VTT_TAG.sub("", cue_text)).strip()
        if not cue_text:
            continue
        segments.append(TranscriptSegment(start_time=start, end_time=end, text=cue_text))

    validate_transcript(segments, gap_warning_seconds=gap_warning_seconds)
    return segments


def parse_srt(content: str, *, gap_warning_seconds: float | None = 2.0) -> list[TranscriptSegment]:
    """Parse SubRip captions, accepting comma or dot millisecond separators."""
    return _parse_blocks(
        content, format_name="SRT", gap_warning_seconds=gap_warning_seconds
    )


def parse_vtt(content: str, *, gap_warning_seconds: float | None = 2.0) -> list[TranscriptSegment]:
    """Parse WebVTT captions, dropping cue settings and markup tags."""
    return _parse_blocks(
        content, format_name="WebVTT", gap_warning_seconds=gap_warning_seconds
    )


def validate_transcript(
    segments: Sequence[TranscriptSegment],
    *,
    gap_warning_seconds: float | None = 2.0,
) -> list[str]:
    """Reject unordered/overlapping cues and warn when gaps exceed the threshold.

    The returned list contains the same gap messages emitted as
    :class:`TranscriptGapWarning`. Set the threshold to ``None`` to disable gap
    warnings; overlap and ordering validation always remain enabled.
    """
    if gap_warning_seconds is not None and gap_warning_seconds < 0:
        raise ValueError("gap_warning_seconds must be non-negative or None")

    gap_messages: list[str] = []
    previous: TranscriptSegment | None = None
    for index, current in enumerate(segments, start=1):
        if previous is not None:
            if current.start_time < previous.start_time:
                raise TranscriptValidationError(
                    f"Transcript segment {index} starts before the previous segment"
                )
            if current.start_time < previous.end_time:
                raise TranscriptValidationError(
                    f"Transcript segments {index - 1} and {index} overlap"
                )
            gap = current.start_time - previous.end_time
            if gap_warning_seconds is not None and gap > gap_warning_seconds:
                message = (
                    f"Transcript gap of {gap:.3f}s between segments {index - 1} and {index}"
                )
                gap_messages.append(message)
                warnings.warn(message, TranscriptGapWarning, stacklevel=2)
        previous = current
    return gap_messages
