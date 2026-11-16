"""P1.5.1: Concept-first generation, question rules, and critic tests.

All tests use recorded fixtures. No live Gemini calls.
See: tests/fixtures/ingest/mary_*.json and linux_*.json
"""

from __future__ import annotations

import json
import pathlib
import pytest

from backend.utils.question_rules import (
    normalize_text,
    check_checkpoint,
    filter_checkpoints,
)
from backend.services.concept_service import (
    label_window,
    label_windows,
    suitability_verdict,
    verify_transcript_evidence,
    assign_confidence,
    EvidenceItem,
    parse_gemini_concepts,
    build_concept_extraction_prompt,
)
from backend.services.checkpoint_critic import (
    build_critic_prompt,
    _parse_critic_response,
    apply_critic_verdicts,
)

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "ingest"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_fixture(name: str) -> dict:
    with open(FIXTURES / name) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------


class TestNormalizeText:
    def test_lowercases(self):
        assert normalize_text("HELLO World") == "hello world"

    def test_nfkc_normalization(self):
        # Ligature → decomposed
        assert "fi" in normalize_text("\ufb01le")  # ﬁle → file

    def test_strips_trailing_punctuation(self):
        assert normalize_text("hello.") == "hello"
        assert normalize_text("hello!?;:") == "hello"

    def test_preserves_internal_symbols(self):
        norm = normalize_text("C++ and != and ls -la")
        assert "c++" in norm
        assert "!=" in norm
        assert "ls -la" in norm

    def test_collapses_whitespace(self):
        assert normalize_text("hello   world") == "hello world"


# ---------------------------------------------------------------------------
# R1: Banned question stems
# ---------------------------------------------------------------------------


class TestR1BannedStems:
    @pytest.mark.parametrize("question,should_fail", [
        # Should fail (banned stem)
        ("Which of the following was mentioned in the lecture?", True),
        ("According to the instructor, what name was used?", True),
        ("What did the instructor say about return values?", True),
        ("As stated in the video, what does ls do?", True),
        ("In the lecture, what does chmod do?", True),
        ("Did the instructor mention mary?", True),
        ("What was discussed in the tutorial?", True),
        # Should pass (legitimate questions)
        ("What does the return statement do in Python?", False),
        ("Which of the following correctly describes function scope?", False),
        ("When a function uses the global keyword, what changes?", False),
        ("How does the pipe operator connect two commands?", False),
        ("Which chmod mode grants execute permission to the owner only?", False),
        ("What is the difference between > and >> in shell redirection?", False),
    ])
    def test_stem_detection(self, question: str, should_fail: bool):
        result = check_checkpoint(
            question=question,
            options=["a", "b"],
            correct_answer="a",
            skip_r4=True,
        )
        if should_fail:
            assert not result.passed, f"Should have failed R1: {question!r}"
            assert result.failed_rule == "R1"
        else:
            # R3 might fail (single-letter options), but should not fail R1
            assert result.failed_rule != "R1", f"Should not fail R1: {question!r}"

    def test_mary_fixture_all_rejected(self):
        """The Mary baseline checkpoints must ALL fail R1 (banned stems)."""
        baseline = _load_fixture("mary_baseline.json")
        bad_checkpoints = baseline["checkpoints"]

        for chk in bad_checkpoints:
            opts = chk.get("options", [])
            result = check_checkpoint(
                question=chk["question"],
                options=opts,
                correct_answer=chk.get("correct_answer"),
                skip_r4=True,
            )
            assert not result.passed, (
                f"Expected FAIL for banned question: {chk['question']!r}, "
                f"got result={result}"
            )
            # All three baseline checkpoints have banned stems
            assert result.failed_rule == "R1", (
                f"Expected R1 failure, got {result.failed_rule}: {result.reason}"
            )


# ---------------------------------------------------------------------------
# R2: Banned option text
# ---------------------------------------------------------------------------


class TestR2BannedOptions:
    @pytest.mark.parametrize("option", [
        "All of the above",
        "None of the above",
        "Both A and B",
        "Both of the above",
        "None of these",
        "All of these",
    ])
    def test_banned_option_rejected(self, option: str):
        result = check_checkpoint(
            question="What does the return keyword do?",
            options=[option, "It sends a value back to the caller"],
            correct_answer="It sends a value back to the caller",
            skip_r4=True,
        )
        assert not result.passed
        assert result.failed_rule == "R2"

    def test_good_options_pass(self):
        result = check_checkpoint(
            question="What does the return keyword do in Python?",
            options=[
                "It sends a value back to the caller",
                "It terminates the program",
                "It prints output to the console",
                "It imports a module",
            ],
            correct_answer="It sends a value back to the caller",
            skip_r4=True,
        )
        assert result.passed or result.failed_rule not in ("R1", "R2")


