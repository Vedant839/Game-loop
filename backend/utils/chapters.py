"""Chapter line parser for creator context.

Implements §7.3.5: parses pasted chapter lines of the form:
  MM:SS Title
  H:MM:SS Title
Malformed lines are ignored with a warning reported.
"""

from __future__ import annotations

import re
from pydantic import BaseModel, Field


class Chapter(BaseModel):
    time_s: float = Field(..., ge=0.0)
    title: str = Field(..., min_length=1)


class ParsedChaptersResult(BaseModel):
    chapters: list[Chapter]
    warnings: list[str]


_CHAPTER_REGEX = re.compile(
    r"^\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s*[-–—:]?\s*(.+)$"
)


def parse_chapters(text: str) -> ParsedChaptersResult:
    """Parse chapter lines into time_s and title.

    Accepts lines like:
      00:00 Introduction
      1:23 Setup
      01:02:15 Advanced Topics
    """
    chapters: list[Chapter] = []
    warnings: list[str] = []

    for line_num, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        match = _CHAPTER_REGEX.match(line)
        if not match:
            warnings.append(f"Line {line_num}: could not parse chapter timestamp from '{raw_line}'")
            continue

        hours_str, minutes_str, seconds_str, title = match.groups()
        hours = int(hours_str) if hours_str else 0
        minutes = int(minutes_str)
        seconds = int(seconds_str)
        title = title.strip()

        if not title:
            warnings.append(f"Line {line_num}: missing chapter title in '{raw_line}'")
            continue

        time_s = float(hours * 3600 + minutes * 60 + seconds)
        chapters.append(Chapter(time_s=time_s, title=title))

    # Sort chapters by timestamp ascending
    chapters.sort(key=lambda c: c.time_s)
    return ParsedChaptersResult(chapters=chapters, warnings=warnings)

