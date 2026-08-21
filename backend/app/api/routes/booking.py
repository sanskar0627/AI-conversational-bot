"""Booking routes: GET /api/booking/slots, POST /api/book-site-visit."""

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_booking_service, get_store
from app.memory.store import SessionStore
from app.models.requests import BookingRequest
from app.models.responses import BookingResponse, SlotsResponse
from app.services.booking import BookingService

router = APIRouter()


@router.get("/booking/slots", response_model=SlotsResponse)
def list_slots(
    session_id: str = Query(..., min_length=1),
    store: SessionStore = Depends(get_store),
    booking: BookingService = Depends(get_booking_service),
) -> SlotsResponse:
    store.get(session_id)
    return SlotsResponse(slots=booking.get_available_slots())


@router.post("/book-site-visit", response_model=BookingResponse)
def book_site_visit(
    payload: BookingRequest,
    store: SessionStore = Depends(get_store),
    booking: BookingService = Depends(get_booking_service),
) -> BookingResponse:
    session = store.get(payload.session_id)
    result = booking.attempt_booking(
        session_id=payload.session_id,
        name=payload.name,
        phone=payload.phone,
        slot_id=payload.slot_id,
    )
    if result.success:
        session.booking = {
            "status": "confirmed",
            "slot": result.slot,
            "confirmation_id": result.confirmation_id,
            "failure_count": session.booking.get("failure_count", 0),
            "history": [*session.booking.get("history", []), {"event": "confirmed", "slot": result.slot}],
        }
        if payload.name:
            session.profile["name"] = payload.name
        if payload.phone:
            session.profile["phone"] = payload.phone
    else:
        session.booking["failure_count"] = session.booking.get("failure_count", 0) + 1
        session.booking["status"] = "failed"
        session.booking.setdefault("history", []).append(
            {"event": "failed", "reason": result.reason, "slot": payload.slot_id}
        )
    store.save(session)
    return result
