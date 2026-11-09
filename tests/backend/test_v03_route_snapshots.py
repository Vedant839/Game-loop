"""Small response-shape snapshots for the public V0.3 API routes."""

from fastapi.testclient import TestClient
from fastapi.routing import APIRoute

from backend.database import get_database
from backend.main import app


client = TestClient(app)


def test_no_api_route_accepts_uid_query_parameter() -> None:
    for route in app.routes:
        if isinstance(route, APIRoute):
            assert "{uid" not in route.path.lower()
            assert all(param.alias.lower() != "uid" for param in route.dependant.query_params)


def _assert_student_lecture_has_no_private_fields(value) -> None:
    private = {
        "correct_answer", "accepted_answers", "key_concepts", "reference_answer",
        "misconceptions", "passing_score", "hints", "solution_code", "recall_pool",
    }
    if isinstance(value, dict):
        assert not (private & value.keys())
        for child in value.values():
            _assert_student_lecture_has_no_private_fields(child)
    elif isinstance(value, list):
        for child in value:
            _assert_student_lecture_has_no_private_fields(child)


def test_public_lecture_route_returns_sanitized_response_shape() -> None:
    response = client.get("/api/lectures/linear_algebra_vectors")

    assert response.status_code == 200
    assert set(response.json()) == {
        "id", "title", "subject", "grade", "duration_seconds", "video_url",
        "timing_config", "transcript", "interventions",
    }
    _assert_student_lecture_has_no_private_fields(response.json())


def test_session_lecture_route_returns_sanitized_lecture() -> None:
    created = client.post("/api/sessions", json={"lecture_id": "linear_algebra_vectors"})
    assert created.status_code == 201

    response = client.get(f"/api/sessions/{created.json()['session_id']}/lecture")

    assert response.status_code == 200
    assert response.json()["id"] == "linear_algebra_vectors"
    _assert_student_lecture_has_no_private_fields(response.json())


def test_unknown_session_cannot_fetch_a_lecture() -> None:
    response = client.get("/api/sessions/fabricated-session/lecture")

    assert response.status_code == 404


def test_v03_telemetry_route_response_shape(creator_token_factory) -> None:
    get_database().record_telemetry(
        client_id="snapshot_client", session_id="snapshot_session", user_id="snapshot_user",
        event_type="snapshot_event", payload={"source": "test"}, timestamp=1.0,
    )
    response = client.get(
        "/api/telemetry?client_id=snapshot_client",
        headers=creator_token_factory("snapshot_client"),
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert set(response.json()[0]) == {
        "id", "client_id", "session_id", "user_id", "event_type", "payload", "timestamp"
    }


def test_v03_learners_route_response_shape(creator_token_factory) -> None:
    response = client.get(
        "/api/learners/snapshot_client/snapshot_user",
        headers=creator_token_factory("snapshot_client"),
    )

    assert response.status_code == 200
    assert set(response.json()) == {
        "user_id", "client_id", "concept_mastery", "streak", "friction_index",
        "total_interventions", "total_correct",
    }


def test_v03_sessions_route_response_shape() -> None:
    created = client.post("/api/sessions", json={"lecture_id": "math_sample_lecture"})

    assert created.status_code == 201
    session_id = created.json()["session_id"]
    response = client.get(f"/api/sessions/{session_id}")

    assert response.status_code == 200
    assert set(response.json()) == {
        "session_id", "lecture_id", "version", "client_id", "external_user_id",
        "active_intervention_id", "interventions",
    }
    assert set(response.json()["interventions"][0]) == {"id", "trigger_time", "state", "policy"}
