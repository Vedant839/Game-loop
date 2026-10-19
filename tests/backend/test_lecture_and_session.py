"""Unit and integration tests for lecture validation and runtime session state machine."""

import types

import pytest
from fastapi.testclient import TestClient

from backend.main import app, generate_interventions_for_lecture
from backend.schemas.lecture import Difficulty, Intervention, InterventionType, Lecture, Option, TimingConfig
from backend.services.lecture_service import LectureService, get_lecture_service
from backend.services.session_service import SessionError, SessionService

client = TestClient(app)


def test_timing_config_invariant_rejects_invalid_values() -> None:
    # 2 * tolerance >= min_trigger_gap must raise ValueError
    with pytest.raises(ValueError, match="Timing configuration invariant violated"):
        TimingConfig(min_trigger_gap=10.0, tolerance=5.0)


def test_api_only_lists_linear_algebra_and_custom_lectures() -> None:
    res = client.get("/api/lectures")
    assert res.status_code == 200
    lecture_ids = [item["id"] for item in res.json()]
    assert "linear_algebra_vectors" in lecture_ids
    assert "math_sample_lecture" not in lecture_ids
    assert "physics_kinematics" not in lecture_ids


def test_lecture_service_loads_canonical_sample_lecture() -> None:
    service = LectureService()
    lecture = service.get_lecture("math_sample_lecture")
    assert lecture is not None
    assert lecture.id == "math_sample_lecture"
    assert len(lecture.interventions) == 4
    assert lecture.interventions[0].type.value == "single_choice"
    assert lecture.interventions[2].type.value == "multiple_selection"


def test_generate_interventions_refreshes_runtime_lecture_without_old_interventions(monkeypatch) -> None:
    lecture_service = get_lecture_service()
    stale_lecture = lecture_service.get_lecture("linear_algebra_vectors")
    assert stale_lecture is not None
    stale_lecture = stale_lecture.model_copy(
        update={
            "interventions": [
                Intervention(
                    id="stale_int_1",
                    trigger_time=15.0,
                    concept="Old vector idea",
                    difficulty=Difficulty.EASY,
                    type=InterventionType.SINGLE_CHOICE,
                    question="This is a stale question from a previous generation.",
                    options=[
                        Option(id="opt_a", text="Stale option A"),
                        Option(id="opt_b", text="Stale option B"),
                        Option(id="opt_c", text="Stale option C"),
                        Option(id="opt_d", text="Stale option D"),
                    ],
                    correct_answer="opt_a",
                    correct_feedback="Correct.",
                    incorrect_feedback="Wrong.",
                )
            ]
        },
        deep=True,
    )
    lecture_service.set_runtime_lecture(stale_lecture)

    captured: dict[str, list[Intervention]] = {}

    def fake_generate(lecture: Lecture, api_key: str, target_count: int, max_count: int) -> Lecture:
        captured["before_generate"] = lecture.interventions
        return lecture.model_copy(
            update={
                "interventions": [
                    Intervention(
                        id="fresh_int_1",
                        trigger_time=30.0,
                        concept="Fresh vector idea",
                        difficulty=Difficulty.EASY,
                        type=InterventionType.SINGLE_CHOICE,
                        question="Which statement best matches the lecture's vector idea?",
                        options=[
                            Option(id="opt_a", text="Fresh option A"),
                            Option(id="opt_b", text="Fresh option B"),
                            Option(id="opt_c", text="Fresh option C"),
                            Option(id="opt_d", text="Fresh option D"),
                        ],
                        correct_answer="opt_a",
                        correct_feedback="Correct.",
                        incorrect_feedback="Wrong.",
                    )
                ]
            },
            deep=True,
        )

    monkeypatch.setattr("backend.main.generate_interventions_with_gemini", fake_generate)
    monkeypatch.setattr(
        "backend.main.settings",
        types.SimpleNamespace(gemini_api_key=types.SimpleNamespace(get_secret_value=lambda: "test-key")),
    )

    response = generate_interventions_for_lecture("linear_algebra_vectors")

    assert response.interventions[0].concept == "Fresh vector idea"
    assert captured["before_generate"] == []


