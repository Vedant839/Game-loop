"""V0.2 backend tests: LearnerService, adaptive tier selection, and inquiry experiment submission."""

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas.lecture import (
    Difficulty,
    Intervention,
    InterventionType,
    Lecture,
    Option,
    SandboxConfig,
    SandboxEnvironment,
    TestCase,
)
from backend.schemas.session import InquiryExperimentSubmission
from backend.services.learner_service import LearnerService
from backend.services.lecture_service import LectureService
from backend.services.session_service import SessionService

client = TestClient(app)


# ---------------------------------------------------------------------------
# LearnerService
# ---------------------------------------------------------------------------


def test_learner_service_creates_profile_on_first_access() -> None:
    svc = LearnerService()
    profile = svc.get_or_create_profile("test_client", "user_abc")
    assert profile.user_id == "user_abc"
    assert profile.client_id == "test_client"
    assert profile.streak == 0
    assert profile.total_interventions == 0


def test_learner_service_tier_defaults_to_two_for_fresh_learner() -> None:
    svc = LearnerService()
    profile = svc.get_or_create_profile("test_client", "user_new")
    tier = svc.resolve_intervention_tier(profile, "some_concept")
    assert tier == 2


def test_learner_service_tier_drops_to_one_on_repeated_failures() -> None:
    svc = LearnerService()
    svc.get_or_create_profile("c", "u_struggle")
    # Simulate two consecutive failures to push streak to -2
    svc.record_attempt("c", "u_struggle", "concept_x", is_correct=False, tier=2)
    svc.record_attempt("c", "u_struggle", "concept_x", is_correct=False, tier=2)
    profile = svc.get_or_create_profile("c", "u_struggle")
    tier = svc.resolve_intervention_tier(profile, "concept_x")
    assert tier == 1


def test_learner_service_tier_rises_to_three_on_consecutive_correct() -> None:
    svc = LearnerService()
    svc.get_or_create_profile("c", "u_expert")
    svc.record_attempt("c", "u_expert", "concept_y", is_correct=True, tier=2)
    svc.record_attempt("c", "u_expert", "concept_y", is_correct=True, tier=2)
    profile = svc.get_or_create_profile("c", "u_expert")
    tier = svc.resolve_intervention_tier(profile, "concept_y")
    assert tier == 3


def test_v03_engine_streak_characterization() -> None:
    """Characterization test: V0.3 difficulty engine streak signed dynamics remain unchanged."""
    svc = LearnerService()
    svc.get_or_create_profile("client_char", "user_char")

    # Correct increments
    svc.record_attempt("client_char", "user_char", "concept_a", is_correct=True, tier=2)
    assert svc.get_or_create_profile("client_char", "user_char").streak == 1

    svc.record_attempt("client_char", "user_char", "concept_a", is_correct=True, tier=2)
    assert svc.get_or_create_profile("client_char", "user_char").streak == 2

    svc.record_attempt("client_char", "user_char", "concept_a", is_correct=True, tier=2)
    assert svc.get_or_create_profile("client_char", "user_char").streak == 3

    # Incorrect resets to negative and decrements
    svc.record_attempt("client_char", "user_char", "concept_a", is_correct=False, tier=2)
    assert svc.get_or_create_profile("client_char", "user_char").streak == -1

    svc.record_attempt("client_char", "user_char", "concept_a", is_correct=False, tier=2)
    assert svc.get_or_create_profile("client_char", "user_char").streak == -2


def test_learner_service_tier_override_bypasses_heuristic() -> None:
    svc = LearnerService()
    profile = svc.get_or_create_profile("c", "u_override")
    # Force Tier 1 even though fresh learner would get Tier 2
    tier = svc.resolve_intervention_tier(profile, "concept_z", tier_override=1)
    assert tier == 1


