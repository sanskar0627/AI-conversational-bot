"""Deterministic site-visit slot inventory. Booking attempts land in later commits."""

from __future__ import annotations

import hashlib
import secrets
import string
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.responses import BookingResponse, SlotInfo
from app.utils.validators import is_valid_name, is_valid_phone, is_valid_slot_id

IST = ZoneInfo("Asia/Kolkata")
HORIZON_DAYS = 7
SLOT_HOURS = (10, 12, 14, 16)
SLOT_ID_FORMAT = "%Y-%m-%d-%H%M"
UNAVAILABLE_SEED = 79
UNAVAILABLE_PERCENT = 22
SUNDAY = 6
SUNDAY_MORNING_HOUR = 10
FAILURE_DETERMINISTIC = "deterministic"
FAILURE_ALWAYS_ONCE = "always_fail_once"
CONFIRMATION_PREFIX = "NS-"
CONFIRMATION_ALPHABET = string.ascii_uppercase + string.digits

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


def is_sunday_morning(starts_at: datetime) -> bool:
    """Sunday 10:00 is the demo trigger: offered, but booking later fails as taken."""
    return starts_at.weekday() == SUNDAY and starts_at.hour == SUNDAY_MORNING_HOUR


def _seeded_unavailable(slot_id: str, *, seed: int = UNAVAILABLE_SEED) -> bool:
    digest = hashlib.sha256(f"{seed}:{slot_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 100 < UNAVAILABLE_PERCENT


def generate_inventory(
    now: datetime,
    *,
    days: int = HORIZON_DAYS,
    seed: int = UNAVAILABLE_SEED,
) -> list[VisitSlot]:
    """Next `days` calendar days, 10:00–18:00 in 2-hour slots (IST).

    A seeded subset is marked unavailable so demos stay reproducible. Sunday
    morning stays listed so the assignment's slot-taken path can be triggered.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)
    start_day = now.date()
    slots: list[VisitSlot] = []
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        for hour in SLOT_HOURS:
            starts_at = datetime(
                day.year, day.month, day.day, hour, 0, tzinfo=IST
            )
            if starts_at <= now:
                continue
            slot_id = make_slot_id(starts_at)
            unavailable = _seeded_unavailable(slot_id, seed=seed) and not is_sunday_morning(
                starts_at
            )
            slots.append(
                VisitSlot(
                    slot_id=slot_id,
                    starts_at=starts_at,
                    available=not unavailable,
                )
            )
    return slots


def mint_confirmation_id() -> str:
    token = "".join(secrets.choice(CONFIRMATION_ALPHABET) for _ in range(6))
    return f"{CONFIRMATION_PREFIX}{token}"


def format_slot_offer(slots: list[SlotInfo]) -> str:
    """Deterministic offer line the engine injects into the agent reply."""
    labels = ", ".join(slot.label for slot in slots)
    return f"Available: {labels}." if labels else "Available: (none right now)."


class BookingService:
    """In-memory slot inventory. Simulator attempts come after the inventory lands."""

    def __init__(
        self,
        *,
        now_fn: NowFn | None = None,
        seed: int = UNAVAILABLE_SEED,
        failure_mode: str | None = None,
    ) -> None:
        self._now = now_fn or _now_ist
        self._seed = seed
        settings = get_settings()
        self._failure_mode = (failure_mode if failure_mode is not None else settings.booking_failure_mode).strip()
        self._forced_fail_sessions: set[str] = set()
        self._taken: set[str] = set()

    def list_inventory(self) -> list[VisitSlot]:
        slots = generate_inventory(self._now(), seed=self._seed)
        return [
            replace(slot, available=False) if slot.slot_id in self._taken else slot
            for slot in slots
        ]

    def get_slot(self, slot_id: str) -> VisitSlot | None:
        return next((slot for slot in self.list_inventory() if slot.slot_id == slot_id), None)

    def get_available_slots(self, limit: int = 8) -> list[SlotInfo]:
        open_slots = [slot for slot in self.list_inventory() if slot.available]
        return [slot.to_info() for slot in open_slots[:limit]]

    def nearest_alternatives(self, slot_id: str, *, limit: int = 3) -> list[SlotInfo]:
        """Open slots closest in time to `slot_id`, excluding the requested one."""
        target = parse_slot_id(slot_id) or self._now()
        ranked = sorted(
            (
                slot
                for slot in self.list_inventory()
                if slot.available and slot.slot_id != slot_id
            ),
            key=lambda slot: abs((slot.starts_at - target).total_seconds()),
        )
        return [slot.to_info() for slot in ranked[:limit]]

    def attempt_booking(
        self,
        *,
        session_id: str,
        name: str,
        phone: str,
        slot_id: str,
    ) -> BookingResponse:
        if not is_valid_name(name or ""):
            return BookingResponse(success=False, reason="invalid_name")
        if not is_valid_phone(phone or ""):
            return BookingResponse(success=False, reason="invalid_phone")

        matching = next(
            (slot for slot in self.list_inventory() if slot.slot_id == slot_id),
            None,
        )
        if matching is None:
            return BookingResponse(
                success=False,
                reason="slot_taken",
                alternatives=self.nearest_alternatives(slot_id, limit=3),
            )

        if self._should_force_system_error(session_id):
            return BookingResponse(
                success=False,
                reason="system_error",
                alternatives=self.nearest_alternatives(slot_id, limit=3),
            )

        if is_sunday_morning(matching.starts_at) or not matching.available:
            return BookingResponse(
                success=False,
                reason="slot_taken",
                alternatives=self.nearest_alternatives(slot_id, limit=3),
            )
        self._taken.add(slot_id)
        return BookingResponse(
            success=True,
            confirmation_id=mint_confirmation_id(),
            slot=slot_id,
            slot_label=matching.label,
        )

    def _should_force_system_error(self, session_id: str) -> bool:
        if self._failure_mode != FAILURE_ALWAYS_ONCE:
            return False
        if session_id in self._forced_fail_sessions:
            return False
        self._forced_fail_sessions.add(session_id)
        return True
