"""Lecture, Transcript, and Intervention Pydantic schemas and deterministic validation rules."""

from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class Difficulty(str, Enum):
    EASY = "Easy"
    MEDIUM = "Medium"
    HARD = "Hard"
    TOUGH = "Tough"


class InterventionType(str, Enum):
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_SELECTION = "multiple_selection"
    PREDICT_AND_VERIFY = "predict_and_verify"
    INQUIRY_SANDBOX = "inquiry_sandbox"


class SandboxEnvironment(str, Enum):
    PYTHON_WASM = "python_wasm"
    JAVASCRIPT_EVAL = "javascript_eval"
    PARAMETRIC_SIM = "parametric_sim"


class TestCase(BaseModel):
    name: str = Field(..., min_length=1)
    input_data: str | None = None
    expected_output: str = Field(..., min_length=1)


class SandboxConfig(BaseModel):
    environment: SandboxEnvironment = SandboxEnvironment.PYTHON_WASM
    initial_code: str = Field(default="")
    solution_code: str | None = None
    test_cases: list[TestCase] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)


class Option(BaseModel):
    id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)


class InterventionVariant(BaseModel):
    tier: int = Field(..., ge=1, le=3)
    prompt: str = Field(..., min_length=1)
    hypothesis_prompt: str | None = None
    hypothesis_options: list[Option] = Field(default_factory=list)
    sandbox_config: SandboxConfig | None = None
    correct_answer: str | list[str] | None = None
    correct_feedback: str = Field(..., min_length=1)
    incorrect_feedback: str = Field(..., min_length=1)


class Intervention(BaseModel):
    id: str = Field(..., min_length=1)
    trigger_time: float = Field(..., ge=0.0)
    concept: str = Field(..., min_length=1)
    difficulty: Difficulty
    type: InterventionType
    question: str = Field(..., min_length=1)
    options: list[Option] = Field(default_factory=list)
    correct_answer: str | list[str] | None = None
    correct_feedback: str = Field(default="Great job!")
    incorrect_feedback: str = Field(default="Not quite right.")
    # V0.2 Inquiry & Sandbox Extensions
    sandbox_config: SandboxConfig | None = None
    hypothesis_prompt: str | None = None
    hypothesis_options: list[Option] = Field(default_factory=list)
    variants: dict[int, InterventionVariant] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_intervention(self) -> "Intervention":
        if self.type in (InterventionType.SINGLE_CHOICE, InterventionType.MULTIPLE_SELECTION):
            if len(self.options) < 2:
                raise ValueError(f"Intervention '{self.id}' requires at least 2 options.")
            option_ids = [opt.id for opt in self.options]
            if len(option_ids) != len(set(option_ids)):
                raise ValueError(f"Intervention '{self.id}' has duplicate option IDs.")

            if self.type == InterventionType.SINGLE_CHOICE:
                if not isinstance(self.correct_answer, str):
                    raise ValueError(
                        f"Intervention '{self.id}' is single_choice but correct_answer is not a string."
                    )
                if self.correct_answer not in option_ids:
                    raise ValueError(
                        f"Intervention '{self.id}' correct_answer '{self.correct_answer}' is not in options."
                    )
            elif self.type == InterventionType.MULTIPLE_SELECTION:
                if not isinstance(self.correct_answer, list) or len(self.correct_answer) == 0:
                    raise ValueError(
                        f"Intervention '{self.id}' is multiple_selection but correct_answer is empty or not a list."
                    )
                if len(self.correct_answer) != len(set(self.correct_answer)):
                    raise ValueError(
                        f"Intervention '{self.id}' correct_answer contains duplicate option IDs."
                    )
                for ans in self.correct_answer:
                    if not isinstance(ans, str) or ans not in option_ids:
                        raise ValueError(
                            f"Intervention '{self.id}' correct_answer item '{ans}' is not in options."
                        )
        elif self.type in (InterventionType.PREDICT_AND_VERIFY, InterventionType.INQUIRY_SANDBOX):
            if not self.sandbox_config and not self.variants:
                raise ValueError(
                    f"Inquiry intervention '{self.id}' must provide either sandbox_config or tier variants."
                )
        return self


class TranscriptSegment(BaseModel):
    start_time: float = Field(..., ge=0.0)
    end_time: float = Field(..., gt=0.0)
    text: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_segment_times(self) -> "TranscriptSegment":
        if self.start_time >= self.end_time:
            raise ValueError(
                f"Transcript segment start_time ({self.start_time}) must be strictly less than end_time ({self.end_time})."
            )
        return self


class TimingConfig(BaseModel):
    min_trigger_gap: float = Field(default=15.0, gt=0.0)
    tolerance: float = Field(default=2.0, gt=0.0)

    @model_validator(mode="after")
    def validate_timing_invariant(self) -> "TimingConfig":
        # SPEC.md Section 26: 2 * tolerance < MIN_TRIGGER_GAP
        if 2 * self.tolerance >= self.min_trigger_gap:
            raise ValueError(
                f"Timing configuration invariant violated: 2 * tolerance ({2 * self.tolerance}) "
                f"must be strictly less than min_trigger_gap ({self.min_trigger_gap})."
            )
        return self


class Lecture(BaseModel):
    id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    subject: str = Field(..., min_length=1)
    grade: str = Field(..., min_length=1)
    duration_seconds: float = Field(..., gt=0.0)
    video_url: str = Field(..., min_length=1)
    timing_config: TimingConfig = Field(default_factory=TimingConfig)
    transcript: list[TranscriptSegment] = Field(default_factory=list)
    interventions: list[Intervention] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_lecture_constraints(self) -> "Lecture":
        # Check transcript bounds
        for i, seg in enumerate(self.transcript):
            if seg.end_time > self.duration_seconds:
                raise ValueError(
                    f"Transcript segment {i} end_time ({seg.end_time}) exceeds lecture duration ({self.duration_seconds})."
                )

        # Check maximum interventions count (SPEC Section 27)
        if len(self.interventions) > 6:
            raise ValueError(
                f"Lecture contains {len(self.interventions)} interventions, exceeding maximum allowed of 6."
            )

        # Check intervention timestamps and trigger spacing
        prev_trigger_time: float | None = None
        for i, intv in enumerate(self.interventions):
            if intv.trigger_time > self.duration_seconds:
                raise ValueError(
                    f"Intervention '{intv.id}' trigger_time ({intv.trigger_time}) exceeds lecture duration ({self.duration_seconds})."
                )

            if prev_trigger_time is not None:
                gap = intv.trigger_time - prev_trigger_time
                if gap < self.timing_config.min_trigger_gap:
                    raise ValueError(
                        f"Intervention '{intv.id}' trigger_time ({intv.trigger_time}) gap ({gap:.2f}s) "
                        f"from previous intervention ({prev_trigger_time:.2f}s) is less than min_trigger_gap ({self.timing_config.min_trigger_gap}s)."
                    )
            prev_trigger_time = intv.trigger_time

        return self


class LectureSummary(BaseModel):
    id: str
    title: str
    subject: str
    grade: str
    duration_seconds: float
    video_url: str
    intervention_count: int
