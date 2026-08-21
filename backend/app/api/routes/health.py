"""GET /api/health — liveness plus whether an OpenRouter key is configured."""

from fastapi import APIRouter

from app.config import get_settings
from app.models.responses import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        model=settings.openrouter_model,
        llm_configured=settings.llm_configured,
    )
