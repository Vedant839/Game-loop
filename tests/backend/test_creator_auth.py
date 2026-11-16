"""Coverage for DB-backed creator authentication and tenant boundaries."""

import hashlib
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.database import get_database
from backend.main import app
from backend.database import DatabaseUnavailableError
from scripts.create_token import create_token
from scripts.revoke_token import revoke_token
from scripts.migrate import migrate_database

client = TestClient(app)


def test_creator_routes_reject_missing_token():
    assert client.get("/api/telemetry").status_code == 401
    assert client.get("/api/learners/default_client/learner").status_code == 401
    assert client.get("/api/studio/lectures/math_sample_lecture").status_code == 401
    assert client.post("/api/lectures", json={}).status_code == 401


def test_database_unavailability_during_auth_returns_503(monkeypatch):
    import backend.auth as auth

    def unavailable(_token_hash):
        raise DatabaseUnavailableError("database unreachable")

    monkeypatch.setattr(
        auth,
        "get_database",
        lambda: SimpleNamespace(creators=SimpleNamespace(get_token=unavailable)),
    )
    response = client.get(
        "/api/telemetry", headers={"Authorization": "Bearer valid-shaped-token"}
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "Database temporarily unavailable"}


def test_token_cli_creates_hashed_token_and_revocation_is_enforced():
    migrate_database(get_database().db_path)
    raw = create_token("creator_a", "cli-test")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    stored = get_database().creators.get_token(digest)
    assert stored is not None
    assert stored["creator_id"] == "creator_a"
    assert raw not in stored.values()
    assert revoke_token(raw)
    assert client.get("/api/telemetry", headers={"Authorization": f"Bearer {raw}"}).status_code == 401


def test_revoked_creator_token_is_rejected(creator_token_factory):
    header = creator_token_factory("creator_a")
    token = header["Authorization"].removeprefix("Bearer ")
    assert revoke_token(token)
    response = client.get("/api/telemetry", headers=header)
    assert response.status_code == 401


def test_creator_cannot_read_another_creators_telemetry_or_profile(creator_token_factory):
    creator_a = creator_token_factory("creator_a")
    creator_token_factory("creator_b")
    db = get_database()
    db.record_telemetry(
        client_id="creator_a", session_id="a-session", user_id="a-user",
        event_type="event", payload={}, timestamp=1.0,
    )
    db.record_telemetry(
        client_id="creator_b", session_id="b-session", user_id="b-user",
        event_type="event", payload={}, timestamp=2.0,
    )

    own = client.get("/api/telemetry", headers=creator_a)
    assert own.status_code == 200
    assert {row["client_id"] for row in own.json()} == {"creator_a"}
    assert client.get("/api/telemetry?client_id=creator_b", headers=creator_a).status_code == 403
    assert client.get("/api/learners/creator_b/b-user", headers=creator_a).status_code == 403


def test_first_creator_can_list_sample_lecture_and_its_sessions(creator_token_factory):
    header = creator_token_factory("default_client")
    created = client.post(
        "/api/sessions",
        json={"lecture_id": "math_sample_lecture", "client_id": "default_client", "learner_id": "sample-learner"},
    )
    assert created.status_code == 201

    lectures = client.get("/api/lectures")
    assert any(item["id"] == "math_sample_lecture" for item in lectures.json())

    sessions = client.get(
        "/api/studio/sessions?lecture_id=math_sample_lecture", headers=header
    )
    assert sessions.status_code == 200
    assert any(item["session_id"] == created.json()["session_id"] for item in sessions.json())
    assert all("external_user_id" not in item for item in sessions.json())


def test_studio_lecture_route_preserves_full_answers(creator_token_factory):
    header = creator_token_factory("default_client")

    response = client.get(
        "/api/studio/lectures/math_sample_lecture", headers=header
    )

    assert response.status_code == 200
    assert any(
        intervention.get("correct_answer") is not None
        for intervention in response.json()["interventions"]
    )


def test_studio_lecture_is_scoped_to_the_creating_creator(creator_token_factory, monkeypatch):
    from backend.services.lecture_service import get_lecture_service

    creator_a = creator_token_factory("creator_a")
    creator_b = creator_token_factory("creator_b")
    service = get_lecture_service()
    lecture = service.get_lecture("math_sample_lecture")
    assert lecture is not None
    lecture.id = "creator_b_private_lecture"

    def fail_if_file_copy_is_written(_lecture):
        raise AssertionError("POST /api/lectures must persist to the repository only")

    monkeypatch.setattr(service, "save_lecture", fail_if_file_copy_is_written)

    created = client.post(
        "/api/lectures", headers=creator_b, json=lecture.model_dump(mode="json")
    )
    assert created.status_code == 201

    own = client.get("/api/studio/lectures/creator_b_private_lecture", headers=creator_b)
    other = client.get("/api/studio/lectures/creator_b_private_lecture", headers=creator_a)

    assert own.status_code == 200
    assert any(item.get("correct_answer") for item in own.json()["interventions"])
    assert other.status_code == 404
    assert get_database().lectures.get_lecture("creator_b_private_lecture")["creator_id"] == "creator_b"
    assert not (service.lectures_dir / "creator_b_private_lecture.json").exists()

    listed = client.get("/api/lectures")
    summary = next(item for item in listed.json() if item["id"] == "creator_b_private_lecture")
    assert set(summary) == {"id", "duration_seconds", "video_url", "intervention_count"}
