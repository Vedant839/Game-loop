"""Database timeout, read-retry, and 503 mapping tests."""

from __future__ import annotations

import pytest
import urllib.error
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.database import (
    Database,
    DatabaseUnavailableError,
    _install_turso_request_timeout,
)
from backend.main import app
from backend.services import session_service


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("GAME_LOOP_DB_PATH", str(tmp_path / "timeout.db"))
    monkeypatch.setenv("GAME_LOOP_DATABASE_READ_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("GAME_LOOP_DATABASE_TIMEOUT_SECONDS", "10")
    get_settings.cache_clear()
    database = Database(db_path=tmp_path / "timeout.db")
    yield database
    get_settings.cache_clear()


def test_load_session_retries_transient_timeouts(db, monkeypatch):
    calls = {"n": 0}

    def flaky_load(session_id: str):
        calls["n"] += 1
        if calls["n"] < 3:
            raise DatabaseUnavailableError("database request timed out")
        return {"session_id": session_id}

    monkeypatch.setattr(db.sessions, "load_session", flaky_load)
    assert db.load_session("sess-1")["session_id"] == "sess-1"
    assert calls["n"] == 3


def test_load_session_gives_up_after_bounded_retries(db, monkeypatch):
    calls = {"n": 0}

    def always_timeout(session_id: str):
        calls["n"] += 1
        raise DatabaseUnavailableError("database request timed out")

    monkeypatch.setattr(db.sessions, "load_session", always_timeout)
    with pytest.raises(DatabaseUnavailableError):
        db.load_session("sess-missing")
    assert calls["n"] == db.read_max_attempts


def test_writes_are_not_retried_on_timeout(db, monkeypatch):
    calls = {"n": 0}

    def flaky_record(**kwargs):
        calls["n"] += 1
        raise DatabaseUnavailableError("database request timed out")

    monkeypatch.setattr(db.telemetry, "record_telemetry", flaky_record)
    with pytest.raises(DatabaseUnavailableError):
        db.record_telemetry("c", "s", "u", "event", {})
    assert calls["n"] == 1


def test_connection_maps_timeout_error_to_unavailable(db, monkeypatch):
    class FakeConn:
        def execute(self, *args, **kwargs):
            raise TimeoutError("simulated statement timeout")

        def commit(self) -> None:
            return None

        def rollback(self) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr("sqlite3.connect", lambda *args, **kwargs: FakeConn())
    with pytest.raises(DatabaseUnavailableError, match="timed out"):
        with db.connection() as conn:
            conn.execute("SELECT 1")


def test_turso_request_uses_configured_timeout(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"{}"

    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    class FakeSession:
        _base_url = "https://db.example"

        def _headers(self):
            return {}

        def _reset_stream(self):
            pass

    class FakeConnection:
        _session = FakeSession()

    conn = FakeConnection()
    _install_turso_request_timeout(conn, 2.5)
    assert conn._session._post("/v3/pipeline", {}) == b"{}"
    assert captured["timeout"] == 2.5


def test_turso_network_failure_maps_to_unavailable(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            urllib.error.URLError("offline")
        ),
    )

    class FakeSession:
        _base_url = "https://db.example"

        def _headers(self):
            return {}

        def _reset_stream(self):
            pass

    class FakeConnection:
        _session = FakeSession()

    conn = FakeConnection()
    _install_turso_request_timeout(conn, 2.5)
    with pytest.raises(DatabaseUnavailableError, match="unreachable"):
        conn._session._post("/v3/pipeline", {})


def test_api_returns_503_when_database_unavailable(monkeypatch):
    def boom(self, session_id: str):
        raise DatabaseUnavailableError("database request timed out")

    monkeypatch.setattr(session_service.SessionService, "get_session", boom)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/sessions/does-not-matter")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database temporarily unavailable"}
