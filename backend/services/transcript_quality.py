"""Deterministic transcript quality analyzer and preflight gate.

Implements §7.3.1 of the Game-Loop V0.4 Content Understanding Layer.
Analyzes caption timing and word density in 30-second windows without making
any LLM or external provider calls. Nothing is persisted.
"""

from __future__ import annotations

import re
from typing import Any
from pydantic import BaseModel, Field

# Default thresholds (configurable per §7.3.1)
DEFAULT_STRONG_MIN_WPM: float = 60.0
DEFAULT_STRONG_MIN_COVERAGE: float = 0.5
WINDOW_SIZE_SECONDS: float = 30.0

_NON_SPEECH_PATTERN = re.compile(
    r"(\[music\]|\[silence\]|\[applause\]|\[laughter\]|\[no audio\]|\[inaudible\]|\(music\)|\(applause\)|♪+|\.{3,})",
    re.IGNORECASE,
)


class WindowReport(BaseModel):
    start_s: float
    end_s: float
    words: int
    coverage: float
    verdict: str  # "strong" | "weak"


class WeakSpan(BaseModel):
    start_s: float
    end_s: float


class PreflightReport(BaseModel):
    windows: list[WindowReport]
    speech_coverage: float
    longest_silent_stretch_s: float
    weak_windows: list[WeakSpan]
    suitability: str  # "good" | "mixed" | "limited" | "unknown"
    message: str


def strip_non_speech(text: str) -> str:
    """Remove non-speech tags such as [Music], (Applause), ♪, etc."""
    cleaned = _NON_SPEECH_PATTERN.sub(" ", text)
    return " ".join(cleaned.split())


