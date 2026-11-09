"""Helpers for removing evaluation secrets from student-facing lecture payloads."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_PRIVATE_FIELDS = {
    "correct_answer",
    "accepted_answers",
    "hints",
    "solution_code",
    "recall_pool",
}
def sanitize_student_lecture(lecture: dict[str, Any]) -> dict[str, Any]:
    """Return a copy without answer keys, solution hints, rubrics, or recall pools."""
    sanitized = deepcopy(lecture)

    def strip_private_fields(value: Any) -> None:
        if isinstance(value, dict):
            value.pop("rubric", None)
            for field in _PRIVATE_FIELDS:
                value.pop(field, None)
            for child in list(value.values()):
                strip_private_fields(child)
            sandbox_config = value.get("sandbox_config")
            if isinstance(sandbox_config, dict) and not sandbox_config:
                value.pop("sandbox_config", None)
        elif isinstance(value, list):
            for child in value:
                strip_private_fields(child)

    strip_private_fields(sanitized)
    return sanitized
