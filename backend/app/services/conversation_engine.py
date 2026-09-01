"""Conversation engine: state machine, compliance overrides, hallucination checks."""

from __future__ import annotations

import re
import time

from app.exceptions import CreditsExhaustedError, LLMRateLimitedError, LLMTimeoutError
from app.memory.schemas import (
    HISTORY_WINDOW,
    TERMINAL_STATES,
    ConversationState,
    SessionMemory,
    TurnRecord,
    utc_now,
)
from app.memory.store import SessionStore, build_memory_snapshot, merge_extracted_fields
from app.memory.summary import refresh_rolling_summary
from app.models.llm_output import AgentAction, DetectedLanguage, ExtractedFields, StructuredTurn
from app.models.responses import BookingSnapshot, ChatResponse
from app.prompts import facts, system_prompt
from app.services.booking import BookingService, format_slot_offer
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
SAFE_PRICE_REPLY = (
    "Let me have our team confirm the exact figures. 2 BHK starts from 1.35 crore "
    "onwards and 3 BHK from 1.75 crore onwards. What else can I help with?"
)
HALLUCINATION_REPAIR_INSTRUCTION = (
    "Your previous reply mentioned prices, discounts, or figures that are not in FACTS. "
    "Only 2 BHK ₹1.35 crore onwards and 3 BHK ₹1.75 crore onwards may be stated. "
    "Never invent discounts, possession dates, or other prices. "
    "Return ONLY valid JSON matching the schema, with a corrected reply."
)
# Numbers the agent may attach to crore / ₹. Lakh equivalents of the same prices.
_ALLOWED_CRORE = {facts.PRICE_2BHK_CRORE, facts.PRICE_3BHK_CRORE}
_ALLOWED_LAKH = {facts.PRICE_2BHK_CRORE * 100, facts.PRICE_3BHK_CRORE * 100}

_CURRENCY_AMOUNT_RE = re.compile(
    r"(?:₹|rs\.?\s*|inr\s*)(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)
_UNIT_AMOUNT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(crore|cr\b|lakh|lac)",
    re.IGNORECASE,
)
_DISCOUNT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:%|percent)(?:\s*(?:off|discount))?"
    r"|(?:discount|off)\s*(?:of\s*)?(\d+(?:[.,]\d+)?)\s*(?:%|percent)",
    re.IGNORECASE,
)

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


def reply_has_disallowed_figures(text: str) -> bool:
    """True when the reply quotes a price/discount outside the closed fact sheet."""
    if not text:
        return False
    if _DISCOUNT_RE.search(text):
        return True
    for match in _CURRENCY_AMOUNT_RE.finditer(text):
        amount = _parse_amount(match.group(1))
        if amount is not None and amount not in _ALLOWED_CRORE and amount not in _ALLOWED_LAKH:
            return True
    for match in _UNIT_AMOUNT_RE.finditer(text):
        amount = _parse_amount(match.group(1))
        unit = match.group(2).lower()
        if amount is None:
            continue
        if unit.startswith("cr"):
            if amount not in _ALLOWED_CRORE:
                return True
        elif amount not in _ALLOWED_LAKH:
            return True
    return False


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


