"""Slot inventory stub. Real simulator lands in Stage 06."""

from __future__ import annotations

from app.models.responses import BookingResponse, SlotInfo

STUB_SLOTS: list[SlotInfo] = [
    SlotInfo(slot_id="stub-sat-1100", label="Saturday 11:00 AM", available=True),
    SlotInfo(slot_id="stub-sat-1500", label="Saturday 3:00 PM", available=True),
    SlotInfo(slot_id="stub-sun-1100", label="Sunday 11:00 AM", available=True),
    SlotInfo(slot_id="stub-sun-1500", label="Sunday 3:00 PM", available=True),
]


class BookingService:
    """Placeholder booking simulator used by Stage 02 endpoints and the engine."""

    def get_available_slots(self, limit: int = 8) -> list[SlotInfo]:
        return [slot for slot in STUB_SLOTS if slot.available][:limit]

    def attempt_booking(
        self,
        *,
        session_id: str,
        name: str,
        phone: str,
        slot_id: str,
    ) -> BookingResponse:
        matching = next((slot for slot in STUB_SLOTS if slot.slot_id == slot_id), None)
        if matching is None or not matching.available:
            return BookingResponse(
                success=False,
                reason="slot_taken",
                alternatives=self.get_available_slots(limit=3),
            )
        return BookingResponse(
            success=True,
            confirmation_id="NS-STUB01",
            slot=slot_id,
        )
