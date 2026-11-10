from fastapi.testclient import TestClient
from types import SimpleNamespace

from backend.main import app
from backend.database import get_database
from backend.services.lecture_service import LectureService


def test_creator_ingest_parses_captions_and_persists_lecture(tmp_path, monkeypatch, creator_token_factory):
    import backend.main as main

    service = LectureService(tmp_path / "lectures")
    service.lectures_dir.mkdir(parents=True)
    monkeypatch.setattr(main, "get_lecture_service", lambda: service)
    monkeypatch.setattr(main, "settings", SimpleNamespace(gemini_api_key=None))
    token = creator_token_factory("ingest_creator")
    response = TestClient(app).post(
        "/api/creator/ingest",
        headers=token,
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
    assert not {"title", "subject", "grade"}.intersection(lecture)
    assert lecture["transcript"][0]["text"] == "A vector has magnitude and direction."
    assert lecture["interventions"]
    assert service.get_lecture(lecture["id"]) is not None
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
