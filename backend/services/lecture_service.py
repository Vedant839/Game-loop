"""Lecture loader and repository service."""

import json
from pathlib import Path
from backend.config import get_settings
from backend.schemas.lecture import Lecture, LectureSummary
from backend.schemas.lecture import Intervention, Option, InterventionType, Difficulty
from backend.schemas.lecture import TranscriptSegment


class LectureService:
    def __init__(self, lectures_dir: Path | None = None) -> None:
        if lectures_dir is None:
            settings = get_settings()
            lectures_dir = settings.lectures_dir
        self.lectures_dir = lectures_dir
        self._runtime_lectures: dict[str, Lecture] = {}

    def list_lectures(self) -> list[LectureSummary]:
        summaries: list[LectureSummary] = []
        if not self.lectures_dir.exists():
            return summaries

        hidden_ids = {"math_sample_lecture", "physics_kinematics", "python_basics_lists"}
        for file_path in sorted(self.lectures_dir.glob("*.json")):
            try:
                lecture = self.get_lecture_by_file(file_path)
                lecture = self._runtime_lectures.get(lecture.id, lecture)
                if lecture.id in hidden_ids and lecture.id != "linear_algebra_vectors":
                    continue
                summaries.append(
                    LectureSummary(
                        id=lecture.id,
                        title=lecture.title,
                        subject=lecture.subject,
                        grade=lecture.grade,
                        duration_seconds=lecture.duration_seconds,
                        video_url=lecture.video_url,
                        intervention_count=len(lecture.interventions),
                    )
                )
            except Exception:
                # Invalid JSON files are skipped or flagged
                continue

        priority = {"linear_algebra_vectors": 0, "linux_command_line": 1}
        return sorted(summaries, key=lambda lecture: (priority.get(lecture.id, 99), lecture.title))

    def get_lecture(self, lecture_id: str) -> Lecture | None:
        runtime_lecture = self._runtime_lectures.get(lecture_id)
        if runtime_lecture is not None:
            return runtime_lecture.model_copy(deep=True)

        file_path = self.lectures_dir / f"{lecture_id}.json"
        if not file_path.exists():
            return None
        return self.get_lecture_by_file(file_path)

    def get_lecture_by_file(self, file_path: Path) -> Lecture:
        content = file_path.read_text(encoding="utf-8-sig")
        data = json.loads(content)
        return Lecture.model_validate(data)

    def save_lecture(self, lecture: Lecture) -> None:
        file_path = self.lectures_dir / f"{lecture.id}.json"
        data = lecture.model_dump(mode="json")
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def set_runtime_lecture(self, lecture: Lecture) -> None:
        """Keep generated lecture content available to sessions without writing files."""
        self._runtime_lectures[lecture.id] = lecture.model_copy(deep=True)


_lecture_service_instance: LectureService | None = None


def get_lecture_service() -> LectureService:
    global _lecture_service_instance
    if _lecture_service_instance is None:
        _lecture_service_instance = LectureService()
    return _lecture_service_instance

    
def _first_words(text: str, count: int = 6) -> str:
    parts = text.strip().split()
    return " ".join(parts[:count]) if parts else "key point"


def _nearest_transcript_segment(lecture: Lecture, time: float) -> TranscriptSegment | None:
    best = None
    best_dist = None
    for seg in lecture.transcript:
        mid = (seg.start_time + seg.end_time) / 2.0
        dist = abs(mid - time)
        if best is None or dist < best_dist:
            best = seg
            best_dist = dist
    return best


def _build_generated_interventions(lecture: Lecture, max_count: int) -> list[Intervention]:
    # Determine seed trigger times across lecture duration
    dur = lecture.duration_seconds
    if dur <= 0:
        return []

    fractions = [0.2, 0.4, 0.6, 0.8]
    times = [min(dur - 1.0, max(0.0, dur * f)) for f in fractions[:max_count]]

    # Enforce min_trigger_gap between successive generated times
    min_gap = lecture.timing_config.min_trigger_gap
    adjusted = []
    for t in times:
        if not adjusted:
            adjusted.append(t)
        else:
            prev = adjusted[-1]
            if t - prev < min_gap:
                adjusted.append(prev + min_gap)
            else:
                adjusted.append(t)

    interventions: list[Intervention] = []
    for i, t in enumerate(adjusted):
        seg = _nearest_transcript_segment(lecture, t)
        concept_text = _first_words(seg.text if seg is not None else lecture.title, 6)
        # Build simple deterministic options: correct is the concept, others are generic distractors
        opts = [
            Option(id="opt_a", text=concept_text),
            Option(id="opt_b", text="Related concept"),
            Option(id="opt_c", text="Another idea"),
            Option(id="opt_d", text="None of the above"),
        ]
        intv = Intervention(
            id=f"gen_int_{i+1}",
            trigger_time=round(t, 2),
            concept=concept_text,
            difficulty=Difficulty.EASY if i < 2 else Difficulty.MEDIUM,
            type=InterventionType.SINGLE_CHOICE,
            question=f"What is the main idea of this segment (around {int(t)}s)?",
            options=opts,
            correct_answer="opt_a",
            correct_feedback="Correct.",
            incorrect_feedback="Not quite."
        )
        interventions.append(intv)

    return interventions


def _generate_for_lecture(lecture: Lecture, max_count: int = 4) -> Lecture:
    # Clone lecture and attach generated interventions (do not persist changes)
    generated = lecture.model_copy()
    generated.interventions = _build_generated_interventions(generated, max_count)
    return generated

