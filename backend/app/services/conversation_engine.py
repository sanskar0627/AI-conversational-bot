"""Conversation engine: state machine, compliance overrides, hallucination checks."""

from __future__ import annotations

import time

from app.memory.schemas import TERMINAL_STATES, ConversationState, SessionMemory
from app.memory.store import SessionStore
from app.models.llm_output import AgentAction, DetectedLanguage, ExtractedFields, StructuredTurn
from app.models.responses import BookingSnapshot, ChatResponse
from app.prompts import system_prompt
from app.services.booking import BookingService
from app.services.escalation import EscalationService
from app.services.intent import (
    Intent,
    classify_objection,
    consecutive_intent_count,
    infer_language,
    is_stop_request,
)
from app.services.llm_client import LLMClient
from app.utils.logging import get_logger, mask_pii

logger = get_logger(__name__)

STOPPED_REPLIES = {
    "english": "Understood. We won't contact you again. Take care.",
    "hindi": "समझ गया। हम आपसे दोबारा संपर्क नहीं करेंगे। आपका दिन शुभ हो।",
    "hinglish": "Samajh gaya. Hum aapko dobara contact nahi karenge. Take care.",
}
CLOSED_REPLY = (
    "This conversation has ended. Start a new session if you'd like help with Northstar One."
)
HISTORY_WINDOW = 10

