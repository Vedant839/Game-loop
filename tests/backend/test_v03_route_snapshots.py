"""Small response-shape snapshots for the public V0.3 API routes."""

from fastapi.testclient import TestClient

from backend.database import get_database
from backend.main import app


client = TestClient(app)


def test_v03_lectures_route_response_shape() -> None:
    response = client.get("/api/lectures")

    assert response.status_code == 200
    assert response.json()
    assert set(response.json()[0]) == {
        "id", "title", "subject", "grade", "duration_seconds", "video_url", "intervention_count"
    }


def test_v03_telemetry_route_response_shape() -> None:
    get_database().record_telemetry(
        client_id="snapshot_client", session_id="snapshot_session", user_id="snapshot_user",
        event_type="snapshot_event", payload={"source": "test"}, timestamp=1.0,
    )
    response = client.get("/api/telemetry?client_id=snapshot_client")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert set(response.json()[0]) == {
        "id", "client_id", "session_id", "user_id", "event_type", "payload", "timestamp"
    }


def test_v03_learners_route_response_shape() -> None:
    response = client.get("/api/learners/snapshot_client/snapshot_user")

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
