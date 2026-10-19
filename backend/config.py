"""Local-only runtime configuration without exposing secret values."""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Configuration is loaded from environment variables and an ignored local file."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / "api.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        validation_alias="GAME_LOOP_CORS_ORIGINS",
    )
    gemini_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("gemini_api_key", "GEMINI_API_KEY"),
    )
    media_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "media",
        validation_alias=AliasChoices("media_dir", "GAME_LOOP_MEDIA_DIR"),
    )
    lectures_dir: Path = Field(
        default=PROJECT_ROOT / "data" / "lectures",
        validation_alias=AliasChoices("lectures_dir", "GAME_LOOP_LECTURES_DIR"),
    )

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
