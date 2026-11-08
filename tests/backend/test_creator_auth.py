"""Coverage for DB-backed creator authentication and tenant boundaries."""

import hashlib

from fastapi.testclient import TestClient

from backend.database import get_database
from backend.main import app
from scripts.create_token import create_token
from scripts.revoke_token import revoke_token
from scripts.migrate import migrate_database

client = TestClient(app)


def test_creator_routes_reject_missing_token():
    assert client.get("/api/telemetry").status_code == 401
    assert client.get("/api/learners/default_client/learner").status_code == 401
    assert client.post("/api/lectures", json={}).status_code == 401


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
