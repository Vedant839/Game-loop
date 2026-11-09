from fastapi.testclient import TestClient

from backend.main import app
from tests.backend.test_v03_open_ended_and_skip import (
    lecture_with_open_ended,
    test_client as migrated_test_client,
)


client = TestClient(app)
PRIVATE_RESPONSE_FIELDS = {
    "correct_answer",
    "accepted_answers",
    "rubric",
    "key_concepts",
    "reference_answer",
    "reference_rubric",
    "misconceptions",
    "passing_score",
    "hints",
    "solution_code",
    "recall_pool",
}


def _assert_no_private_fields(value):
    if isinstance(value, dict):
        assert not (PRIVATE_RESPONSE_FIELDS & value.keys())
        for child in value.values():
            _assert_no_private_fields(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_private_fields(child)


def test_session_response_scan_through_completion(
    migrated_test_client, lecture_with_open_ended
):
    lecture_id = lecture_with_open_ended.id
    _assert_no_private_fields(client.get(f"/api/lectures/{lecture_id}").json())

    created = client.post(
        "/api/sessions",
        json={"lecture_id": lecture_id, "client_id": "scan_test", "learner_id": "student"},
    )
    assert created.status_code == 201
    session_id = created.json()["session_id"]
    _assert_no_private_fields(created.json())
    _assert_no_private_fields(client.get(f"/api/sessions/{session_id}").json())
    _assert_no_private_fields(client.get(f"/api/sessions/{session_id}/lecture").json())
    _assert_no_private_fields(
        client.post(f"/api/sessions/{session_id}/sync", json={"playback_position": 0}).json()
    )

    activated = client.post(
        f"/api/sessions/{session_id}/activate",
        json={"intervention_id": "q_skip", "playback_position": 10},
    )
    assert activated.status_code == 200
    _assert_no_private_fields(activated.json())
    _assert_no_private_fields(
        client.post(
            f"/api/sessions/{session_id}/hint", json={"intervention_id": "q_skip"}
        ).json()
    )
    answered = client.post(
        f"/api/sessions/{session_id}/submit",
        json={
            "intervention_id": "q_skip",
            "idempotency_key": "scan-answer",
            "answer": "yes",
        },
    )
    assert answered.status_code == 200
    _assert_no_private_fields(answered.json())

    open_ended_activation = client.post(
        f"/api/sessions/{session_id}/activate",
        json={"intervention_id": "q_open_req", "playback_position": 25},
    )
    assert open_ended_activation.status_code == 200
    _assert_no_private_fields(open_ended_activation.json())
    submission = client.post(
        f"/api/sessions/{session_id}/submissions/open-ended",
        json={
            "intervention_id": "q_open_req",
            "idempotency_key": "scan-open-ended",
            "user_answer": "Parallel lines preserve equal alternate interior angles.",
        },
    )
    assert submission.status_code == 202
    _assert_no_private_fields(submission.json())
    submission_id = submission.json()["submission_id"]
    status = client.get(
        f"/api/sessions/{session_id}/submissions/{submission_id}"
    )
    assert status.status_code == 200
    _assert_no_private_fields(status.json())

    assessed = client.post(
        f"/api/sessions/{session_id}/submissions/{submission_id}/self-assess",
        json={"self_assessed_correct": True},
    )
    assert assessed.status_code == 200
    _assert_no_private_fields(assessed.json())

    skipped_session = client.post("/api/sessions", json={"lecture_id": lecture_id}).json()
    skipped = client.post(
        f"/api/sessions/{skipped_session['session_id']}/interventions/q_skip/skip",
        json={"reason": "scan"},
    )
    assert skipped.status_code == 200
    _assert_no_private_fields(skipped.json())
