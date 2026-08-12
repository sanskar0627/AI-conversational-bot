"""GET /api/analytics/{session_id} — stub analytics after the session is closed."""

from fastapi import APIRouter, Depends

from app.dependencies import get_store
from app.exceptions import SessionActiveError
from app.memory.store import SessionStore
from app.models.responses import AnalyticsResponse

router = APIRouter()


@router.get("/analytics/{session_id}", response_model=AnalyticsResponse)
def get_analytics(
    session_id: str,
    store: SessionStore = Depends(get_store),
) -> AnalyticsResponse:
    session = store.get(session_id)
    if session.analytics is None:
        raise SessionActiveError()
    return AnalyticsResponse.model_validate(session.analytics)