# (state, intent) → next state. Overrides (stop / escalate / booking events) run first.
TRANSITION_TABLE: dict[tuple[ConversationState, Intent], ConversationState] = {
    # Greeting
    (ConversationState.GREETING, Intent.greeting): ConversationState.DISCOVERY,
    (ConversationState.GREETING, Intent.thank_you): ConversationState.DISCOVERY,
    (ConversationState.GREETING, Intent.abusive_offtopic): ConversationState.DISCOVERY,
    (ConversationState.GREETING, Intent.not_interested): ConversationState.NOT_INTERESTED,
    (ConversationState.GREETING, Intent.stop_communication): ConversationState.STOPPED,
    (ConversationState.GREETING, Intent.human_agent): ConversationState.ESCALATED,
    (ConversationState.GREETING, Intent.pricing): ConversationState.FAQ,
    (ConversationState.GREETING, Intent.location): ConversationState.FAQ,
    (ConversationState.GREETING, Intent.amenities): ConversationState.FAQ,
    (ConversationState.GREETING, Intent.availability): ConversationState.FAQ,
    (ConversationState.GREETING, Intent.configuration): ConversationState.FAQ,
    (ConversationState.GREETING, Intent.unknown_question): ConversationState.FAQ,
    (ConversationState.GREETING, Intent.budget_inquiry): ConversationState.QUALIFICATION,
    (ConversationState.GREETING, Intent.site_visit): ConversationState.BOOKING,
    (ConversationState.GREETING, Intent.objection): ConversationState.OBJECTION_HANDLING,
    (ConversationState.GREETING, Intent.busy): ConversationState.FOLLOW_UP,
    (ConversationState.GREETING, Intent.call_later): ConversationState.FOLLOW_UP,
    # Discovery
    (ConversationState.DISCOVERY, Intent.budget_inquiry): ConversationState.QUALIFICATION,
    (ConversationState.DISCOVERY, Intent.site_visit): ConversationState.BOOKING,
    (ConversationState.DISCOVERY, Intent.pricing): ConversationState.FAQ,
    (ConversationState.DISCOVERY, Intent.location): ConversationState.FAQ,
    (ConversationState.DISCOVERY, Intent.amenities): ConversationState.FAQ,
    (ConversationState.DISCOVERY, Intent.availability): ConversationState.FAQ,
    (ConversationState.DISCOVERY, Intent.configuration): ConversationState.FAQ,
    (ConversationState.DISCOVERY, Intent.unknown_question): ConversationState.FAQ,
    (ConversationState.DISCOVERY, Intent.objection): ConversationState.OBJECTION_HANDLING,
    (ConversationState.DISCOVERY, Intent.not_interested): ConversationState.NOT_INTERESTED,
    (ConversationState.DISCOVERY, Intent.busy): ConversationState.FOLLOW_UP,
    (ConversationState.DISCOVERY, Intent.call_later): ConversationState.FOLLOW_UP,
    (ConversationState.DISCOVERY, Intent.human_agent): ConversationState.ESCALATED,
    (ConversationState.DISCOVERY, Intent.stop_communication): ConversationState.STOPPED,
    (ConversationState.DISCOVERY, Intent.greeting): ConversationState.DISCOVERY,
    (ConversationState.DISCOVERY, Intent.thank_you): ConversationState.DISCOVERY,
    # FAQ → Discovery once the question is answered (non-FAQ follow-up)
    (ConversationState.FAQ, Intent.greeting): ConversationState.DISCOVERY,
    (ConversationState.FAQ, Intent.thank_you): ConversationState.DISCOVERY,
    (ConversationState.FAQ, Intent.budget_inquiry): ConversationState.QUALIFICATION,
    (ConversationState.FAQ, Intent.site_visit): ConversationState.BOOKING,
    (ConversationState.FAQ, Intent.objection): ConversationState.OBJECTION_HANDLING,
    (ConversationState.FAQ, Intent.not_interested): ConversationState.NOT_INTERESTED,
    (ConversationState.FAQ, Intent.busy): ConversationState.FOLLOW_UP,
    (ConversationState.FAQ, Intent.call_later): ConversationState.FOLLOW_UP,
    (ConversationState.FAQ, Intent.human_agent): ConversationState.ESCALATED,
    (ConversationState.FAQ, Intent.stop_communication): ConversationState.STOPPED,
    (ConversationState.FAQ, Intent.pricing): ConversationState.FAQ,
    (ConversationState.FAQ, Intent.location): ConversationState.FAQ,
    (ConversationState.FAQ, Intent.amenities): ConversationState.FAQ,
    (ConversationState.FAQ, Intent.availability): ConversationState.FAQ,
    (ConversationState.FAQ, Intent.configuration): ConversationState.FAQ,
    (ConversationState.FAQ, Intent.unknown_question): ConversationState.FAQ,
    # Qualification
    (ConversationState.QUALIFICATION, Intent.objection): ConversationState.OBJECTION_HANDLING,
    (ConversationState.QUALIFICATION, Intent.site_visit): ConversationState.BOOKING,
    (ConversationState.QUALIFICATION, Intent.reschedule): ConversationState.BOOKING,
    (ConversationState.QUALIFICATION, Intent.stop_communication): ConversationState.STOPPED,
    (ConversationState.QUALIFICATION, Intent.not_interested): ConversationState.NOT_INTERESTED,
    (ConversationState.QUALIFICATION, Intent.busy): ConversationState.FOLLOW_UP,
    (ConversationState.QUALIFICATION, Intent.call_later): ConversationState.FOLLOW_UP,
    (ConversationState.QUALIFICATION, Intent.human_agent): ConversationState.ESCALATED,
    (ConversationState.QUALIFICATION, Intent.pricing): ConversationState.FAQ,
    (ConversationState.QUALIFICATION, Intent.budget_inquiry): ConversationState.QUALIFICATION,
    (ConversationState.QUALIFICATION, Intent.configuration): ConversationState.QUALIFICATION,
    (ConversationState.QUALIFICATION, Intent.thank_you): ConversationState.QUALIFICATION,
    # Objection handling
    (ConversationState.OBJECTION_HANDLING, Intent.budget_inquiry): ConversationState.QUALIFICATION,
    (ConversationState.OBJECTION_HANDLING, Intent.configuration): ConversationState.QUALIFICATION,
    (ConversationState.OBJECTION_HANDLING, Intent.pricing): ConversationState.QUALIFICATION,
    (ConversationState.OBJECTION_HANDLING, Intent.thank_you): ConversationState.QUALIFICATION,
    (ConversationState.OBJECTION_HANDLING, Intent.greeting): ConversationState.QUALIFICATION,
    (ConversationState.OBJECTION_HANDLING, Intent.site_visit): ConversationState.BOOKING,
    (ConversationState.OBJECTION_HANDLING, Intent.call_later): ConversationState.FOLLOW_UP,
    (ConversationState.OBJECTION_HANDLING, Intent.busy): ConversationState.FOLLOW_UP,
    (ConversationState.OBJECTION_HANDLING, Intent.not_interested): ConversationState.NOT_INTERESTED,
    (ConversationState.OBJECTION_HANDLING, Intent.objection): ConversationState.OBJECTION_HANDLING,
    (ConversationState.OBJECTION_HANDLING, Intent.stop_communication): ConversationState.STOPPED,
    (ConversationState.OBJECTION_HANDLING, Intent.human_agent): ConversationState.ESCALATED,
    # Booking
    (ConversationState.BOOKING, Intent.reschedule): ConversationState.BOOKING,
    (ConversationState.BOOKING, Intent.cancel_booking): ConversationState.BOOKING,
    (ConversationState.BOOKING, Intent.site_visit): ConversationState.BOOKING,
    (ConversationState.BOOKING, Intent.goodbye): ConversationState.CLOSED,
    (ConversationState.BOOKING, Intent.thank_you): ConversationState.CLOSED,
    (ConversationState.BOOKING, Intent.busy): ConversationState.FOLLOW_UP,
    (ConversationState.BOOKING, Intent.call_later): ConversationState.FOLLOW_UP,
    (ConversationState.BOOKING, Intent.not_interested): ConversationState.NOT_INTERESTED,
    (ConversationState.BOOKING, Intent.objection): ConversationState.OBJECTION_HANDLING,
    (ConversationState.BOOKING, Intent.stop_communication): ConversationState.STOPPED,
    (ConversationState.BOOKING, Intent.human_agent): ConversationState.ESCALATED,
    # Booking failed → retry alternative returns to Booking
    (ConversationState.BOOKING_FAILED, Intent.site_visit): ConversationState.BOOKING,
    (ConversationState.BOOKING_FAILED, Intent.reschedule): ConversationState.BOOKING,
    (ConversationState.BOOKING_FAILED, Intent.stop_communication): ConversationState.STOPPED,
    (ConversationState.BOOKING_FAILED, Intent.human_agent): ConversationState.ESCALATED,
    (ConversationState.BOOKING_FAILED, Intent.call_later): ConversationState.FOLLOW_UP,
    (ConversationState.BOOKING_FAILED, Intent.not_interested): ConversationState.NOT_INTERESTED,
    # Follow-up captured → close
    (ConversationState.FOLLOW_UP, Intent.goodbye): ConversationState.CLOSED,
    (ConversationState.FOLLOW_UP, Intent.thank_you): ConversationState.CLOSED,
    (ConversationState.FOLLOW_UP, Intent.call_later): ConversationState.FOLLOW_UP,
    (ConversationState.FOLLOW_UP, Intent.busy): ConversationState.FOLLOW_UP,
    (ConversationState.FOLLOW_UP, Intent.stop_communication): ConversationState.STOPPED,
    # Not interested → polite close
    (ConversationState.NOT_INTERESTED, Intent.goodbye): ConversationState.CLOSED,
    (ConversationState.NOT_INTERESTED, Intent.thank_you): ConversationState.CLOSED,
    (ConversationState.NOT_INTERESTED, Intent.not_interested): ConversationState.CLOSED,
    (ConversationState.NOT_INTERESTED, Intent.stop_communication): ConversationState.STOPPED,
    # Escalated → handoff confirmed
    (ConversationState.ESCALATED, Intent.goodbye): ConversationState.CLOSED,
    (ConversationState.ESCALATED, Intent.thank_you): ConversationState.CLOSED,
    (ConversationState.ESCALATED, Intent.human_agent): ConversationState.ESCALATED,
    (ConversationState.ESCALATED, Intent.stop_communication): ConversationState.STOPPED,
}


