"""Deterministic flash recall evaluator (Server-side, no LLM calls).

Implements §5.1 of Game-Loop V0.4:
- Format A: Exact option ID match
- Format B: Normalized string match with Unicode NFKC, lowercase, strip trailing punctuation,
  collapsed internal whitespace, preserving symbols/code syntax (e.g. C++, !=, ls -la).
- Single attempt only. Skips the remediation ladder.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Sequence


_TRAILING_PUNCTUATION_PATTERN = re.compile(r"[\.,!\?;:]+$")
_WHITESPACE_COLLAPSE_PATTERN = re.compile(r"\s+")


def normalize_flash_recall_string(text: str) -> str:
    """Normalize user input or accepted answer according to §5.1 Format B pipeline.
    
    1. Apply Unicode normalization ('NFKC').
    2. Convert to lowercase.
    3. Strip trailing punctuation (. , ! ? ; :).
    4. Collapse internal contiguous whitespace to a single space.
    5. Preserve symbols and code syntax (e.g. C++, !=, ls -la remain intact).
    """
    if not text:
        return ""

    # Step 1: Unicode normalization (NFKC)
    normalized = unicodedata.normalize("NFKC", text)

    # Step 2: Convert to lowercase
    normalized = normalized.lower()

    # Step 3: Strip surrounding whitespace then trailing punctuation
    normalized = normalized.strip()
    normalized = _TRAILING_PUNCTUATION_PATTERN.sub("", normalized).strip()

    # Step 4: Collapse internal whitespace to a single space
    normalized = _WHITESPACE_COLLAPSE_PATTERN.sub(" ", normalized)

    return normalized


def evaluate_flash_recall(
    submitted_answer: str,
    *,
    has_options: bool = False,
    correct_answer: str | None = None,
    accepted_answers: Sequence[str] | None = None,
) -> tuple[bool, str]:
    """Evaluate a flash recall answer server-side without calling Gemini.
    
    Returns (is_correct, feedback).
    """
    # Format A: Option-based
    if has_options:
        sub = submitted_answer.strip()
        expected = (correct_answer or "").strip()
        is_correct = (sub == expected)
        feedback = "Correct! Well remembered." if is_correct else "Incorrect option selected."
        return is_correct, feedback

    # Format B: Normalized string match
    normalized_sub = normalize_flash_recall_string(submitted_answer)
    if not normalized_sub:
        return False, "Empty answer submitted."

    # Candidates from accepted_answers and correct_answer
    candidates: list[str] = []
    if accepted_answers:
        candidates.extend(accepted_answers)
    if correct_answer and correct_answer not in candidates:
        candidates.append(correct_answer)

    normalized_candidates = [normalize_flash_recall_string(c) for c in candidates if c]

    is_correct = normalized_sub in normalized_candidates
    feedback = "Correct! Quick and accurate recall." if is_correct else "Incorrect recall."
    return is_correct, feedback
