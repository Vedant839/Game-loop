"""Recorded-fixture integration coverage for the concept-first ingest pipeline."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.database import get_database
from backend.main import app
from backend.schemas.lecture import Lecture
from backend.services.checkpoint_generator import checkpoint_count
from backend.services.ingest_pipeline import _chunks, run_understanding_pipeline
from backend.services.lecture_service import LectureService
from backend.utils.question_rules import filter_checkpoints

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ingest"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _as_srt(segments: list[dict]) -> str:
    def stamp(seconds: float) -> str:
        ms = int(round(seconds * 1000))
        hours, ms = divmod(ms, 3_600_000)
        minutes, ms = divmod(ms, 60_000)
        seconds_part, ms = divmod(ms, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds_part:02d},{ms:03d}"
    return "\n\n".join(
        f"{index}\n{stamp(seg['start_time'])} --> {stamp(seg['end_time'])}\n{seg['text']}"
        for index, seg in enumerate(segments, start=1)
    )


class FakeGeminiClient:
    """Fake Gemini transport: replies are fixture-derived and never use the network."""

    def __init__(
        self, concepts=None, *, fail_on: str | None = None,
        quota_on: str | None = None, invalid_on: str | None = None,
    ):
        self.concepts = concepts or []
        self.fail_on = fail_on
        self.quota_on = quota_on
        self.invalid_on = invalid_on
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        prompt = kwargs["contents"]
        self.calls.append(kwargs)
        stage = (
            "extract" if "TRANSCRIPT_START" in prompt
            else "generate" if "CONCEPT_DATA_START" in prompt
            else "critic"
        )
        if stage == self.fail_on:
            raise RuntimeError("provider failed; key=fixture-secret")
        if stage == self.quota_on:
            from backend.services.gemini_client import GeminiQuotaExceeded
            raise GeminiQuotaExceeded("quota")
        if stage == self.invalid_on:
            return SimpleNamespace(text="not valid json")

        if stage == "extract":
            data = {"concepts": self.concepts}
        elif stage == "generate":
            block = prompt.split("CONCEPT_DATA_START\n", 1)[1].split("\nCONCEPT_DATA_END", 1)[0]
            selected = json.loads(block)
            mary_questions = [
                "Which of the following was mentioned in the lecture?",
                "According to the instructor, what name was used in the greet example?",
                "What did the instructor say was printed when greet was called?",
                "What does return send back to the caller?",
            ]
            data = {"checkpoints": []}
            for index, concept in enumerate(selected):
                data["checkpoints"].append({
                    "concept_id": concept["concept_id"],
                    "type": "single_choice",
                    "question": mary_questions[index] if len(selected) == 4 else "What key idea does this concept explain?",
                    "options": [
                        {"id": "a", "text": "The concept's defining behavior"},
                        {"id": "b", "text": "A color and shape"},
                        {"id": "c", "text": "A mass and volume"},
                        {"id": "d", "text": "A speed and temperature"},
                    ],
                    "correct_answer": "a",
                })
        else:
            ids = re.findall(r"CHECKPOINT_START id=([^\s]+)", prompt)
            data = {"verdicts": [{"id": item, "verdict": "keep", "reason": ""} for item in ids]}
        return SimpleNamespace(text=json.dumps(data))


def _mary_concepts() -> list[dict]:
    return [
        {
            "name": "Function return values",
            "kind": "definition",
            "description": "A function can return a result to its caller.",
            "start_s": 90.0, "end_s": 120.0,
            "evidence": [{"source": "transcript", "quote": "A function can return a result instead of just printing."}],
        },
        {
            "name": "Using returned values",
            "kind": "procedure",
            "description": "A returned value can be assigned and reused.",
            "start_s": 180.0, "end_s": 240.0,
            "evidence": [{"source": "transcript", "quote": "You can assign the returned value to a variable and use it later."}],
        },
        {
            "name": "Keyword arguments",
            "kind": "syntax",
            "description": "Keyword arguments pass values by name.",
            "start_s": 300.0, "end_s": 360.0,
            "evidence": [{"source": "transcript", "quote": "Keyword arguments allow you to pass values by name rather than position"}],
        },
        {
            "name": "Global keyword behavior",
            "kind": "command",
            "description": "The global keyword lets a function modify an outer variable.",
            "start_s": 420.0, "end_s": 480.0,
            "evidence": [{"source": "transcript", "quote": "The global keyword lets a function modify a variable defined outside."}],
        },
    ]


def _run(lecture_data: dict, fake: FakeGeminiClient, *, intensity="standard") -> Lecture:
    return run_understanding_pipeline(
        Lecture.model_validate(lecture_data), intensity=intensity,
        api_key="fixture-api-key", creator_id="fixture_creator",
        gemini_client=fake, enforce_monthly_cap=False,
    )


def test_mary_pipeline_rejects_baseline_bad_stems_and_keeps_only_bound_checkpoints():
    data = _load("mary_transcript.json")
    # The recorded transcript is 10 minutes; this extended fixture variant has
    # enough placement capacity to exercise the full three-bad/one-good regression set.
    data["duration_seconds"] = 1000.0
    fake = FakeGeminiClient(_mary_concepts())
    result = _run(data, fake)

    baseline = _load("mary_baseline.json")["checkpoints"]
    rejected, dropped = filter_checkpoints([
        {
            "id": item["id"], "question": item["question"],
            "options": item["options"], "correct_answer": item["correct_answer"],
            "type": "single_choice",
        }
        for item in baseline
    ], skip_r4=True)
    assert not rejected
    assert len(dropped) == 3
    assert len(result.interventions) == 1
    assert all("mentioned in the lecture" not in item.question.lower() for item in result.interventions)
    concept_ids = {item["concept_id"] for item in result.concepts}
    assert all(item.concept_id in concept_ids and item.evidence for item in result.interventions)
    assert all(any(evidence.get("quote") for evidence in item.evidence) for item in result.interventions)
    assert result.analysis_report["generation"]["rejected_by_rules"] == 3
    assert all(
        item.get("rule") == "R1"
        for item in result.analysis_report["generation"]["rejections"]
        if item.get("stage") == "rules"
    )
    assert len([call for call in fake.calls if "CONCEPT_DATA_START" in call["contents"]]) == 1


def test_extraction_chunks_are_at_most_ten_minutes_with_thirty_second_overlap():
    segments = [
        {"start_time": 560.0, "end_time": 590.0, "text": "first"},
        {"start_time": 580.0, "end_time": 610.0, "text": "overlap"},
        {"start_time": 1170.0, "end_time": 1190.0, "text": "last"},
    ]
    chunks = _chunks(segments, 1200.0)
    assert [(start, end) for start, end, _ in chunks] == [
        (0.0, 600.0), (570.0, 1170.0), (1140.0, 1200.0),
    ]
    assert all(end - start <= 600.0 for start, end, _ in chunks)
    assert any(seg["text"] == "overlap" for seg in chunks[0][2])
    assert any(seg["text"] == "overlap" for seg in chunks[1][2])


def test_linux_short_lecture_output_obeys_checkpoint_and_gap_ceiling():
    data = _load("linux_transcript.json")
    data["duration_seconds"] = 161.0
    data["transcript"] = [
        segment for segment in data["transcript"]
        if segment["start_time"] < 161.0
    ]
    data["transcript"][-1]["end_time"] = min(data["transcript"][-1]["end_time"], 161.0)
    concepts = [{
        "name": "Linux file permissions", "kind": "definition",
        "description": "Permission characters encode access rights.",
        "start_s": 90.0, "end_s": 150.0,
        "evidence": [{"source": "transcript", "quote": "The next nine characters form three groups of three"}],
    }]
    result = _run(data, FakeGeminiClient(concepts))
    capacity_by_gap = max(0, int((161.0 - 20.0) // 90.0) + 1)
    assert len(result.interventions) <= checkpoint_count(161.0, "standard")
    assert len(result.interventions) <= capacity_by_gap
    assert result.generator_version == 2


def test_fabricated_evidence_quote_is_dropped_and_counted():
    data = _load("mary_transcript.json")
    concept = dict(_mary_concepts()[0])
    concept["evidence"] = [{"source": "transcript", "quote": "This fabricated supporting statement never occurred."}]
    result = _run(data, FakeGeminiClient([concept]))
    assert result.concepts == []
    assert result.analysis_report["generation"]["dropped_no_evidence"] == 1
    assert any(item["stage"] == "evidence" for item in result.analysis_report["generation"]["rejections"])


def test_creator_context_evidence_is_fenced_time_anchored_and_never_high_confidence():
    note = "A stable concept is supported by this creator note."
    lecture = Lecture.model_validate({
        "id": "context_fixture",
        "duration_seconds": 300,
        "video_url": "https://example.com/context.mp4",
        "transcript": [{
            "start_time": 90, "end_time": 120,
            "text": note,
        }],
        "interventions": [],
    })
    concept = {
        "name": "Stable concept", "kind": "definition",
        "description": "A stable concept is explained by the creator note.",
        "start_s": 90, "end_s": 120,
        "evidence": [{"source": "creator_context", "quote": note}],
    }
    fake = FakeGeminiClient([concept])
    result = run_understanding_pipeline(
        lecture, intensity="standard", api_key="fixture-api-key",
        creator_id="context_fixture", gemini_client=fake,
        enforce_monthly_cap=False,
        creator_context={
            "notes": note,
            "chapters": "00:00 Introduction\nmalformed chapter line",
        },
    )

    assert result.concepts[0]["confidence"] == "medium"
    assert result.interventions[0].review_state == "needs_review"
    assert result.concepts[0]["evidence"][0]["quote"] == note
    assert result.analysis_report["context_warnings"]
    extraction_prompt = next(call["contents"] for call in fake.calls if "TRANSCRIPT_START" in call["contents"])
    assert f"CONTEXT_START\n{note}\nCONTEXT_END" in extraction_prompt
    assert "CHAPTERS_START" in extraction_prompt
    assert "Introduction" in extraction_prompt


def test_context_size_limit_rejects_combined_notes_and_chapters(tmp_path, monkeypatch, creator_token_factory):
    import backend.main as main

    service = LectureService(tmp_path / "lectures")
    service.lectures_dir.mkdir(parents=True)
    monkeypatch.setattr(main, "get_lecture_service", lambda: service)
    response = TestClient(app).post(
        "/api/creator/ingest",
        headers=creator_token_factory("context_size"),
        json={
            "video_url": "https://example.com/context-size.mp4",
            "duration_seconds": 300,
            "creator_context": {"notes": "n" * 60_000, "chapters": "c" * 42_401},
        },
    )
    assert response.status_code == 422


def test_critic_failure_demotes_all_remaining_checkpoints_to_needs_review():
    result = _run(_load("mary_transcript.json"), FakeGeminiClient([_mary_concepts()[0]], fail_on="critic"))
    assert len(result.interventions) == 1
    assert result.interventions[0].review_state == "needs_review"
    assert result.analysis_report["critic_unavailable"] is True


def test_ingest_medium_checkpoint_is_hidden_from_public_and_session_lecture_routes(
    tmp_path, monkeypatch, creator_token_factory
):
    import backend.main as main
    import backend.services.session_service as session_module

    data = _load("mary_transcript.json")
    data["duration_seconds"] = 1000.0
    service = LectureService(tmp_path / "lectures")
    service.lectures_dir.mkdir(parents=True)
    db = get_database()
    monkeypatch.setattr(session_module, "get_lecture_service", lambda: service)
    monkeypatch.setattr(main, "settings", SimpleNamespace(gemini_api_key=None))
    fake = FakeGeminiClient(_mary_concepts())
    monkeypatch.setitem(app.dependency_overrides, main.get_gemini_client, lambda: fake)
    response = TestClient(app).post(
        "/api/creator/ingest",
        headers={**creator_token_factory("p151_creator"), "X-Gemini-Key": "fixture-api-key"},
        json={
            "video_url": data["video_url"], "duration_seconds": data["duration_seconds"],
            "captions": _as_srt(data["transcript"]),
            "captions_format": "srt", "intensity": "standard",
            "creator_context": {
                "notes": "private-ingest-context-sentinel",
                "chapters": "00:00 Private chapter sentinel",
            },
        },
    )
    assert response.status_code == 201
    lecture_id = response.json()["id"]
    assert response.json()["interventions"][0]["review_state"] == "needs_review"

    public_payload = TestClient(app).get(f"/api/lectures/{lecture_id}").json()
    assert public_payload["interventions"] == []
    assert not {"concepts", "analysis_report", "creator_context", "visual_evidence"}.intersection(public_payload)
    assert "private-ingest-context-sentinel" not in json.dumps(public_payload)
    assert "Private chapter sentinel" not in json.dumps(public_payload)

    session_response = TestClient(app).post("/api/sessions", json={"lecture_id": lecture_id})
    assert session_response.status_code == 201
    session_payload = TestClient(app).get(
        f"/api/sessions/{session_response.json()['session_id']}/lecture"
    ).json()
    assert session_payload["interventions"] == []
    assert not {"concepts", "analysis_report", "creator_context", "visual_evidence"}.intersection(session_payload)
    assert "private-ingest-context-sentinel" not in json.dumps(session_payload)
    assert "Private chapter sentinel" not in json.dumps(session_payload)


def test_ingest_session_uses_repository_and_excludes_needs_review(tmp_path, monkeypatch, creator_token_factory):
    import backend.main as main
    import backend.services.session_service as session_module
    from backend.config import get_settings
    from backend.services.session_service import get_session_service

    service = LectureService(tmp_path / "lectures")
    service.lectures_dir.mkdir(parents=True)

    def fail_if_file_service_is_used(_lecture_id):
        raise AssertionError("session creation and restore must use lectures.content")

    monkeypatch.setattr(service, "get_lecture", fail_if_file_service_is_used)
    monkeypatch.setattr(session_module, "get_lecture_service", lambda: service)
    monkeypatch.setattr(main, "settings", SimpleNamespace(gemini_api_key=None))

    class TwoConfidenceFake(FakeGeminiClient):
        def generate_content(self, **kwargs):
            if "CONCEPT_DATA_START" not in kwargs["contents"]:
                return super().generate_content(**kwargs)
            selected = json.loads(
                kwargs["contents"].split("CONCEPT_DATA_START\n", 1)[1]
                .split("\nCONCEPT_DATA_END", 1)[0]
            )
            return SimpleNamespace(text=json.dumps({"checkpoints": [
                {
                    "concept_id": concept["concept_id"],
                    "type": "single_choice",
                    "question": f"Which statement describes {concept['name']}?",
                    "options": [
                        {"id": "a", "text": "The defining behavior"},
                        {"id": "b", "text": "A color and shape"},
                        {"id": "c", "text": "A mass and volume"},
                        {"id": "d", "text": "A speed and temperature"},
                    ],
                    "correct_answer": "a",
                }
                for concept in selected
            ]}))

    concepts = [
        {
            "name": "Auto concept", "kind": "definition",
            "description": "The first concept has independently supported evidence.",
            "start_s": 1.0, "end_s": 4.0,
            "evidence": [
                {"source": "transcript", "quote": "An auto concept is supported by stable transcript evidence."},
                {"source": "creator_context", "quote": "The auto concept is also supported by this creator note."},
            ],
        },
        {
            "name": "Review concept", "kind": "definition",
            "description": "The second concept has only one weak transcript source.",
            "start_s": 211.0, "end_s": 214.0,
            "evidence": [
                {"source": "transcript", "quote": "A review concept has only this transcript evidence."},
            ],
        },
    ]
    fake = TwoConfidenceFake(concepts)
    monkeypatch.setitem(app.dependency_overrides, main.get_gemini_client, lambda: fake)

    response = TestClient(app).post(
        "/api/creator/ingest",
        headers={
            **creator_token_factory("p151_db_session"),
            "X-Gemini-Key": "fixture-api-key",
        },
        json={
            "video_url": "https://example.com/review-filter.mp4",
            "duration_seconds": 500,
            "captions": (
                "1\n00:00:01,000 --> 00:00:04,000\n"
                "An auto concept is supported by stable transcript evidence.\n\n"
                "2\n00:03:31,000 --> 00:03:34,000\n"
                "A review concept has only this transcript evidence."
            ),
            "captions_format": "srt",
            "intensity": "standard",
            "creator_context": {"notes": "The auto concept is also supported by this creator note."},
        },
    )
    assert response.status_code == 201, response.text
    lecture_id = response.json()["id"]
    interventions = response.json()["interventions"]
    auto = next(item for item in interventions if item["review_state"] == "auto")
    needs_review = next(item for item in interventions if item["review_state"] == "needs_review")

    database_row = get_database().lectures.get_lecture(lecture_id)
    assert database_row is not None
    assert json.loads(database_row["content"])["id"] == lecture_id
    assert not (get_settings().lectures_dir / f"{lecture_id}.json").exists()
    assert list(service.lectures_dir.glob("*.json")) == []

    client = TestClient(app)
    created = client.post("/api/sessions", json={"lecture_id": lecture_id})
    assert created.status_code == 201, created.text
    session_id = created.json()["session_id"]
    assert [item["id"] for item in created.json()["interventions"]] == [auto["id"]]
    stored_session = get_database().load_session(session_id)
    assert set(stored_session["interventions_state"]) == {auto["id"]}
    session_lecture = client.get(f"/api/sessions/{session_id}/lecture")
    assert "The auto concept is also supported by this creator note." not in session_lecture.text

    session_service = get_session_service()
    session_service._sessions.pop(session_id)
    restored = client.get(f"/api/sessions/{session_id}")
    assert restored.status_code == 200
    assert [item["id"] for item in restored.json()["interventions"]] == [auto["id"]]

    rejected_submission = client.post(
        f"/api/sessions/{session_id}/submit",
        json={
            "intervention_id": needs_review["id"],
            "idempotency_key": "hidden-review-checkpoint",
            "answer": "a",
        },
    )
    assert rejected_submission.status_code == 404


def test_provider_failure_returns_safe_502_and_does_not_persist(tmp_path, monkeypatch, creator_token_factory, caplog):
    import backend.main as main

    service = LectureService(tmp_path / "lectures")
    service.lectures_dir.mkdir(parents=True)
    monkeypatch.setattr(main, "get_lecture_service", lambda: service)
    monkeypatch.setattr(main, "settings", SimpleNamespace(gemini_api_key=None))
    fake = FakeGeminiClient([], fail_on="extract")
    monkeypatch.setitem(app.dependency_overrides, main.get_gemini_client, lambda: fake)
    response = TestClient(app).post(
        "/api/creator/ingest",
        headers={**creator_token_factory("p151_failure"), "X-Gemini-Key": "fixture-secret"},
        json={
            "video_url": "https://example.com/failure.mp4", "duration_seconds": 300,
            "captions": "A sufficiently described concept appears in this lecture.",
            "captions_format": "text", "intensity": "standard",
        },
    )
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "understanding_unavailable"
    assert "fixture-secret" not in response.text
    assert "fixture-secret" not in caplog.text
    assert list(service.lectures_dir.glob("*.json")) == []


def test_quota_failure_returns_429_without_persisting(tmp_path, monkeypatch, creator_token_factory):
    import backend.main as main

    service = LectureService(tmp_path / "lectures")
    service.lectures_dir.mkdir(parents=True)
    monkeypatch.setattr(main, "get_lecture_service", lambda: service)
    monkeypatch.setattr(main, "settings", SimpleNamespace(gemini_api_key=None))
    fake = FakeGeminiClient([], quota_on="extract")
    monkeypatch.setitem(app.dependency_overrides, main.get_gemini_client, lambda: fake)
    response = TestClient(app).post(
        "/api/creator/ingest",
        headers={**creator_token_factory("p151_quota"), "X-Gemini-Key": "fixture-api-key"},
        json={
            "video_url": "https://example.com/quota.mp4", "duration_seconds": 300,
            "captions": "A sufficiently described concept appears in this lecture.",
            "captions_format": "text", "intensity": "standard",
        },
    )
    assert response.status_code == 429
    assert list(service.lectures_dir.glob("*.json")) == []


def test_ingest_without_key_returns_understanding_unavailable(tmp_path, monkeypatch, creator_token_factory):
    import backend.main as main

    service = LectureService(tmp_path / "lectures")
    service.lectures_dir.mkdir(parents=True)
    monkeypatch.setattr(main, "get_lecture_service", lambda: service)
    monkeypatch.setattr(main, "settings", SimpleNamespace(gemini_api_key=None))
    fake = FakeGeminiClient([])
    monkeypatch.setitem(app.dependency_overrides, main.get_gemini_client, lambda: fake)
    response = TestClient(app).post(
        "/api/creator/ingest",
        headers=creator_token_factory("p151_no_key"),
        json={
            "video_url": "https://example.com/no-key.mp4", "duration_seconds": 300,
            "captions": "A sufficiently described concept appears in this lecture.",
            "captions_format": "text", "intensity": "standard",
        },
    )
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "understanding_unavailable"
    assert fake.calls == []
    assert list(service.lectures_dir.glob("*.json")) == []


def test_invalid_generation_output_returns_502_without_persisting(tmp_path, monkeypatch, creator_token_factory):
    import backend.main as main

    service = LectureService(tmp_path / "lectures")
    service.lectures_dir.mkdir(parents=True)
    monkeypatch.setattr(main, "get_lecture_service", lambda: service)
    monkeypatch.setattr(main, "settings", SimpleNamespace(gemini_api_key=None))
    fake = FakeGeminiClient([{
        "name": "Vector properties", "kind": "definition",
        "description": "A vector has magnitude and direction.",
        "start_s": 1.0, "end_s": 4.0,
        "evidence": [{"source": "transcript", "quote": "A vector has magnitude and direction."}],
    }], invalid_on="generate")
    monkeypatch.setitem(app.dependency_overrides, main.get_gemini_client, lambda: fake)
    response = TestClient(app).post(
        "/api/creator/ingest",
        headers={**creator_token_factory("p151_invalid"), "X-Gemini-Key": "fixture-api-key"},
        json={
            "video_url": "https://example.com/invalid.mp4", "duration_seconds": 300,
            "captions": "1\n00:00:01,000 --> 00:00:04,000\nA vector has magnitude and direction.",
            "captions_format": "srt", "intensity": "standard",
        },
    )
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "understanding_unavailable"
    assert "analysis_report" in response.json()["detail"]
    assert list(service.lectures_dir.glob("*.json")) == []
