"""Analytics assembly stub. Scoring rubric lands in Stage 08."""

from __future__ import annotations

from app.memory.schemas import ConversationState, SessionMemory
from app.models.responses import AnalyticsResponse


def build_stub_analytics(memory: SessionMemory) -> AnalyticsResponse:
    """Deterministic placeholder payload so end-session and GET analytics work now."""
    booking = memory.booking or {}
    user_turns = [turn for turn in memory.turns if turn.get("role") == "user"]
    duration = int((memory.last_active_at - memory.created_at).total_seconds())
    return AnalyticsResponse(
        session_id=memory.session_id,
        customer_name=memory.profile.get("name"),
        phone=memory.profile.get("phone"),
        language=memory.language_history[-1] if memory.language_history else None,
        languages_used=list(dict.fromkeys(memory.language_history)),
        budget_range=memory.profile.get("budget"),
        configuration=memory.profile.get("configuration"),
        timeline=memory.profile.get("timeline"),
        buying_purpose=memory.profile.get("purpose"),
        financing=memory.profile.get("financing"),
        city=memory.profile.get("city"),
        interest_level=None,
        intent_history=memory.intent_history,
        objections=memory.objections,
        booking_status=booking.get("status"),
        booking_slot=booking.get("slot"),
        confirmation_id=booking.get("confirmation_id"),
        escalation=memory.escalation,
        stop_requested=memory.state == ConversationState.STOPPED,
        follow_up_required=False,
        follow_up_reason=None,
        sentiment=None,
        conversation_duration_seconds=duration,
        turn_count=len(user_turns),
        lead_score=None,
        lead_grade=None,
        confidence=None,
        summary="Stub analytics — full scoring lands in Stage 08.",
    )
