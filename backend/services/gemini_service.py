"""Gemini authoring pipeline for generating content-relevant interventions.

Implements SPEC sections 18-26: calls Gemini with the full timestamped transcript
and lecture metadata, parses structured JSON output, applies the deterministic
validation pipeline (schema, timestamp, spacing/conflict, count), and returns a
final intervention set that is guaranteed to pass Lecture.model_validate.

Gemini is used at AUTHORING time only. The runtime never calls this service.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.schemas.lecture import (
    Difficulty,
    Intervention,
    InterventionType,
    Lecture,
    Option,
    TranscriptSegment,
)

logger = logging.getLogger(__name__)

MAX_INTERVENTIONS = 6
TARGET_INTERVENTIONS = 4

# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _build_transcript_text(segments: list[TranscriptSegment]) -> str:
    lines = []
    for seg in segments:
        lines.append(f"[{seg.start_time:.1f}s - {seg.end_time:.1f}s] {seg.text}")
    return "\n".join(lines)


def _build_prompt(lecture: Lecture) -> str:
    transcript_text = _build_transcript_text(lecture.transcript)

    return f"""You are an expert educational content author. Your task is to generate
learning interventions (quiz questions) for the following lecture.

LECTURE METADATA
================
Title: {lecture.title}
Subject: {lecture.subject}
Grade: {lecture.grade}
Duration: {lecture.duration_seconds:.1f} seconds

TIMESTAMPED TRANSCRIPT
======================
{transcript_text}

AUTHORING REQUIREMENTS
======================
- Generate between {TARGET_INTERVENTIONS} and {MAX_INTERVENTIONS} interventions.
- Each intervention must be DIRECTLY based on content in the transcript at the
  specified timestamp — do NOT invent concepts not covered in the lecture.
- Choose pedagogically valuable pause points: after a key definition, after a
  worked example, or when the learner must apply what was just shown.
- Intervention types allowed: "single_choice" or "multiple_selection".
- Difficulty must be one of: "Easy", "Medium", "Hard", "Tough".
- trigger_time must be within the transcript segment that inspired the question
  and within [0, {lecture.duration_seconds:.1f}] seconds.
- Interventions must be spaced at least {lecture.timing_config.min_trigger_gap:.1f}s apart.
- Each option must have a unique id (e.g. "opt_a", "opt_b", "opt_c", "opt_d").
- correct_answer: string id for single_choice; array of string ids for multiple_selection.
- For multiple_selection, correct_answer must have ≥ 2 correct options.
- Questions must be self-contained and answerable from the lecture content alone.

OUTPUT FORMAT
=============
Respond with ONLY a valid JSON array — no markdown fences, no prose.
Each element must match this schema exactly:

{{
  "id": "int_1",
  "trigger_time": <float seconds>,
  "transcript_segment_start": <float — start_time of the segment this question relates to>,
  "transcript_segment_end": <float — end_time of the segment this question relates to>,
  "concept": "<brief concept name>",
  "difficulty": "Easy" | "Medium" | "Hard" | "Tough",
  "type": "single_choice" | "multiple_selection",
  "question": "<question text>",
  "options": [
    {{"id": "opt_a", "text": "<option text>"}},
    {{"id": "opt_b", "text": "<option text>"}},
    {{"id": "opt_c", "text": "<option text>"}},
    {{"id": "opt_d", "text": "<option text>"}}
  ],
  "correct_answer": "<opt_id>" or ["<opt_id>", "<opt_id>"],
  "correct_feedback": "<brief explanation of why this is correct>",
  "incorrect_feedback": "<brief explanation of the correct answer>"
}}

