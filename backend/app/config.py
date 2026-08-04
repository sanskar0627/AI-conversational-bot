"""Application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent
_PLACEHOLDER_API_KEY = "sk-or-your-key-here"


class Settings(BaseSettings):
    """Env-driven config. Looks for `.env` in the repo root and `backend/`."""

    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env", _BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    cors_origins: str = "http://localhost:5173"
    session_ttl_minutes: int = 60
    llm_timeout_seconds: int = 30
    booking_failure_mode: str = "deterministic"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def llm_configured(self) -> bool:
        key = self.openrouter_api_key.strip()
        return bool(key) and key != _PLACEHOLDER_API_KEY


@lru_cache
def get_settings() -> Settings:
    return Settings()
