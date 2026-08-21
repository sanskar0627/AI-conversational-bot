"""POST /api/chat — single conversation turn."""

from fastapi import APIRouter, Depends

from app.dependencies import get_engine, get_rate_limiter
from app.models.requests import ChatRequest
from app.models.responses import ChatResponse
from app.services.conversation_engine import ConversationEngine
from app.utils.rate_limit import RateLimiter

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    engine: ConversationEngine = Depends(get_engine),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> ChatResponse:
    limiter.check(payload.session_id)
    return await engine.handle_turn(payload.session_id, payload.message)
