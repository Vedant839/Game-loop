"""Pytest configuration and isolation fixtures."""

import hashlib
import os
import secrets

import pytest
from backend.config import get_settings
from backend import database
from backend.services import evaluator_service, learner_service, lecture_service, session_service
from scripts.migrate import migrate_database


@pytest.fixture(autouse=True)
def isolate_test_db(tmp_path, monkeypatch):
    """Ensure every test has an isolated SQLite database and reset service singletons."""
    test_db_path = tmp_path / "test_game_loop.db"
    monkeypatch.setenv("GAME_LOOP_DB_PATH", str(test_db_path))
    get_settings.cache_clear()

    # Reset singletons
    database._db_instance = None
    evaluator_service._evaluator_service_instance = None
    learner_service._learner_service_instance = None
    lecture_service._lecture_service_instance = None
    session_service._session_service_instance = None

    yield test_db_path

    # Clean up singletons after test
    database._db_instance = None
    evaluator_service._evaluator_service_instance = None
    learner_service._learner_service_instance = None
    lecture_service._lecture_service_instance = None
    session_service._session_service_instance = None
    get_settings.cache_clear()



@pytest.fixture
def creator_token_factory():
    """Create a DB-backed creator token and return its bearer header."""
    database_instance = database.get_database()
    migrate_database(database_instance.db_path)

    def issue(creator_id: str = "default_client") -> dict[str, str]:
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        database_instance.creators.save_token(
            token_hash=token_hash,
            creator_id=creator_id,
            label="pytest",
        )
        return {"Authorization": f"Bearer {raw_token}"}

    return issue
