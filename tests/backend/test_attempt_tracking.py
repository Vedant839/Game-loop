from backend.database import get_database
from backend.schemas.lecture import Difficulty, Intervention, InterventionType, Lecture
from backend.services.session_service import SessionService


class _LectureService:
    def __init__(self, lecture):
        self.lecture = lecture

    def get_lecture(self, lecture_id):
        return self.lecture if lecture_id == self.lecture.id else None


def test_first_try_correct_is_persisted_once_on_initial_evaluation():
    lecture = Lecture(
        id="attempt_tracking",
        duration_seconds=30,
        video_url="https://example.com/video.mp4",
        interventions=[
            Intervention(
                id="checkpoint",
                trigger_time=10,
                concept="test concept",
                difficulty=Difficulty.EASY,
                type=InterventionType.SINGLE_CHOICE,
                question="Choose A",
                options=[{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                correct_answer="a",
            )
        ],
    )
    database = get_database()
    service = SessionService(lecture_service=_LectureService(lecture), db=database)
    state = service.create_session(lecture.id)
    session_id = state.session_id
    service.activate_intervention(session_id, "checkpoint", 10)

    result = service.submit_answer(
        session_id, "checkpoint", "incorrect-first-attempt", "b"
    )
    assert result.is_correct is False

    loaded = database.load_session(session_id)
    assert loaded["attempt_counts"]["checkpoint"] == 1
    assert loaded["first_try_correct"]["checkpoint"] is False

    # Later evaluations cannot overwrite the first recorded outcome.
    service.record_evaluation_completed(session_id, "checkpoint", is_correct=True)
    reloaded = SessionService(lecture_service=_LectureService(lecture), db=database)
    assert reloaded._get_or_load_session(session_id).first_try_correct["checkpoint"] is False
