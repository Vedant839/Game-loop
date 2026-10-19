"""Gemini authoring pipeline for lecture intervention generation.

Upgraded for V0.2:
Gemini dynamically generates diverse interactive learning interventions:
- predict_and_verify (Hypothesize -> Sandboxed experimentation -> Verification)
- inquiry_sandbox (Hands-on coding / command testing against test cases)
- single_choice / multiple_selection (Conceptual reasoning checks)

The proposed intervention set is validated and filtered deterministically.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from backend.schemas.lecture import (
    Difficulty,
    Intervention,
    InterventionType,
    Lecture,
    Option,
    SandboxConfig,
    SandboxEnvironment,
    TestCase,
    TimingConfig,
)

logger = logging.getLogger(__name__)

SUPPORTED_GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash",
]


# ---------------------------------------------------------------------------
# Pydantic response schema sent to Gemini as response_format
# ---------------------------------------------------------------------------


class _GeneratedOption(BaseModel):
    id: str = Field(description="Short unique ID for this option, e.g. 'opt_a' or 'h_a'")
    text: str = Field(description="Option text shown to the student")


class _GeneratedTestCase(BaseModel):
    name: str = Field(description="Name or description of what this test case checks")
    expected_output: str = Field(description="Exact or substring expected in stdout")


class _GeneratedSandboxConfig(BaseModel):
    environment: str = Field(
        default="python_wasm",
        description="One of: python_wasm, javascript_eval",
    )
    initial_code: str = Field(
        default="",
        description="Initial code or terminal simulation script for the student to run or complete",
    )
    test_cases: list[_GeneratedTestCase] = Field(
        default_factory=list,
        description="List of automated test case expectations",
    )
    hints: list[str] = Field(
        default_factory=list,
        description="1-2 helpful hints if student is stuck",
    )


class _GeneratedIntervention(BaseModel):
    trigger_time: float = Field(
        description=(
            "Exact timestamp (seconds) within the lecture where playback should pause. "
            "Must be at least 5 seconds before the end of the lecture and must respect "
            "the minimum gap between successive interventions."
        )
    )
    concept: str = Field(
        description="Short label (3-8 words) identifying the concept being explored"
    )
    difficulty: str = Field(description="One of: Easy, Medium, Hard, Tough")
    type: str = Field(
        description="One of: predict_and_verify, inquiry_sandbox, single_choice, multiple_selection"
    )
    question: str = Field(
        description="The primary question or challenge prompt posed to the student"
    )
    hypothesis_prompt: str | None = Field(
        default=None,
        description="For predict_and_verify: question asking student to predict what will happen before running code",
    )
    hypothesis_options: list[_GeneratedOption] = Field(
        default_factory=list,
        description="For predict_and_verify: 2 to 4 prediction options for the student's hypothesis",
    )
    sandbox_config: _GeneratedSandboxConfig | None = Field(
        default=None,
        description="For predict_and_verify and inquiry_sandbox: executable code sandbox configuration",
    )
    options: list[_GeneratedOption] = Field(
        default_factory=list,
        description="Answer options for single_choice/multiple_selection (empty if predict_and_verify)",
    )
    correct_answer: str | list[str] | None = Field(
        default=None,
        description="The correct option ID(s) for multiple choice or hypothesis prediction",
    )
    correct_feedback: str = Field(
        description="Feedback explaining why the result or answer is correct"
    )
    incorrect_feedback: str = Field(
        description="Feedback addressing the likely misconception"
    )


class _GeminiInterventionSet(BaseModel):
    interventions: list[_GeneratedIntervention] = Field(
        description="Proposed interventions ordered by trigger_time ascending"
    )


# ---------------------------------------------------------------------------
# Authoring helper
# ---------------------------------------------------------------------------


def _build_prompt(lecture: Lecture, target_count: int, max_count: int) -> str:
    """Build the prompt that is sent to Gemini as the authoring contract."""
    timing = lecture.timing_config

    transcript_lines = []
    for seg in lecture.transcript:
        transcript_lines.append(
            f"  [{seg.start_time:.1f}s – {seg.end_time:.1f}s] {seg.text}"
        )
    transcript_text = (
        "\n".join(transcript_lines) if transcript_lines else "  (no transcript provided)"
    )

    max_trigger = lecture.duration_seconds - 5.0

    return (
        "You are an expert learning systems designer creating deeply engaging, inquiry-driven learning "
        "interventions for an interactive video learning engine. Your goal is to eliminate passive watching "
        "and force the learner to think, hypothesize, experiment, and verify.\n\n"
        "## Lecture Metadata\n"
        f"- Title: {lecture.title}\n"
        f"- Subject: {lecture.subject}\n"
        f"- Grade: {lecture.grade}\n"
        f"- Duration: {lecture.duration_seconds:.0f} seconds\n\n"
        "## Full Timestamped Transcript\n"
        f"{transcript_text}\n\n"
        "## Core Pedagogical Requirement: Diversity Beyond MCQs\n"
        "Do NOT just generate multiple-choice questions! Traditional 4-option quizzes encourage passive guessing. "
        "Instead, generate a balanced set of interventions with at least ONE 'predict_and_verify' or 'inquiry_sandbox' "
        "intervention where students experiment with code, scripts, or terminal logic.\n\n"
        "### Supported Intervention Types:\n"
        "1. 'predict_and_verify' (HIGH PRIORITY):\n"
        "   - Give the student a code snippet or simulated command sequence in `sandbox_config.initial_code`.\n"
        "   - Ask them in `hypothesis_prompt` to predict what will happen before running it.\n"
        "   - Provide 2-4 plausible hypothesis predictions in `hypothesis_options` (with correct_answer matching the true prediction).\n"
        "   - Provide `sandbox_config` with runnable code (`python_wasm` or `javascript_eval`) and `test_cases` checking the output.\n"
        "2. 'inquiry_sandbox':\n"
        "   - Give the student a hands-on coding or terminal challenge.\n"
        "   - Include starter code in `sandbox_config.initial_code` and automated `test_cases` checking expected outputs.\n"
        "3. 'single_choice' or 'multiple_selection':\n"
        "   - Use for deep conceptual reasoning, trade-off analysis, or diagnosing a misconception.\n"
        "   - Options must be plausible, thought-provoking explanations, not trivial recall.\n\n"
        "## Authoring Rules:\n"
        f"1. Generate between {target_count} and {max_count} interventions.\n"
        "2. Each intervention must be directly grounded in the lecture content above.\n"
        "3. Trigger times rules:\n"
        f"   - Each trigger_time must be >= 0 and <= {max_trigger:.1f} seconds.\n"
        f"   - The minimum gap between any two trigger_times is {timing.min_trigger_gap} seconds.\n"
        "   - Interventions must be listed in strictly ascending trigger_time order.\n"
        "4. Feedback must teach: correct feedback explains the underlying mechanism; incorrect feedback addresses the cognitive error.\n\n"
        "Generate the diverse interventions now as structured JSON."
    )


def _validate_and_filter(
    raw: list[_GeneratedIntervention],
    timing_config: TimingConfig,
    duration_seconds: float,
    max_count: int,
) -> list[Intervention]:
    """Deterministically validate and filter Gemini-proposed interventions."""
    valid: list[Intervention] = []
    last_trigger: float | None = None
    seen_ids: set[str] = set()

    for i, raw_intv in enumerate(raw):
        generated_id = f"gen_int_{i + 1}"

        # Map type
        try:
            intv_type = InterventionType(raw_intv.type)
        except ValueError:
            logger.warning("Dropping intervention %d: unknown type '%s'", i, raw_intv.type)
            continue

        # Map difficulty
        try:
            difficulty = Difficulty(raw_intv.difficulty)
        except ValueError:
            logger.warning(
                "Dropping intervention %d: unknown difficulty '%s'", i, raw_intv.difficulty
            )
            continue

        # Validate trigger time bounds
        t = raw_intv.trigger_time
        if t < 0 or t > duration_seconds:
            logger.warning(
                "Dropping intervention %d: trigger_time %.2f out of bounds [0, %.2f]",
                i,
                t,
                duration_seconds,
            )
            continue

        # Validate spacing
        if last_trigger is not None and (t - last_trigger) < timing_config.min_trigger_gap:
            logger.warning(
                "Dropping intervention %d: trigger_time %.2f too close to previous %.2f "
                "(gap=%.2f < min=%.2f)",
                i,
                t,
                last_trigger,
                t - last_trigger,
                timing_config.min_trigger_gap,
            )
            continue

        # Options processing
        options: list[Option] = []
        for opt in raw_intv.options:
            options.append(Option(id=opt.id, text=opt.text))

        hypo_options: list[Option] = []
        for opt in raw_intv.hypothesis_options:
            hypo_options.append(Option(id=opt.id, text=opt.text))

        # Sandbox config processing
        sandbox_config: SandboxConfig | None = None
        if raw_intv.sandbox_config:
            env_str = raw_intv.sandbox_config.environment
            env = (
                SandboxEnvironment.JAVASCRIPT_EVAL
                if env_str == "javascript_eval"
                else SandboxEnvironment.PYTHON_WASM
            )
            test_cases = [
                TestCase(name=tc.name, expected_output=tc.expected_output)
                for tc in raw_intv.sandbox_config.test_cases
            ]
            sandbox_config = SandboxConfig(
                environment=env,
                initial_code=raw_intv.sandbox_config.initial_code or "",
                test_cases=test_cases,
                hints=raw_intv.sandbox_config.hints or [],
            )

        # For predict_and_verify or inquiry_sandbox, ensure sandbox_config exists
        if intv_type in (InterventionType.PREDICT_AND_VERIFY, InterventionType.INQUIRY_SANDBOX):
            if not sandbox_config:
                sandbox_config = SandboxConfig(
                    environment=SandboxEnvironment.PYTHON_WASM,
                    initial_code="# Write and test your solution here:\nprint('Running test...')",
                    test_cases=[TestCase(name="Execution test", expected_output="test")],
                    hints=["Review the transcript segment for the syntax."],
                )

        # Ensure unique generated IDs
        unique_id = generated_id
        suffix = 0
        while unique_id in seen_ids:
            suffix += 1
            unique_id = f"{generated_id}_{suffix}"
        seen_ids.add(unique_id)

        try:
            intv = Intervention(
                id=unique_id,
                trigger_time=round(t, 2),
                concept=raw_intv.concept,
                difficulty=difficulty,
                type=intv_type,
                question=raw_intv.question,
                options=options,
                hypothesis_prompt=raw_intv.hypothesis_prompt,
                hypothesis_options=hypo_options,
                sandbox_config=sandbox_config,
                correct_answer=raw_intv.correct_answer,
                correct_feedback=raw_intv.correct_feedback,
                incorrect_feedback=raw_intv.incorrect_feedback,
            )
        except ValidationError as exc:
            logger.warning("Dropping intervention %d: schema validation failed: %s", i, exc)
            continue

        valid.append(intv)
        last_trigger = t

        if len(valid) >= max_count:
            break

    return valid


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_interventions_with_gemini(
    lecture: Lecture,
    api_key: str,
    target_count: int = 4,
    max_count: int = 6,
    models: list[str] | None = None,
) -> Lecture:
    """Call Gemini to generate lecture-specific diverse interventions."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key, http_options={"timeout": 45000})

    prompt = _build_prompt(lecture, target_count, max_count)
    response_schema = _GeminiInterventionSet.model_json_schema()
    models_to_try = models or SUPPORTED_GEMINI_MODELS

    def _call(model_name: str) -> str | None:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )
        text = getattr(response, "text", None)
        if text:
            return text
        return None

    raw_text: str | None = None
    last_exc: Exception | None = None

    for model_name in models_to_try:
        for attempt in range(1, 3):
            try:
                raw_text = _call(model_name)
                if raw_text:
                    break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(
                    "Gemini call (%s) attempt %d failed: %s", model_name, attempt, exc
                )
                if attempt == 1:
                    time.sleep(1.5)
        if raw_text:
            break

    if not raw_text:
        raise RuntimeError(
            f"Gemini generation failed after retries. Last error: {last_exc}"
        )

    try:
        data: Any = json.loads(raw_text)
        intervention_set = _GeminiInterventionSet.model_validate(data)
    except Exception as exc:
        raise RuntimeError(f"Failed to parse Gemini response as JSON: {exc}") from exc

    valid_interventions = _validate_and_filter(
        raw=intervention_set.interventions,
        timing_config=lecture.timing_config,
        duration_seconds=lecture.duration_seconds,
        max_count=max_count,
    )

    if not valid_interventions:
        raise RuntimeError(
            "Gemini generation produced zero valid interventions after validation."
        )

    logger.info(
        "Gemini generated %d valid diverse interventions for lecture '%s'",
        len(valid_interventions),
        lecture.id,
    )

    generated = lecture.model_copy()
    generated.interventions = valid_interventions
    return generated
