"""Prompt render: FACTS, schema, channel variants, memory injection."""

from __future__ import annotations

from app.memory.schemas import ConversationState, SessionMemory
from app.prompts import facts
from app.prompts.system_prompt import (
    BLOCK_HEADINGS,
    CHAT_CHANNEL_VARIANT,
    HARD_RULES_BLOCK,
    NEVER_REASK_RULE,
    OUTPUT_FEW_SHOTS,
    VOICE_CHANNEL_VARIANT,
    render,
)
from app.services.intent import Intent


def test_all_eleven_block_headings_present() -> None:
    prompt = render()
    for heading in BLOCK_HEADINGS:
        assert heading in prompt, f"missing {heading}"
    assert len(BLOCK_HEADINGS) == 11


def test_facts_block_is_the_closed_sheet() -> None:
    prompt = render()
    facts_text = facts.render_facts_block()
    assert facts_text in prompt
    assert facts.COMPANY_NAME in prompt
    assert facts.PROJECT_NAME in prompt
    assert facts.LOCATION in prompt
    assert facts.PRICE_2BHK_DISPLAY in prompt
    assert facts.PRICE_3BHK_DISPLAY in prompt
    assert "1.35" in prompt
    assert "1.75" in prompt
    assert "onwards" in prompt
    for topic in ("possession", "amenities", "RERA", "discounts"):
        assert topic.lower() in facts_text.lower()


def test_output_schema_and_few_shots_present() -> None:
    prompt = render()
    assert "detected_language" in prompt
    assert "extracted_fields" in prompt
    assert "sentiment" in prompt
    assert '"action"' in prompt or "action:" in prompt
    for intent in Intent:
        assert intent.value in prompt
    assert OUTPUT_FEW_SHOTS in prompt
    assert "thoda mehenga lag raha hai yaar" in prompt
    assert HARD_RULES_BLOCK in prompt


def test_voice_channel_contains_voice_rules() -> None:
    voice = render(channel="voice")
    chat = render(channel="chat")
    assert "CHANNEL: voice" in voice
    assert VOICE_CHANNEL_VARIANT in voice
    assert "one crore thirty-five lakh" in voice
    assert "tell me" in voice
    assert CHAT_CHANNEL_VARIANT not in voice
    assert "CHANNEL: chat" in chat
    assert CHAT_CHANNEL_VARIANT in chat
    assert "type" in chat
    assert VOICE_CHANNEL_VARIANT not in chat


def test_memory_and_state_injected() -> None:
    memory = SessionMemory(
        session_id="s1",
        channel="chat",
        state=ConversationState.QUALIFICATION,
        profile={
            "name": "Rahul",
            "configuration": "2 BHK",
            "budget": "1.4 Cr",
        },
        rolling_summary="Asked 2 BHK price; budget around 1.4 Cr.",
        language_history=["hinglish"],
        intent_history=[{"turn": 1, "intent": "pricing"}],
        booking={
            "status": "none",
            "slot": None,
            "confirmation_id": None,
            "failure_count": 0,
            "history": [],
        },
    )
    prompt = render(memory=memory, state=memory.state, channel="chat")
    assert "Rahul" in prompt
    assert "2 BHK" in prompt
    assert "1.4 Cr" in prompt
    assert NEVER_REASK_RULE in prompt
    assert "Asked 2 BHK price" in prompt
    assert "QUALIFICATION" in prompt
    assert "hinglish" in prompt
    assert "pricing" in prompt


def test_default_render_has_empty_known_info() -> None:
    prompt = render()
    assert "(none yet)" in prompt
    assert "CHANNEL: chat" in prompt
    assert "Current state: GREETING" in prompt
    assert "TOOL RESULT: (none this turn)" in prompt
