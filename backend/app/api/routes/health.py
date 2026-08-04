"""GET /api/health — liveness plus whether an OpenRouter key is configured."""

from fastapi import APIRouter

from app.config import get_settings

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str | bool]:
    settings = get_settings()
    return {
        "status": "ok",
        "model": settings.openrouter_model,
        "llm_configured": settings.llm_configured,
    }
