"""Outbound API response models."""

from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    retryable: bool


class HealthResponse(BaseModel):
    status: str
    model: str
    llm_configured: bool


class SessionResponse(BaseModel):
    session_id: str
    greeting: str


class BookingSnapshot(BaseModel):
    status: str = "none"
    slot: str | None = None
    confirmation_id: str | None = None
    failure_count: int = 0
    history: list[Any] = Field(default_factory=list)


class SlotInfo(BaseModel):
    slot_id: str
    label: str
    available: bool = True


class SlotsResponse(BaseModel):
    slots: list[SlotInfo]


class BookingResponse(BaseModel):
    success: bool
    confirmation_id: str | None = None
    slot: str | None = None
    reason: str | None = None
    alternatives: list[SlotInfo] | None = None


class ProfileFieldSnapshot(BaseModel):
    value: Any
    confidence: str
    last_updated_turn: int = 0


class MemorySnapshot(BaseModel):
    """Public memory view for the MemoryPanel and GET /session/{id}/memory."""

    profile: dict[str, ProfileFieldSnapshot] = Field(default_factory=dict)
    state: str
    intent_history: list[Any] = Field(default_factory=list)
    objections: list[Any] = Field(default_factory=list)
    booking: BookingSnapshot = Field(default_factory=BookingSnapshot)
    language: str | None = None


class ChatResponse(BaseModel):
    reply: str
    state: str
    language: str
    memory_snapshot: MemorySnapshot
    booking: BookingSnapshot = Field(default_factory=BookingSnapshot)


class AnalyticsResponse(BaseModel):
    """Stub schema; Stage 08 fills scoring, sentiment, and summary for real."""

    session_id: str
    customer_name: str | None = None
    phone: str | None = None
    language: str | None = None
    languages_used: list[str] = Field(default_factory=list)
    budget_range: str | None = None
    configuration: str | None = None
    timeline: str | None = None
    buying_purpose: str | None = None
    financing: str | None = None
    city: str | None = None
    interest_level: str | None = None
    intent_history: list[Any] = Field(default_factory=list)
    objections: list[Any] = Field(default_factory=list)
    booking_status: str | None = None
    booking_slot: str | None = None
    confirmation_id: str | None = None
    escalation: dict[str, Any] | None = None
    stop_requested: bool = False
    follow_up_required: bool = False
    follow_up_reason: str | None = None
    sentiment: str | None = None
    conversation_duration_seconds: int | None = None
    turn_count: int | None = None
    lead_score: int | None = None
    lead_grade: str | None = None
    confidence: float | None = None
    summary: str | None = None
