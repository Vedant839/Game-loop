import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.database import get_database
from backend.main import app
from backend.services.lecture_service import LectureService
import backend.services.lecture_service as lecture_service_module
import backend.services.session_service as session_service_module


client = TestClient(app)


def test_hints_are_gated_by_persisted_attempt_count(tmp_path: Path, monkeypatch):
    lecture_dir = tmp_path / "lectures"
    lecture_dir.mkdir()
    lecture = {
        "id": "hint_test_lecture",
        "title": "Hints",
        "subject": "Test",
        "grade": "1",
        "duration_seconds": 30,
        "video_url": "https://example.com/video.mp4",
        "interventions": [
            {
                "id": "checkpoint",
                "trigger_time": 10,
                "concept": "test concept",
                "difficulty": "Easy",
                "type": "single_choice",
                "question": "Choose the correct option",
                "options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                "correct_answer": "a",
                "hints": ["First hint", "Second hint"],
                "sandbox_config": {
                    "solution_code": "secret solution",
                    "hints": ["Sandbox first", "Sandbox second"],
                },
            }
        ],
    }
    (lecture_dir / "hint_test_lecture.json").write_text(json.dumps(lecture), encoding="utf-8")
    monkeypatch.setattr(
        lecture_service_module, "_lecture_service_instance", LectureService(lecture_dir)
    )
    monkeypatch.setattr(session_service_module, "_session_service_instance", None)

    created = client.post("/api/sessions", json={"lecture_id": "hint_test_lecture"})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    activated = client.post(
        f"/api/sessions/{session_id}/activate",
        json={"intervention_id": "checkpoint", "playback_position": 10},
    )
    assert activated.status_code == 200
    assert "hints" not in activated.json()["sandbox_config"]
    assert "solution_code" not in activated.json()["sandbox_config"]

    before_attempt = client.post(
        f"/api/sessions/{session_id}/hint", json={"intervention_id": "checkpoint"}
    )
    assert before_attempt.status_code == 400
    assert before_attempt.json()["detail"] == "Must attempt the checkpoint before requesting a hint."

    submitted = client.post(
        f"/api/sessions/{session_id}/submit",
        json={"intervention_id": "checkpoint", "idempotency_key": "attempt-1", "answer": "b"},
    )
    assert submitted.status_code == 200

    service = session_service_module.get_session_service()
    session = service._get_or_load_session(session_id)
    assert session.attempt_counts["checkpoint"] == 1
    service._sessions.pop(session_id)
    first_hint = client.post(
        f"/api/sessions/{session_id}/hint", json={"intervention_id": "checkpoint"}
    )
    assert first_hint.status_code == 200
    assert first_hint.json() == {"hint": "First hint"}

    # Retry handling is implemented in the later remediation step; exercise the
    # persisted second-attempt branch directly until that flow is introduced.
    session = service._get_or_load_session(session_id)
    session.attempt_counts["checkpoint"] = 2
    service._persist_session(session, intervention_ids={"checkpoint"})
    service._sessions.pop(session_id)
    second_hint = client.post(
        f"/api/sessions/{session_id}/hint", json={"intervention_id": "checkpoint"}
    )
    assert second_hint.status_code == 200
    assert second_hint.json() == {"hint": "Second hint"}

    with get_database().connection() as conn:
        row = conn.execute(
            "SELECT attempt_count, hint_used FROM session_interventions "
            "WHERE session_id = ? AND intervention_id = ?",
            (session_id, "checkpoint"),
        ).fetchone()
    assert tuple(row) == (2, 2)
