"""Creator ingestion request models."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


MAX_CREATOR_CONTEXT_BYTES: int = 100 * 1024  # 100 KB limit


class CreatorContext(BaseModel):
    notes: str = ""
    chapters: str = ""

    @field_validator("notes")
    @classmethod
    def validate_notes_size(cls, v: str) -> str:
        if len(v.encode("utf-8")) > MAX_CREATOR_CONTEXT_BYTES:
            raise ValueError("Creator context notes exceed 100 KB limit")
        return v

    @model_validator(mode="after")
    def validate_total_size(self) -> "CreatorContext":
        context_bytes = len(self.notes.encode("utf-8")) + len(self.chapters.encode("utf-8"))
        if context_bytes > MAX_CREATOR_CONTEXT_BYTES:
            raise ValueError("Creator context exceeds 100 KB limit")
        return self


class IngestLectureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_url: str = Field(..., min_length=1, max_length=2048)
    duration_seconds: float = Field(..., gt=0)
    captions: str = ""
    captions_format: Literal["srt", "vtt", "text"] = "text"
    intensity: Literal["light", "standard", "intense"] = "standard"
    creator_context: CreatorContext | None = None
    visual_evidence: list[dict[str, Any]] | None = None

    @field_validator("video_url")
    @classmethod
    def validate_video_url(cls, value: str) -> str:
        value = value.strip()
        if value.startswith("/"):
            return value
        parsed = HttpUrl(value)
        return str(parsed)


class PreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_seconds: float = Field(..., gt=0)
    captions: str = ""
    captions_format: Literal["srt", "vtt", "text"] = "text"
    transcript: list[dict[str, Any]] | None = None
