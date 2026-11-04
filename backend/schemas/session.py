"""Runtime Session Pydantic schemas."""

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class InterventionStateEnum(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EVALUATING = "EVALUATING"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    BYPASSED = "BYPASSED"


class InterventionPolicy(str, Enum):
    SKIPPABLE = "skippable"
    REQUIRED = "required"
    REQUIRED_WITH_RETRY = "required_with_retry"


class ResumptionPolicy(str, Enum):
    IMMEDIATE_OPTIMISTIC = "immediate_optimistic"
    WAIT_FOR_RESULT = "wait_for_result"


class SubmissionStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    FAILED = "failed"


class InterventionSessionState(BaseModel):
    id: str
    trigger_time: float
    state: InterventionStateEnum
    policy: InterventionPolicy = InterventionPolicy.SKIPPABLE



class SessionState(BaseModel):
    session_id: str
    lecture_id: str
    version: int
    client_id: str | None = None
    external_user_id: str | None = None
    active_intervention_id: str | None = None
    interventions: list[InterventionSessionState]


class CreateSessionRequest(BaseModel):
    lecture_id: str
    client_id: str | None = "default_client"
    external_user_id: str | None = "default_learner"
    tier_override: int | None = None


class ActivateInterventionRequest(BaseModel):
    intervention_id: str
    playback_position: float
    expected_version: int | None = None


class SubmitAnswerRequest(BaseModel):
    intervention_id: str
    idempotency_key: str = Field(..., min_length=1)
    answer: str | list[str]
    expected_version: int | None = None


class SyncPlaybackRequest(BaseModel):
    playback_position: float
    expected_version: int | None = None


class EvaluationResult(BaseModel):
    is_correct: bool
    feedback: str
    submitted_answer: str | list[str]
    session_state: SessionState
    # V0.2 inquiry and adaptive feedback additions
    tier: int = 1
    mastery_delta: float = 0.0
    suggested_next_tier: int = 1


class ActiveInterventionPayload(BaseModel):
    id: str
    trigger_time: float
    concept: str
    difficulty: str
    type: str
    question: str
    options: list[dict[str, str]]
    session_state: SessionState
    # V0.2 inquiry and sandbox fields
    tier: int = 1
    hypothesis_prompt: str | None = None
    hypothesis_options: list[dict[str, str]] = Field(default_factory=list)
    sandbox_config: dict[str, Any] | None = None
    # V0.3 policy and rubric fields
    policy: InterventionPolicy = InterventionPolicy.SKIPPABLE
    resumption_policy: ResumptionPolicy = ResumptionPolicy.IMMEDIATE_OPTIMISTIC
    rubric: dict[str, Any] | None = None



class LearnerProfile(BaseModel):
    user_id: str
    client_id: str = "default_client"
    concept_mastery: dict[str, float] = Field(default_factory=dict)
    streak: int = 0
    friction_index: float = 1.0
    total_interventions: int = 0
    total_correct: int = 0


class InquiryExperimentSubmission(BaseModel):
    intervention_id: str
    idempotency_key: str = Field(..., min_length=1)
    hypothesis_answer: str | list[str] | None = None
    code_submitted: str | None = None
    test_results: list[dict[str, Any]] = Field(default_factory=list)
    passed_tests: bool = False
    reflection: str | None = None
    expected_version: int | None = None


class B2BTelemetryEvent(BaseModel):
    event_type: str
    client_id: str
    user_id: str
    session_id: str
    lecture_id: str
    intervention_id: str | None = None
    timestamp: float
    payload: dict[str, Any] = Field(default_factory=dict)


class SkipInterventionRequest(BaseModel):
    intervention_id: str | None = None
    reason: str | None = "learner_choice"
    expected_version: int | None = None



class OpenEndedSubmissionRequest(BaseModel):
    intervention_id: str
    idempotency_key: str = Field(..., min_length=1)
    user_answer: str = Field(..., min_length=1)
    expected_version: int | None = None


class OpenEndedSubmissionResponse(BaseModel):
    submission_id: str
    status: SubmissionStatus
    resumption_policy: ResumptionPolicy
    message: str
    session_state: SessionState


class SubmissionStatusResponse(BaseModel):
    submission_id: str
    status: SubmissionStatus
    ai_score: float | None = None
    is_correct: bool | None = None
    formative_feedback: str | None = None
    misconceptions_detected: list[str] = Field(default_factory=list)
    self_assessed: bool = False
    evaluation_latency_ms: int | None = None
    reference_rubric: dict[str, Any] | None = None


class SelfAssessRequest(BaseModel):
    self_assessed_correct: bool
    expected_version: int | None = None

