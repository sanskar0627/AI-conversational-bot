"""Booking routes: GET /api/booking/slots, POST /api/book-site-visit."""

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_booking_service, get_store
from app.memory.store import SessionStore
from app.models.requests import BookingRequest
from app.models.responses import BookingResponse, SlotsResponse
from app.services.booking import BookingService, apply_booking_result

router = APIRouter()


@router.get("/booking/slots", response_model=SlotsResponse)
def list_slots(
    session_id: str = Query(..., min_length=1),
    store: SessionStore = Depends(get_store),
    booking: BookingService = Depends(get_booking_service),
) -> SlotsResponse:
    session = store.get(session_id)
    slots = booking.get_available_slots()
    session.booking["offered_slots"] = [slot.slot_id for slot in slots]
    store.save(session)
    return SlotsResponse(slots=slots)


@router.post("/book-site-visit", response_model=BookingResponse)
def book_site_visit(
    payload: BookingRequest,
    store: SessionStore = Depends(get_store),
    booking: BookingService = Depends(get_booking_service),
) -> BookingResponse:
    session = store.get(payload.session_id)
    already_confirmed = session.booking.get("status") == "confirmed"
    if already_confirmed and session.booking.get("slot") != payload.slot_id:
        result = booking.reschedule(
            session_id=payload.session_id,
            name=payload.name,
            phone=payload.phone,
            old_slot_id=session.booking.get("slot"),
            new_slot_id=payload.slot_id,
        )
        event = "rescheduled" if result.success else "failed"
    else:
        result = booking.attempt_booking(
            session_id=payload.session_id,
            name=payload.name,
            phone=payload.phone,
            slot_id=payload.slot_id,
        )
        event = "confirmed" if result.success else "failed"

    apply_booking_result(session, result, event=event, requested_slot=payload.slot_id)
    if payload.name:
        session.profile["name"] = payload.name
    if payload.phone:
        session.profile["phone"] = payload.phone
    store.save(session)
    return result