# ---------------------------------------------------------------------------
# R3: Structural integrity
# ---------------------------------------------------------------------------


class TestR3Structural:
    def test_no_options_fails(self):
        result = check_checkpoint(
            question="What does scope mean?",
            options=[],
            correct_answer="A",
            skip_r4=True,
        )
        assert not result.passed
        assert result.failed_rule == "R3"

    def test_one_option_fails(self):
        result = check_checkpoint(
            question="What does scope mean?",
            options=["only option"],
            correct_answer="only option",
            skip_r4=True,
        )
        assert not result.passed
        assert result.failed_rule == "R3"

    def test_duplicate_options_fail(self):
        result = check_checkpoint(
            question="What does scope mean?",
            options=["local variable", "local variable", "global variable"],
            correct_answer="local variable",
            skip_r4=True,
        )
        assert not result.passed
        assert result.failed_rule == "R3"

    def test_missing_correct_answer_fails(self):
        result = check_checkpoint(
            question="What does scope mean?",
            options=["local", "global", "dynamic"],
            correct_answer=None,
            skip_r4=True,
        )
        assert not result.passed
        assert result.failed_rule == "R3"

    def test_valid_checkpoint_passes_r3(self):
        result = check_checkpoint(
            question="What does function scope mean in Python?",
            options=["Variables inside a function are local by default",
                     "Variables inside a function are global by default",
                     "Scope only applies to class definitions"],
            correct_answer="Variables inside a function are local by default",
            skip_r4=True,
        )
        assert result.passed


# ---------------------------------------------------------------------------
# R4: Concept binding
# ---------------------------------------------------------------------------


class TestR4ConceptBinding:
    def test_missing_concept_id_fails(self):
        result = check_checkpoint(
            question="What does scope mean?",
            options=["a", "b", "c"],
            correct_answer="a",
            concept_id=None,
            evidence=[{"source": "transcript", "quote": "variables inside a function"}],
            skip_r4=False,
        )
        assert not result.passed
        assert result.failed_rule == "R4"

    def test_missing_evidence_fails(self):
        result = check_checkpoint(
            question="What does scope mean?",
            options=["a", "b", "c"],
            correct_answer="a",
            concept_id="concept_001",
            evidence=[],
            skip_r4=False,
        )
        assert not result.passed
        assert result.failed_rule == "R4"

    def test_bound_checkpoint_passes(self):
        result = check_checkpoint(
            question="What does function scope mean in Python?",
            options=["Variables inside a function are local by default",
                     "Variables are always global",
                     "Scope does not exist in Python"],
            correct_answer="Variables inside a function are local by default",
            concept_id="concept_005",
            evidence=[{"source": "transcript", "quote": "variables inside a function are local by default"}],
            skip_r4=False,
        )
        assert result.passed


# ---------------------------------------------------------------------------
# filter_checkpoints
# ---------------------------------------------------------------------------


class TestFilterCheckpoints:
    def test_filters_banned_and_keeps_good(self):
        checkpoints = [
            {
                "id": "bad",
                "question": "Which of the following was mentioned in the lecture?",
                "options": ["return", "print", "lambda", "scope"],
                "correct_answer": "return",
                "type": "single_choice",
            },
            {
                "id": "good",
                "question": "What does the return keyword send back to the caller?",
                "options": ["A value from the function", "A new function call",
                             "The module name", "Nothing"],
                "correct_answer": "A value from the function",
                "type": "single_choice",
            },
        ]
        kept, dropped = filter_checkpoints(checkpoints, skip_r4=True)
        assert len(kept) == 1
        assert kept[0]["id"] == "good"
        assert len(dropped) == 1
        assert dropped[0]["id"] == "bad"
        assert dropped[0]["_drop_rule"] == "R1"


# ---------------------------------------------------------------------------
# Transcript window labelling
# ---------------------------------------------------------------------------


