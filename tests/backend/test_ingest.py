from fastapi.testclient import TestClient
from types import SimpleNamespace

from backend.main import app
from backend.database import get_database
from backend.services.lecture_service import LectureService
import json


class FakeGeminiClient:
    def generate_content(self, **kwargs):
        prompt = kwargs["contents"]
        if "TRANSCRIPT_START" in prompt:
            payload = {"concepts": [{
                "name": "Vector magnitude and direction",
                "kind": "definition",
                "description": "A vector has magnitude and direction.",
                "start_s": 1.0,
                "end_s": 4.0,
                "evidence": [{"source": "transcript", "quote": "A vector has magnitude and direction."}],
            }]}
        elif "CONCEPT_DATA_START" in prompt:
            match = prompt.split("CONCEPT_DATA_START\n", 1)[1].split("\nCONCEPT_DATA_END", 1)[0]
            concepts = json.loads(match)
            payload = {"checkpoints": [{
                "concept_id": concept["concept_id"], "type": "single_choice",
                "question": "What two properties define a vector?",
                "options": [
                    {"id": "a", "text": "Magnitude and direction"},
                    {"id": "b", "text": "Color and shape"},
                    {"id": "c", "text": "Mass and volume"},
                    {"id": "d", "text": "Speed and temperature"},
                ],
                "correct_answer": "a",
            } for concept in concepts]}
        else:
            import re
            ids = re.findall(r"CHECKPOINT_START id=([^\s]+)", prompt)
            payload = {"verdicts": [{"id": item, "verdict": "keep", "reason": ""} for item in ids]}
        return type("Response", (), {"text": json.dumps(payload)})()


def test_creator_ingest_parses_captions_and_persists_lecture(tmp_path, monkeypatch, creator_token_factory):
    import backend.main as main

    service = LectureService(tmp_path / "lectures")
    service.lectures_dir.mkdir(parents=True)
    monkeypatch.setattr(main, "get_lecture_service", lambda: service)
    monkeypatch.setattr(main, "settings", SimpleNamespace(gemini_api_key=None))
    monkeypatch.setitem(app.dependency_overrides, main.get_gemini_client, lambda: FakeGeminiClient())
    token = creator_token_factory("ingest_creator")
    response = TestClient(app).post(
        "/api/creator/ingest",
        headers={**token, "X-Gemini-Key": "fake-test-key"},
        json={
            "video_url": "https://example.com/vectors.mp4",
            "duration_seconds": 300,
            "captions": "1\n00:00:01,000 --> 00:00:04,000\nA vector has magnitude and direction.",
            "captions_format": "srt",
            "intensity": "standard",
        },
    )

    assert response.status_code == 201
    lecture = response.json()
    assert response.headers["x-generation-mode"] == "concept_v2"
    assert lecture["generator_version"] == 2
    assert lecture["interventions"][0]["concept_id"] == lecture["concepts"][0]["concept_id"]
    assert not {"title", "subject", "grade"}.intersection(lecture)
    assert lecture["transcript"][0]["text"] == "A vector has magnitude and direction."
    assert lecture["interventions"]
    assert service.get_lecture(lecture["id"]) is not None
    assert get_database().lectures.get_lecture(lecture["id"]) is not None
    assert list(service.lectures_dir.glob("*.json")) == []
    event = get_database().export_telemetry(client_id="ingest_creator")[0]
    assert event["event_type"] == "lecture_ingestion_completed"
    assert event["payload"]["duration_ms"] >= 0


def test_creator_ingest_rejects_bad_caption_file(creator_token_factory):
    response = TestClient(app).post(
        "/api/creator/ingest",
        headers=creator_token_factory("ingest_creator"),
        json={
            "video_url": "https://example.com/video.mp4",
            "duration_seconds": 60,
            "captions": "not an SRT file",
            "captions_format": "srt",
        },
    )
    assert response.status_code == 422


def test_creator_ingest_rejects_school_metadata_fields(creator_token_factory):
    response = TestClient(app).post(
        "/api/creator/ingest",
        headers=creator_token_factory("ingest_creator"),
        json={
            "video_url": "https://example.com/video.mp4",
            "duration_seconds": 300,
            "title": "No longer part of the model",
        },
    )
    assert response.status_code == 422