Generate the JSON array now:"""


# ---------------------------------------------------------------------------
# JSON extraction helpers
# ---------------------------------------------------------------------------

def _extract_json_array(raw: str) -> list[dict[str, Any]]:
    """Extract the first JSON array from the model response."""
    # Strip markdown code fences if present
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text, flags=re.IGNORECASE)
    text = text.strip()

    # Try to parse directly
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Find the first [...] block
    match = re.search(r"(\[.*\])", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(1))
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract a JSON array from Gemini response. Raw response: {raw[:500]!r}")


# ---------------------------------------------------------------------------
# Per-intervention deterministic validation (SPEC §23)
# ---------------------------------------------------------------------------

def _validate_single_intervention(
    raw: dict[str, Any],
    lecture: Lecture,
    index: int,
) -> Intervention | None:
    """Validate and coerce one raw dict into an Intervention, or return None."""
    try:
        # Normalise id
        intv_id = str(raw.get("id") or f"gen_{index + 1}")

        # trigger_time must be within lecture duration
        trigger_time = float(raw["trigger_time"])
        if not (0 <= trigger_time <= lecture.duration_seconds):
            logger.warning("Dropping intervention %s: trigger_time %.2f outside duration", intv_id, trigger_time)
            return None

        # transcript_segment check: relocation allowed within same segment (SPEC §25)
        seg_start = raw.get("transcript_segment_start")
        seg_end = raw.get("transcript_segment_end")
        if seg_start is not None and seg_end is not None:
            seg_start = float(seg_start)
            seg_end = float(seg_end)
            if not (seg_start <= trigger_time <= seg_end):
                # Relocate: snap to midpoint of segment if still within duration
                mid = (seg_start + seg_end) / 2.0
                if 0 <= mid <= lecture.duration_seconds:
                    logger.info(
                        "Relocating intervention %s trigger %.2f → %.2f (segment midpoint)",
                        intv_id, trigger_time, mid,
                    )
                    trigger_time = mid
                else:
                    logger.warning("Dropping intervention %s: cannot relocate within segment", intv_id)
                    return None

        # Parse type
        raw_type = str(raw.get("type", "")).lower()
        if raw_type == "single_choice":
            intv_type = InterventionType.SINGLE_CHOICE
        elif raw_type in ("multiple_selection", "multiple_choice"):
            intv_type = InterventionType.MULTIPLE_SELECTION
        else:
            logger.warning("Dropping intervention %s: unknown type %r", intv_id, raw_type)
            return None

        # Parse difficulty
        raw_diff = str(raw.get("difficulty", "Medium")).strip().capitalize()
        try:
            difficulty = Difficulty(raw_diff)
        except ValueError:
            difficulty = Difficulty.MEDIUM

        # Parse options
        raw_options = raw.get("options", [])
        if not isinstance(raw_options, list) or len(raw_options) < 2:
            logger.warning("Dropping intervention %s: fewer than 2 options", intv_id)
            return None
        options = [Option(id=str(o["id"]), text=str(o["text"])) for o in raw_options]
        option_ids = [o.id for o in options]
        if len(option_ids) != len(set(option_ids)):
            logger.warning("Dropping intervention %s: duplicate option IDs", intv_id)
            return None

        # Parse correct_answer
        correct_answer = raw.get("correct_answer")
        if intv_type == InterventionType.SINGLE_CHOICE:
            if not isinstance(correct_answer, str) or correct_answer not in option_ids:
                logger.warning("Dropping intervention %s: invalid single_choice correct_answer", intv_id)
                return None
        else:  # multiple_selection
            if isinstance(correct_answer, str):
                correct_answer = [correct_answer]
            if not isinstance(correct_answer, list) or len(correct_answer) < 1:
                logger.warning("Dropping intervention %s: empty multiple_selection correct_answer", intv_id)
                return None
            correct_answer = list(dict.fromkeys(correct_answer))  # dedup, preserve order
            for ans in correct_answer:
                if ans not in option_ids:
                    logger.warning("Dropping intervention %s: correct_answer %r not in options", intv_id, ans)
                    return None

        concept = str(raw.get("concept") or "Key concept")[:100]
        question = str(raw.get("question") or "What did you just learn?")
        correct_feedback = str(raw.get("correct_feedback") or "Correct!")
        incorrect_feedback = str(raw.get("incorrect_feedback") or "Review the material and try again.")

        return Intervention(
            id=intv_id,
            trigger_time=round(trigger_time, 2),
            concept=concept,
            difficulty=difficulty,
            type=intv_type,
            question=question,
            options=options,
            correct_answer=correct_answer,
            correct_feedback=correct_feedback,
            incorrect_feedback=incorrect_feedback,
        )

    except Exception as exc:
        logger.warning("Dropping intervention at index %d due to error: %s", index, exc)
        return None


# ---------------------------------------------------------------------------
# Spacing / conflict resolution (SPEC §26)
# ---------------------------------------------------------------------------

def _apply_spacing_rules(
    candidates: list[Intervention],
    min_trigger_gap: float,
    tolerance: float,
) -> list[Intervention]:
    """Drop later conflicting interventions; earlier one always wins (SPEC §26)."""
    accepted: list[Intervention] = []
    for intv in candidates:
        conflict = False
        for prev in accepted:
            gap = abs(intv.trigger_time - prev.trigger_time)
            if gap < min_trigger_gap:
                logger.info(
                    "Dropping intervention %s (trigger %.2f): too close to %s (trigger %.2f, gap %.2f < %.2f)",
                    intv.id, intv.trigger_time, prev.id, prev.trigger_time, gap, min_trigger_gap,
                )
                conflict = True
                break
        if not conflict:
            accepted.append(intv)
    return accepted


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class GeminiAuthoringError(Exception):
    """Raised when Gemini authoring fails after all retries."""


def generate_interventions_with_gemini(lecture: Lecture, api_key: str) -> list[Intervention]:
    """Call Gemini to generate content-relevant interventions for *lecture*.

    Follows the SPEC §18 pipeline:
    1. Build prompt with full transcript + metadata
    2. Call Gemini (retry once on failure, SPEC §22)
    3. Parse JSON
    4. Validate each intervention independently (SPEC §23)
    5. Drop invalid interventions
    6. Apply spacing/conflict resolution (SPEC §26)
    7. Cap at MAX_INTERVENTIONS keeping original Gemini order (SPEC §27)
    8. Fail if zero valid interventions remain (SPEC §24)

    Returns the validated list of Intervention objects.
    Raises GeminiAuthoringError on unrecoverable failures.
    """
    from google import genai  # deferred to avoid import cost when key is absent
    from google.genai import types

    client = genai.Client(api_key=api_key, http_options={"timeout": 30000})
    prompt = _build_prompt(lecture)

    raw_text: str | None = None
    last_error: Exception | None = None

    # SPEC §22: one retry on complete generation failure
    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            raw_text = getattr(response, "text", None)
            if raw_text:
                break
        except Exception as exc:
            last_error = exc
            logger.warning("Gemini call attempt %d failed: %s", attempt + 1, exc)

    if not raw_text:
        raise GeminiAuthoringError(
            f"Gemini generation failed after 2 attempts. Last error: {last_error}"
        )

    # Parse JSON
    try:
        raw_items: list[dict[str, Any]] = _extract_json_array(raw_text)
    except ValueError as exc:
        raise GeminiAuthoringError(f"Failed to parse Gemini response as JSON array: {exc}") from exc

    logger.info("Gemini returned %d raw intervention candidates", len(raw_items))

    # Validate each individually, drop invalid (SPEC §23)
    valid: list[Intervention] = []
    for i, item in enumerate(raw_items):
        intv = _validate_single_intervention(item, lecture, i)
        if intv is not None:
            valid.append(intv)

    logger.info("%d interventions passed individual validation", len(valid))

    # Sort by trigger_time (preserve Gemini order for equal timestamps)
    valid.sort(key=lambda x: x.trigger_time)

    # Apply spacing / conflict resolution (SPEC §26)
    spaced = _apply_spacing_rules(
        valid,
        min_trigger_gap=lecture.timing_config.min_trigger_gap,
        tolerance=lecture.timing_config.tolerance,
    )

    logger.info("%d interventions after spacing rules", len(spaced))

    # Cap at MAX_INTERVENTIONS (SPEC §27/invariant 21)
    final = spaced[:MAX_INTERVENTIONS]

    # SPEC §24: zero valid interventions = generation failure
    if not final:
        raise GeminiAuthoringError(
            "Zero valid interventions remained after validation and spacing. "
            "Gemini output was not usable for this lecture."
        )

    return final