def test_learner_service_mastery_increases_on_correct() -> None:
    svc = LearnerService()
    delta, next_tier = svc.record_attempt("c", "u_mastery", "concept", is_correct=True, tier=2)
    assert delta > 0
    profile = svc.get_or_create_profile("c", "u_mastery")
    assert profile.concept_mastery["concept"] > 0.5


def test_learner_service_mastery_decreases_on_incorrect() -> None:
    svc = LearnerService()
    delta, _ = svc.record_attempt("c", "u_drops", "concept", is_correct=False, tier=2)
    assert delta < 0
    profile = svc.get_or_create_profile("c", "u_drops")
    assert profile.concept_mastery["concept"] < 0.5


# ---------------------------------------------------------------------------
# Inquiry lecture schema validation
# ---------------------------------------------------------------------------


def test_predict_and_verify_intervention_validates_with_sandbox() -> None:
    intv = Intervention(
        id="py_test_1",
        trigger_time=50.0,
        concept="List References",
        difficulty=Difficulty.MEDIUM,
        type=InterventionType.PREDICT_AND_VERIFY,
        question="What does print(a) output?",
        sandbox_config=SandboxConfig(
            environment=SandboxEnvironment.PYTHON_WASM,
            initial_code="a = [1,2,3]\nb = a\nb.append(4)\nprint(a)",
            test_cases=[TestCase(name="output check", expected_output="[1, 2, 3, 4]")],
        ),
        correct_feedback="Correct!",
        incorrect_feedback="Not quite.",
    )
    assert intv.type == InterventionType.PREDICT_AND_VERIFY
    assert intv.sandbox_config is not None
    assert len(intv.sandbox_config.test_cases) == 1


def test_inquiry_sandbox_intervention_requires_sandbox_or_variants() -> None:
    with pytest.raises(ValueError, match="must provide either sandbox_config or tier variants"):
        Intervention(
            id="bad_inquiry",
            trigger_time=60.0,
            concept="Concept",
            difficulty=Difficulty.HARD,
            type=InterventionType.INQUIRY_SANDBOX,
            question="Do something.",
            correct_feedback="Good.",
            incorrect_feedback="Bad.",
        )


# ---------------------------------------------------------------------------
# Session experiment submission
# ---------------------------------------------------------------------------


def _make_inquiry_lecture() -> Lecture:
    return Lecture(
        id="test_inquiry_lecture",
        title="Test Inquiry",
        subject="CS",
        grade="Grade 10",
        duration_seconds=300.0,
        video_url="/media/math_sample_lecture.mp4",
        timing_config={"min_trigger_gap": 30.0, "tolerance": 3.0},
        transcript=[
            {"start_time": 0.0, "end_time": 60.0, "text": "Intro to lists in Python."},
            {"start_time": 60.0, "end_time": 120.0, "text": "Reference semantics and loops."},
            {"start_time": 120.0, "end_time": 300.0, "text": "List comprehensions and functions."},
        ],
        interventions=[
            Intervention(
                id="inq_1",
                trigger_time=65.0,
                concept="List Reference Semantics",
                difficulty=Difficulty.MEDIUM,
                type=InterventionType.PREDICT_AND_VERIFY,
                question="What does print(a) output after b = a; b.append(4)?",
                sandbox_config=SandboxConfig(
                    environment=SandboxEnvironment.PYTHON_WASM,
                    initial_code="a = [1,2,3]\nb = a\nb.append(4)\nprint(a)",
                    test_cases=[
                        TestCase(name="Output is correct", expected_output="[1, 2, 3, 4]")
                    ],
                    hints=["b = a does NOT copy the list."],
                ),
                correct_feedback="Correct! b and a reference the same list.",
                incorrect_feedback="Not quite — in Python, b = a makes b an alias, not a copy.",
            )
        ],
    )


