"""Test SlowAPI enforcement and the proxy/token rate-limit keys."""

from starlette.requests import Request
from fastapi.testclient import TestClient

from backend.main import app
from backend.rate_limit import (
    get_creator_rate_limit_key,
    get_real_client_ip,
    limiter,
)


def _request(headers: list[tuple[bytes, bytes]], client="127.0.0.1") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": (client, 1234),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


def test_real_client_ip_uses_rightmost_forwarded_address():
    request = _request(
        [(b"x-forwarded-for", b"203.0.113.10, 198.51.100.20")]
    )
    assert get_real_client_ip(request) == "198.51.100.20"


def test_creator_rate_key_hashes_bearer_token():
    first = _request([(b"authorization", b"Bearer creator-secret")])
    second = _request([(b"authorization", b"Bearer other-secret")])
    key = get_creator_rate_limit_key(first)
    assert key.startswith("creator:")
    assert "creator-secret" not in key
    assert key != get_creator_rate_limit_key(second)


def test_session_creation_is_limited_by_rightmost_forwarded_ip():
    limiter.reset()
    client = TestClient(app)
    for index in range(30):
        response = client.post(
            "/api/sessions",
            json={"lecture_id": "math_sample_lecture"},
            headers={
                "X-Forwarded-For": f"192.0.2.{index + 1}, 198.51.100.44"
            },
        )
        assert response.status_code == 201

    limited = client.post(
        "/api/sessions",
        json={"lecture_id": "math_sample_lecture"},
        headers={"X-Forwarded-For": "203.0.113.88, 198.51.100.44"},
    )
    assert limited.status_code == 429
    limiter.reset()
