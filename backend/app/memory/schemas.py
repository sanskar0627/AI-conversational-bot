"""Minimal session memory schemas. Full profile semantics land in Stage 05."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


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


class SessionMemory(BaseModel):
    """In-memory session record. Stage 05 replaces profile dict with LeadProfile."""

    session_id: str
    channel: str
    state: ConversationState = ConversationState.GREETING
    profile: dict[str, Any] = Field(default_factory=dict)
    turns: list[dict[str, Any]] = Field(default_factory=list)
    language_history: list[str] = Field(default_factory=list)
    intent_history: list[dict[str, Any]] = Field(default_factory=list)
    objections: list[dict[str, Any]] = Field(default_factory=list)
    booking: dict[str, Any] = Field(
        default_factory=lambda: {
            "status": "none",
            "slot": None,
            "confirmation_id": None,
            "failure_count": 0,
            "history": [],
        }
    )
    escalation: dict[str, Any] | None = None
    rolling_summary: str = ""
    analytics: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utc_now)
    last_active_at: datetime = Field(default_factory=utc_now)
