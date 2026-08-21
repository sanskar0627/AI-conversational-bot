"""Session memory schemas: lead profile with confidence, turns, and session record."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.logging import mask_phone

HISTORY_WINDOW = 10
SUMMARY_RECOMPUTE_EVERY = 5

PROFILE_FIELD_NAMES: tuple[str, ...] = (
    "name",
    "phone",
    "budget_min",
    "budget_max",
    "configuration",
    "timeline",
    "purpose",
    "financing",
    "city",
    "visit_interest",
)

IDENTITY_FIELDS = frozenset({"name", "phone"})
VOLATILE_FIELDS = frozenset({"budget_min", "budget_max", "timeline", "visit_interest"})
CONFLICT_FIELDS = frozenset({"configuration", "purpose", "financing", "city"})

_BUDGET_NUMBER_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(crore|cr|lakh|lac)?",
    re.IGNORECASE,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ConversationState(str, Enum):
    GREETING = "GREETING"
    DISCOVERY = "DISCOVERY"
    QUALIFICATION = "QUALIFICATION"
    FAQ = "FAQ"
    OBJECTION_HANDLING = "OBJECTION_HANDLING"
    BOOKING = "BOOKING"
    BOOKING_FAILED = "BOOKING_FAILED"
    FOLLOW_UP = "FOLLOW_UP"
    NOT_INTERESTED = "NOT_INTERESTED"
    ESCALATED = "ESCALATED"
    STOPPED = "STOPPED"
    CLOSED = "CLOSED"


TERMINAL_STATES = frozenset({ConversationState.STOPPED, ConversationState.CLOSED})


class FieldConfidence(str, Enum):
    confirmed = "confirmed"
    stated = "stated"
    uncertain = "uncertain"


class ProfileField(BaseModel):
    value: Any
    confidence: FieldConfidence = FieldConfidence.stated
    last_updated_turn: int = 0
    clarification_asked: bool = False

    @field_validator("confidence", mode="before")
    @classmethod
    def coerce_confidence(cls, value: object) -> object:
        if value in (None, ""):
            return FieldConfidence.stated
        if isinstance(value, str):
            lowered = value.strip().lower()
            aliases = {
                "high": FieldConfidence.confirmed,
                "certain": FieldConfidence.confirmed,
                "ok": FieldConfidence.stated,
                "medium": FieldConfidence.stated,
                "low": FieldConfidence.uncertain,
                "guess": FieldConfidence.uncertain,
            }
            if lowered in aliases:
                return aliases[lowered]
        return value


class LeadProfile(BaseModel):
    """Structured lead fields. Each populated field carries value + confidence."""

    model_config = ConfigDict(extra="ignore")

    name: ProfileField | None = None
    phone: ProfileField | None = None
    budget_min: ProfileField | None = None
    budget_max: ProfileField | None = None
    configuration: ProfileField | None = None
    timeline: ProfileField | None = None
    purpose: ProfileField | None = None
    financing: ProfileField | None = None
    city: ProfileField | None = None
    visit_interest: ProfileField | None = None

    def get(self, name: str, default: Any = None) -> Any:
        """Return a field's raw value. `budget` is synthesized from min/max."""
        if name == "budget":
            display = self.budget_display()
            return default if display is None else display
        field = getattr(self, name, None)
        if not isinstance(field, ProfileField):
            return default
        return field.value

    def __getitem__(self, name: str) -> Any:
        if name not in PROFILE_FIELD_NAMES and name != "budget":
            raise KeyError(name)
        return self.get(name)

    def __setitem__(self, name: str, value: Any) -> None:
        if name not in PROFILE_FIELD_NAMES:
            raise KeyError(name)
        if isinstance(value, ProfileField):
            setattr(self, name, value)
            return
        setattr(
            self,
            name,
            ProfileField(value=value, confidence=FieldConfidence.stated, last_updated_turn=0),
        )

    def field(self, name: str) -> ProfileField | None:
        if name not in PROFILE_FIELD_NAMES:
            return None
        current = getattr(self, name)
        return current if isinstance(current, ProfileField) else None

    def set_field(
        self,
        name: str,
        value: Any,
        *,
        confidence: FieldConfidence,
        turn: int,
        clarification_asked: bool = False,
    ) -> None:
        setattr(
            self,
            name,
            ProfileField(
                value=value,
                confidence=confidence,
                last_updated_turn=turn,
                clarification_asked=clarification_asked,
            ),
        )

    def populated_fields(self) -> list[tuple[str, ProfileField]]:
        items: list[tuple[str, ProfileField]] = []
        for name in PROFILE_FIELD_NAMES:
            field = getattr(self, name)
            if isinstance(field, ProfileField) and field.value not in (None, "", [], {}):
                items.append((name, field))
        return items

    def budget_display(self) -> str | None:
        low = self.budget_min.value if self.budget_min else None
        high = self.budget_max.value if self.budget_max else None
        if low in (None, "") and high in (None, ""):
            return None
        if high in (None, "") or low == high:
            return _format_budget_amount(low)
        if low in (None, ""):
            return _format_budget_amount(high)
        return f"{_format_budget_amount(low)}-{_format_budget_amount(high)}"

    def public_profile(self, *, mask_phones: bool = True) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for name, field in self.populated_fields():
            value = field.value
            if mask_phones and name == "phone" and value not in (None, ""):
                value = mask_phone(str(value))
            result[name] = {
                "value": value,
                "confidence": field.confidence.value,
                "last_updated_turn": field.last_updated_turn,
            }
        return result

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> LeadProfile:
        if not data:
            return cls()
        incoming = dict(data)
        if "budget" in incoming and "budget_min" not in incoming and "budget_max" not in incoming:
            parsed = parse_budget_value(incoming.pop("budget"))
            if parsed is not None:
                incoming["budget_min"] = parsed[0]
                incoming["budget_max"] = parsed[1]
        kwargs: dict[str, Any] = {}
        for name in PROFILE_FIELD_NAMES:
            raw = incoming.get(name)
            if raw is None or raw == "":
                continue
            kwargs[name] = _coerce_profile_field(raw)
        return cls(**kwargs)


