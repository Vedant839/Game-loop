"""Pytest configuration and isolation fixtures."""

import os
import pytest
from backend.config import get_settings
from backend import database
from backend.services import evaluator_service, learner_service, lecture_service, session_service


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