def analyze_transcript_quality(
    segments: list[dict[str, Any]] | None,
    duration_seconds: float,
    plain_text: str | None = None,
    strong_min_wpm: float = DEFAULT_STRONG_MIN_WPM,
    strong_min_coverage: float = DEFAULT_STRONG_MIN_COVERAGE,
) -> PreflightReport:
    """Analyze caption timing and word density across 30-second windows.

    If segments are absent or have no timestamps (plain text only),
    suitability is 'unknown', all windows are treated as 'strong',
    and the message notes that timestamped captions give better placement.
    """
    if duration_seconds <= 0:
        duration_seconds = 1.0

    # Handle untimed plain text or empty segments
    if not segments:
        text = plain_text or ""
        words = len(strip_non_speech(text).split())
        num_windows = max(1, int(duration_seconds // WINDOW_SIZE_SECONDS) + (1 if duration_seconds % WINDOW_SIZE_SECONDS > 0 else 0))
        windows = [
            WindowReport(
                start_s=i * WINDOW_SIZE_SECONDS,
                end_s=min((i + 1) * WINDOW_SIZE_SECONDS, duration_seconds),
                words=words // num_windows,
                coverage=1.0,
                verdict="strong",
            )
            for i in range(num_windows)
        ]
        return PreflightReport(
            windows=windows,
            speech_coverage=1.0,
            longest_silent_stretch_s=0.0,
            weak_windows=[],
            suitability="unknown",
            message="No timestamped captions provided. Checkpoints will be placed uniformly. Providing timed captions (SRT/VTT) gives much better checkpoint placement.",
        )

    # Process timed segments
    # Filter and clean segments
    cleaned_segments = []
    for s in segments:
        text = strip_non_speech(str(s.get("text", "")))
        start = float(s.get("start_time", s.get("start_s", 0.0)))
        end = float(s.get("end_time", s.get("end_s", 0.0)))
        if end > start and text:
            cleaned_segments.append({"start": start, "end": end, "words": len(text.split()), "text": text})

    cleaned_segments.sort(key=lambda x: x["start"])

    # Calculate speech coverage and longest silent stretch
    total_speech_seconds = 0.0
    longest_silent_stretch = 0.0
    last_speech_end = 0.0

    for seg in cleaned_segments:
        if seg["start"] > last_speech_end:
            silent_gap = seg["start"] - last_speech_end
            if silent_gap > longest_silent_stretch:
                longest_silent_stretch = silent_gap
        # Effective non-overlapping duration
        overlap_start = max(seg["start"], last_speech_end)
        if seg["end"] > overlap_start:
            total_speech_seconds += (seg["end"] - overlap_start)
            last_speech_end = seg["end"]

    # Trailing silence after last segment
    if duration_seconds > last_speech_end:
        silent_gap = duration_seconds - last_speech_end
        if silent_gap > longest_silent_stretch:
            longest_silent_stretch = silent_gap

    overall_speech_coverage = round(min(1.0, total_speech_seconds / duration_seconds), 2)

    # Compute windows
    windows: list[WindowReport] = []
    t = 0.0
    while t < duration_seconds:
        window_end = min(t + WINDOW_SIZE_SECONDS, duration_seconds)
        window_dur = window_end - t

        # Calculate words and coverage within this window
        words_in_window = 0.0
        covered_seconds = 0.0

        for seg in cleaned_segments:
            overlap_s = max(seg["start"], t)
            overlap_e = min(seg["end"], window_end)
            if overlap_e > overlap_s:
                dur = seg["end"] - seg["start"]
                portion = (overlap_e - overlap_s) / dur if dur > 0 else 0
                words_in_window += seg["words"] * portion
                covered_seconds += (overlap_e - overlap_s)

        coverage = covered_seconds / window_dur if window_dur > 0 else 0.0
        # WPM is words * 2 for a 30s window (or words / dur * 60)
        wpm = (words_in_window / window_dur) * 60.0 if window_dur > 0 else 0.0
        is_strong = (wpm >= strong_min_wpm) and (coverage >= strong_min_coverage)
        verdict = "strong" if is_strong else "weak"

        windows.append(
            WindowReport(
                start_s=round(t, 1),
                end_s=round(window_end, 1),
                words=round(words_in_window),
                coverage=round(coverage, 2),
                verdict=verdict,
            )
        )
        t = window_end

    # Determine weak_fraction and suitability
    if not windows:
        return PreflightReport(
            windows=[],
            speech_coverage=0.0,
            longest_silent_stretch_s=duration_seconds,
            weak_windows=[],
            suitability="unknown",
            message="Unable to analyze lecture timing.",
        )

    weak_count = sum(1 for w in windows if w.verdict == "weak")
    weak_fraction = weak_count / len(windows)

    if weak_fraction <= 0.20:
        suitability = "good"
        message = "Narration covers most of this video. Checkpoints should be reliable."
    elif weak_fraction <= 0.50:
        suitability = "mixed"
        message = "Some sections have little narration. You can add notes or run visual analysis on the highlighted sections."
    else:
        suitability = "limited"
        pct = int(overall_speech_coverage * 100)
        message = f"Only {pct}% of this video is narrated. Expect fewer checkpoints. Adding notes or running visual analysis will improve results."

    # Merge adjacent weak windows into WeakSpan runs
    weak_spans: list[WeakSpan] = []
    current_run_start: float | None = None
    current_run_end: float | None = None

    for w in windows:
        if w.verdict == "weak":
            if current_run_start is None:
                current_run_start = w.start_s
            current_run_end = w.end_s
        else:
            if current_run_start is not None and current_run_end is not None:
                weak_spans.append(WeakSpan(start_s=current_run_start, end_s=current_run_end))
                current_run_start = None
                current_run_end = None

    if current_run_start is not None and current_run_end is not None:
        weak_spans.append(WeakSpan(start_s=current_run_start, end_s=current_run_end))

    return PreflightReport(
        windows=windows,
        speech_coverage=overall_speech_coverage,
        longest_silent_stretch_s=round(longest_silent_stretch, 1),
        weak_windows=weak_spans,
        suitability=suitability,
        message=message,
    )

