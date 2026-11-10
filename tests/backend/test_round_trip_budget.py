"""Count SQL execution requests on the session hot paths."""

from __future__ import annotations

from contextlib import contextmanager

from backend.database import get_database
from backend.services.lecture_service import get_lecture_service
from backend.services.session_service import SessionService


class CountingConnection:
    """Count DB-API statements while delegating behavior to the test database."""

    def __init__(self, connection, counts: list[str]):
        self.connection = connection
        self.counts = counts

    def execute(self, sql, parameters=()):
        self.counts.append(sql.strip().split(maxsplit=1)[0].upper())
        return self.connection.execute(sql, parameters)

    def executemany(self, sql, parameters):
        self.counts.append("EXECUTEMANY")
        return self.connection.executemany(sql, parameters)

    def __getattr__(self, name):
        return getattr(self.connection, name)


def test_session_hot_path_database_statement_budget(monkeypatch):
    db = get_database()
    counts: list[str] = []
    raw_connection = db.connection

    @contextmanager
    def counted_connection():
        with raw_connection() as connection:
            yield CountingConnection(connection, counts)

    monkeypatch.setattr(db, "connection", counted_connection)
    service = SessionService(lecture_service=get_lecture_service(), db=db)
    lecture = service.lecture_service.get_lecture("math_sample_lecture")
    assert lecture is not None
    target = lecture.interventions[0]

    state = service.create_session(
        "math_sample_lecture", client_id="budget", external_user_id="submit"
    )
    create_session_count = len(counts)
    counts.clear()

    service.activate_intervention(
        state.session_id,
        target.id,
        playback_position=target.trigger_time,
    )
    activate_count = len(counts)
    counts.clear()

    service.submit_answer(
        state.session_id,
        intervention_id=target.id,
        idempotency_key="budget-submit",
        answer=target.correct_answer,
    )
    submit_count = len(counts)
    persisted = db.load_session(state.session_id)
    assert persisted is not None
    assert persisted["interventions_state"][target.id] == "COMPLETED"
    assert "budget-submit" in persisted["completed_submissions"]
    counts.clear()

    sync_state = service.create_session(
        "math_sample_lecture", client_id="budget", external_user_id="sync"
    )
    counts.clear()
    service.sync_playback(sync_state.session_id, playback_position=10_000.0)
    sync_count = len(counts)

    # The hint endpoint is not implemented yet; its count is documented as N/A.
    assert {
        "create_session": create_session_count,
        "activate": activate_count,
        "sync": sync_count,
        "submit": submit_count,
    } == {"create_session": 5, "activate": 7, "sync": 5, "submit": 4}
