"""Engine wiring: hallucination post-check, actions, closed-session short-circuit."""

from __future__ import annotations

from app.memory.schemas import ConversationState
from app.memory.store import SessionStore
from app.models.llm_output import AgentAction, Intent
from app.services.conversation_engine import (
    SAFE_PRICE_REPLY,
    ConversationEngine,
    reply_has_disallowed_figures,
)
from tests.conftest import FakeLLMClient, canned_turn


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
