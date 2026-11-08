"""Integration tests for V0.3 skip endpoint, open-ended semantic grading, and telemetry."""

import asyncio
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.schemas.lecture import (
    Difficulty,
    Intervention,
    InterventionPolicy,
    InterventionType,
    Lecture,
    Option,
    ResumptionPolicy,
    RubricConfig,
    RubricMisconception,
    TimingConfig,
)
from backend.services.lecture_service import get_lecture_service


@pytest.fixture
def test_client():
    return TestClient(app)


@pytest.fixture
def lecture_with_open_ended():
    intv_skippable_mcq = Intervention(
        id="q_skip",
        trigger_time=10.0,
        concept="geometry.parallel",
        difficulty=Difficulty.EASY,
        type=InterventionType.SINGLE_CHOICE,
        question="Are parallel lines intersecting?",
        options=[Option(id="no", text="No"), Option(id="yes", text="Yes")],
        correct_answer="no",
        policy=InterventionPolicy.SKIPPABLE,
    )
    intv_required_open = Intervention(
        id="q_open_req",
        trigger_time=25.0,
        concept="geometry.proofs",
        difficulty=Difficulty.HARD,
        type=InterventionType.OPEN_ENDED,
        question="Explain why alternate interior angles are equal when two parallel lines are cut by a transversal.",
        policy=InterventionPolicy.REQUIRED,
        resumption_policy=ResumptionPolicy.IMMEDIATE_OPTIMISTIC,
        rubric=RubricConfig(
            key_concepts=["transversal", "parallel lines", "rotation"],
            misconceptions=[
                RubricMisconception(
                    tag="assume_perpendicular",
                    description="Assumes transversal is perpendicular",
                    remediation="Remind learner transversal does not have to be perpendicular",
                )
            ],
            reference_answer="Because rotating 180 degrees around the midpoint of the transversal segment maps one angle directly onto the other.",
            passing_score=0.6,
        ),
    )
    lecture = Lecture(
        id="v03_proofs_lecture",
        title="Geometric Proofs",
        subject="Mathematics",
        grade="Grade 9",
        duration_seconds=90.0,
        video_url="/media/proofs.mp4",
        timing_config=TimingConfig(min_trigger_gap=10.0, tolerance=1.5),
        interventions=[intv_skippable_mcq, intv_required_open],
    )
    lecture_svc = get_lecture_service()
    lecture_svc.set_runtime_lecture(lecture)
    return lecture


def test_skip_endpoint_success_and_forbidden(test_client, lecture_with_open_ended):
    # 1. Create session
    resp = test_client.post(
        "/api/sessions",
        json={"lecture_id": lecture_with_open_ended.id, "client_id": "test_lms", "external_user_id": "student_1"},
    )
    assert resp.status_code == 201
    session_id = resp.json()["session_id"]

    # 2. Activate skippable intervention
    test_client.post(
        f"/api/sessions/{session_id}/activate",
        json={"intervention_id": "q_skip", "playback_position": 10.0},
    )

    # 3. Skip skippable intervention -> 200 OK
    skip_resp = test_client.post(
        f"/api/sessions/{session_id}/interventions/q_skip/skip",
        json={"reason": "too_easy"},
    )
    assert skip_resp.status_code == 200
    state = skip_resp.json()
    q_state = next(i for i in state["interventions"] if i["id"] == "q_skip")
    assert q_state["state"] == "SKIPPED"

    # 4. Attempting to skip REQUIRED intervention -> 403 Forbidden
    test_client.post(
        f"/api/sessions/{session_id}/activate",
        json={"intervention_id": "q_open_req", "playback_position": 25.0},
    )
    forbid_resp = test_client.post(
        f"/api/sessions/{session_id}/interventions/q_open_req/skip",
        json={"reason": "want_to_skip"},
    )
    assert forbid_resp.status_code == 403
    assert "cannot be skipped" in forbid_resp.json()["detail"]


def test_open_ended_submission_and_evaluation(test_client, lecture_with_open_ended):
    # Create session
    resp = test_client.post(
        "/api/sessions",
        json={"lecture_id": lecture_with_open_ended.id, "client_id": "test_lms", "external_user_id": "student_2"},
    )
    session_id = resp.json()["session_id"]

    # Activate open-ended intervention
    test_client.post(
        f"/api/sessions/{session_id}/activate",
        json={"intervention_id": "q_open_req", "playback_position": 25.0},
    )

    # Submit open-ended answer
    sub_resp = test_client.post(
        f"/api/sessions/{session_id}/submissions/open-ended",
        json={
            "intervention_id": "q_open_req",
            "idempotency_key": "sub_open_1",
            "user_answer": "When parallel lines are intersected by a transversal, the rotation maps the alternate interior angles.",
        },
    )
    assert sub_resp.status_code == 202
    sub_data = sub_resp.json()
    assert sub_data["status"] == "pending"
    assert sub_data["resumption_policy"] == "immediate_optimistic"
    submission_id = sub_data["submission_id"]

    # Check status
    status_resp = test_client.get(f"/api/sessions/{session_id}/submissions/{submission_id}")
    assert status_resp.status_code == 200
    stat_data = status_resp.json()
    assert stat_data["submission_id"] == submission_id


def test_self_assess_flow(test_client, lecture_with_open_ended):
    # Create session
    resp = test_client.post(
        "/api/sessions",
        json={"lecture_id": lecture_with_open_ended.id, "client_id": "test_lms", "external_user_id": "student_3"},
    )
    session_id = resp.json()["session_id"]

    # Activate
    test_client.post(
        f"/api/sessions/{session_id}/activate",
        json={"intervention_id": "q_open_req", "playback_position": 25.0},
    )

    # Submit open-ended answer
    sub_resp = test_client.post(
        f"/api/sessions/{session_id}/submissions/open-ended",
        json={
            "intervention_id": "q_open_req",
            "idempotency_key": "sub_open_self_assess",
            "user_answer": "My reasoning here...",
        },
    )
    submission_id = sub_resp.json()["submission_id"]

    # Self-assess
    sa_resp = test_client.post(
        f"/api/sessions/{session_id}/submissions/{submission_id}/self-assess",
        json={"self_assessed_correct": True},
    )
    assert sa_resp.status_code == 200
    state = sa_resp.json()
    q_state = next(i for i in state["interventions"] if i["id"] == "q_open_req")
    assert q_state["state"] == "COMPLETED"


def test_telemetry_export(test_client, lecture_with_open_ended, creator_token_factory):
    # Trigger a skip to create a telemetry event
    resp = test_client.post(
        "/api/sessions",
        json={"lecture_id": lecture_with_open_ended.id, "client_id": "telemetry_client", "external_user_id": "u1"},
    )
    session_id = resp.json()["session_id"]
    test_client.post(
        f"/api/sessions/{session_id}/activate",
        json={"intervention_id": "q_skip", "playback_position": 10.0},
    )
    test_client.post(f"/api/sessions/{session_id}/interventions/q_skip/skip")

    # Export telemetry
    t_resp = test_client.get(
        "/api/telemetry?client_id=telemetry_client",
        headers=creator_token_factory("telemetry_client"),
    )
    assert t_resp.status_code == 200
    events = t_resp.json()
    assert len(events) >= 1
    assert any(e["event_type"] == "intervention_skipped" for e in events)
