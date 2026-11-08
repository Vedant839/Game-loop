"""Monthly Gemini quota and API-key log redaction checks."""

import logging
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend import config
from backend.database import get_database
from backend.main import generate_interventions_for_lecture
from scripts.migrate import migrate_database


def test_monthly_token_cap_blocks_gemini_call(monkeypatch):
    migrate_database(get_database().db_path)
    db = get_database()
    db.creators.log_usage("existing", "creator_a", "old", "generation", 100)
    monkeypatch.setenv("GEMINI_API_KEY", "quota-test-key")
    config.get_settings.cache_clear()
    import backend.main as main
    monkeypatch.setattr(main, "settings", SimpleNamespace(
        gemini_api_key=SimpleNamespace(get_secret_value=lambda: "quota-test-key"),
        creator_monthly_token_cap=100,
    ))
    monkeypatch.setattr(main, "generate_interventions_with_gemini", lambda **kwargs: pytest.fail("Gemini should not run over quota"))

    with pytest.raises(HTTPException) as exc:
        generate_interventions_for_lecture("linear_algebra_vectors", creator={"creator_id": "creator_a"})
    assert exc.value.status_code == 429


def test_simulated_gemini_failure_redacts_key_from_logs_and_response(monkeypatch, caplog):
    migrate_database(get_database().db_path)
    secret = "simulated-provider-key-987"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    config.get_settings.cache_clear()
    import backend.main as main
    monkeypatch.setattr(main, "settings", SimpleNamespace(
        gemini_api_key=SimpleNamespace(get_secret_value=lambda: secret),
        creator_monthly_token_cap=500_000,
    ))

    def fail_with_key(**kwargs):
        logging.getLogger("backend.services.gemini_authoring_service").warning("provider error echoed %s", secret)
        raise RuntimeError(f"provider failed using {secret}")

    monkeypatch.setattr(main, "generate_interventions_with_gemini", fail_with_key)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(HTTPException) as exc:
            generate_interventions_for_lecture("linear_algebra_vectors", creator={"creator_id": "creator_a"})

    assert exc.value.status_code == 502
    assert secret not in caplog.text
    assert secret not in str(exc.value.detail)
    config.get_settings.cache_clear()
