from backend.lecture_sanitizer import sanitize_student_lecture


def test_sanitizer_removes_nested_student_secrets_without_mutating_source():
    lecture = {
        "id": "lecture",
        "recall_pool": [{"question": "Recall this", "correct_answer": "answer"}],
        "interventions": [
            {
                "correct_answer": "option_a",
                "accepted_answers": ["answer"],
                "hints": ["hint"],
                "rubric": {
                    "key_concepts": ["private concept"],
                    "reference_answer": "private answer",
                    "misconceptions": ["private misconception"],
                    "passing_score": 0.7,
                },
                "sandbox_config": {"solution_code": "secret", "hints": ["sandbox hint"]},
                "mobile_fallback": {"question": "public", "correct_answer": "secret"},
                "variants": {"1": {"correct_answer": "variant secret"}},
            }
        ],
    }

    sanitized = sanitize_student_lecture(lecture)

    intervention = sanitized["interventions"][0]
    assert sanitized["id"] == "lecture"
    assert "recall_pool" not in sanitized
    assert "rubric" not in intervention
    assert "sandbox_config" not in intervention
    assert intervention["mobile_fallback"] == {"question": "public"}
    assert intervention["variants"]["1"] == {}
    assert lecture["recall_pool"]
    assert lecture["interventions"][0]["rubric"]["reference_answer"] == "private answer"