class TestWindowLabelling:
    def test_narrated_window_is_strong(self):
        segments = [
            {"start_time": 0.0, "end_time": 30.0,
             "text": "The Linux file system is organized as a hierarchical tree starting from the root directory represented by a forward slash the ls command lists directory contents."},
        ]
        result = label_window(segments, 0.0, 30.0)
        assert result == "strong"

    def test_music_only_window_is_weak(self):
        segments = [
            {"start_time": 0.0, "end_time": 30.0, "text": "[Music]"},
        ]
        result = label_window(segments, 0.0, 30.0)
        assert result == "weak"

    def test_empty_window_is_weak(self):
        result = label_window([], 0.0, 30.0)
        assert result == "weak"

    def test_mary_low_density_window_is_weak(self):
        """Mary fixture first 30s has very few words - should be weak."""
        fixture = _load_fixture("mary_transcript.json")
        segs = fixture["transcript"]
        # First segment is 30s and has ~6 words
        result = label_window(segs, 0.0, 30.0)
        assert result == "weak"

    def test_linux_narration_window_is_strong(self):
        """Linux fixture has dense narration - should be strong."""
        fixture = _load_fixture("linux_transcript.json")
        segs = fixture["transcript"]
        result = label_window(segs, 0.0, 60.0)
        assert result == "strong"

    def test_suitability_verdict_good(self):
        windows = [{"verdict": "strong"}] * 8 + [{"verdict": "weak"}] * 2
        assert suitability_verdict(windows) == "good"

    def test_suitability_verdict_mixed(self):
        windows = [{"verdict": "strong"}] * 5 + [{"verdict": "weak"}] * 5
        assert suitability_verdict(windows) == "mixed"

    def test_suitability_verdict_limited(self):
        windows = [{"verdict": "strong"}] * 2 + [{"verdict": "weak"}] * 8
        assert suitability_verdict(windows) == "limited"

    def test_mary_suitability_is_limited_or_mixed(self):
        """The Mary lecture has thin narration; suitability should be limited or mixed."""
        fixture = _load_fixture("mary_transcript.json")
        segs = fixture["transcript"]
        windows = label_windows(segs, fixture["duration_seconds"])
        verdict = suitability_verdict(windows)
        assert verdict in ("limited", "mixed"), f"Expected limited or mixed, got {verdict}"

    def test_linux_suitability_is_good_or_mixed(self):
        fixture = _load_fixture("linux_transcript.json")
        segs = fixture["transcript"]
        windows = label_windows(segs, fixture["duration_seconds"])
        verdict = suitability_verdict(windows)
        assert verdict in ("good", "mixed"), f"Expected good or mixed, got {verdict}"


# ---------------------------------------------------------------------------
# Evidence verification
# ---------------------------------------------------------------------------


class TestEvidenceVerification:
    def test_verbatim_quote_in_transcript_verified(self):
        segments = [
            {"start_time": 180.0, "end_time": 240.0,
             "text": "Using return, the function sends a value back to the caller."},
        ]
        assert verify_transcript_evidence(
            quote="the function sends a value back to the caller",
            concept_start=180.0,
            concept_end=240.0,
            segments=segments,
        )

    def test_nonexistent_quote_not_verified(self):
        segments = [
            {"start_time": 0.0, "end_time": 30.0, "text": "Hello world."},
        ]
        assert not verify_transcript_evidence(
            quote="the function sends a value back",
            concept_start=0.0,
            concept_end=30.0,
            segments=segments,
        )

    def test_short_quote_not_verified(self):
        segments = [
            {"start_time": 0.0, "end_time": 30.0, "text": "return value"},
        ]
        # "return" is only 1 word and <15 chars → too short
        assert not verify_transcript_evidence(
            quote="return",
            concept_start=0.0,
            concept_end=30.0,
            segments=segments,
        )

    def test_window_padding_allows_nearby_segments(self):
        # Segment is 5s before concept window start; padding=10s so should work
        segments = [
            {"start_time": 85.0, "end_time": 115.0,
             "text": "default parameters let you define a fallback value"},
        ]
        assert verify_transcript_evidence(
            quote="default parameters let you define a fallback value",
            concept_start=100.0,
            concept_end=130.0,
            segments=segments,
        )


# ---------------------------------------------------------------------------
# Confidence assignment
# ---------------------------------------------------------------------------


class TestConfidenceAssignment:
    def _strong_window(self) -> list[dict]:
        return [{"start_s": 0.0, "end_s": 30.0, "verdict": "strong"}]

    def _weak_window(self) -> list[dict]:
        return [{"start_s": 0.0, "end_s": 30.0, "verdict": "weak"}]

    def test_transcript_in_strong_window_is_high(self):
        item = EvidenceItem(source="transcript", quote="q", start_s=5.0, end_s=25.0, verified=True)
        assert assign_confidence([item], self._strong_window(), 5.0, 25.0) == "high"

    def test_transcript_in_weak_window_is_medium(self):
        item = EvidenceItem(source="transcript", quote="q", start_s=5.0, end_s=25.0, verified=True)
        assert assign_confidence([item], self._weak_window(), 5.0, 25.0) == "medium"

    def test_two_independent_sources_is_high(self):
        t = EvidenceItem(source="transcript", quote="q", start_s=5.0, end_s=25.0, verified=True)
        v = EvidenceItem(source="visual", quote="", ref="v_001", start_s=5.0, end_s=25.0, verified=True)
        # Even if windows are weak, two independent sources → high
        assert assign_confidence([t, v], self._weak_window(), 5.0, 25.0) == "high"

    def test_one_visual_is_medium(self):
        v = EvidenceItem(source="visual", quote="", ref="v_001", start_s=5.0, end_s=25.0, verified=True)
        assert assign_confidence([v], self._strong_window(), 5.0, 25.0) == "medium"

    def test_no_verified_evidence_is_low(self):
        item = EvidenceItem(source="transcript", quote="q", start_s=5.0, end_s=25.0, verified=False)
        assert assign_confidence([item], self._strong_window(), 5.0, 25.0) == "low"


