"""Deterministic site-visit slot inventory and booking simulator."""

from __future__ import annotations

import hashlib
import re
import secrets
import string
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.memory.schemas import SessionMemory
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
MAX_VALIDATION_ATTEMPTS = 2
VALIDATION_REASONS = frozenset({"invalid_name", "invalid_phone"})
FOLLOW_UP_CANCELLED = "cancelled_visit"

_WEEKDAY_NAMES = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}
_TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.IGNORECASE)

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


def format_confirmation_reply(result: BookingResponse) -> str:
    label = result.slot_label or result.slot or "your chosen slot"
    return f"You're booked for {label}. Confirmation ID {result.confirmation_id}."


def format_failure_reply(result: BookingResponse) -> str:
    labels = ", ".join(slot.label for slot in (result.alternatives or []))
    alt = f" Alternatives: {labels}." if labels else ""
    if result.reason == "slot_taken":
        return f"That slot just got taken.{alt}".strip()
    if result.reason == "system_error":
        return f"The booking system hit a glitch. Please retry.{alt}".strip()
    return f"I couldn't complete that booking.{alt}".strip()


def format_cancel_reply(label: str | None) -> str:
    if label:
        return f"I've cancelled your visit for {label}. We'll follow up if you'd like to reschedule."
    return "I've cancelled the site visit. We'll follow up if you'd like to book again."


def format_validation_reply(reason: str, *, attempts: int) -> str:
    if attempts >= MAX_VALIDATION_ATTEMPTS:
        return (
            "I still don't have a valid name and 10-digit Indian mobile, "
            "so I can't lock a visit yet. Our team can book it once you share them."
        )
    if reason == "invalid_phone":
        return "Please share a 10-digit Indian mobile starting with 6 to 9 so I can confirm the visit."
    return "Please share your full name and a 10-digit Indian mobile so I can confirm the visit."


def apply_booking_result(
    memory: SessionMemory,
    result: BookingResponse,
    *,
    event: str,
    requested_slot: str | None = None,
) -> None:
    """Write a simulator result onto session booking state (engine and API share this)."""
    booking = memory.booking
    history = booking.setdefault("history", [])
    if result.reason in VALIDATION_REASONS:
        booking["validation_attempts"] = int(booking.get("validation_attempts") or 0) + 1
        booking["reason"] = result.reason
        history.append({"event": "validation_failed", "reason": result.reason})
        return
    if event == "cancelled":
        history.append(
            {
                "event": "cancelled",
                "slot": booking.get("slot"),
                "id": booking.get("confirmation_id"),
            }
        )
        booking["status"] = "cancelled"
        booking["slot"] = None
        booking["confirmation_id"] = None
        booking["reason"] = "cancelled"
        booking["alternatives"] = []
        booking["follow_up_required"] = True
        booking["follow_up_reason"] = FOLLOW_UP_CANCELLED
        return
    if result.success:
        if event == "rescheduled":
            history.append(
                {
                    "event": "rescheduled",
                    "from": booking.get("slot"),
                    "to": result.slot,
                    "old_id": booking.get("confirmation_id"),
                    "id": result.confirmation_id,
                }
            )
        else:
            history.append(
                {
                    "event": "confirmed",
                    "id": result.confirmation_id,
                    "slot": result.slot,
                }
            )
        booking["status"] = "confirmed"
        booking["slot"] = result.slot
        booking["confirmation_id"] = result.confirmation_id
        booking["reason"] = None
        booking["alternatives"] = []
        booking["follow_up_required"] = False
        booking["follow_up_reason"] = None
        return
    booking["failure_count"] = int(booking.get("failure_count") or 0) + 1
    booking["status"] = "failed"
    booking["reason"] = result.reason
    booking["alternatives"] = [slot.model_dump() for slot in (result.alternatives or [])]
    history.append({"event": "failed", "reason": result.reason, "slot": requested_slot})


class BookingService:
    """Deterministic in-memory visit simulator: inventory, failures, reschedule, cancel."""

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

    def reschedule(
        self,
        *,
        session_id: str,
        name: str,
        phone: str,
        old_slot_id: str | None,
        new_slot_id: str,
    ) -> BookingResponse:
        """Cancel the old hold only after the new slot books successfully."""
        held = bool(old_slot_id) and old_slot_id in self._taken
        if old_slot_id:
            self._taken.discard(old_slot_id)
        result = self.attempt_booking(
            session_id=session_id,
            name=name,
            phone=phone,
            slot_id=new_slot_id,
        )
        if result.success:
            return result
        if held and old_slot_id:
            self._taken.add(old_slot_id)
        return result

    def cancel(self, *, slot_id: str | None) -> BookingResponse:
        if not slot_id:
            return BookingResponse(success=False, reason="no_booking")
        self._taken.discard(slot_id)
        slot = self.get_slot(slot_id)
        return BookingResponse(
            success=True,
            slot=slot_id,
            slot_label=slot.label if slot else None,
            reason="cancelled",
        )

    def resolve_slot_id(self, text: str, offered_ids: list[str] | None = None) -> str | None:
        """Map a customer message or extracted slot onto an inventory id."""
        offered = [item for item in (offered_ids or []) if item]
        raw = (text or "").strip()
        if is_valid_slot_id(raw):
            return raw
        lowered = raw.lower()
        for slot_id in offered:
            if slot_id.lower() in lowered:
                return slot_id

        inventory = self.list_inventory()
        for slot in inventory:
            if slot.label.lower() in lowered:
                return slot.slot_id

        weekday = _weekday_in_text(lowered)
        hour = _hour_in_text(lowered)
        pool = [slot for slot in inventory if slot.slot_id in offered] or [
            slot for slot in inventory if slot.available or is_sunday_morning(slot.starts_at)
        ]
        matched = [
            slot
            for slot in pool
            if (weekday is None or slot.starts_at.weekday() == weekday)
            and (hour is None or slot.starts_at.hour == hour)
        ]
        if weekday is None and hour is None:
            return None
        if len(matched) == 1:
            return matched[0].slot_id
        if offered:
            offered_match = [slot for slot in matched if slot.slot_id in offered]
            if len(offered_match) == 1:
                return offered_match[0].slot_id
            if offered_match:
                return offered_match[0].slot_id
        return matched[0].slot_id if matched else None

    def _should_force_system_error(self, session_id: str) -> bool:
        if self._failure_mode != FAILURE_ALWAYS_ONCE:
            return False
        if session_id in self._forced_fail_sessions:
            return False
        self._forced_fail_sessions.add(session_id)
        return True


def _weekday_in_text(text: str) -> int | None:
    for name, value in sorted(_WEEKDAY_NAMES.items(), key=lambda item: -len(item[0])):
        if re.search(rf"\b{re.escape(name)}\b", text):
            return value
    return None


def _hour_in_text(text: str) -> int | None:
    match = _TIME_RE.search(text)
    if not match:
        return None
    hour = int(match.group(1))
    meridian = (match.group(3) or "").lower()
    if meridian == "pm" and hour < 12:
        hour += 12
    if meridian == "am" and hour == 12:
        hour = 0
    if hour not in SLOT_HOURS and not meridian:
        # 4 → 16:00 in our afternoon inventory
        if hour + 12 in SLOT_HOURS:
            hour += 12
    return hour
