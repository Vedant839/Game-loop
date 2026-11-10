"""Creator ingestion request models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class IngestLectureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_url: str = Field(..., min_length=1, max_length=2048)
    duration_seconds: float = Field(..., gt=0)
    captions: str = ""
    captions_format: Literal["srt", "vtt", "text"] = "text"
    intensity: Literal["light", "standard", "intense"] = "standard"

    @field_validator("video_url")
    @classmethod
    def validate_video_url(cls, value: str) -> str:
        value = value.strip()
        if value.startswith("/"):
            return value
        parsed = HttpUrl(value)
        return str(parsed)
