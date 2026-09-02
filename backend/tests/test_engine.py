"""Engine wiring: hallucination post-check, actions, closed-session short-circuit."""

from __future__ import annotations

from datetime import datetime

from app.memory.schemas import ConversationState
from app.memory.store import SessionStore
from app.models.llm_output import AgentAction, Intent
from app.services.booking import IST, BookingService, is_sunday_morning
from app.services.conversation_engine import (
    SAFE_PRICE_REPLY,
    ConversationEngine,
    reply_has_disallowed_figures,
)
from tests.conftest import FakeLLMClient, canned_turn

FROZEN = datetime(2026, 9, 2, 9, 0, tzinfo=IST)


def _booking() -> BookingService:
    return BookingService(now_fn=lambda: FROZEN, failure_mode="deterministic")


def test_disallowed_price_and_discount_patterns() -> None:
    assert reply_has_disallowed_figures("The final price is ₹1.2 crore.")
    assert reply_has_disallowed_figures("We can do 20% discount.")
    assert reply_has_disallowed_figures("2 crore all-in.")
    assert not reply_has_disallowed_figures(
        "2 BHK starts from 1.35 crore onwards and 3 BHK from 1.75 crore onwards."
    )
    assert not reply_has_disallowed_figures("₹1.35 Cr onwards for 2 BHK.")
    assert not reply_has_disallowed_figures("A 2 BHK in Sector 79, callback in 2 working hours.")


async def test_hallucinated_price_is_caught_and_regenerated() -> None:
    store = SessionStore(ttl_minutes=60)
    llm = FakeLLMClient(
        turns=[
            canned_turn(
                intent=Intent.pricing,
                reply="Great news — the final price is ₹1.2 crore.",
            ),
            canned_turn(
                intent=Intent.pricing,
                reply="2 BHK starts from 1.35 crore onwards. Does that range work?",
            ),
        ]
    )
    engine = ConversationEngine(store=store, llm_client=llm)
    session = store.create("chat")

    response = await engine.handle_turn(session.session_id, "What's the 2 BHK price?")
    assert len(llm.calls) == 2
    assert "1.2" not in response.reply
    assert "1.35" in response.reply
    repair_messages = llm.calls[1][1]
    assert any(
        "not in FACTS" in message["content"]
        for message in repair_messages
        if message["role"] == "user"
    )


async def test_persistent_hallucination_falls_back_to_canned_reply() -> None:
    store = SessionStore(ttl_minutes=60)
    llm = FakeLLMClient(
        turns=[
            canned_turn(intent=Intent.pricing, reply="Locked at ₹1.2 crore final price."),
            canned_turn(intent=Intent.pricing, reply="Okay 20% discount on 2 crore."),
        ]
    )
    engine = ConversationEngine(store=store, llm_client=llm)
    session = store.create("chat")

    response = await engine.handle_turn(session.session_id, "Give me a discount price")
    assert len(llm.calls) == 2
    assert response.reply == SAFE_PRICE_REPLY


async def test_allowed_prices_do_not_trigger_regeneration() -> None:
    store = SessionStore(ttl_minutes=60)
    llm = FakeLLMClient(
        turn=canned_turn(
            intent=Intent.pricing,
            reply="2 BHK starts from 1.35 crore onwards.",
        )
    )
    engine = ConversationEngine(store=store, llm_client=llm)
    session = store.create("chat")
    await engine.handle_turn(session.session_id, "2 BHK price?")
    assert len(llm.calls) == 1


async def test_propose_slots_and_close_actions() -> None:
    store = SessionStore(ttl_minutes=60)
    llm = FakeLLMClient(
        turns=[
            canned_turn(
                intent=Intent.site_visit,
                action=AgentAction.propose_slots,
                reply="I can offer a few visit slots.",
            ),
            canned_turn(
                intent=Intent.goodbye,
                action=AgentAction.close,
                reply="Thanks, we'll see you then.",
            ),
        ]
    )
    engine = ConversationEngine(store=store, llm_client=llm)
    session = store.create("chat")

    offered = await engine.handle_turn(session.session_id, "I want a site visit")
    assert offered.state == ConversationState.BOOKING.value
    assert offered.reply.startswith("Available:")
    assert "I can offer a few visit slots." not in offered.reply
    memory = store.get(session.session_id, touch=False)
    assert memory.booking["status"] == "slots_offered"

    closed = await engine.handle_turn(session.session_id, "thanks, bye")
    assert closed.state == ConversationState.CLOSED.value


async def test_escalate_action_stores_payload() -> None:
    store = SessionStore(ttl_minutes=60)
    llm = FakeLLMClient(
        turn=canned_turn(
            intent=Intent.human_agent,
            action=AgentAction.escalate,
            reply="A senior consultant will call within 2 working hours.",
        )
    )
    engine = ConversationEngine(store=store, llm_client=llm)
    session = store.create("chat")
    session.profile = {"name": "Neha", "phone": "9876543210"}
    store.save(session)

    response = await engine.handle_turn(session.session_id, "connect me to an agent")
    assert response.state == ConversationState.ESCALATED.value
    memory = store.get(session.session_id, touch=False)
    assert memory.escalation is not None
    assert memory.escalation["reason"] == "human_requested"
    assert memory.escalation["customer_name"] == "Neha"


