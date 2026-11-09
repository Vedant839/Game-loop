"""Deterministic checkpoint placement and safe recall-pool construction."""

from __future__ import annotations

import re

from backend.schemas.lecture import Intervention, Lecture, Option

SPACING_SECONDS = {"light": 330.0, "standard": 210.0, "intense": 150.0}
MIN_CHECKPOINT_GAP_SECONDS = 90.0


def checkpoint_count(duration_seconds: float, intensity: str) -> int:
    spacing = SPACING_SECONDS.get(intensity, SPACING_SECONDS["standard"])
    if duration_seconds < spacing + 20:
        return 0
    return max(1, int((duration_seconds - 20) // spacing))


def _clean_concept(text: str) -> str:
    words = re.findall(r"[\w+.-]+", text)
    return " ".join(words[:7]) or "the key idea"


def _natural_boundaries(lecture: Lecture) -> list[float]:
    return sorted({
        round(segment.end_time, 2)
        for segment in lecture.transcript
        if MIN_CHECKPOINT_GAP_SECONDS <= segment.end_time <= lecture.duration_seconds - 20
    })


def _checkpoint_times(lecture: Lecture, intensity: str, count: int) -> list[float]:
    spacing = SPACING_SECONDS.get(intensity, SPACING_SECONDS["standard"])
    boundaries = _natural_boundaries(lecture)
    selected: list[float] = []
    for index in range(count):
        target = spacing * (index + 1)
        if target > lecture.duration_seconds - 20:
            break
        candidates = [
            point for point in boundaries
            if point not in selected
            and (not selected or point - selected[-1] >= MIN_CHECKPOINT_GAP_SECONDS)
        ]
        if candidates:
            nearest = min(candidates, key=lambda point: abs(point - target))
            if abs(nearest - target) <= max(spacing * 0.45, 45):
                selected.append(nearest)
                continue
        candidate = min(target, lecture.duration_seconds - 20)
        if not selected or candidate - selected[-1] >= MIN_CHECKPOINT_GAP_SECONDS:
            selected.append(round(candidate, 2))
    return selected


def _recall_pool(lecture: Lecture, interventions: list[Intervention]) -> list[dict[str, object]]:
    candidates: list[tuple[str, str]] = []
    for segment in lecture.transcript:
        text = " ".join(segment.text.split())
        if text:
            concept = _clean_concept(text)
            candidates.append((concept, text))
    for intervention in interventions:
        answer = intervention.concept.strip()
        if answer:
            candidates.append((_clean_concept(answer), intervention.question))

    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for concept, answer in candidates:
        key = concept.casefold()
        if key not in seen:
            seen.add(key)
            unique.append((concept, answer))
        if len(unique) == 5:
            break

    if not unique:
        return []
    questions = [
        "What is one key idea about {concept}?",
        "In your own words, explain {concept}.",
        "What is one detail you remember about {concept}?",
    ]
    while len(unique) < 3:
        concept, answer = unique[len(unique) % len(unique)]
        unique.append((concept, answer))
    return [
        {
            "id": f"recall_{index + 1}",
            "type": "flash_recall",
            "question": questions[index % len(questions)].format(concept=concept),
            "expected_answer": answer,
        }
        for index, (concept, answer) in enumerate(unique[:5])
    ]


def enrich_generated_lecture(lecture: Lecture, intensity: str = "standard") -> Lecture:
    """Snap generated checkpoints to transcript boundaries and attach fallback data."""
    result = lecture.model_copy(deep=True)
    count = checkpoint_count(result.duration_seconds, intensity)
    times = _checkpoint_times(result, intensity, count)
    ordered = sorted(result.interventions, key=lambda item: item.trigger_time)[:min(count, len(times))]
    enriched: list[Intervention] = []
    for index, intervention in enumerate(ordered):
        updates: dict[str, object] = {}
        if index < len(times):
            updates["trigger_time"] = times[index]
        if intervention.sandbox_config is not None:
            options = intervention.hypothesis_options or [
                Option(id="mobile_correct", text=f"The result follows from {intervention.concept}."),
                Option(id="mobile_distractor_1", text="The result is unrelated to the concept."),
                Option(id="mobile_distractor_2", text="No change occurs in the result."),
            ]
            answer = intervention.correct_answer
            option_ids = {option.id for option in options}
            if not isinstance(answer, str) or answer not in option_ids:
                answer = options[0].id
            updates["mobile_fallback"] = {
                "question": intervention.hypothesis_prompt or f"Which result best matches {intervention.concept}?",
                "options": [option.model_dump(mode="json") for option in options],
                "correct_answer": answer,
            }
        enriched.append(intervention.model_copy(update=updates))
    result.interventions = enriched
    result.recall_pool = _recall_pool(result, enriched)
    return result