def test_experiment_submission_passes_when_tests_pass() -> None:
    inquiry_lecture = _make_inquiry_lecture()
    lecture_service = LectureService()
    lecture_service.set_runtime_lecture(inquiry_lecture)
    session_service = SessionService(lecture_service=lecture_service)

    state = session_service.create_session("test_inquiry_lecture")
    session_id = state.session_id

    session_service.activate_intervention(
        session_id=session_id,
        intervention_id="inq_1",
        playback_position=65.0,
    )

    result = session_service.submit_experiment(
        session_id=session_id,
        submission=InquiryExperimentSubmission(
            intervention_id="inq_1",
            idempotency_key="exp_key_1",
            passed_tests=True,
            code_submitted="a = [1,2,3]\nb = a\nb.append(4)\nprint(a)",
        ),
    )
    assert result.is_correct
    assert "Correct" in result.feedback
    assert result.mastery_delta > 0


def test_experiment_submission_fails_when_tests_fail() -> None:
    inquiry_lecture = _make_inquiry_lecture()
    lecture_service = LectureService()
    lecture_service.set_runtime_lecture(inquiry_lecture)
    session_service = SessionService(lecture_service=lecture_service)

    state = session_service.create_session("test_inquiry_lecture")
    session_id = state.session_id

    session_service.activate_intervention(
        session_id=session_id,
        intervention_id="inq_1",
        playback_position=65.0,
    )

    result = session_service.submit_experiment(
        session_id=session_id,
        submission=InquiryExperimentSubmission(
            intervention_id="inq_1",
            idempotency_key="exp_key_2",
            passed_tests=False,
            code_submitted="print([1,2,3])",
        ),
    )
    assert not result.is_correct
    assert result.mastery_delta < 0


def test_experiment_submission_idempotent() -> None:
    inquiry_lecture = _make_inquiry_lecture()
    lecture_service = LectureService()
    lecture_service.set_runtime_lecture(inquiry_lecture)
    session_service = SessionService(lecture_service=lecture_service)

    state = session_service.create_session("test_inquiry_lecture")
    session_id = state.session_id

    session_service.activate_intervention(
        session_id=session_id,
        intervention_id="inq_1",
        playback_position=65.0,
    )

    sub = InquiryExperimentSubmission(
        intervention_id="inq_1",
        idempotency_key="exp_key_idem",
        passed_tests=True,
        code_submitted="a=[1,2,3];b=a;b.append(4);print(a)",
    )
    first = session_service.submit_experiment(session_id=session_id, submission=sub)
    second = session_service.submit_experiment(session_id=session_id, submission=sub)
    assert first == second
    assert second.session_state.version == first.session_state.version


def test_api_experiment_endpoint_integration() -> None:
    inquiry_lecture = _make_inquiry_lecture()
    from backend.services.lecture_service import get_lecture_service
    get_lecture_service().set_runtime_lecture(inquiry_lecture)
    from backend.services.session_service import get_session_service
    state = get_session_service().create_session("test_inquiry_lecture")
    session_id = state.session_id

    get_session_service().activate_intervention(
        session_id=session_id,
        intervention_id="inq_1",
        playback_position=65.0,
    )

    res = client.post(
        f"/api/sessions/{session_id}/experiment",
        json={
            "intervention_id": "inq_1",
            "idempotency_key": "api_exp_key",
            "passed_tests": True,
            "code_submitted": "print([1,2,3,4])",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_correct"] is True
    assert data["tier"] >= 1


def test_api_learner_profile_endpoint(creator_token_factory) -> None:
    res = client.get(
        "/api/learners/test_corp/learner_42",
        headers=creator_token_factory("test_corp"),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["user_id"] == "learner_42"
    assert data["client_id"] == "test_corp"


def test_python_basics_lecture_loads_and_validates() -> None:
    svc = LectureService()
    lecture = svc.get_lecture("python_basics_lists")
    assert lecture is not None
    assert lecture.id == "python_basics_lists"
    types = [i.type.value for i in lecture.interventions]
    assert "predict_and_verify" in types
    assert "inquiry_sandbox" in types
