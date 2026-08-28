"""Deterministic site-visit slot inventory. Booking attempts land in later commits."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.models.responses import BookingResponse, SlotInfo
from app.utils.validators import is_valid_slot_id

IST = ZoneInfo("Asia/Kolkata")
HORIZON_DAYS = 7
SLOT_HOURS = (10, 12, 14, 16)
SLOT_ID_FORMAT = "%Y-%m-%d-%H%M"

NowFn = Callable[[], datetime]


def _now_ist() -> datetime:
    return datetime.now(IST)


def parse_slot_id(slot_id: str) -> datetime | None:
    """Parse `2026-08-23-1100` into an IST datetime, or None if malformed."""
    if not is_valid_slot_id(slot_id):
        return None
    try:
        naive = datetime.strptime(slot_id, SLOT_ID_FORMAT)
    except ValueError:
        return None
    return naive.replace(tzinfo=IST)


def make_slot_id(starts_at: datetime) -> str:
    return starts_at.strftime(SLOT_ID_FORMAT)


def format_slot_label(starts_at: datetime) -> str:
    """Short spoken label, e.g. `Sat 10 AM`."""
    hour = starts_at.strftime("%I").lstrip("0") or "12"
    return f"{starts_at.strftime('%a')} {hour} {starts_at.strftime('%p')}"


@dataclass(frozen=True)
class VisitSlot:
    slot_id: str
    starts_at: datetime
    available: bool = True

    @property
    def label(self) -> str:
        return format_slot_label(self.starts_at)

    def to_info(self) -> SlotInfo:
        return SlotInfo(slot_id=self.slot_id, label=self.label, available=self.available)


def generate_inventory(now: datetime, *, days: int = HORIZON_DAYS) -> list[VisitSlot]:
    """Next `days` calendar days, 10:00–18:00 in 2-hour slots (IST)."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)
    start_day = now.date()
    slots: list[VisitSlot] = []
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        for hour in SLOT_HOURS:
            starts_at = datetime(day.year, day.month, day.day, hour, 0, tzinfo=IST)
            if starts_at <= now:
                continue
            slots.append(
                VisitSlot(
                    slot_id=make_slot_id(starts_at),
                    starts_at=starts_at,
                    available=True,
                )
            )
    return slots


class BookingService:
    """In-memory slot inventory. Simulator attempts come after the inventory lands."""

    def __init__(self, *, now_fn: NowFn | None = None) -> None:
        self._now = now_fn or _now_ist

    def list_inventory(self) -> list[VisitSlot]:
        return generate_inventory(self._now())

    def get_available_slots(self, limit: int = 8) -> list[SlotInfo]:
        open_slots = [slot for slot in self.list_inventory() if slot.available]
        return [slot.to_info() for slot in open_slots[:limit]]

    def attempt_booking(
        self,
        *,
        session_id: str,
        name: str,
        phone: str,
        slot_id: str,
    ) -> BookingResponse:
        matching = next(
            (slot for slot in self.list_inventory() if slot.slot_id == slot_id),
            None,
        )
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
