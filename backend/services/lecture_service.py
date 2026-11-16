"""Lecture loader and repository service."""

import json
import re
import unicodedata
from pathlib import Path
from backend.config import get_settings
from backend.schemas.lecture import Lecture, LectureSummary
from backend.schemas.lecture import Intervention, Option, InterventionType, Difficulty
from backend.schemas.lecture import TranscriptSegment
from backend.services.checkpoint_generator import SPACING_SECONDS, enrich_generated_lecture


class LectureService:
    def __init__(self, lectures_dir: Path | None = None, db: Any | None = None) -> None:
        if lectures_dir is None:
            settings = get_settings()
            lectures_dir = settings.lectures_dir
        self.lectures_dir = lectures_dir
        self.db = db
        self._runtime_lectures: dict[str, Lecture] = {}

    def _ensure_db(self) -> Any | None:
        if self.db is None:
            try:
                from backend.database import get_database
                self.db = get_database()
            except Exception:
                pass
        return self.db

    def list_lectures(self) -> list[LectureSummary]:
        summaries: list[LectureSummary] = []
        if not self.lectures_dir.exists():
            return summaries

        for file_path in sorted(self.lectures_dir.glob("*.json")):
            try:
                lecture = self.get_lecture_by_file(file_path)
                lecture = self._runtime_lectures.get(lecture.id, lecture)
                summaries.append(
                    LectureSummary(
                        id=lecture.id,
                        duration_seconds=lecture.duration_seconds,
                        video_url=lecture.video_url,
                        intervention_count=len(lecture.interventions),
                    )
                )
            except Exception:
                # Invalid JSON files are skipped or flagged
                continue

        priority = {"math_sample_lecture": 0}
        return sorted(summaries, key=lambda lecture: (priority.get(lecture.id, 99), lecture.id))

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

    def is_sample_lecture(self, lecture_id: str) -> bool:
        """Return whether an ID belongs to the canonical or bundled demo set."""
        if lecture_id == "math_sample_lecture":
            return True
        sample_dir = self.lectures_dir.parent.parent / "sample_lectures"
        if not sample_dir.exists():
            return False
        for video_path in sample_dir.glob("*.mp4"):
            ascii_stem = unicodedata.normalize("NFKD", video_path.stem).encode("ascii", "ignore").decode()
            bundled_id = re.sub(r"[^a-z0-9]+", "_", ascii_stem.lower()).strip("_")
            if bundled_id == lecture_id:
                return True
        return False

    def save_lecture(self, lecture: Lecture) -> None:
        file_path = self.lectures_dir / f"{lecture.id}.json"
        data = lecture.model_dump(mode="json")
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def set_runtime_lecture(self, lecture: Lecture) -> None:
        """Keep generated lecture content available to sessions without writing files."""
        self._runtime_lectures[lecture.id] = lecture.model_copy(deep=True)


_lecture_service_instance: LectureService | None = None


def get_lecture_service(db: Any | None = None) -> LectureService:
    global _lecture_service_instance
    if _lecture_service_instance is None:
        _lecture_service_instance = LectureService(db=db)
    elif db is not None and _lecture_service_instance.db is None:
        _lecture_service_instance.db = db
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


def _build_generated_interventions(
    lecture: Lecture, max_count: int, intensity: str = "standard"
) -> list[Intervention]:
    # Determine seed trigger times across lecture duration
    dur = lecture.duration_seconds
    if dur <= 0:
        return []

    spacing = SPACING_SECONDS.get(intensity, SPACING_SECONDS["standard"])
    times = [min(dur - 20.0, spacing * (index + 1)) for index in range(max_count)]

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
        concept_text = _first_words(seg.text if seg is not None else "the key idea", 6)
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


def _generate_for_lecture(
    lecture: Lecture, max_count: int = 4, intensity: str = "standard"
) -> Lecture:
    # Clone lecture and attach generated interventions (do not persist changes)
    generated = lecture.model_copy()
    generated.interventions = _build_generated_interventions(generated, max_count, intensity)
    return enrich_generated_lecture(generated, intensity)