class TurnRecord(BaseModel):
    turn_no: int
    role: str
    text: str
    language: str | None = None
    intent: str | None = None
    timestamp: datetime = Field(default_factory=utc_now)

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-style access so older turn-list loops keep working."""
        return getattr(self, key, default)


class PendingConfirmation(BaseModel):
    field: str
    previous_value: Any
    proposed_value: Any


def default_booking() -> dict[str, Any]:
    return {
        "status": "none",
        "slot": None,
        "confirmation_id": None,
        "failure_count": 0,
        "history": [],
    }


class SessionMemory(BaseModel):
    """Full in-memory session record for the conversation lifetime (TTL 60 min)."""

    model_config = ConfigDict(validate_assignment=True)

    session_id: str
    channel: str
    state: ConversationState = ConversationState.GREETING
    profile: LeadProfile = Field(default_factory=LeadProfile)
    turns: list[TurnRecord] = Field(default_factory=list)
    language_history: list[str] = Field(default_factory=list)
    intent_history: list[dict[str, Any]] = Field(default_factory=list)
    objections: list[dict[str, Any]] = Field(default_factory=list)
    booking: dict[str, Any] = Field(default_factory=default_booking)
    escalation: dict[str, Any] | None = None
    rolling_summary: str = ""
    pending_confirmation: PendingConfirmation | None = None
    summary_updated_at_len: int = 0
    analytics: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utc_now)
    last_active_at: datetime = Field(default_factory=utc_now)

    @field_validator("profile", mode="before")
    @classmethod
    def coerce_profile(cls, value: object) -> object:
        if value is None:
            return LeadProfile()
        if isinstance(value, LeadProfile):
            return value
        if isinstance(value, dict):
            return LeadProfile.from_mapping(value)
        return value

    @field_validator("turns", mode="before")
    @classmethod
    def coerce_turns(cls, value: object) -> object:
        if not value:
            return value
        if not isinstance(value, list):
            return value
        records: list[TurnRecord | dict[str, Any]] = []
        for index, item in enumerate(value):
            if isinstance(item, TurnRecord):
                records.append(item)
                continue
            if not isinstance(item, dict):
                continue
            text = item.get("text") or item.get("content") or ""
            records.append(
                {
                    "turn_no": item.get("turn_no") or index + 1,
                    "role": item.get("role") or "user",
                    "text": text,
                    "language": item.get("language"),
                    "intent": item.get("intent"),
                    "timestamp": item.get("timestamp") or utc_now(),
                }
            )
        return records

    def user_turn_count(self) -> int:
        return sum(1 for record in self.turns if record.role == "user")

    def recent_turns(self, limit: int = HISTORY_WINDOW) -> list[TurnRecord]:
        return self.turns[-limit:]

    def public_view(self) -> dict[str, Any]:
        language = self.language_history[-1] if self.language_history else None
        return {
            "profile": self.profile.public_profile(mask_phones=True),
            "state": self.state.value,
            "intent_history": self.intent_history,
            "objections": self.objections,
            "booking": self.booking,
            "language": language,
        }


def _coerce_profile_field(raw: Any) -> ProfileField:
    if isinstance(raw, ProfileField):
        return raw
    if isinstance(raw, dict) and "value" in raw:
        return ProfileField.model_validate(raw)
    return ProfileField(value=raw, confidence=FieldConfidence.stated, last_updated_turn=0)


def parse_budget_value(raw: Any) -> tuple[Any, Any] | None:
    """Split a budget string into (min, max). Numeric amounts are stored in crore."""
    if raw in (None, ""):
        return None
    if isinstance(raw, (int, float)):
        return raw, raw
    text = str(raw).strip()
    if not text:
        return None
    numbers = _BUDGET_NUMBER_RE.findall(text)
    if not numbers:
        return text, text
    amounts = [_to_crore(match[0], match[1] or text) for match in numbers]
    amounts = [amount for amount in amounts if amount is not None]
    if not amounts:
        return text, text
    if len(amounts) == 1:
        return amounts[0], amounts[0]
    return min(amounts), max(amounts)


def _to_crore(number: str, unit_hint: str) -> float | None:
    try:
        amount = float(number.replace(",", ""))
    except ValueError:
        return None
    lowered = unit_hint.lower()
    if "lakh" in lowered or "lac" in lowered:
        return round(amount / 100.0, 4)
    return amount


def _format_budget_amount(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        return f"{value:g} Cr"
    return str(value)