async def test_confirm_booking_reply_only_echoes_simulator_outcome() -> None:
    store = SessionStore(ttl_minutes=60)
    booking = _booking()
    llm = FakeLLMClient(
        turns=[
            canned_turn(
                intent=Intent.site_visit,
                action=AgentAction.propose_slots,
                reply="You're booked. Confirmation ID NS-FAKE01.",
            ),
            canned_turn(
                intent=Intent.site_visit,
                action=AgentAction.confirm_booking,
                reply="Locked it. Confirmation ID NS-FAKE01.",
            ),
        ]
    )
    engine = ConversationEngine(store=store, llm_client=llm, booking=booking)
    session = store.create("chat")
    session.profile = {"name": "Rahul", "phone": "9810012345"}
    store.save(session)

    offered = await engine.handle_turn(session.session_id, "I want a site visit")
    assert "NS-FAKE01" not in offered.reply
    memory = store.get(session.session_id, touch=False)
    slot_id = memory.booking["offered_slots"][0]
    slot = booking.get_slot(slot_id)
    assert slot is not None

    confirmed = await engine.handle_turn(session.session_id, f"book {slot.label}")
    cid = confirmed.booking.confirmation_id
    assert cid and cid.startswith("NS-") and cid != "NS-FAKE01"
    assert cid in confirmed.reply
    assert slot.label in confirmed.reply
    assert "NS-FAKE01" not in confirmed.reply
    taken = booking.get_slot(slot_id)
    assert taken is not None and taken.available is False


async def test_sunday_morning_failure_reply_uses_simulator_alternatives() -> None:
    store = SessionStore(ttl_minutes=60)
    booking = _booking()
    sunday = next(slot for slot in booking.list_inventory() if is_sunday_morning(slot.starts_at))
    llm = FakeLLMClient(
        turn=canned_turn(
            intent=Intent.site_visit,
            action=AgentAction.confirm_booking,
            reply="Booked NS-FAKE01 for Sunday morning.",
        )
    )
    engine = ConversationEngine(store=store, llm_client=llm, booking=booking)
    session = store.create("chat")
    session.profile = {"name": "Rahul", "phone": "9810012345"}
    session.booking["offered_slots"] = [sunday.slot_id]
    store.save(session)

    failed = await engine.handle_turn(session.session_id, sunday.slot_id)
    assert failed.booking.failure_count == 1
    assert failed.booking.status == "failed"
    assert "NS-FAKE01" not in failed.reply
    assert "Alternatives:" in failed.reply
    assert failed.booking.alternatives
    assert all(item.slot_id != sunday.slot_id for item in failed.booking.alternatives)
    for alt in failed.booking.alternatives:
        assert alt.label in failed.reply


async def test_invalid_phone_never_attempts_booking_and_caps_corrections() -> None:
    store = SessionStore(ttl_minutes=60)
    booking = _booking()
    llm = FakeLLMClient(
        turn=canned_turn(
            intent=Intent.site_visit,
            action=AgentAction.confirm_booking,
            reply="Booked NS-FAKE01.",
        )
    )
    engine = ConversationEngine(store=store, llm_client=llm, booking=booking)
    session = store.create("chat")
    session.profile = {"name": "Rahul"}
    session.booking["offered_slots"] = [booking.get_available_slots(limit=1)[0].slot_id]
    store.save(session)

    first = await engine.handle_turn(session.session_id, "book the first slot")
    assert "NS-FAKE01" not in first.reply
    assert "10-digit" in first.reply
    assert booking._taken == set()
    memory = store.get(session.session_id, touch=False)
    assert memory.booking["validation_attempts"] == 1
    assert memory.booking["failure_count"] == 0

    second = await engine.handle_turn(session.session_id, "book it anyway")
    assert memory.booking["failure_count"] == 0
    assert store.get(session.session_id, touch=False).booking["validation_attempts"] == 2
    assert "can't lock a visit" in second.reply
    assert booking._taken == set()


async def test_cancel_confirmed_visit_sets_follow_up() -> None:
    store = SessionStore(ttl_minutes=60)
    booking = _booking()
    slot = booking.get_available_slots(limit=1)[0]
    booked = booking.attempt_booking(
        session_id="pre",
        name="Rahul",
        phone="9810012345",
        slot_id=slot.slot_id,
    )
    llm = FakeLLMClient(
        turn=canned_turn(
            intent=Intent.cancel_booking,
            reply="Sure, I'll invent NS-FAKE01 while cancelling.",
        )
    )
    engine = ConversationEngine(store=store, llm_client=llm, booking=booking)
    session = store.create("chat")
    session.profile = {"name": "Rahul", "phone": "9810012345"}
    session.booking["status"] = "confirmed"
    session.booking["slot"] = booked.slot
    session.booking["confirmation_id"] = booked.confirmation_id
    store.save(session)

    cancelled = await engine.handle_turn(session.session_id, "cancel my visit")
    assert cancelled.state == ConversationState.FOLLOW_UP.value
    assert "cancelled" in cancelled.reply.lower()
    assert "NS-FAKE01" not in cancelled.reply
    memory = store.get(session.session_id, touch=False)
    assert memory.booking["status"] == "cancelled"
    assert memory.booking["follow_up_required"] is True
    freed = booking.get_slot(slot.slot_id)
    assert freed is not None and freed.available is True
