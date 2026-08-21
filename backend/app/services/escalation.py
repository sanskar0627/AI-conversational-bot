"""Escalation trigger detection and payload builder."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.memory.schemas import ConversationState, SessionMemory
from app.models.llm_output import AgentAction, StructuredTurn
from app.services.intent import Intent, consecutive_intent_count, is_stop_request
from app.utils.logging import get_logger, mask_pii

logger = get_logger(__name__)

REASON_HUMAN_REQUESTED = "human_requested"
REASON_SENSITIVE_TOPIC = "sensitive_topic"
REASON_UNKNOWN_X2 = "unknown_question_x2"
REASON_BOOKING_FAILED = "booking_failed"
REASON_URGENCY = "urgency"

_SENSITIVE_RE = re.compile(
    r"""
    (?:
        \brera\b
        | stamp\s*-?duty
        | income\s*tax
        | capital\s*gains
        | legal\s*(?:notice|advice|issue)
        | court\s*case
        | \blawyer\b
        | \badvocate\b
        | loan\s*approval
        | pre-?approved
        | interest\s*rate
        | \bcomplaint\b
        | \bdispute\b
        | consumer\s*court
        | registration\s*charges
        | \bshikayat\b
        | कानूनी
        | शिकायत
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_URGENCY_RE = re.compile(
    r"""
    (?:
        \burgent(?:ly)?\b
        | aaj\s+hi
        | flying\s+out
        | leaving\s+tomorrow
        | \bimmediately\b
        | as\s+soon\s+as\s+possible
        | \basap\b
        | abhi\s+chahiye
        | \bemergency\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_FAQ_OR_DISCOVERY = frozenset(
    {ConversationState.FAQ, ConversationState.DISCOVERY}
)


def contains_sensitive_topic(text: str) -> bool:
    return bool(text and _SENSITIVE_RE.search(text))


def contains_urgency(text: str) -> bool:
    return bool(text and _URGENCY_RE.search(text))


class EscalationService:
    """Deterministic escalation: the LLM may propose; this service decides."""

    def should_escalate(
        self,
        memory: SessionMemory,
        turn: StructuredTurn,
        *,
        user_message: str,
        start_state: ConversationState,
    ) -> str | None:
        """Return a reason code, or None if this turn should not escalate."""
        if is_stop_request(user_message) or turn.intent == Intent.stop_communication:
            return None
        if turn.intent == Intent.human_agent or turn.action == AgentAction.escalate:
            return REASON_HUMAN_REQUESTED
        if contains_sensitive_topic(user_message):
            return REASON_SENSITIVE_TOPIC
        unknown_streak = consecutive_intent_count(
            memory.intent_history, Intent.unknown_question
        )
        if unknown_streak >= 2 and start_state in _FAQ_OR_DISCOVERY:
            return REASON_UNKNOWN_X2
        if int(memory.booking.get("failure_count") or 0) >= 2:
            return REASON_BOOKING_FAILED
        if contains_urgency(user_message):
            return REASON_URGENCY
        return None

    def build_payload(
        self,
        memory: SessionMemory,
        reason: str,
        *,
        urgency: str | None = None,
        user_message: str = "",
    ) -> dict[str, Any]:
        language = (
            memory.language_history[-1]
            if memory.language_history
            else "english"
        )
        if urgency is None:
            urgency = "high" if contains_urgency(user_message) else "normal"
        payload = {
            "session_id": memory.session_id,
            "reason": reason,
            "urgency": urgency,
            "customer_name": memory.profile.get("name"),
            "phone": memory.profile.get("phone"),
            "language": language,
            "summary": _session_summary(memory),
            "pending_questions": _pending_questions(memory),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        logger.info(
            "escalation session=%s reason=%s urgency=%s phone=%s",
            memory.session_id,
            reason,
            urgency,
            mask_pii(str(payload.get("phone") or "")),
        )
        return payload


def _session_summary(memory: SessionMemory) -> str:
    if memory.rolling_summary:
        return memory.rolling_summary
    intents = [item.get("intent") for item in memory.intent_history if item.get("intent")]
    if not intents:
        return ""
    return "Intents: " + ", ".join(str(intent) for intent in intents[-8:])


def _pending_questions(memory: SessionMemory) -> list[str]:
    user_turns = [record for record in memory.turns if record.get("role") == "user"]
    questions: list[str] = []
    for item in memory.intent_history:
        if item.get("intent") != Intent.unknown_question.value:
            continue
        idx = int(item.get("turn") or 0) - 1
        if 0 <= idx < len(user_turns):
            text = user_turns[idx].get("text")
            if isinstance(text, str) and text:
                questions.append(text)
    return questions
