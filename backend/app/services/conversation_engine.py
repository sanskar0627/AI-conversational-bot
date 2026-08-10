"""Turn orchestration skeleton. State machine and actions land in Stages 04/06."""

from __future__ import annotations

import time

from app.memory.schemas import TERMINAL_STATES, ConversationState, SessionMemory
from app.memory.store import SessionStore
from app.models.llm_output import ExtractedFields, StructuredTurn
from app.models.responses import BookingSnapshot, ChatResponse
from app.prompts import system_prompt
from app.services.booking import BookingService
from app.services.escalation import EscalationService
from app.services.llm_client import LLMClient
from app.utils.logging import get_logger, mask_pii

logger = get_logger(__name__)

STOPPED_REPLY = "Understood. We won't contact you again. Take care."
CLOSED_REPLY = (
    "This conversation has ended. Start a new session if you'd like help with Northstar One."
)
HISTORY_WINDOW = 10


class ConversationEngine:
    """Load memory → prompt → LLM → merge → action (stub) → ChatResponse."""

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

        started = time.perf_counter()
        prompt = system_prompt.render(
            memory=memory,
            state=memory.state,
            channel=memory.channel,
        )
        history = self._history_messages(memory)
        turn = await self._llm.complete_turn(
            system_prompt=prompt,
            messages=[
                *history,
                {"role": "user", "content": f"Customer message: {message}"},
            ],
        )
        self._merge_extracted_fields(memory, turn.extracted_fields)
        self._execute_action(memory, turn)
        self._persist_turn(memory, message, turn)
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

    def _terminal_response(self, memory: SessionMemory) -> ChatResponse:
        reply = STOPPED_REPLY if memory.state == ConversationState.STOPPED else CLOSED_REPLY
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

    def _execute_action(self, memory: SessionMemory, turn: StructuredTurn) -> None:
        """Action handlers are wired in Stage 04 (stop/close/escalate) and Stage 06 (booking)."""
        return

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

    def _to_response(self, memory: SessionMemory, reply: str, language: str) -> ChatResponse:
        return ChatResponse(
            reply=reply,
            state=memory.state.value,
            language=language,
            memory_snapshot=dict(memory.profile),
            booking=BookingSnapshot.model_validate(memory.booking),
        )
