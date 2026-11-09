"""Monthly Gemini quota and API-key log redaction checks."""

import logging
import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend import config
from backend.database import get_database
from backend.main import generate_interventions_for_lecture
from backend.services.evaluator_service import EvaluatorService, EvaluationOutput
from backend.services.gemini_client import (
    GeminiClient,
    GeminiProviderError,
    GeminiQuotaExceeded,
)
from scripts.migrate import migrate_database


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/lectures/linear_algebra_vectors/generate_interventions",
            "headers": [],
            "client": ("testclient", 1234),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


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

    def invoke_through_client(**kwargs):
        return kwargs["gemini_client"].generate_content(
            api_key=kwargs["api_key"],
            creator_id=kwargs["creator_id"],
            lecture_id="linear_algebra_vectors",
            event_type="lecture_generation",
            model="fake-model",
            contents="prompt",
        )

    monkeypatch.setattr(main, "generate_interventions_with_gemini", invoke_through_client)

    with pytest.raises(HTTPException) as exc:
        generate_interventions_for_lecture(
            request=_request(),
            lecture_id="linear_algebra_vectors",
            creator={"creator_id": "creator_a"},
        )
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
        class FakeModels:
            def generate_content(self, **_provider_kwargs):
                raise RuntimeError(f"provider failed using {secret}")

        kwargs["gemini_client"].provider_factory = lambda **_factory_kwargs: SimpleNamespace(
            models=FakeModels()
        )
        return kwargs["gemini_client"].generate_content(
            api_key=kwargs["api_key"],
            creator_id=kwargs["creator_id"],
            lecture_id="linear_algebra_vectors",
            event_type="lecture_generation",
            model="fake-model",
            contents="prompt",
        )

    monkeypatch.setattr(main, "generate_interventions_with_gemini", fail_with_key)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(HTTPException) as exc:
            generate_interventions_for_lecture(
                request=_request(),
                lecture_id="linear_algebra_vectors",
                creator={"creator_id": "creator_a"},
            )

    assert exc.value.status_code == 502
    assert secret not in caplog.text
    assert secret not in str(exc.value.detail)
    assert get_database().creators.get_monthly_token_usage("creator_a") > 0
    config.get_settings.cache_clear()


def test_evaluator_logs_each_provider_call_and_uses_offline_fallback(monkeypatch):
    migrate_database(get_database().db_path)
    db = get_database()
    evaluator = EvaluatorService(db)
    evaluator.settings = SimpleNamespace(
        gemini_api_key=SimpleNamespace(get_secret_value=lambda: "fake-key"),
        creator_monthly_token_cap=1000,
    )
    evaluator.gemini_client.settings = evaluator.settings
    calls = {"n": 0}

    class FakeModels:
        def generate_content(self, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("simulated provider failure")
            return SimpleNamespace(
                text=json.dumps({
                    "score": 1.0,
                    "is_correct": True,
                    "formative_feedback": "Good.",
                    "misconceptions_detected": [],
                }),
                usage_metadata=SimpleNamespace(total_token_count=5),
            )

    evaluator.gemini_client.provider_factory = lambda **_kwargs: SimpleNamespace(
        models=FakeModels()
    )
    for _ in range(2):
        result = asyncio.run(
            evaluator._call_gemini_or_fallback(
                "Explain vectors.",
                "A vector has magnitude and direction.",
                {"key_concepts": ["magnitude"]},
                creator_id="quota_creator",
                lecture_id="linear_algebra_vectors",
            )
        )
        assert result.score >= 0

    usage = db.creators.get_monthly_token_usage("quota_creator")
    assert calls["n"] == 2
    assert usage > 1


def test_evaluator_over_cap_skips_gemini_and_uses_fallback(monkeypatch):
    migrate_database(get_database().db_path)
    db = get_database()
    db.creators.log_usage("over-cap", "quota_creator", "lecture", "prior", 10)
    evaluator = EvaluatorService(db)
    evaluator.settings = SimpleNamespace(
        gemini_api_key=SimpleNamespace(get_secret_value=lambda: "fake-key"),
        creator_monthly_token_cap=10,
    )
    evaluator.gemini_client.settings = evaluator.settings
    evaluator.gemini_client.provider_factory = lambda **_kwargs: pytest.fail(
        "Gemini must not run over quota"
    )

    result = asyncio.run(
        evaluator._call_gemini_or_fallback(
            "Explain vectors.",
            "A vector has magnitude and direction.",
            {"key_concepts": ["magnitude"]},
            creator_id="quota_creator",
            lecture_id="lecture",
        )
    )
    assert result.score >= 0
    assert db.creators.get_monthly_token_usage("quota_creator") == 10


def test_authoring_usage_is_logged_for_each_failed_model_call(monkeypatch):
    migrate_database(get_database().db_path)
    db = get_database()
    from google import genai

    import backend.services.gemini_authoring_service as authoring
    from backend.services.lecture_service import get_lecture_service

    class FakeModels:
        def __init__(self):
            self.calls = 0

        def generate_content(self, **_kwargs):
            self.calls += 1
            raise RuntimeError("simulated provider failure")

    models = FakeModels()

    class FakeClient:
        def __init__(self, **_kwargs):
            self.models = models

    monkeypatch.setattr(genai, "Client", FakeClient)
    monkeypatch.setattr(authoring.time, "sleep", lambda _seconds: None)
    lecture = get_lecture_service().get_lecture("linear_algebra_vectors")

    with pytest.raises(RuntimeError, match="generation failed"):
        authoring.generate_interventions_with_gemini(
            lecture,
            api_key="fake-key",
            models=["fake-model"],
            db=db,
            creator_id="authoring_creator",
        )

    assert models.calls == 2
    assert db.creators.get_monthly_token_usage("authoring_creator") > 1


def test_gemini_client_logs_provider_usage_and_sanitizes_failures(caplog):
    migrate_database(get_database().db_path)
    db = get_database()
    settings = SimpleNamespace(creator_monthly_token_cap=100)
    response = SimpleNamespace(
        text="ok", usage_metadata=SimpleNamespace(total_token_count=23)
    )
    client = GeminiClient(
        db=db,
        settings=settings,
        provider_factory=lambda **_kwargs: SimpleNamespace(
            models=SimpleNamespace(generate_content=lambda **_call: response)
        ),
    )

    client.generate_content(
        api_key="fake-key",
        creator_id="client_test",
        lecture_id="lecture",
        event_type="student_evaluation",
        model="fake-model",
        contents="some prompt",
    )
    assert db.creators.get_monthly_token_usage("client_test") == 23
    assert "api_key" not in vars(client)

    secret = "creator-key-that-must-not-leak"
    client.provider_factory = lambda **_kwargs: SimpleNamespace(
        models=SimpleNamespace(
            generate_content=lambda **_call: (_ for _ in ()).throw(
                RuntimeError(f"provider echoed {secret}")
            )
        )
    )
    with pytest.raises(GeminiProviderError) as exc:
        client.generate_content(
            api_key=secret,
            creator_id="client_test",
            lecture_id="lecture",
            event_type="student_evaluation",
            model="fake-model",
            contents="another prompt",
        )
    assert secret not in str(exc.value)
    assert secret not in caplog.text
    assert db.creators.get_monthly_token_usage("client_test") > 23

    settings.creator_monthly_token_cap = db.creators.get_monthly_token_usage("client_test")
    with pytest.raises(GeminiQuotaExceeded):
        client.generate_content(
            api_key=secret,
            creator_id="client_test",
            lecture_id="lecture",
            event_type="student_evaluation",
            model="fake-model",
            contents="blocked prompt",
        )
