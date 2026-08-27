"""Escalation triggers and payload completeness."""

from __future__ import annotations

from app.memory.schemas import ConversationState, SessionMemory
from app.memory.store import SessionStore
from app.models.llm_output import AgentAction, Intent
from app.models.responses import BookingResponse
from app.services.booking import BookingService
from app.services.conversation_engine import ConversationEngine
from app.services.escalation import (
    REASON_BOOKING_FAILED,
    REASON_HUMAN_REQUESTED,
    REASON_SENSITIVE_TOPIC,
    REASON_UNKNOWN_X2,
    REASON_URGENCY,
    EscalationService,
    contains_sensitive_topic,
    contains_urgency,
)
from tests.conftest import FakeLLMClient, canned_turn

PAYLOAD_KEYS = {
    "session_id",
    "reason",
    "urgency",
    "customer_name",
    "phone",
    "language",
    "summary",
    "pending_questions",
    "timestamp",
}


def _memory(**overrides: object) -> SessionMemory:
    payload = {
        "session_id": "sess-1",
        "channel": "chat",
        "state": ConversationState.FAQ,
        "profile": {"name": "Rahul", "phone": "9810012345"},
        "intent_history": [],
        "turns": [],
        "language_history": ["hinglish"],
    }
    payload.update(overrides)
    return SessionMemory.model_validate(payload)


def test_sensitive_and_urgency_detectors() -> None:
    assert contains_sensitive_topic("What is the RERA number?")
    assert contains_sensitive_topic("I will file a complaint")
    assert contains_sensitive_topic("loan approval kab milegi")
    assert not contains_sensitive_topic("I need a loan, can the team help?")
    assert contains_urgency("this is urgent")
    assert contains_urgency("aaj hi dekhna hai")
    assert not contains_urgency("maybe next month")


def test_should_escalate_each_trigger() -> None:
    service = EscalationService()
    unknown_turn = canned_turn(intent=Intent.unknown_question)

    human = service.should_escalate(
        _memory(),
        canned_turn(intent=Intent.human_agent, action=AgentAction.escalate),
        user_message="kisi insaan se baat karao",
        start_state=ConversationState.DISCOVERY,
    )
    assert human == REASON_HUMAN_REQUESTED

    sensitive = service.should_escalate(
        _memory(),
        unknown_turn,
        user_message="send me the RERA certificate",
        start_state=ConversationState.FAQ,
    )
    assert sensitive == REASON_SENSITIVE_TOPIC

    unknown_memory = _memory(
        intent_history=[
            {"turn": 1, "intent": Intent.unknown_question.value},
            {"turn": 2, "intent": Intent.unknown_question.value},
        ]
    )
    unknown = service.should_escalate(
        unknown_memory,
        unknown_turn,
        user_message="possession date kab hai?",
        start_state=ConversationState.FAQ,
    )
    assert unknown == REASON_UNKNOWN_X2

    booking_memory = _memory(
        state=ConversationState.BOOKING_FAILED,
        booking={"status": "failed", "failure_count": 2, "history": []},
    )
    booking = service.should_escalate(
        booking_memory,
        canned_turn(intent=Intent.site_visit),
        user_message="try another slot",
        start_state=ConversationState.BOOKING_FAILED,
    )
    assert booking == REASON_BOOKING_FAILED

    urgency = service.should_escalate(
        _memory(state=ConversationState.DISCOVERY, intent_history=[]),
        canned_turn(intent=Intent.site_visit),
        user_message="flying out tomorrow, aaj hi visit chahiye",
        start_state=ConversationState.DISCOVERY,
    )
    assert urgency == REASON_URGENCY


def test_stop_request_does_not_escalate() -> None:
    service = EscalationService()
    reason = service.should_escalate(
        _memory(),
        canned_turn(intent=Intent.stop_communication, action=AgentAction.stop),
        user_message="stop messaging me",
        start_state=ConversationState.FAQ,
    )
    assert reason is None


def test_build_payload_has_section_14_fields() -> None:
    memory = _memory(
        intent_history=[{"turn": 1, "intent": Intent.unknown_question.value}],
        turns=[{"role": "user", "text": "possession date?"}],
        rolling_summary="Asked about possession; facts unknown.",
    )
    payload = EscalationService().build_payload(
        memory,
        REASON_UNKNOWN_X2,
        user_message="this is urgent",
    )
    assert set(payload) == PAYLOAD_KEYS
    assert payload["session_id"] == "sess-1"
    assert payload["reason"] == REASON_UNKNOWN_X2
    assert payload["urgency"] == "high"
    assert payload["customer_name"] == "Rahul"
    assert payload["phone"] == "9810012345"
    assert payload["language"] == "hinglish"
    assert payload["summary"]
    assert payload["pending_questions"] == ["possession date?"]
    assert payload["timestamp"]


async def test_unknown_x2_engine_attaches_complete_payload() -> None:
    store = SessionStore(ttl_minutes=60)
    llm = FakeLLMClient(
        turns=[
            canned_turn(
                intent=Intent.unknown_question,
                reply="I don't have the possession date. I'll have the team confirm.",
            ),
            canned_turn(
                intent=Intent.unknown_question,
                reply="I don't have the RERA number either.",
            ),
        ]
    )
    engine = ConversationEngine(store=store, llm_client=llm)
    session = store.create("chat")
    session.state = ConversationState.DISCOVERY
    store.save(session)

    first = await engine.handle_turn(session.session_id, "possession date kab hai?")
    assert first.state == ConversationState.FAQ.value
    second = await engine.handle_turn(session.session_id, "carpet area kitna hai?")
    assert second.state == ConversationState.ESCALATED.value

    memory = store.get(session.session_id, touch=False)
    assert memory.escalation is not None
    assert set(memory.escalation) == PAYLOAD_KEYS
    assert memory.escalation["reason"] == REASON_UNKNOWN_X2
    assert memory.escalation["session_id"] == session.session_id
    assert "possession date kab hai?" in memory.escalation["pending_questions"]


class _FailingBooking(BookingService):
    def attempt_booking(self, **kwargs: object) -> BookingResponse:
        return BookingResponse(
            success=False,
            reason="slot_taken",
            alternatives=self.get_available_slots(limit=3),
        )


async def test_booking_failure_x2_engine_escalates_with_payload() -> None:
    store = SessionStore(ttl_minutes=60)
    llm = FakeLLMClient(
        turn=canned_turn(
            intent=Intent.site_visit,
            action=AgentAction.confirm_booking,
            reply="Let me lock that slot.",
        )
    )
    engine = ConversationEngine(
        store=store,
        llm_client=llm,
        booking=_FailingBooking(),
    )
    session = store.create("chat")
    session.state = ConversationState.BOOKING
    session.profile = {"name": "Rahul", "phone": "9810012345"}
    session.booking["slot"] = "stub-sat-1100"
    store.save(session)

    first = await engine.handle_turn(session.session_id, "book Saturday 11")
    assert first.state == ConversationState.BOOKING_FAILED.value
    assert first.booking.failure_count == 1

    second = await engine.handle_turn(session.session_id, "try Saturday 11 again")
    assert second.state == ConversationState.ESCALATED.value
    memory = store.get(session.session_id, touch=False)
    assert memory.booking["failure_count"] == 2
    assert memory.escalation is not None
    assert set(memory.escalation) == PAYLOAD_KEYS
    assert memory.escalation["reason"] == REASON_BOOKING_FAILED
