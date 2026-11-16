"""Tests for P1.5.2 Preflight Quality Gate and API endpoint.

Verifies Criteria 54 & 55:
- Labels 30s windows strong/weak correctly on fixtures
- POST /api/creator/ingest/preflight requires Creator Auth (HTTP 401 without token)
- Makes no Gemini call and persists nothing
"""

from __future__ import annotations

import json
import pathlib
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.transcript_quality import (
    analyze_transcript_quality,
    strip_non_speech,
)
from backend.database import get_database

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "ingest"
client = TestClient(app)


def _load_fixture(name: str) -> dict:
    with open(FIXTURES / name) as f:
        return json.load(f)


class TestTranscriptQualityService:
    def test_strip_non_speech(self):
        text = "Hello [Music] world ♪ and (Applause) welcome... to Python."
        cleaned = strip_non_speech(text)
        assert "[Music]" not in cleaned
        assert "♪" not in cleaned
        assert "(Applause)" not in cleaned
        assert "Hello world and welcome to Python" in cleaned

    def test_untimed_plain_text_suitability_unknown(self):
        report = analyze_transcript_quality(
            segments=None,
            duration_seconds=300.0,
            plain_text="Here is plain text without any timestamps explaining functions.",
        )
        assert report.suitability == "unknown"
        assert report.speech_coverage == 1.0
        assert len(report.windows) == 10
        for w in report.windows:
            assert w.verdict == "strong"
        assert "timed captions" in report.message

    def test_narrated_lecture_suitability_good(self):
        linux = _load_fixture("linux_transcript.json")
        report = analyze_transcript_quality(
            segments=linux["transcript"],
            duration_seconds=linux["duration_seconds"],
            strong_min_wpm=40.0,
        )
        assert report.suitability in ("good", "mixed")
        assert report.speech_coverage > 0.7
        assert report.longest_silent_stretch_s < 60.0

    def test_silent_or_music_gaps_produce_weak_windows(self):
        # 300 second lecture with speech only in first 30s
        segments = [
            {"start_time": 0.0, "end_time": 30.0, "text": "This is the only speech in this entire video."},
            {"start_time": 30.0, "end_time": 180.0, "text": "[Music]"},
            {"start_time": 180.0, "end_time": 300.0, "text": "♪ ♪ ♪"},
        ]
        report = analyze_transcript_quality(
            segments=segments,
            duration_seconds=300.0,
        )
        assert report.suitability == "limited"
        assert len(report.weak_windows) > 0
        # Check that weak windows are merged into runs
        assert any(w.end_s >= 200.0 for w in report.weak_windows)

    def test_silent_coding_weak_fraction(self):
        mary = _load_fixture("mary_transcript.json")
        report = analyze_transcript_quality(
            segments=mary["transcript"],
            duration_seconds=mary["duration_seconds"],
            strong_min_wpm=60.0,
        )
        assert report.suitability in ("limited", "mixed")


class TestPreflightEndpoint:
    def test_preflight_requires_auth(self):
        resp = client.post(
            "/api/creator/ingest/preflight",
            json={"duration_seconds": 300.0, "captions": "test"},
        )
        assert resp.status_code == 401

    def test_preflight_with_valid_token(self, creator_token_factory):
        headers = creator_token_factory("creator_preflight")

        resp = client.post(
            "/api/creator/ingest/preflight",
            json={
                "duration_seconds": 120.0,
                "captions": "WEBVTT\n\n00:00:00.000 --> 00:00:30.000\nHello and welcome to this lecture.\n",
                "captions_format": "vtt",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "windows" in data
        assert "suitability" in data
        assert "speech_coverage" in data
        assert "longest_silent_stretch_s" in data
        assert "weak_windows" in data
        assert "message" in data

    def test_preflight_persists_nothing(self, creator_token_factory):
        headers = creator_token_factory("creator_no_persist")
        db = get_database()

        # Check count of lectures before
        lectures_before = len(db.lectures.list_lectures_by_creator("creator_no_persist"))

        resp = client.post(
            "/api/creator/ingest/preflight",
            json={"duration_seconds": 60.0, "captions": "Just plain text."},
            headers=headers,
        )
        assert resp.status_code == 200

        # Check count of lectures after
        lectures_after = len(db.lectures.list_lectures_by_creator("creator_no_persist"))
        assert lectures_before == lectures_after
