"""Stop-phrase overrides, intent history, and objection recording."""

from __future__ import annotations

import pytest

from app.memory.schemas import ConversationState
from app.memory.store import SessionStore
from app.models.llm_output import AgentAction, Intent
from app.services.conversation_engine import (
    ConversationEngine,
    apply_stop_override,
    stopped_reply,
)
from app.services.intent import classify_objection, is_stop_request
from tests.conftest import FakeLLMClient, canned_turn

STOP_PHRASES = [
    "stop messaging me",
    "Stop messaging",
    "don't call again",
    "do not call me",
    "unsubscribe",
    "leave me alone",
    "dobara mat karna",
    "band karo",
    "message mat karo",
    "दोबारा मत करना",
    "बंद करो",
]


@pytest.mark.parametrize("phrase", STOP_PHRASES)
def test_multilingual_stop_phrases_detected(phrase: str) -> None:
    assert is_stop_request(phrase), phrase


@pytest.mark.parametrize(
    "phrase",
    [
        "call me later",
        "I'm busy, call tomorrow",
        "what's the 2 BHK price?",
        "don't call it a scam, I just want details",
    ],
)
def test_non_stop_phrases_are_not_opt_outs(phrase: str) -> None:
    assert not is_stop_request(phrase), phrase


def test_stop_regex_wins_over_llm_intent() -> None:
    turn = canned_turn(
        intent=Intent.pricing,
        action=AgentAction.none,
        reply="2 BHK starts from 1.35 crore onwards. Shall I book a visit?",
    )
    overridden = apply_stop_override("stop messaging me", turn)
    assert overridden.intent == Intent.stop_communication
    assert overridden.action == AgentAction.stop
    assert "crore" not in overridden.reply.lower()
    assert "visit" not in overridden.reply.lower()
    assert overridden.reply == stopped_reply("english")


@pytest.mark.asyncio
async def test_stop_request_skips_llm_and_is_terminal() -> None:
    store = SessionStore(ttl_minutes=60)
    llm = FakeLLMClient()
    engine = ConversationEngine(store=store, llm_client=llm)
    session = store.create("chat")

    response = await engine.handle_turn(session.session_id, "Please unsubscribe")
    assert llm.calls == []
    assert response.state == ConversationState.STOPPED.value
    memory = store.get(session.session_id, touch=False)
    assert memory.state == ConversationState.STOPPED
    assert memory.intent_history[-1]["intent"] == Intent.stop_communication.value


@pytest.mark.asyncio
async def test_message_after_stop_is_opt_out_only_without_llm() -> None:
    store = SessionStore(ttl_minutes=60)
    llm = FakeLLMClient()
    engine = ConversationEngine(store=store, llm_client=llm)
    session = store.create("chat")
    await engine.handle_turn(session.session_id, "stop messaging me")
    llm.calls.clear()

    response = await engine.handle_turn(
        session.session_id, "wait, what's the 3 BHK price and can I visit?"
    )
    assert llm.calls == []
    assert response.state == ConversationState.STOPPED.value
    lowered = response.reply.lower()
    assert "crore" not in lowered
    assert "bhk" not in lowered
    assert "visit" not in lowered
    assert "1.35" not in response.reply
    assert "1.75" not in response.reply


@pytest.mark.asyncio
async def test_intent_history_and_objections_accumulate() -> None:
    store = SessionStore(ttl_minutes=60)
    llm = FakeLLMClient(
        turns=[
            canned_turn(intent=Intent.greeting, reply="Hi, I'm Aisha."),
            canned_turn(
                intent=Intent.objection,
                reply="I hear you — starting prices are onwards, and the team can talk payment plans.",
            ),
            canned_turn(
                intent=Intent.budget_inquiry,
                reply="Got it, that range can work for 2 BHK.",
            ),
        ]
    )
    engine = ConversationEngine(store=store, llm_client=llm)
    session = store.create("chat")

    await engine.handle_turn(session.session_id, "Hi")
    await engine.handle_turn(session.session_id, "thoda mehenga hai")
    await engine.handle_turn(session.session_id, "budget 1.4 cr hai")

    memory = store.get(session.session_id, touch=False)
    intents = [item["intent"] for item in memory.intent_history]
    assert intents == [
        Intent.greeting.value,
        Intent.objection.value,
        Intent.budget_inquiry.value,
    ]
    assert [item["turn"] for item in memory.intent_history] == [1, 2, 3]
    assert len(memory.objections) == 1
    assert memory.objections[0]["type"] == "price"
    assert memory.objections[0]["turn"] == 2
    assert memory.objections[0]["resolved"] is True
    assert memory.state == ConversationState.QUALIFICATION.value


def test_classify_objection_subtypes() -> None:
    assert classify_objection("this is too expensive") == "price"
    assert classify_objection("I need to discuss with family") == "decision_delay"
    assert classify_objection("we need a loan") == "financing"
    assert classify_objection("looking at other builders too") == "competitor"
    assert classify_objection("is this a scam?") == "trust"
    assert classify_objection("hmm not sure") == "other"
