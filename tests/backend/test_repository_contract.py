"""Backend contract suite; set GAME_LOOP_TEST_DATABASE=turso for a scratch Turso DB."""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.config import get_settings
from backend.database import Database
from backend.schemas.lecture import Difficulty, Intervention, InterventionType, Lecture, Option, TimingConfig
from backend.services.learner_service import LearnerService
from backend.services.lecture_service import LectureService
from backend.services.session_service import SessionService
from scripts.migrate import migrate_database


class ContractLectures(LectureService):
    def __init__(self) -> None:
        self.lecture = Lecture(
            id="contract-lecture", title="Contract", subject="Math", grade="9",
            duration_seconds=30, video_url="/contract.mp4",
            timing_config=TimingConfig(min_trigger_gap=5, tolerance=1),
            interventions=[Intervention(
                id="checkpoint", trigger_time=5, concept="algebra",
                difficulty=Difficulty.EASY, type=InterventionType.SINGLE_CHOICE,
                question="Two plus two?", options=[Option(id="four", text="4"), Option(id="five", text="5")],
                correct_answer="four",
            )],
        )

    def get_lecture(self, lecture_id: str) -> Lecture | None:
        return self.lecture if lecture_id == self.lecture.id else None


@pytest.fixture
def contract_db(tmp_path, monkeypatch):
    backend = os.getenv("GAME_LOOP_TEST_DATABASE", "sqlite").lower()
    monkeypatch.setenv("GAME_LOOP_DATABASE_BACKEND", backend)
    if backend == "turso":
        assert os.getenv("TURSO_DATABASE_URL"), "TURSO_DATABASE_URL must point to a scratch DB"
        assert os.getenv("TURSO_AUTH_TOKEN"), "TURSO_AUTH_TOKEN is required"
    else:
        monkeypatch.setenv("GAME_LOOP_DB_PATH", str(tmp_path / "contract.db"))
    get_settings.cache_clear()
    db = Database()
    migrate_database(db.db_path)
    yield db
    get_settings.cache_clear()


def test_repository_contract_migration_lifecycle_submission_profile_and_delete_rollback(
    contract_db, monkeypatch
):
    db = contract_db
    assert migrate_database(db.db_path) is False

    session_service = SessionService(lecture_service=ContractLectures(), db=db)
    run_id = uuid.uuid4().hex
    creator_id = f"contract-creator-{run_id}"
    learner_id = f"contract-learner-{run_id}"
    submission_id = f"contract-submission-{run_id}"
    idempotency_key = f"contract-key-{run_id}"
    original_connection = db.connection
    try:
        state = session_service.create_session(
            lecture_id="contract-lecture", client_id=creator_id, external_user_id=learner_id
        )
        assert db.load_session(state.session_id)["session_id"] == state.session_id

        db.save_submission(
            submission_id=submission_id, session_id=state.session_id,
            intervention_id="checkpoint", idempotency_key=idempotency_key, user_answer="4",
            status="completed", resumption_policy="immediate_optimistic", is_correct=True,
        )
        assert db.get_submission(submission_id)["user_answer"] == "4"

        learner = LearnerService(db=db)
        learner.record_attempt(creator_id, learner_id, "algebra", True, 1)
        assert db.load_learner_profile(creator_id, learner_id)["total_correct"] == 1

        db.record_telemetry(creator_id, state.session_id, learner_id, "contract", {})

        @contextmanager
        def fail_during_delete():
            with original_connection() as connection:
                class FailingConnection:
                    def execute(self, sql, parameters=()):
                        if sql.lstrip().upper().startswith("DELETE FROM LEARNER_PROFILES"):
                            raise RuntimeError("injected failure")
                        return connection.execute(sql, parameters)

                    def __getattr__(self, name):
                        return getattr(connection, name)

                yield FailingConnection()

        monkeypatch.setattr(db, "connection", fail_during_delete)
        with pytest.raises(RuntimeError, match="injected failure"):
            db.delete_learner(creator_id, learner_id)
        monkeypatch.setattr(db, "connection", original_connection)

        assert db.load_session(state.session_id) is not None
        assert db.load_learner_profile(creator_id, learner_id) is not None
        assert db.export_telemetry(client_id=creator_id)

        assert db.delete_learner(creator_id, learner_id) == 2
        assert db.load_session(state.session_id) is None
        assert db.load_learner_profile(creator_id, learner_id) is None
        assert db.get_submission(submission_id) is None
        assert db.export_telemetry(client_id=creator_id) == []
    finally:
        monkeypatch.setattr(db, "connection", original_connection)
        db.delete_learner(creator_id, learner_id)


def test_repository_contract_concurrent_writes(contract_db):
    db = contract_db
    run_id = uuid.uuid4().hex
    creator_id = f"concurrent-creator-{run_id}"
    try:
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(
                lambda index: db.record_telemetry(
                    creator_id, f"session-{run_id}-{index}", f"learner-{run_id}-{index}",
                    "concurrent_write", {"index": index},
                ),
                range(5),
            ))
        events = db.export_telemetry(client_id=creator_id, limit=10)
        assert len(events) == 5
        assert {event["payload"]["index"] for event in events} == set(range(5))
    finally:
        with db.connection() as conn:
            conn.execute("DELETE FROM telemetry_events WHERE client_id = ?", (creator_id,))
