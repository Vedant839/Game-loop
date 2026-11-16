"""Visual evidence validation helper.

Implements §7.3.6: validates visual evidence submitted from browser-side
analysis against weak windows and size limits.
"""

from __future__ import annotations

import json
import re
from typing import Any
from pydantic import BaseModel, Field

MAX_VISUAL_ITEMS = 200
MAX_VISUAL_TOTAL_BYTES = 200 * 1024  # 200 KB
WINDOW_PADDING_SECONDS = 5.0

_CONTROL_CHARS_REGEX = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class VisualEvidenceItem(BaseModel):
    id: str = Field(..., min_length=1, max_length=50)
    start_s: float = Field(..., ge=0.0)
    end_s: float = Field(..., ge=0.0)
    description: str = Field(default="", max_length=400)
    code: str | None = Field(default=None, max_length=1500)


def sanitize_text(text: str) -> str:
    """Strip control characters except newline and tab."""
    return _CONTROL_CHARS_REGEX.sub("", text)


def validate_visual_evidence(
    raw_items: list[dict[str, Any]] | None,
    weak_windows: list[dict[str, float]] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Validate visual evidence items against weak windows and size limits.

    Returns:
        (valid_items, rejected_count)
    """
    if not raw_items:
        return [], 0

    # Total size check
    serialized = json.dumps(raw_items)
    if len(serialized.encode("utf-8")) > MAX_VISUAL_TOTAL_BYTES:
        return [], len(raw_items)

    valid_items: list[dict[str, Any]] = []
    rejected_count = 0

    windows = weak_windows or []

    for item in raw_items[:MAX_VISUAL_ITEMS]:
        try:
            parsed = VisualEvidenceItem.model_validate(item)
            if parsed.end_s <= parsed.start_s:
                rejected_count += 1
                continue

            # Check if span lies within any weak window ± 5s
            if windows:
                in_weak_window = any(
                    (parsed.start_s >= w.get("start_s", 0.0) - WINDOW_PADDING_SECONDS)
                    and (parsed.end_s <= w.get("end_s", 0.0) + WINDOW_PADDING_SECONDS)
                    for w in windows
                )
                if not in_weak_window:
                    rejected_count += 1
                    continue

            cleaned_desc = sanitize_text(parsed.description)
            cleaned_code = sanitize_text(parsed.code) if parsed.code else None

            valid_items.append({
                "id": parsed.id,
                "start_s": round(parsed.start_s, 2),
                "end_s": round(parsed.end_s, 2),
                "description": cleaned_desc[:400],
                "code": cleaned_code[:1500] if cleaned_code else None,
            })
        except Exception:
            rejected_count += 1

    return valid_items, rejected_count