# ---------------------------------------------------------------------------
# Critic
# ---------------------------------------------------------------------------


class TestCritic:
    def test_parse_keep_verdict(self):
        raw = '{"verdicts": [{"id": "chk_1", "verdict": "keep", "reason": ""}]}'
        verdicts = _parse_critic_response(raw, ["chk_1"])
        assert verdicts["chk_1"] == "keep"

    def test_parse_drop_verdict_valid_reason(self):
        raw = '{"verdicts": [{"id": "chk_1", "verdict": "drop", "reason": "incidental_detail"}]}'
        verdicts = _parse_critic_response(raw, ["chk_1"])
        assert verdicts["chk_1"] == "drop"

    def test_invalid_drop_reason_becomes_keep(self):
        raw = '{"verdicts": [{"id": "chk_1", "verdict": "drop", "reason": "made_up_reason"}]}'
        verdicts = _parse_critic_response(raw, ["chk_1"])
        # Invalid reason → conservative keep
        assert verdicts["chk_1"] == "keep"

    def test_parse_failure_keeps_all(self):
        verdicts = _parse_critic_response("not json at all", ["chk_1", "chk_2"])
        assert verdicts["chk_1"] == "keep"
        assert verdicts["chk_2"] == "keep"

    def test_missing_id_defaults_to_keep(self):
        raw = '{"verdicts": []}'
        verdicts = _parse_critic_response(raw, ["chk_1"])
        assert verdicts["chk_1"] == "keep"

    def test_apply_verdicts_splits_correctly(self):
        checkpoints = [
            {"id": "keep_me", "question": "?"},
            {"id": "drop_me", "question": "?"},
        ]
        verdicts = {"keep_me": "keep", "drop_me": "drop"}
        kept, dropped = apply_critic_verdicts(checkpoints, verdicts)
        assert len(kept) == 1
        assert kept[0]["id"] == "keep_me"
        assert len(dropped) == 1
        assert dropped[0]["id"] == "drop_me"

    def test_critic_cannot_raise_confidence(self):
        """Verifying the design: apply_critic_verdicts only drops, never modifies kept items."""
        checkpoints = [{"id": "c1", "confidence": "medium", "question": "Q?"}]
        verdicts = {"c1": "keep"}
        kept, _ = apply_critic_verdicts(checkpoints, verdicts)
        # The kept checkpoint is unmodified
        assert kept[0]["confidence"] == "medium"

    def test_build_critic_prompt_fences_data(self):
        checkpoints = [
            {
                "id": "c1",
                "concept_name": "Return values",
                "concept_description": "Functions can send values back to callers",
                "evidence_quotes": ["the function sends a value back to the caller"],
                "question": "What does return do?",
                "options": ["Sends value back", "Prints output"],
                "correct_answer": "Sends value back",
            }
        ]
        prompt = build_critic_prompt(checkpoints)
        assert "CHECKPOINT_START" in prompt
        assert "CHECKPOINT_END" in prompt
        assert "DATA" in prompt  # fencing instruction


# ---------------------------------------------------------------------------
# Integration: Mary fixture → zero banned patterns
# ---------------------------------------------------------------------------


class TestMaryFixtureRegression:
    """Criterion 57 & 68: Mary fixture must yield zero banned patterns
    when the question rules filter runs on the baseline checkpoints."""

    def test_mary_baseline_has_zero_passing_checkpoints(self):
        """All Mary baseline (bad) checkpoints must be rejected by question rules."""
        baseline = _load_fixture("mary_baseline.json")
        checkpoints = baseline["checkpoints"]

        # Convert baseline format to filter_checkpoints format
        filter_input = [
            {
                "id": chk["id"],
                "question": chk["question"],
                "options": chk.get("options", []),
                "correct_answer": chk.get("correct_answer"),
                "type": "single_choice",
            }
            for chk in checkpoints
        ]

        kept, dropped = filter_checkpoints(filter_input, skip_r4=True)
        assert len(kept) == 0, (
            f"Expected 0 checkpoints to pass for Mary fixture, but {len(kept)} passed: "
            + str([k["question"] for k in kept])
        )
        assert len(dropped) == len(checkpoints)
        # All failures should be R1
        for d in dropped:
            assert d["_drop_rule"] == "R1", (
                f"Expected R1 failure, got {d['_drop_rule']}: {d['question']!r}"
            )

