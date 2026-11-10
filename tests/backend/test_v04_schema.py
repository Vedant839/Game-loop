from backend.schemas.lecture import Difficulty, Intervention, InterventionType, Lecture


def test_flash_recall_revision_mobile_fallback_and_recall_pool_schema():
    lecture = Lecture(
        id="expanded_lecture",
        duration_seconds=180,
        video_url="https://example.com/video.mp4",
        recall_pool=[{"question": "Recall", "correct_answer": "secret"}],
        interventions=[
            Intervention(
                id=f"checkpoint-{index}",
                revision=2,
                trigger_time=10 + index * 20,
                concept=f"concept-{index}",
                difficulty=Difficulty.EASY,
                type=InterventionType.FLASH_RECALL,
                question=f"Recall concept {index}",
                mobile_fallback={"question": "Select an answer", "correct_answer": "a"},
            )
            for index in range(7)
        ],
    )

    assert lecture.interventions[-1].revision == 2
    assert lecture.interventions[-1].type == InterventionType.FLASH_RECALL
    assert len(lecture.interventions) == 7
    assert lecture.recall_pool[0]["question"] == "Recall"
