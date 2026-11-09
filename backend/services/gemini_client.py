"""Single quota-aware, usage-logging interface for Google Gemini calls."""

from __future__ import annotations

import json
import uuid
from typing import Any, Callable

from backend.config import Settings, get_settings
from backend.database import Database, get_database


class GeminiQuotaExceeded(RuntimeError):
    """Raised before a provider call when the creator has reached the monthly cap."""


class GeminiProviderError(RuntimeError):
    """Provider failure with details removed to avoid leaking credentials or prompts."""


def _default_provider_factory(*, api_key: str, timeout_ms: int) -> Any:
    from google import genai

    return genai.Client(api_key=api_key, http_options={"timeout": timeout_ms})


def _estimate_tokens(value: Any) -> int:
    if isinstance(value, str):
        serialized = value
    else:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
    return max(1, (len(serialized) + 3) // 4)


def _reported_token_count(response: Any) -> int | None:
    metadata = getattr(response, "usage_metadata", None)
    count = getattr(metadata, "total_token_count", None) if metadata is not None else None
    return int(count) if isinstance(count, int) and count > 0 else None


class GeminiClient:
    """Centralize provider creation, monthly quota checks, and usage recording.

    Credentials are supplied per call and are never stored on this object.
    ``provider_factory`` is injectable so tests can use a local fake provider.
    """

    def __init__(
        self,
        db: Database | None = None,
        settings: Settings | None = None,
        provider_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.db = db or get_database()
        self.settings = settings or get_settings()
        self.provider_factory = provider_factory or _default_provider_factory

    def generate_content(
        self,
        *,
        api_key: str,
        creator_id: str,
        lecture_id: str,
        event_type: str,
        model: str,
        contents: Any,
        config: Any = None,
        timeout_ms: int = 30000,
        enforce_monthly_cap: bool = True,
    ) -> Any:
        if enforce_monthly_cap and (
            self.db.creators.get_monthly_token_usage(creator_id)
            >= self.settings.creator_monthly_token_cap
        ):
            raise GeminiQuotaExceeded("Monthly Gemini token cap reached")

        input_estimate = _estimate_tokens(contents)
        response: Any = None
        tokens_used = input_estimate
        try:
            provider = self.provider_factory(api_key=api_key, timeout_ms=timeout_ms)
            response = provider.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
            tokens_used = _reported_token_count(response) or max(
                1,
                input_estimate + _estimate_tokens(getattr(response, "text", "") or ""),
            )
            return response
        except GeminiQuotaExceeded:
            raise
        except Exception:
            raise GeminiProviderError("Gemini provider call failed") from None
        finally:
            self.db.creators.log_usage(
                str(uuid.uuid4()), creator_id, lecture_id, event_type, tokens_used
            )