def next_state(
    state: ConversationState,
    intent: Intent,
    *,
    action: AgentAction = AgentAction.none,
    booking_event: str | None = None,
    consecutive_unknowns: int = 0,
    booking_failure_count: int = 0,
    escalate: bool = False,
) -> ConversationState:
    """Advance the FSM. Deterministic overrides beat the transition table."""
    if state in TERMINAL_STATES:
        return state

    if action == AgentAction.stop or intent == Intent.stop_communication:
        return ConversationState.STOPPED

    unknown_escalates = consecutive_unknowns >= 2 and state in {
        ConversationState.FAQ,
        ConversationState.DISCOVERY,
    }
    booking_escalates = booking_failure_count >= 2
    if (
        escalate
        or action == AgentAction.escalate
        or intent == Intent.human_agent
        or unknown_escalates
        or booking_escalates
    ):
        return ConversationState.ESCALATED

    if action == AgentAction.close:
        return ConversationState.CLOSED

    if booking_event == "failed":
        return ConversationState.BOOKING_FAILED
    if action == AgentAction.propose_slots or booking_event == "retry":
        return ConversationState.BOOKING

    mapped = TRANSITION_TABLE.get((state, intent), state)
    if booking_event == "confirmed" and mapped not in {
        ConversationState.CLOSED,
        ConversationState.STOPPED,
        ConversationState.ESCALATED,
    }:
        return ConversationState.BOOKING
    if action == AgentAction.confirm_booking and mapped == state:
        return ConversationState.BOOKING
    return mapped


