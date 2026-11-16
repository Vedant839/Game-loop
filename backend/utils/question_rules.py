"""Deterministic question quality rules for V0.4 Content Understanding Layer.

These rules are applied AFTER Gemini generates a checkpoint proposal and BEFORE
the checkpoint critic call. They are purely pattern-based and require no LLM.

Rules:
  R1 - Banned question stems (surface-recall, 'mentioned in lecture', etc.)
  R2 - Banned option text (all/none of the above, etc.)
  R3 - Structural integrity (min options, unique correct answer present, no duplicates)
  R4 - Concept binding (concept_id exists, at least one evidence item)

Each rule returns a RuleResult. A checkpoint that fails any rule is DROPPED.
The rule engine logs the first failing reason per checkpoint.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Normalisation (same pipeline used in flash-recall grading and evidence
# verification so a single import can re-use it)
# ---------------------------------------------------------------------------


def normalize_text(text: str) -> str:
    """NFKC → lowercase → collapse whitespace → strip trailing punctuation."""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"[.,!?;:]+$", "", text)
    return text


# ---------------------------------------------------------------------------
# R1: Banned question stems
# ---------------------------------------------------------------------------
# Patterns on NORMALIZED question text.  Any match → drop.
# Keep patterns narrow enough to avoid false positives on good questions.
_BANNED_STEM_PATTERNS: list[re.Pattern[str]] = [
    # "mentioned in the lecture/video"
    re.compile(r"\bmentioned\s+in\s+the\s+(lecture|video|tutorial|presentation|talk)\b"),
    # "was said" / "was mentioned" / "was discussed"
    re.compile(r"\bwas\s+(said|mentioned|discussed|shown|used|called)\b"),
    # "did the instructor (say|mention|call|use|show)"
    re.compile(r"\bdid\s+the\s+(instructor|speaker|presenter|teacher)\s+(say|mention|call|use|show|name)\b"),
    # "according to the (lecture|video|instructor|speaker)"
    re.compile(r"\baccording\s+to\s+the\s+(lecture|video|instructor|speaker|presenter|teacher)\b"),
    # "which of the following was (mentioned|discussed|used|shown)"
    re.compile(r"\bwhich\s+of\s+the\s+following\s+was\s+(mentioned|discussed|used|shown|covered|presented)\b"),
    # "as stated in", "as explained in", "as described in"
    re.compile(r"\bas\s+(stated|explained|described|shown|mentioned)\s+in\b"),
    # "in the video/lecture, ..."
    re.compile(r"\bin\s+the\s+(video|lecture|tutorial|presentation),?\s+"),
    # "the instructor said/mentioned/called/used"
    re.compile(r"\bthe\s+(instructor|speaker|presenter|teacher)\s+(said|mentioned|called|used|showed)\b"),
]


def _fails_r1(question_normalized: str) -> str | None:
    """Return the matched pattern text if the question fails R1, else None."""
    for pattern in _BANNED_STEM_PATTERNS:
        m = pattern.search(question_normalized)
        if m:
            return m.group(0)
    return None


# ---------------------------------------------------------------------------
# R2: Banned option text
# ---------------------------------------------------------------------------
_BANNED_OPTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\ball\s+of\s+the\s+above\b"),
    re.compile(r"\bnone\s+of\s+the\s+above\b"),
    re.compile(r"\bboth\s+a\s+and\s+b\b"),
    re.compile(r"\bboth\s+of\s+the\s+above\b"),
    re.compile(r"\bnone\s+of\s+these\b"),
    re.compile(r"\ball\s+of\s+these\b"),
]


def _fails_r2(options_normalized: list[str]) -> str | None:
    """Return the matched option text if any option fails R2, else None."""
    for opt in options_normalized:
        for pattern in _BANNED_OPTION_PATTERNS:
            if pattern.search(opt):
                return opt
    return None


# ---------------------------------------------------------------------------
# R3: Structural integrity
# ---------------------------------------------------------------------------


@dataclass
class R3Result:
    passed: bool
    reason: str = ""


def _check_r3(
    options: list[str],
    correct_answer: str | list[str] | None,
    intervention_type: str,
) -> R3Result:
    """Check structural validity rules."""
    # Flash recall checkpoints (accepted_answers list) skip option-based rules
    if intervention_type == "flash_recall":
        if not correct_answer:
            return R3Result(False, "flash_recall has no accepted_answers")
        return R3Result(True)

    # For choice-based types, options are required
    if not options:
        return R3Result(False, "no options provided")
    if len(options) < 2:
        return R3Result(False, f"only {len(options)} option(s), need at least 2")

    # Duplicate options
    seen: set[str] = set()
    for opt in options:
        norm = normalize_text(opt)
        if norm in seen:
            return R3Result(False, f"duplicate option: '{opt}'")
        seen.add(norm)

    # Correct answer must be present
    if correct_answer is None:
        return R3Result(False, "correct_answer is None")

    if isinstance(correct_answer, list):
        # multiple_selection
        if len(correct_answer) == 0:
            return R3Result(False, "correct_answer list is empty")
        for ans in correct_answer:
            if ans not in options:
                return R3Result(False, f"correct_answer '{ans}' not in options")
    else:
        # single_choice or option-id based flash recall
        if correct_answer not in options:
            # For ID-based: options are option dicts, correct_answer is an option ID
            # We allow this check to be called with either raw text or IDs;
            # callers must pass the correct_answer normalised for the type.
            return R3Result(False, f"correct_answer '{correct_answer}' not in options")

    # Exactly one correct answer for single_choice
    if intervention_type == "single_choice" and isinstance(correct_answer, list):
        return R3Result(False, "single_choice must have a string correct_answer, not a list")

    return R3Result(True)


# ---------------------------------------------------------------------------
# R4: Concept binding
# ---------------------------------------------------------------------------


def _fails_r4(concept_id: str | None, evidence: list[dict] | None) -> str | None:
    """Return failure reason if concept binding is missing, else None."""
    if not concept_id:
        return "missing concept_id"
    if not evidence:
        return "no evidence items"
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class RuleCheckResult:
    passed: bool
    failed_rule: str = ""
    reason: str = ""


def check_checkpoint(
    *,
    question: str,
    options: list[str],
    correct_answer: str | list[str] | None,
    intervention_type: str = "single_choice",
    concept_id: str | None = None,
    evidence: list[dict] | None = None,
    skip_r4: bool = False,
) -> RuleCheckResult:
    """Run all four rules against a checkpoint.

    Args:
        question: The question text (unnormalized).
        options: Option texts (unnormalized) for choice types; option IDs for ID-based types.
        correct_answer: Correct option text, option ID, list of option IDs, or list of accepted strings.
        intervention_type: 'single_choice', 'multiple_selection', 'flash_recall', etc.
        concept_id: The concept_id from the concept map (required for R4).
        evidence: Evidence items for the concept (required for R4).
        skip_r4: Set True for legacy (generator_version 1) checkpoints where concept binding
                 was not produced.

    Returns:
        RuleCheckResult with passed=True if all rules pass.
    """
    q_norm = normalize_text(question)

    # R1
    banned_stem = _fails_r1(q_norm)
    if banned_stem is not None:
        return RuleCheckResult(False, "R1", f"banned stem: '{banned_stem}'")

    # R2 (only for choice-based)
    if options:
        opts_norm = [normalize_text(o) for o in options]
        banned_opt = _fails_r2(opts_norm)
        if banned_opt is not None:
            return RuleCheckResult(False, "R2", f"banned option text: '{banned_opt}'")

    # R3
    r3 = _check_r3(options, correct_answer, intervention_type)
    if not r3.passed:
        return RuleCheckResult(False, "R3", r3.reason)

    # R4
    if not skip_r4:
        r4_fail = _fails_r4(concept_id, evidence)
        if r4_fail is not None:
            return RuleCheckResult(False, "R4", r4_fail)

    return RuleCheckResult(True)


def filter_checkpoints(
    checkpoints: list[dict],
    *,
    skip_r4: bool = False,
) -> tuple[list[dict], list[dict]]:
    """Filter a list of checkpoint dicts. Returns (kept, dropped).

    Each dict is expected to have keys: question, options (list of option text
    or IDs), correct_answer, type, and optionally concept_id and evidence.
    The function does NOT modify the input dicts.
    """
    kept: list[dict] = []
    dropped: list[dict] = []

    for chk in checkpoints:
        result = check_checkpoint(
            question=chk.get("question", ""),
            options=chk.get("options", []),
            correct_answer=chk.get("correct_answer"),
            intervention_type=chk.get("type", "single_choice"),
            concept_id=chk.get("concept_id"),
            evidence=chk.get("evidence"),
            skip_r4=skip_r4,
        )
        if result.passed:
            kept.append(chk)
        else:
            dropped.append({**chk, "_drop_rule": result.failed_rule, "_drop_reason": result.reason})

    return kept, dropped