def test_session_lifecycle_and_state_transitions() -> None:
    lecture_service = LectureService()
    session_service = SessionService(lecture_service=lecture_service)

    # 1. Create session
    session_state = session_service.create_session("math_sample_lecture")
    session_id = session_state.session_id
    assert session_state.version == 1
    assert session_state.active_intervention_id is None
    assert all(i.state == "PENDING" for i in session_state.interventions)

    # 2. Activate intervention int_1 at trigger_time 25.0 (tolerance 2.0 -> window [23.0, 27.0])
    active_payload = session_service.activate_intervention(
        session_id=session_id,
        intervention_id="int_1",
        playback_position=24.5,
    )
    assert active_payload.id == "int_1"
    assert active_payload.type == "single_choice"
    assert active_payload.session_state.active_intervention_id == "int_1"
    assert active_payload.session_state.version == 2
    assert active_payload.session_state.interventions[0].state == "ACTIVE"

    # 3. Attempting to activate another intervention while one is ACTIVE raises SessionError
    with pytest.raises(SessionError, match="currently ACTIVE"):
        session_service.activate_intervention(
            session_id=session_id,
            intervention_id="int_2",
            playback_position=55.0,
        )

    # 4. Submit incorrect answer for int_1
    eval_result = session_service.submit_answer(
        session_id=session_id,
        intervention_id="int_1",
        idempotency_key="key_1",
        answer="opt_b",
    )
    assert not eval_result.is_correct
    assert "Incorrect" in eval_result.feedback
    assert eval_result.session_state.active_intervention_id is None
    assert eval_result.session_state.interventions[0].state == "COMPLETED"
    assert eval_result.session_state.version == 3

    # 5. Idempotent submission returns identical result without version bump
    idempotent_result = session_service.submit_answer(
        session_id=session_id,
        intervention_id="int_1",
        idempotency_key="key_1",
        answer="opt_b",
    )
    assert idempotent_result == eval_result
    assert idempotent_result.session_state.version == 3

    # 6. Terminal state check: completed intervention cannot be reactivated
    with pytest.raises(SessionError, match="terminal state"):
        session_service.activate_intervention(
            session_id=session_id,
            intervention_id="int_1",
            playback_position=25.0,
        )


def test_session_uses_runtime_generated_lecture_without_persisting() -> None:
    lecture_service = LectureService()
    base_lecture = lecture_service.get_lecture("linear_algebra_vectors")
    assert base_lecture is not None
    assert base_lecture.interventions == []

    runtime_intervention = Intervention(
        id="runtime_int_1",
        trigger_time=30.0,
        concept="Vector Direction",
        difficulty=Difficulty.EASY,
        type=InterventionType.SINGLE_CHOICE,
        question="Which move best checks whether direction matters for this vector?",
        options=[
            Option(id="opt_a", text="Compare vectors with the same length but different directions."),
            Option(id="opt_b", text="Ignore direction and only compare length."),
            Option(id="opt_c", text="Switch to an unrelated formula."),
            Option(id="opt_d", text="Use any number from the transcript."),
        ],
        correct_answer="opt_a",
        correct_feedback="Correct. Direction is part of what defines a vector.",
        incorrect_feedback="Not quite. A vector carries both magnitude and direction.",
    )
    generated_lecture = base_lecture.model_copy(
        update={"interventions": [runtime_intervention]},
        deep=True,
    )

    lecture_service.set_runtime_lecture(generated_lecture)
    session_service = SessionService(lecture_service=lecture_service)

    session_state = session_service.create_session("linear_algebra_vectors")

    assert [i.id for i in session_state.interventions] == ["runtime_int_1"]
    reloaded_from_disk = LectureService().get_lecture("linear_algebra_vectors")
    assert reloaded_from_disk is not None
    assert reloaded_from_disk.interventions == []


