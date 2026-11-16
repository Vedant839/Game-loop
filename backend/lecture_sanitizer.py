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
    # P1.5 Rev 8.0 content-understanding internal fields
    "concepts",
    "analysis_report",
    "creator_context",
    "visual_evidence",
    "generator_version",
    "evidence",
    "confidence",
    "review_state",
    "origin",
}


def sanitize_student_lecture(lecture: dict[str, Any]) -> dict[str, Any]:
    """Return a copy without answer keys, solution hints, rubrics, recall pools,
    or internal content understanding fields. Checkpoints with review_state == 'needs_review'
    are omitted entirely.
    """
    sanitized = deepcopy(lecture)

    # Filter out interventions with review_state == "needs_review"
    if "interventions" in sanitized and isinstance(sanitized["interventions"], list):
        sanitized["interventions"] = [
            intv for intv in sanitized["interventions"]
            if not (isinstance(intv, dict) and intv.get("review_state") == "needs_review")
        ]

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
            mobile_fallback = value.get("mobile_fallback")
            if isinstance(mobile_fallback, dict):
                mobile_fallback.pop("correct_answer", None)
        elif isinstance(value, list):
            for child in value:
                strip_private_fields(child)

    strip_private_fields(sanitized)
    return sanitized
