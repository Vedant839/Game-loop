from backend.schemas.lecture import (
    Difficulty,
    Intervention,
    InterventionType,
    Lecture,
    SandboxConfig,
    TimingConfig,
    TranscriptSegment,
)
from backend.services.checkpoint_generator import checkpoint_count, enrich_generated_lecture
from backend.services.lecture_service import _generate_for_lecture


def _lecture(duration: int = 1800) -> Lecture:
    transcript = [
        TranscriptSegment(start_time=float(start), end_time=float(start + 100), text=f"Concept {start} explained clearly.")
        for start in range(0, duration - 100, 120)
    ]
    return Lecture(
        id="checkpoint_test", title="Checkpoint test", subject="Science", grade="12",
        duration_seconds=float(duration), video_url="https://example.com/video.mp4",
        timing_config=TimingConfig(min_trigger_gap=90, tolerance=2),
        transcript=transcript, interventions=[],
    )


def test_intensity_changes_density_and_allows_more_than_six_checkpoints():
    assert checkpoint_count(1800, "light") < checkpoint_count(1800, "standard")
    assert checkpoint_count(1800, "standard") < checkpoint_count(1800, "intense")
    lecture = _generate_for_lecture(_lecture(), max_count=checkpoint_count(1800, "intense"), intensity="intense")
    assert len(lecture.interventions) > 6
    assert all(
        right.trigger_time - left.trigger_time >= 90
        for left, right in zip(lecture.interventions, lecture.interventions[1:])
    )
    assert 3 <= len(lecture.recall_pool) <= 5


def test_sandbox_checkpoints_receive_mobile_multiple_choice_fallback():
    lecture = _lecture(600)
    lecture.transcript = [TranscriptSegment(start_time=0, end_time=600, text="A concept described in a long segment.")]
    lecture.interventions = [Intervention(
        id="sandbox", revision=3, trigger_time=200, concept="vectors", difficulty=Difficulty.EASY,
        type=InterventionType.PREDICT_AND_VERIFY, question="Predict the result.",
        sandbox_config=SandboxConfig(initial_code="print(1)", solution_code="print(1)"),
        correct_feedback="Correct.", incorrect_feedback="Try again.",
    )]

    result = enrich_generated_lecture(lecture, "standard")

    assert result.interventions[0].mobile_fallback is not None
    assert result.interventions[0].revision == 3
    assert len(result.interventions[0].mobile_fallback["options"]) >= 2
    assert 3 <= len(result.recall_pool) <= 5
