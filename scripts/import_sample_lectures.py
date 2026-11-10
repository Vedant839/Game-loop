"""Import videos with Gemini-generated transcript sidecars for local testing."""

from __future__ import annotations

import json
import re
import shutil
import struct
import unicodedata
from pathlib import Path
from urllib.parse import quote

from backend.config import PROJECT_ROOT
from backend.schemas.lecture import Lecture, TimingConfig, TranscriptSegment


SAMPLE_DIR = PROJECT_ROOT / "sample_lectures"
LECTURES_DIR = PROJECT_ROOT / "data" / "lectures"
MEDIA_DIR = PROJECT_ROOT / "data" / "media"


def lecture_id_for(file_path: Path) -> str:
    ascii_stem = unicodedata.normalize("NFKD", file_path.stem).encode("ascii", "ignore").decode()
    lecture_id = re.sub(r"[^a-z0-9]+", "_", ascii_stem.lower()).strip("_")
    if not lecture_id:
        raise ValueError(f"Could not derive an ID for {file_path.name}")
    return lecture_id


def read_mp4_duration(file_path: Path) -> float:
    """Read the MP4 movie-header duration without asking creators to enter it."""
    content = file_path.read_bytes()
    marker = content.find(b"mvhd")
    if marker < 0:
        raise ValueError(f"MP4 duration metadata is missing from {file_path.name}")
    version = content[marker + 4]
    if version == 0:
        timescale = struct.unpack_from(">I", content, marker + 16)[0]
        duration_ticks = struct.unpack_from(">I", content, marker + 20)[0]
    elif version == 1:
        timescale = struct.unpack_from(">I", content, marker + 24)[0]
        duration_ticks = struct.unpack_from(">Q", content, marker + 28)[0]
    else:
        raise ValueError(f"Unsupported MP4 duration metadata in {file_path.name}")
    if not timescale:
        raise ValueError(f"Invalid MP4 duration metadata in {file_path.name}")
    return duration_ticks / timescale


def import_sample_lectures() -> int:
    sources = sorted(SAMPLE_DIR.glob("*.mp4"))
    if not sources:
        raise FileNotFoundError(f"No sample videos found in {SAMPLE_DIR}")

    imported = 0
    for source in sources:
        lecture_id = lecture_id_for(source)
        transcript_path = SAMPLE_DIR / f"{lecture_id}.transcript.json"
        if not transcript_path.exists():
            raise FileNotFoundError(f"Transcript is missing for {source.name}: {transcript_path.name}")

        transcript_data = json.loads(transcript_path.read_text(encoding="utf-8"))
        duration = read_mp4_duration(source)
        transcript_duration = float(transcript_data["duration_seconds"])
        raw_segments = transcript_data["segments"]
        latest_segment_end = max(
            (float(segment["end_seconds"]) for segment in raw_segments),
            default=transcript_duration,
        )
        # Gemini's timeline can drift from the MP4's own clock. Keep the full
        # generated transcript while mapping its timestamps into the real clip.
        time_scale = duration / max(transcript_duration, latest_segment_end)
        segments = [
            TranscriptSegment(
                start_time=max(0.0, min(duration - 0.05, float(segment["start_seconds"]) * time_scale)),
                end_time=min(duration, float(segment["end_seconds"]) * time_scale),
                text=str(segment["text"]).strip(),
            )
            for segment in raw_segments
            if str(segment.get("text", "")).strip()
            and float(segment["start_seconds"]) * time_scale
            < min(duration, float(segment["end_seconds"]) * time_scale)
        ]
        if not segments:
            raise ValueError(f"Transcript is empty for {source.name}")
        transcript_data["duration_seconds"] = duration
        transcript_data["segments"] = [
            {
                "start_seconds": segment.start_time,
                "end_seconds": segment.end_time,
                "text": segment.text,
            }
            for segment in segments
        ]
        transcript_path.write_text(json.dumps(transcript_data, ensure_ascii=False, indent=2), encoding="utf-8")

        lecture_path = LECTURES_DIR / f"{lecture_id}.json"
        existing = None
        if lecture_path.exists():
            try:
                existing = Lecture.model_validate_json(lecture_path.read_text(encoding="utf-8"))
            except ValueError:
                existing = None

        media_name = f"{lecture_id}.mp4"
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, MEDIA_DIR / media_name)
        lecture = Lecture(
            id=lecture_id,
            duration_seconds=duration,
            video_url=f"/media/{quote(media_name)}",
            timing_config=existing.timing_config if existing else TimingConfig(),
            transcript=segments,
            interventions=existing.interventions if existing else [],
            recall_pool=existing.recall_pool if existing else [],
        )
        LECTURES_DIR.mkdir(parents=True, exist_ok=True)
        lecture_path.write_text(lecture.model_dump_json(indent=2), encoding="utf-8")
        imported += 1
        print(f"Imported {source.name} as {lecture_id} ({duration:.1f}s, {len(segments)} transcript segments)")

    return imported


if __name__ == "__main__":
    count = import_sample_lectures()
    print(f"Imported {count} sample lectures.")
