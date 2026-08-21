"""Thread-safe in-memory session store with merge/conflict rules and TTL expiry."""

from __future__ import annotations

import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.config import get_settings
from app.exceptions import SessionExpiredError, SessionNotFoundError
from app.memory.schemas import (
    CONFLICT_FIELDS,
    IDENTITY_FIELDS,
    VOLATILE_FIELDS,
    FieldConfidence,
    LeadProfile,
    PendingConfirmation,
    SessionMemory,
    parse_budget_value,
)
from app.models.llm_output import ExtractedFields
from app.models.responses import BookingSnapshot, MemorySnapshot
from app.utils.validators import is_valid_name, is_valid_phone, normalize_phone

NowFn = Callable[[], datetime]

_VAGUE_RE = re.compile(
    r"theek\s*hi|theek\s*thaak|not\s*sure|don'?t\s*know|maybe|flexible|"
    r"around|sort\s*of|kuch\s*bhi|whatever|manageable|ok(ay)?(\s*hai)?$",
    re.IGNORECASE,
)
_AFFIRM_RE = re.compile(
    r"^\s*(yes|yeah|yep|yup|correct|right|haan+|ha\b|haanji|sahi|"
    r"ok(?:ay)?|sure|bilkul|theek\s*hai|that's\s*right|switching)\b",
    re.IGNORECASE,
)
_DENY_RE = re.compile(
    r"^\s*(no|nope|nahi+|nah\b|galat|wrong|not\s+really|keep\s+the|"
    r"2\s*bhk\s*(hi|rakho|rakhen)|stay\s+with)\b",
    re.IGNORECASE,
)
_CONFIG_2_RE = re.compile(r"\b2\s*-?\s*bhk\b", re.IGNORECASE)
_CONFIG_3_RE = re.compile(r"\b3\s*-?\s*bhk\b", re.IGNORECASE)

