from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


def test_health_endpoint_reports_backend_ready() -> None:
    response = client.get(
        "/api/health",
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