def apply_stop_override(user_message: str, turn: StructuredTurn) -> StructuredTurn:
    """If regex says stop, it wins over whatever the LLM returned."""
    if not is_stop_request(user_message):
        return turn
    language = infer_language(user_message, fallback=turn.detected_language.value)
    return turn.model_copy(
        update={
            "intent": Intent.stop_communication,
            "action": AgentAction.stop,
            "reply": STOPPED_REPLIES.get(language, STOPPED_REPLIES["english"]),
            "detected_language": _to_language(language),
        }
    )


def stopped_reply(language: str) -> str:
    return STOPPED_REPLIES.get(language, STOPPED_REPLIES["english"])


def _to_language(value: str) -> DetectedLanguage:
    try:
        return DetectedLanguage(value)
    except ValueError:
        return DetectedLanguage.english


class ConversationEngine:
    """Load memory → (stop override | prompt → LLM → checks → actions) → ChatResponse."""

    def __init__(
        self,
        store: SessionStore,
        llm_client: LLMClient,
        booking: BookingService | None = None,
        escalation: EscalationService | None = None,
    ) -> None:
        self._store = store
        self._llm = llm_client
        self._booking = booking or BookingService()
        self._escalation = escalation or EscalationService()

    async def handle_turn(self, session_id: str, message: str) -> ChatResponse:
        memory = self._store.get(session_id)
        if memory.state in TERMINAL_STATES:
            return self._terminal_response(memory)

        if is_stop_request(message):
            return self._handle_stop(memory, message)

        started = time.perf_counter()
        start_state = memory.state
        prompt = system_prompt.render(
            memory=memory,
            state=memory.state,
            channel=memory.channel,
        )
        history = self._history_messages(memory)
        user_payload = {"role": "user", "content": f"Customer message: {message}"}
        turn = await self._llm.complete_turn(
            system_prompt=prompt,
            messages=[*history, user_payload],
        )
        turn = apply_stop_override(message, turn)

        self._merge_extracted_fields(memory, turn.extracted_fields)
        self._persist_turn(memory, message, turn)

        booking_event = None
        reason = self._escalation.should_escalate(
            memory, turn, user_message=message, start_state=start_state
        )
        self._advance_state(
            memory,
            turn,
            start_state=start_state,
            booking_event=booking_event,
            escalate_reason=reason,
            user_message=message,
        )
        self._maybe_resolve_objection(memory, start_state)
        self._store.save(memory)

        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "turn session=%s state=%s intent=%s action=%s latency_ms=%s",
            memory.session_id,
            memory.state.value,
            turn.intent.value,
            turn.action.value,
            latency_ms,
        )
        logger.debug("user_message=%s", mask_pii(message))
        return self._to_response(memory, turn.reply, turn.detected_language.value)

    def _handle_stop(self, memory: SessionMemory, message: str) -> ChatResponse:
        fallback = memory.language_history[-1] if memory.language_history else "english"
        language = infer_language(message, fallback=fallback)
        reply = stopped_reply(language)
        turn = StructuredTurn(
            reply=reply,
            detected_language=_to_language(language),
            intent=Intent.stop_communication,
            extracted_fields=ExtractedFields(),
            action=AgentAction.stop,
        )
        memory.state = ConversationState.STOPPED
        self._persist_turn(memory, message, turn)
        self._store.save(memory)
        return self._to_response(memory, reply, language)

    def _terminal_response(self, memory: SessionMemory) -> ChatResponse:
        if memory.state == ConversationState.STOPPED:
            fallback = memory.language_history[-1] if memory.language_history else "english"
            reply = stopped_reply(fallback)
        else:
            reply = CLOSED_REPLY
        language = memory.language_history[-1] if memory.language_history else "english"
        return self._to_response(memory, reply, language)

    def _history_messages(self, memory: SessionMemory) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for record in memory.turns[-HISTORY_WINDOW:]:
            role = record.get("role")
            text = record.get("text")
            if role in {"user", "assistant"} and isinstance(text, str):
                messages.append({"role": role, "content": text})
        return messages

    def _merge_extracted_fields(self, memory: SessionMemory, fields: ExtractedFields) -> None:
        """Simple non-null merge. Conflict/overwrite rules land in Stage 05."""
        for key, value in fields.model_dump(exclude_none=True).items():
            memory.profile[key] = value

    def _advance_state(
        self,
        memory: SessionMemory,
        turn: StructuredTurn,
        *,
        start_state: ConversationState,
        booking_event: str | None,
        escalate_reason: str | None,
        user_message: str,
    ) -> None:
        if turn.action == AgentAction.stop or turn.intent == Intent.stop_communication:
            memory.state = ConversationState.STOPPED
            return

        if escalate_reason:
            self._apply_escalation(memory, escalate_reason, user_message)
            return

        memory.state = next_state(
            start_state,
            turn.intent,
            action=turn.action,
            booking_event=booking_event,
            consecutive_unknowns=consecutive_intent_count(
                memory.intent_history, Intent.unknown_question
            ),
            booking_failure_count=int(memory.booking.get("failure_count") or 0),
        )

    def _apply_escalation(
        self, memory: SessionMemory, reason: str, user_message: str
    ) -> None:
        payload = self._escalation.build_payload(
            memory, reason, user_message=user_message
        )
        memory.escalation = payload
        memory.state = ConversationState.ESCALATED

    def _maybe_resolve_objection(
        self, memory: SessionMemory, start_state: ConversationState
    ) -> None:
        if start_state != ConversationState.OBJECTION_HANDLING:
            return
        if memory.state not in {
            ConversationState.QUALIFICATION,
            ConversationState.BOOKING,
            ConversationState.DISCOVERY,
        }:
            return
        for item in reversed(memory.objections):
            if not item.get("resolved"):
                item["resolved"] = True
                break

    def _persist_turn(self, memory: SessionMemory, user_message: str, turn: StructuredTurn) -> None:
        memory.turns.append({"role": "user", "text": user_message})
        memory.turns.append(
            {
                "role": "assistant",
                "text": turn.reply,
                "intent": turn.intent.value,
                "language": turn.detected_language.value,
            }
        )
        memory.language_history.append(turn.detected_language.value)
        turn_no = sum(1 for record in memory.turns if record.get("role") == "user")
        memory.intent_history.append({"turn": turn_no, "intent": turn.intent.value})
        if turn.intent == Intent.objection:
            memory.objections.append(
                {
                    "turn": turn_no,
                    "type": classify_objection(user_message),
                    "resolved": False,
                }
            )

    def _to_response(self, memory: SessionMemory, reply: str, language: str) -> ChatResponse:
        return ChatResponse(
            reply=reply,
            state=memory.state.value,
            language=language,
            memory_snapshot=dict(memory.profile),
            booking=BookingSnapshot.model_validate(memory.booking),
        )