_EXTRACTED_TO_PROFILE = {
    "name": "name",
    "phone": "phone",
    "configuration": "configuration",
    "timeline": "timeline",
    "purpose": "purpose",
    "financing": "financing",
    "city": "city",
    "visit_interest": "visit_interest",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SessionStore:
    """Dict-backed store with lazy TTL sweep and thread-safe access."""

    def __init__(
        self,
        ttl_minutes: int | None = None,
        now_fn: NowFn | None = None,
    ) -> None:
        settings = get_settings()
        self._ttl = timedelta(minutes=ttl_minutes or settings.session_ttl_minutes)
        self._now = now_fn or _utc_now
        self._sessions: dict[str, SessionMemory] = {}
        self._expired_ids: set[str] = set()
        self._lock = threading.RLock()

    def create(self, channel: str) -> SessionMemory:
        self._sweep()
        now = self._now()
        session = SessionMemory(
            session_id=str(uuid.uuid4()),
            channel=channel,
            created_at=now,
            last_active_at=now,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str, *, touch: bool = True) -> SessionMemory:
        self._sweep()
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                if session_id in self._expired_ids:
                    raise SessionExpiredError()
                raise SessionNotFoundError()
            if self._is_expired(session):
                self._mark_expired(session_id)
                raise SessionExpiredError()
            if touch:
                session.last_active_at = self._now()
            return session

    def save(self, session: SessionMemory) -> None:
        with self._lock:
            session.last_active_at = self._now()
            self._sessions[session.session_id] = session
            self._expired_ids.discard(session.session_id)

    def _is_expired(self, session: SessionMemory) -> bool:
        return self._now() - session.last_active_at > self._ttl

    def _mark_expired(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._expired_ids.add(session_id)

    def _sweep(self) -> None:
        with self._lock:
            expired = [
                session_id
                for session_id, session in self._sessions.items()
                if self._is_expired(session)
            ]
            for session_id in expired:
                self._mark_expired(session_id)


def build_memory_snapshot(memory: SessionMemory) -> MemorySnapshot:
    """Masked profile + state for ChatResponse and GET /memory."""
    view = memory.public_view()
    return MemorySnapshot(
        profile=view["profile"],
        state=view["state"],
        intent_history=view["intent_history"],
        objections=view["objections"],
        booking=BookingSnapshot.model_validate(view["booking"]),
        language=view["language"],
    )


def pending_confirmation_hint(memory: SessionMemory) -> str | None:
    pending = memory.pending_confirmation
    if pending is None:
        return None
    return (
        f"Confirm naturally: customer may have switched to {pending.proposed_value} "
        f"(previously {pending.previous_value})."
    )


def do_not_reask_fields(profile: LeadProfile) -> list[str]:
    """Known fields plus uncertain fields that already had one clarification."""
    names: list[str] = []
    for name, field in profile.populated_fields():
        skip = field.confidence != FieldConfidence.uncertain or field.clarification_asked
        if not skip:
            continue
        label = "budget" if name in {"budget_min", "budget_max"} else name
        if label not in names:
            names.append(label)
    return names


def merge_extracted_fields(
    memory: SessionMemory,
    fields: ExtractedFields | dict[str, Any] | None,
    *,
    turn_no: int,
    user_message: str = "",
) -> None:
    """Merge non-null extracted values using overwrite, identity, and conflict rules.

    Every write stamps `turn_no`. Invalid phones never enter the profile. Vague
    answers are stored as `uncertain`. A contradicting `confirmed` value sets
    `pending_confirmation` instead of silently overwriting.
    """
    payload = _extracted_as_dict(fields)
    if not payload and not memory.pending_confirmation:
        return

    if memory.pending_confirmation:
        _resolve_pending_confirmation(memory, payload, turn_no, user_message)

    incoming = _expand_extracted(payload)
    hinted = _confidence_hints(fields)

    for name, value in incoming.items():
        if value in (None, ""):
            continue
        _merge_one_field(
            memory,
            name,
            value,
            turn_no=turn_no,
            user_message=user_message,
            hinted_confidence=hinted.get(name),
        )


def values_equivalent(field_name: str, left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left == right
    if field_name == "configuration":
        return normalize_configuration(left) == normalize_configuration(right)
    if field_name == "phone":
        return normalize_phone(str(left)) == normalize_phone(str(right))
    if field_name == "name":
        return str(left).strip().lower() == str(right).strip().lower()
    if field_name in {"budget_min", "budget_max"}:
        try:
            return float(left) == float(right)
        except (TypeError, ValueError):
            return str(left).strip().lower() == str(right).strip().lower()
    if field_name == "visit_interest":
        return coerce_visit_interest(left) == coerce_visit_interest(right)
    return str(left).strip().lower() == str(right).strip().lower()


def normalize_configuration(value: Any) -> str:
    text = str(value).strip()
    if _CONFIG_3_RE.search(text):
        return "3 BHK"
    if _CONFIG_2_RE.search(text):
        return "2 BHK"
    return re.sub(r"\s+", " ", text)


def coerce_visit_interest(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"yes", "true", "interested", "haan", "sure", "1"}:
        return True
    if text in {"no", "false", "not interested", "nahi", "0"}:
        return False
    return value


def is_vague_value(value: Any) -> bool:
    if value in (None, ""):
        return False
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return False
    return bool(_VAGUE_RE.search(str(value).strip()))


def _merge_one_field(
    memory: SessionMemory,
    name: str,
    value: Any,
    *,
    turn_no: int,
    user_message: str,
    hinted_confidence: FieldConfidence | None,
) -> None:
    profile: LeadProfile = memory.profile
    existing = profile.field(name)
    prepared = _prepare_value(name, value)
    if prepared is None:
        return

    if name == "phone" and not is_valid_phone(str(prepared)):
        return
    if name == "name" and not is_valid_name(str(prepared)):
        return

    if name == "phone":
        prepared = normalize_phone(str(prepared))

    if (
        name == "name"
        and existing is not None
        and existing.value not in (None, "")
        and is_valid_name(str(existing.value))
        and not is_valid_name(str(prepared))
    ):
        return

    if hinted_confidence is not None:
        confidence = hinted_confidence
    elif is_vague_value(value):
        confidence = FieldConfidence.uncertain
    elif name == "configuration" and normalize_configuration(prepared) in {"2 BHK", "3 BHK"}:
        confidence = FieldConfidence.confirmed
    else:
        confidence = FieldConfidence.stated

    if existing is None or existing.value in (None, ""):
        profile.set_field(name, prepared, confidence=confidence, turn=turn_no)
        return

    if values_equivalent(name, existing.value, prepared):
        next_confidence = existing.confidence
        if existing.confidence == FieldConfidence.uncertain and confidence != FieldConfidence.uncertain:
            next_confidence = confidence
        elif confidence == FieldConfidence.confirmed:
            next_confidence = FieldConfidence.confirmed
        elif (
            existing.confidence == FieldConfidence.stated
            and confidence != FieldConfidence.uncertain
        ):
            next_confidence = FieldConfidence.confirmed
        clarification = existing.clarification_asked or existing.confidence == FieldConfidence.uncertain
        profile.set_field(
            name,
            prepared,
            confidence=next_confidence,
            turn=turn_no,
            clarification_asked=clarification,
        )
        return

    if name in VOLATILE_FIELDS:
        clarification = existing.clarification_asked
        if confidence == FieldConfidence.uncertain:
            clarification = True if existing.confidence == FieldConfidence.uncertain else False
        profile.set_field(
            name,
            prepared,
            confidence=confidence,
            turn=turn_no,
            clarification_asked=clarification,
        )
        return

    if name in IDENTITY_FIELDS:
        profile.set_field(name, prepared, confidence=confidence, turn=turn_no)
        return

    if name in CONFLICT_FIELDS and existing.confidence in {
        FieldConfidence.confirmed,
        FieldConfidence.stated,
    }:
        memory.pending_confirmation = PendingConfirmation(
            field=name,
            previous_value=existing.value,
            proposed_value=prepared,
        )
        profile.set_field(name, prepared, confidence=FieldConfidence.stated, turn=turn_no)
        return

    profile.set_field(name, prepared, confidence=confidence, turn=turn_no)


def _resolve_pending_confirmation(
    memory: SessionMemory,
    payload: dict[str, Any],
    turn_no: int,
    user_message: str,
) -> None:
    pending = memory.pending_confirmation
    if pending is None:
        return
    field_name = pending.field
    extracted = payload.get(field_name)
    if field_name == "configuration" and extracted in (None, "") and "configuration" not in payload:
        extracted = None

    if extracted not in (None, ""):
        prepared = _prepare_value(field_name, extracted)
        if prepared is None:
            return
        if values_equivalent(field_name, prepared, pending.proposed_value):
            memory.profile.set_field(
                field_name,
                pending.proposed_value if field_name != "configuration" else normalize_configuration(pending.proposed_value),
                confidence=FieldConfidence.confirmed,
                turn=turn_no,
            )
            memory.pending_confirmation = None
            payload.pop(field_name, None)
            return
        if values_equivalent(field_name, prepared, pending.previous_value):
            revert = pending.previous_value
            if field_name == "configuration":
                revert = normalize_configuration(revert)
            memory.profile.set_field(
                field_name,
                revert,
                confidence=FieldConfidence.confirmed,
                turn=turn_no,
            )
            memory.pending_confirmation = None
            payload.pop(field_name, None)
            return
        return

    if user_message and _AFFIRM_RE.search(user_message.strip()):
        value = pending.proposed_value
        if field_name == "configuration":
            value = normalize_configuration(value)
        memory.profile.set_field(
            field_name, value, confidence=FieldConfidence.confirmed, turn=turn_no
        )
        memory.pending_confirmation = None
        return

    if user_message and _DENY_RE.search(user_message.strip()):
        value = pending.previous_value
        if field_name == "configuration":
            value = normalize_configuration(value)
        memory.profile.set_field(
            field_name, value, confidence=FieldConfidence.confirmed, turn=turn_no
        )
        memory.pending_confirmation = None


def _expand_extracted(payload: dict[str, Any]) -> dict[str, Any]:
    expanded: dict[str, Any] = {}
    for source, target in _EXTRACTED_TO_PROFILE.items():
        if source in payload and payload[source] not in (None, ""):
            expanded[target] = payload[source]

    budget = payload.get("budget")
    budget_min = payload.get("budget_min")
    budget_max = payload.get("budget_max")
    if budget_min not in (None, "") or budget_max not in (None, ""):
        if budget_min not in (None, ""):
            expanded["budget_min"] = budget_min
        if budget_max not in (None, ""):
            expanded["budget_max"] = budget_max
    elif budget not in (None, ""):
        parsed = parse_budget_value(budget)
        if parsed is not None:
            expanded["budget_min"], expanded["budget_max"] = parsed
            if is_vague_value(budget):
                # Keep the raw phrase so uncertain marking still fires.
                if not isinstance(parsed[0], (int, float)):
                    expanded["budget_min"] = budget
                    expanded["budget_max"] = budget
    return expanded


def _prepare_value(name: str, value: Any) -> Any:
    if name == "configuration":
        return normalize_configuration(value)
    if name == "visit_interest":
        return coerce_visit_interest(value)
    if name == "name":
        return str(value).strip()
    if name == "phone":
        return str(value).strip()
    return value


def _extracted_as_dict(fields: ExtractedFields | dict[str, Any] | None) -> dict[str, Any]:
    if fields is None:
        return {}
    if isinstance(fields, ExtractedFields):
        return fields.model_dump(exclude_none=True)
    return {key: value for key, value in fields.items() if value not in (None, "")}


def _confidence_hints(
    fields: ExtractedFields | dict[str, Any] | None,
) -> dict[str, FieldConfidence]:
    if fields is None or isinstance(fields, dict):
        extra = (fields or {}).get("field_confidence") if isinstance(fields, dict) else None
    else:
        extra = getattr(fields, "field_confidence", None)
    if not isinstance(extra, dict):
        return {}
    hints: dict[str, FieldConfidence] = {}
    for key, raw in extra.items():
        try:
            hints[str(key)] = FieldConfidence(str(raw).strip().lower())
        except ValueError:
            continue
    return hints
