"""Session lifecycle: POST /api/session, POST /api/end-session, GET memory."""

from fastapi import APIRouter, Depends

from app.dependencies import get_store
from app.memory.schemas import ConversationState
from app.memory.store import SessionStore, build_memory_snapshot
from app.models.requests import CreateSessionRequest, EndSessionRequest
from app.models.responses import AnalyticsResponse, MemorySnapshot, SessionResponse
from app.services.analytics import build_stub_analytics

router = APIRouter()

STATIC_GREETING = (
    "Hi! I'm Aisha from Northstar Homes. How can I help you with Northstar One today?"
)


@router.post("/session", response_model=SessionResponse)
def create_session(
    payload: CreateSessionRequest,
    store: SessionStore = Depends(get_store),
) -> SessionResponse:
    session = store.create(channel=payload.channel.value)
    return SessionResponse(session_id=session.session_id, greeting=STATIC_GREETING)


@router.get("/session/{session_id}/memory", response_model=MemorySnapshot)
def get_session_memory(
    session_id: str,
    store: SessionStore = Depends(get_store),
) -> MemorySnapshot:
    session = store.get(session_id)
    return build_memory_snapshot(session)


@router.post("/end-session", response_model=AnalyticsResponse)
def end_session(
    payload: EndSessionRequest,
    store: SessionStore = Depends(get_store),
) -> AnalyticsResponse:
    session = store.get(payload.session_id)
    if session.analytics is not None:
        return AnalyticsResponse.model_validate(session.analytics)
    if session.state != ConversationState.STOPPED:
        session.state = ConversationState.CLOSED
    analytics = build_stub_analytics(session)
    session.analytics = analytics.model_dump()
    store.save(session)
    return analytics