def _parse_amount(raw: str) -> float | None:
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


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
        turn = await self._hallucination_post_check(
            memory, prompt, [*history, user_payload], turn
        )
        turn = apply_stop_override(message, turn)

        turn_no = memory.user_turn_count() + 1
        merge_extracted_fields(
            memory,
            turn.extracted_fields,
            turn_no=turn_no,
            user_message=message,
        )
        booking_event = self._execute_booking_action(memory, turn, user_message=message)
        self._persist_turn(memory, message, turn, turn_no=turn_no)
        await refresh_rolling_summary(memory, self._llm)
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
        self._persist_turn(memory, message, turn, turn_no=memory.user_turn_count() + 1)
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

    async def _hallucination_post_check(
        self,
        memory: SessionMemory,
        prompt: str,
        messages: list[dict[str, str]],
        turn: StructuredTurn,
    ) -> StructuredTurn:
        if not reply_has_disallowed_figures(turn.reply):
            return turn
        logger.warning(
            "hallucination_post_check session=%s event=caught",
            memory.session_id,
        )
        repair_messages = [
            *messages,
            {"role": "assistant", "content": turn.reply},
            {"role": "user", "content": HALLUCINATION_REPAIR_INSTRUCTION},
        ]
        try:
            repaired = await self._llm.complete_turn(
                system_prompt=prompt,
                messages=repair_messages,
            )
        except (CreditsExhaustedError, LLMTimeoutError, LLMRateLimitedError):
            raise
        except Exception:
            logger.exception(
                "hallucination_post_check session=%s event=repair_failed",
                memory.session_id,
            )
            return turn.model_copy(update={"reply": SAFE_PRICE_REPLY})

        if reply_has_disallowed_figures(repaired.reply):
            logger.warning(
                "hallucination_post_check session=%s event=replaced_canned",
                memory.session_id,
            )
            return repaired.model_copy(update={"reply": SAFE_PRICE_REPLY})
        return repaired

    def _history_messages(self, memory: SessionMemory) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for record in memory.recent_turns(HISTORY_WINDOW):
            if record.role in {"user", "assistant"} and record.text:
                messages.append({"role": record.role, "content": record.text})
        return messages

    def _execute_booking_action(
        self, memory: SessionMemory, turn: StructuredTurn, *, user_message: str = ""
    ) -> str | None:
        """Run booking tools and overwrite the reply with simulator-produced text."""
        if turn.intent == Intent.reschedule and turn.action != AgentAction.confirm_booking:
            turn.action = AgentAction.propose_slots

        if turn.action == AgentAction.propose_slots:
            slots = self._booking.get_available_slots(limit=3)
            if memory.booking.get("status") != "confirmed":
                memory.booking["status"] = "slots_offered"
            memory.booking["offered_slots"] = [slot.slot_id for slot in slots]
            memory.booking["alternatives"] = [slot.model_dump() for slot in slots]
            memory.booking.setdefault("history", []).append(
                {"event": "propose_slots", "count": len(slots)}
            )
            turn.reply = format_slot_offer(slots)
            return "retry" if memory.state == ConversationState.BOOKING_FAILED else None

        if turn.action != AgentAction.confirm_booking:
            return None

        name = memory.profile.get("name")
        phone = memory.profile.get("phone")
        slot_id = memory.booking.get("slot")
        if not name or not phone or not slot_id:
            return None

        result = self._booking.attempt_booking(
            session_id=memory.session_id,
            name=str(name),
            phone=str(phone),
            slot_id=str(slot_id),
        )
        history = memory.booking.setdefault("history", [])
        if result.success:
            memory.booking["status"] = "confirmed"
            memory.booking["confirmation_id"] = result.confirmation_id
            memory.booking["slot"] = result.slot
            history.append({"event": "confirmed", "id": result.confirmation_id})
            return "confirmed"

        memory.booking["failure_count"] = int(memory.booking.get("failure_count") or 0) + 1
        memory.booking["status"] = "failed"
        history.append({"event": "failed", "reason": result.reason})
        return "failed"

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

    def _persist_turn(
        self,
        memory: SessionMemory,
        user_message: str,
        turn: StructuredTurn,
        *,
        turn_no: int,
    ) -> None:
        now = utc_now()
        memory.turns.append(
            TurnRecord(
                turn_no=turn_no,
                role="user",
                text=user_message,
                language=turn.detected_language.value,
                timestamp=now,
            )
        )
        memory.turns.append(
            TurnRecord(
                turn_no=turn_no,
                role="assistant",
                text=turn.reply,
                language=turn.detected_language.value,
                intent=turn.intent.value,
                timestamp=now,
            )
        )
        memory.language_history.append(turn.detected_language.value)
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
            memory_snapshot=build_memory_snapshot(memory),
            booking=BookingSnapshot.model_validate(memory.booking),
        )