def test_forward_seek_bypasses_pending_interventions() -> None:
    session_service = SessionService()
    session_state = session_service.create_session("math_sample_lecture")
    session_id = session_state.session_id

    # int_1 trigger_time is 25.0, tolerance is 2.0 -> window end is 27.0
    # int_2 trigger_time is 55.0, tolerance is 2.0 -> window end is 57.0
    # Seek to position 100.0 (past int_1 and int_2, before int_3 at 110.0)
    synced_state = session_service.sync_playback(session_id, playback_position=100.0)

    states = {i.id: i.state for i in synced_state.interventions}
    assert states["int_1"] == "BYPASSED"
    assert states["int_2"] == "BYPASSED"
    assert states["int_3"] == "PENDING"
    assert states["int_4"] == "PENDING"


def test_multiple_selection_deterministic_evaluation() -> None:
    session_service = SessionService()
    session_state = session_service.create_session("math_sample_lecture")
    session_id = session_state.session_id

    # Seek to int_3 window (trigger_time 110.0, tolerance 2.0 -> window [108.0, 112.0])
    session_service.activate_intervention(
        session_id=session_id,
        intervention_id="int_3",
        playback_position=110.0,
    )

    # Correct options for int_3: ["opt_sub3", "opt_div2"]
    eval_res = session_service.submit_answer(
        session_id=session_id,
        intervention_id="int_3",
        idempotency_key="key_ms_1",
        answer=["opt_div2", "opt_sub3"],  # Order shouldn't matter
    )

    assert eval_res.is_correct
    assert "Correct!" in eval_res.feedback
    assert eval_res.session_state.interventions[2].state == "COMPLETED"


def test_api_session_endpoints_integration() -> None:
    # 1. Create session via POST /api/sessions
    res = client.post("/api/sessions", json={"lecture_id": "math_sample_lecture"})
    assert res.status_code == 201
    session_data = res.json()
    session_id = session_data["session_id"]
    assert session_data["lecture_id"] == "math_sample_lecture"

    # 2. Activate intervention int_1 via POST /api/sessions/{session_id}/activate
    res_act = client.post(
        f"/api/sessions/{session_id}/activate",
        json={"intervention_id": "int_1", "playback_position": 25.0},
    )
    assert res_act.status_code == 200
    act_data = res_act.json()
    assert act_data["id"] == "int_1"

    # 3. Submit answer via POST /api/sessions/{session_id}/submit
    res_sub = client.post(
        f"/api/sessions/{session_id}/submit",
        json={
            "intervention_id": "int_1",
            "idempotency_key": "api_test_key_1",
            "answer": "opt_a",
        },
    )
    assert res_sub.status_code == 200
    sub_data = res_sub.json()
    assert sub_data["is_correct"] is True
    assert "Correct!" in sub_data["feedback"]


def test_media_serving_full_and_range_requests() -> None:
    # 1. Full GET request returns 200 OK
    res_full = client.get("/media/math_sample_lecture.mp4")
    assert res_full.status_code == 200

    # 2. HEAD request returns 200 OK with Content-Length and Accept-Ranges without body
    res_head = client.head("/media/math_sample_lecture.mp4")
    assert res_head.status_code == 200
    assert res_head.headers["accept-ranges"] == "bytes"
    assert int(res_head.headers["content-length"]) > 0
    assert len(res_head.content) == 0

    # 3. Range GET request returns 206 Partial Content
    res_range = client.get(
        "/media/math_sample_lecture.mp4",
        headers={"Range": "bytes=0-99"},
    )
    assert res_range.status_code == 206
    assert res_range.headers["accept-ranges"] == "bytes"
    assert "bytes 0-99/" in res_range.headers["content-range"]
    assert res_range.headers["content-length"] == "100"
    assert len(res_range.content) == 100


