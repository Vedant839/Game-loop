"""Redact configured Gemini credentials from provider log records."""

import logging

from backend.config import get_settings


class ApiKeyRedactionFilter(logging.Filter):
    """Remove the configured Gemini key from a log record before formatting."""

    def filter(self, record: logging.LogRecord) -> bool:
        key = get_settings().gemini_api_key
        if key is None:
            return True
        secret = key.get_secret_value()
        if not secret:
            return True
        message = record.getMessage().replace(secret, "[REDACTED]")
        record.msg = message
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        return True


def add_api_key_redaction(logger: logging.Logger) -> None:
    if not any(isinstance(item, ApiKeyRedactionFilter) for item in logger.filters):
        logger.addFilter(ApiKeyRedactionFilter())
