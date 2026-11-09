from datetime import datetime, timedelta, timezone

from backend.database import get_database
from backend.schemas.lecture import Lecture, TimingConfig, TranscriptSegment
from backend.services.lecture_service import LectureService
from backend.services.session_service import SessionService
from scripts.migrate import migrate_database


def test_tab_return_requires_more_than_sixty_seconds_and_obeys_cooldown(tmp_path, monkeypatch):
    migrate_database(get_database().db_path)
    lecture = Lecture(
        id="tab_recall_test", title="Tab recall", subject="Science", grade="12",
        duration_seconds=300, video_url="https://example.com/video.mp4",
        timing_config=TimingConfig(),
        transcript=[TranscriptSegment(start_time=0, end_time=10, text="Vectors <script>alert(1)</script> have magnitude.")],
        recall_pool=[{"id": "recall_1", "question": "What is a vector? <script>alert(1)</script>", "expected_answer": "hidden secret answer"}],
    )
    lecture_service = LectureService(tmp_path / "lectures")
    lecture_service.set_runtime_lecture(lecture)
    service = SessionService(lecture_service=lecture_service, db=get_database())
    session_id = service.create_session(lecture.id).session_id

    assert service.tab_event(session_id, 60)["reason"] == "away_time_too_short"
    response = service.tab_event(session_id, 61)
    assert "<script>" not in response["card"]["question"]
    assert "What is a vector?" in response["card"]["question"]
    assert "expected_answer" not in str(response)
    assert service.tab_event(session_id, 500)["reason"] == "cooldown"

    restarted_service = SessionService(lecture_service=lecture_service, db=get_database())
    assert restarted_service.tab_event(session_id, 61)["reason"] == "cooldown"
    old_timestamp = (datetime.now(timezone.utc) - timedelta(seconds=301)).isoformat()
    monkeypatch.setattr(get_database().telemetry, "latest_tab_recall", lambda _session: old_timestamp)
    second = restarted_service.tab_event(session_id, 61)
    assert second["card"] is not None
