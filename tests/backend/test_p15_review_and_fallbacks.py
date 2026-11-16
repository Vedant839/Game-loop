"""Tests for P1.5.3, P1.5.4, P1.5.5, and P1.5.6:
- Creator Context parsing, limits & chapters (Criterion 64)
- Visual Evidence validation & backend static scan (Criteria 65 & 66)
- Checkpoint Review State & Approve APIs (Criteria 26 & 61)
- Fallback reflect checkpoints on unchecked gaps (Criterion 62)
"""

from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import get_database
from backend.schemas.lecture import Lecture, Intervention, Difficulty, InterventionType, TimingConfig
from backend.utils.chapters import parse_chapters
from backend.utils.visual_evidence import validate_visual_evidence
from backend.services.checkpoint_generator import insert_fallback_reflections, MAX_UNCHECKED_GAP_SECONDS

client = TestClient(app)


# ---------------------------------------------------------------------------
# Criterion 64: Chapters & Creator Context limits
# ---------------------------------------------------------------------------


class TestChaptersAndContext:
    def test_parse_chapters_valid(self):
        text = """
        00:00 Introduction
        01:23 Getting Started
        12:45 Deep Dive
        01:05:30 Conclusion
        """
        result = parse_chapters(text)
        assert len(result.chapters) == 4
        assert result.chapters[0].time_s == 0.0
        assert result.chapters[0].title == "Introduction"
        assert result.chapters[1].time_s == 83.0
        assert result.chapters[2].time_s == 765.0
        assert result.chapters[3].time_s == 3930.0
        assert len(result.warnings) == 0

    def test_parse_chapters_with_malformed_lines(self):
        text = "00:00 Introduction\nThis is just a comment, not a chapter line\n02:15 Valid Chapter\ninvalid:timestamp Bad Line"
        result = parse_chapters(text)
        assert len(result.chapters) == 2
        assert len(result.warnings) == 2
        assert "Line 2" in result.warnings[0]
        assert "Line 4" in result.warnings[1]

    def test_creator_context_size_limit_rejection(self, creator_token_factory):
        headers = creator_token_factory("ctx_creator")
        oversized_notes = "x" * (101 * 1024)  # 101 KB > 100 KB limit

        resp = client.post(
            "/api/creator/ingest",
            json={
                "video_url": "https://example.com/video.mp4",
                "duration_seconds": 120.0,
                "captions": "test",
                "creator_context": {"notes": oversized_notes},
            },
            headers=headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Criteria 65 & 66: Visual Evidence Validation & Backend Static Scan
# ---------------------------------------------------------------------------


class TestVisualEvidence:
    def test_validate_visual_evidence_within_weak_window(self):
        weak_windows = [{"start_s": 30.0, "end_s": 90.0}]
        raw = [
            {"id": "v1", "start_s": 35.0, "end_s": 60.0, "description": "Shows terminal command", "code": "ls -la"},
            {"id": "v2", "start_s": 120.0, "end_s": 150.0, "description": "Outside weak window"},  # outside
        ]
        valid, rejected = validate_visual_evidence(raw, weak_windows=weak_windows)
        assert len(valid) == 1
        assert valid[0]["id"] == "v1"
        assert rejected == 1

    def test_backend_contains_no_video_upload_or_gemini_video_calls(self):
        """Criterion 66: Static scan verifying backend never uploads video bytes or sends video to Gemini."""
        import pathlib
        backend_dir = pathlib.Path(__file__).parent.parent.parent / "backend"
        for py_file in backend_dir.glob("**/*.py"):
            text = py_file.read_text(encoding="utf-8")
            # Backend must never upload files to Gemini File API or handle raw video bytes
            assert "client.files.upload" not in text, f"Found video upload in {py_file}"
            assert "mime_type=\"video/" not in text, f"Found video mime type in {py_file}"
            assert "mime_type='video/" not in text, f"Found video mime type in {py_file}"


# ---------------------------------------------------------------------------
# Criteria 26 & 61: Review State, Approval & Editing
# ---------------------------------------------------------------------------


class TestReviewStateAndApproval:
    def _create_sample_lecture(self, db, creator_id="rev_creator") -> Lecture:
        lec = Lecture(
            id=f"lec_{creator_id}",
            duration_seconds=300.0,
            video_url="https://example.com/lec.mp4",
            timing_config=TimingConfig(min_trigger_gap=15.0, tolerance=2.0),
            interventions=[
                Intervention(
                    id="chk_auto",
                    trigger_time=30.0,
                    concept="Concept 1",
                    difficulty=Difficulty.EASY,
                    type=InterventionType.SINGLE_CHOICE,
                    question="Question 1?",
                    options=[{"id": "a", "text": "Opt A"}, {"id": "b", "text": "Opt B"}],
                    correct_answer="a",
                    review_state="auto",
                    revision=1,
                ),
                Intervention(
                    id="chk_needs_review",
                    trigger_time=90.0,
                    concept="Concept 2",
                    difficulty=Difficulty.MEDIUM,
                    type=InterventionType.SINGLE_CHOICE,
                    question="Question 2?",
                    options=[{"id": "a", "text": "Opt A"}, {"id": "b", "text": "Opt B"}],
                    correct_answer="a",
                    review_state="needs_review",
                    revision=1,
                ),
            ],
        )
        db.lectures.save_lecture(
            lecture_id=lec.id,
            creator_id=creator_id,
            title=lec.id,
            video_url=lec.video_url,
            source_type="direct",
            content_json=lec.model_dump_json(),
        )
        return lec

    def test_approve_single_checkpoint_does_not_increment_revision(self, creator_token_factory):
        db = get_database()
        headers = creator_token_factory("creator_appr_1")
        lec = self._create_sample_lecture(db, "creator_appr_1")

        resp = client.post(
            f"/api/studio/lectures/{lec.id}/checkpoints/chk_needs_review/approve",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert data["intervention"]["review_state"] == "approved"
        # Approving alone does NOT change revision
        assert data["intervention"]["revision"] == 1

        # Check DB reflects approval
        stored = db.lectures.get_lecture(lec.id)
        updated_lec = Lecture.model_validate_json(stored["content"])
        target = next(i for i in updated_lec.interventions if i.id == "chk_needs_review")
        assert target.review_state == "approved"
        assert target.revision == 1

        created_session = client.post("/api/sessions", json={"lecture_id": lec.id})
        assert created_session.status_code == 201
        assert {item["id"] for item in created_session.json()["interventions"]} == {
            "chk_auto", "chk_needs_review"
        }

    def test_approve_flagged_approves_all_medium_confidence(self, creator_token_factory):
        db = get_database()
        headers = creator_token_factory("creator_appr_all")
        lec = self._create_sample_lecture(db, "creator_appr_all")

        resp = client.post(
            f"/api/studio/lectures/{lec.id}/approve_flagged",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["approved_count"] == 1

    def test_edit_checkpoint_increments_revision_and_approves(self, creator_token_factory):
        db = get_database()
        headers = creator_token_factory("creator_edit")
        lec = self._create_sample_lecture(db, "creator_edit")

        resp = client.put(
            f"/api/studio/lectures/{lec.id}/checkpoints/chk_needs_review",
            json={"question": "Updated Question 2 with better wording?"},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "updated"
        # Editing sets review_state to approved AND increments revision
        assert data["intervention"]["review_state"] == "approved"
        assert data["intervention"]["revision"] == 2
        assert data["intervention"]["question"] == "Updated Question 2 with better wording?"

    def test_approve_endpoints_enforce_creator_scoping(self, creator_token_factory):
        db = get_database()
        self._create_sample_lecture(db, "owner_creator")
        other_headers = creator_token_factory("other_creator")

        # Other creator cannot approve owner's checkpoint
        resp = client.post(
            "/api/studio/lectures/lec_owner_creator/checkpoints/chk_needs_review/approve",
            headers=other_headers,
        )
        assert resp.status_code == 404
        bulk_resp = client.post(
            "/api/studio/lectures/lec_owner_creator/approve_flagged",
            headers=other_headers,
        )
        assert bulk_resp.status_code == 404


# ---------------------------------------------------------------------------
# Criterion 62: Fallback reflect checkpoints on unchecked gaps
# ---------------------------------------------------------------------------


class TestFallbackReflections:
    def test_fallback_inserted_on_gap_with_weak_windows(self):
        # 1200s lecture with checkpoints at 60s and 800s (gap = 740s > 480s)
        lec = Lecture(
            id="gap_lec",
            duration_seconds=1200.0,
            video_url="https://example.com/video.mp4",
            timing_config=TimingConfig(min_trigger_gap=15.0, tolerance=2.0),
            interventions=[
                Intervention(
                    id="chk_1",
                    trigger_time=60.0,
                    concept="C1",
                    difficulty=Difficulty.EASY,
                    type=InterventionType.SINGLE_CHOICE,
                    question="Q1?",
                    options=[{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                    correct_answer="a",
                ),
                Intervention(
                    id="chk_2",
                    trigger_time=800.0,
                    concept="C2",
                    difficulty=Difficulty.EASY,
                    type=InterventionType.SINGLE_CHOICE,
                    question="Q2?",
                    options=[{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                    correct_answer="a",
                ),
            ],
        )
        weak_windows = [{"start_s": 200.0, "end_s": 400.0}]

        result = insert_fallback_reflections(lec, weak_windows=weak_windows, max_gap=480.0)
        assert len(result.interventions) == 3
        fb = next((i for i in result.interventions if i.id.startswith("fb_chk_")), None)
        assert fb is not None
        assert fb.origin == "fallback"
        assert fb.policy.value == "skippable"
        assert fb.rubric is None
        assert fb.type.value == "open_ended"
        assert "In your own words" in fb.question

    def test_no_fallback_when_gap_is_small(self):
        lec = Lecture(
            id="small_gap_lec",
            duration_seconds=300.0,
            video_url="https://example.com/video.mp4",
            timing_config=TimingConfig(min_trigger_gap=15.0, tolerance=2.0),
            interventions=[
                Intervention(
                    id="chk_1",
                    trigger_time=60.0,
                    concept="C1",
                    difficulty=Difficulty.EASY,
                    type=InterventionType.SINGLE_CHOICE,
                    question="Q1?",
                    options=[{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                    correct_answer="a",
                ),
                Intervention(
                    id="chk_2",
                    trigger_time=200.0,
                    concept="C2",
                    difficulty=Difficulty.EASY,
                    type=InterventionType.SINGLE_CHOICE,
                    question="Q2?",
                    options=[{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                    correct_answer="a",
                ),
            ],
        )
        weak_windows = [{"start_s": 80.0, "end_s": 150.0}]
        # Gap is 140s <= 480s -> no fallback inserted
        result = insert_fallback_reflections(lec, weak_windows=weak_windows, max_gap=480.0)
        assert len(result.interventions) == 2

    def test_no_fallback_when_gap_has_no_weak_windows(self):
        lec = Lecture(
            id="strong_gap_lec",
            duration_seconds=1200.0,
            video_url="https://example.com/video.mp4",
            timing_config=TimingConfig(min_trigger_gap=15.0, tolerance=2.0),
            interventions=[
                Intervention(
                    id="chk_1",
                    trigger_time=60.0,
                    concept="C1",
                    difficulty=Difficulty.EASY,
                    type=InterventionType.SINGLE_CHOICE,
                    question="Q1?",
                    options=[{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                    correct_answer="a",
                ),
                Intervention(
                    id="chk_2",
                    trigger_time=800.0,
                    concept="C2",
                    difficulty=Difficulty.EASY,
                    type=InterventionType.SINGLE_CHOICE,
                    question="Q2?",
                    options=[{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
                    correct_answer="a",
                ),
            ],
        )
        # Empty weak windows (all strong) -> no fallback needed
        result = insert_fallback_reflections(lec, weak_windows=[], max_gap=480.0)
        assert len(result.interventions) == 2
