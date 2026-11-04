"""Tests for game-loop V0.3 persistence, crash-recovery, and policy enforcement."""

import pytest
from backend.database import Database
from backend.schemas.lecture import (
    Difficulty,
    Intervention,
    InterventionPolicy,
    InterventionType,
    Lecture,
    Option,
    TimingConfig,
)
from backend.schemas.session import InterventionStateEnum
from backend.services.learner_service import LearnerService
from backend.services.lecture_service import LectureService
from backend.services.session_service import RuntimeSession, SessionError, SessionService


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_gameloop.db"
    return Database(db_path=db_file)


@pytest.fixture
def sample_lecture():
    intv_skippable = Intervention(
        id="intv_1",
        trigger_time=10.0,
        concept="math.angles",
        difficulty=Difficulty.EASY,
        type=InterventionType.SINGLE_CHOICE,
        question="What is 90 degrees?",
        options=[Option(id="opt_a", text="Right angle"), Option(id="opt_b", text="Acute angle")],
        correct_answer="opt_a",
        policy=InterventionPolicy.SKIPPABLE,
    )
    intv_required = Intervention(
        id="intv_2",
        trigger_time=25.0,
        concept="math.triangles",
        difficulty=Difficulty.MEDIUM,
        type=InterventionType.SINGLE_CHOICE,
        question="Sum of angles in a triangle?",
        options=[Option(id="opt_180", text="180"), Option(id="opt_360", text="360")],
        correct_answer="opt_180",
        policy=InterventionPolicy.REQUIRED,
    )
    return Lecture(
        id="test_lecture_persistence",
        title="Geometry Basics",
        subject="Mathematics",
        grade="Grade 9",
        duration_seconds=60.0,
        video_url="/media/sample.mp4",
        timing_config=TimingConfig(min_trigger_gap=10.0, tolerance=1.5),
        interventions=[intv_skippable, intv_required],
    )


class MockLectureService(LectureService):
    def __init__(self, lecture: Lecture):
        self.lecture = lecture

    def get_lecture(self, lecture_id: str) -> Lecture | None:
        if lecture_id == self.lecture.id:
            return self.lecture
        return None


def test_session_crash_recovery(temp_db, sample_lecture):
    mock_lectures = MockLectureService(sample_lecture)
    svc = SessionService(lecture_service=mock_lectures, db=temp_db)

    # 1. Create session
    session_state = svc.create_session(
        lecture_id=sample_lecture.id,
        client_id="acme_corp",
        external_user_id="alice",
    )
    session_id = session_state.session_id

    # 2. Activate first intervention
    svc.activate_intervention(session_id, "intv_1", playback_position=10.2)
    active_state = svc.get_session(session_id)
    assert active_state.active_intervention_id == "intv_1"
    assert active_state.version == 2

    # 3. Submit answer
    eval_result = svc.submit_answer(
        session_id=session_id,
        intervention_id="intv_1",
        idempotency_key="key_1",
        answer="opt_a",
    )
    assert eval_result.is_correct is True
    assert eval_result.session_state.version == 3

    # 4. SIMULATE SERVER RESTART: Create a brand new SessionService with empty memory cache
    recovered_svc = SessionService(lecture_service=mock_lectures, db=temp_db)
    assert session_id not in recovered_svc._sessions

    # 5. Load session from SQLite
    recovered_state = recovered_svc.get_session(session_id)
    assert recovered_state.session_id == session_id
    assert recovered_state.version == 3
    assert recovered_state.client_id == "acme_corp"
    assert recovered_state.external_user_id == "alice"
    assert recovered_state.active_intervention_id is None

    intv_states = {i.id: i.state for i in recovered_state.interventions}
    assert intv_states["intv_1"] == InterventionStateEnum.COMPLETED
    assert intv_states["intv_2"] == InterventionStateEnum.PENDING


def test_learner_profile_crash_recovery(temp_db):
    learner_svc = LearnerService(db=temp_db)

    delta, next_tier = learner_svc.record_attempt(
        client_id="tenant_x",
        user_id="bob",
        concept="algebra.linear",
        is_correct=True,
        tier=2,
    )
    assert delta > 0

    # SIMULATE SERVER RESTART: Create fresh service instance with empty in-memory cache
    fresh_learner_svc = LearnerService(db=temp_db)
    assert ("tenant_x", "bob") not in fresh_learner_svc._profiles

    recovered_profile = fresh_learner_svc.get_or_create_profile("tenant_x", "bob")
    assert recovered_profile.streak == 1
    assert recovered_profile.total_correct == 1
    assert recovered_profile.concept_mastery["algebra.linear"] == 0.70


def test_skip_policy_and_missing_evidence(temp_db, sample_lecture):
    mock_lectures = MockLectureService(sample_lecture)
    svc = SessionService(lecture_service=mock_lectures, db=temp_db)

    session_state = svc.create_session(
        lecture_id=sample_lecture.id,
        client_id="acme",
        external_user_id="charlie",
    )
    session_id = session_state.session_id

    # intv_1 is SKIPPABLE -> activate and skip
    svc.activate_intervention(session_id, "intv_1", playback_position=9.8)
    skipped_state = svc.skip_intervention(session_id, "intv_1")

    intv_1_state = next(i for i in skipped_state.interventions if i.id == "intv_1")
    assert intv_1_state.state == InterventionStateEnum.SKIPPED
    assert skipped_state.active_intervention_id is None

    # Verify learner mastery was not degraded (missing evidence, ΔM = 0)
    learner_svc = LearnerService(db=temp_db)
    profile = learner_svc.get_or_create_profile("acme", "charlie")
    assert profile.streak == 0
    assert profile.concept_mastery.get("math.angles", 0.5) == 0.5

    # Verify telemetry logged intervention_skipped
    events = temp_db.export_telemetry(client_id="acme")
    assert any(e["event_type"] == "intervention_skipped" for e in events)


def test_required_policy_enforcement(temp_db, sample_lecture):
    mock_lectures = MockLectureService(sample_lecture)
    svc = SessionService(lecture_service=mock_lectures, db=temp_db)

    session_state = svc.create_session(lecture_id=sample_lecture.id)
    session_id = session_state.session_id

    # 1. Attempting to skip REQUIRED intervention intv_2 must fail with 403
    with pytest.raises(SessionError) as exc_info:
        svc.skip_intervention(session_id, "intv_2")
    assert exc_info.value.status_code == 403
    assert "cannot be skipped" in exc_info.value.message

    # 2. Attempting to seek forward past REQUIRED intervention intv_2 must fail with 403
    # First complete intv_1
    svc.activate_intervention(session_id, "intv_1", playback_position=10.0)
    svc.submit_answer(session_id, "intv_1", idempotency_key="k1", answer="opt_a")

    # Now seek past intv_2 (trigger 25.0 + tol 1.5 = 26.5) to position 30.0
    with pytest.raises(SessionError) as seek_exc:
        svc.sync_playback(session_id, playback_position=30.0)
    assert seek_exc.value.status_code == 403
    assert "Cannot seek past required intervention" in seek_exc.value.message
