"""Memory merge rules, rolling summary cadence, and public snapshot."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.dependencies import get_store
from app.memory.schemas import (
    HISTORY_WINDOW,
    SUMMARY_RECOMPUTE_EVERY,
    FieldConfidence,
    PendingConfirmation,
    SessionMemory,
    TurnRecord,
)
from app.memory.store import SessionStore, merge_extracted_fields
from app.memory.summary import (
    deterministic_summary,
    refresh_rolling_summary,
    should_refresh_summary,
)
from app.models.llm_output import ExtractedFields, Intent
from app.prompts.system_prompt import NEVER_REASK_RULE, render
from app.services.conversation_engine import ConversationEngine
from tests.conftest import FakeLLMClient, canned_turn

MASKED_PHONE = "+91XXXXX*****"


def _memory(**overrides: object) -> SessionMemory:
    payload: dict[str, object] = {"session_id": "mem-1", "channel": "chat"}
    payload.update(overrides)
    return SessionMemory.model_validate(payload)


def _add_records(memory: SessionMemory, count: int) -> None:
    for index in range(count):
        role = "user" if index % 2 == 0 else "assistant"
        memory.turns.append(
            TurnRecord(turn_no=index // 2 + 1, role=role, text=f"{role}-{index}")
        )


def test_newest_wins_for_volatile_fields() -> None:
    memory = _memory()
    merge_extracted_fields(
        memory, ExtractedFields(budget="1.4 Cr", timeline="3 months"), turn_no=1
    )
    merge_extracted_fields(
        memory, ExtractedFields(budget="1.6 Cr", timeline="6 months"), turn_no=2
    )
    assert memory.profile.budget_min is not None
    assert memory.profile.budget_min.value == 1.6
    assert memory.profile.budget_min.last_updated_turn == 2
    assert memory.profile.timeline is not None
    assert memory.profile.timeline.value == "6 months"
    assert memory.profile.timeline.last_updated_turn == 2


def test_identity_fields_require_validation_to_replace() -> None:
    memory = _memory()
    merge_extracted_fields(
        memory, ExtractedFields(name="Rahul", phone="9810012345"), turn_no=1
    )
    merge_extracted_fields(memory, ExtractedFields(name="X", phone="12345"), turn_no=2)
    assert memory.profile.get("name") == "Rahul"
    assert memory.profile.get("phone") == "9810012345"

    merge_extracted_fields(
        memory, ExtractedFields(name="Priya", phone="9876543210"), turn_no=3
    )
    assert memory.profile.get("name") == "Priya"
    assert memory.profile.get("phone") == "9876543210"
    assert memory.profile.name is not None
    assert memory.profile.name.last_updated_turn == 3


def test_invalid_phone_never_enters_profile() -> None:
    memory = _memory()
    merge_extracted_fields(memory, ExtractedFields(phone="12345"), turn_no=1)
    assert memory.profile.phone is None
    merge_extracted_fields(memory, ExtractedFields(phone="9810012345"), turn_no=2)
    assert memory.profile.get("phone") == "9810012345"


def test_vague_budget_is_marked_uncertain() -> None:
    memory = _memory()
    merge_extracted_fields(memory, ExtractedFields(budget="theek hi hai"), turn_no=1)
    assert memory.profile.budget_min is not None
    assert memory.profile.budget_min.confidence == FieldConfidence.uncertain
    assert memory.profile.budget_min.clarification_asked is False

    merge_extracted_fields(memory, ExtractedFields(budget="theek thaak"), turn_no=2)
    assert memory.profile.budget_min.clarification_asked is True
    assert memory.profile.budget_min.confidence == FieldConfidence.uncertain


def test_configuration_conflict_sets_pending_then_confirms() -> None:
    memory = _memory()
    merge_extracted_fields(memory, ExtractedFields(configuration="2 BHK"), turn_no=1)
    assert memory.profile.configuration is not None
    assert memory.profile.configuration.confidence == FieldConfidence.confirmed
    assert memory.profile.get("configuration") == "2 BHK"

    merge_extracted_fields(memory, ExtractedFields(configuration="3 BHK"), turn_no=2)
    assert memory.pending_confirmation is not None
    assert memory.pending_confirmation.previous_value == "2 BHK"
    assert memory.profile.get("configuration") == "3 BHK"
    assert memory.profile.configuration.confidence == FieldConfidence.stated

    prompt = render(memory=memory)
    assert "Confirm naturally" in prompt
    assert "3 BHK" in prompt
    assert "2 BHK" in prompt

    merge_extracted_fields(
        memory, ExtractedFields(), turn_no=3, user_message="yes that's right"
    )
    assert memory.pending_confirmation is None
    assert memory.profile.get("configuration") == "3 BHK"
    assert memory.profile.configuration.confidence == FieldConfidence.confirmed


def test_configuration_conflict_deny_restores_previous() -> None:
    memory = _memory()
    merge_extracted_fields(memory, ExtractedFields(configuration="2 BHK"), turn_no=1)
    merge_extracted_fields(memory, ExtractedFields(configuration="3 BHK"), turn_no=2)
    merge_extracted_fields(memory, ExtractedFields(), turn_no=3, user_message="no, 2 BHK rakho")
    assert memory.pending_confirmation is None
    assert memory.profile.get("configuration") == "2 BHK"
    assert memory.profile.configuration is not None
    assert memory.profile.configuration.confidence == FieldConfidence.confirmed


def test_should_refresh_summary_trigger_and_cadence() -> None:
    memory = _memory()
    assert should_refresh_summary(memory) is False
    _add_records(memory, HISTORY_WINDOW)
    assert should_refresh_summary(memory) is False
    _add_records(memory, 1)
    assert len(memory.turns) == HISTORY_WINDOW + 1
    assert should_refresh_summary(memory) is True

    memory.summary_updated_at_len = len(memory.turns)
    assert should_refresh_summary(memory) is False
    _add_records(memory, SUMMARY_RECOMPUTE_EVERY - 1)
    assert should_refresh_summary(memory) is False
    _add_records(memory, 1)
    assert should_refresh_summary(memory) is True


async def test_rolling_summary_uses_llm_then_falls_back() -> None:
    llm = FakeLLMClient()
    llm.summaries = ["Rahul asked about 2 BHK pricing and shared a 1.4 Cr budget."]
    session = _memory()
    _add_records(session, HISTORY_WINDOW + 1)

    await refresh_rolling_summary(session, llm)
    assert session.rolling_summary == llm.summaries[0]
    assert session.summary_updated_at_len == HISTORY_WINDOW + 1
    assert llm.text_calls
    assert "80 words" in llm.text_calls[0][0] or "at most 80" in llm.text_calls[0][0]

    session2 = _memory()
    _add_records(session2, HISTORY_WINDOW + 1)
    llm.summary_error = RuntimeError("upstream down")
    llm.text_calls.clear()
    await refresh_rolling_summary(session2, llm)
    assert session2.rolling_summary
    assert "Known:" in session2.rolling_summary
    assert session2.rolling_summary == deterministic_summary(
        session2, session2.turns[:-HISTORY_WINDOW]
    )


async def test_fifteen_turn_conversation_recalls_turn_two_facts() -> None:
    store = SessionStore(ttl_minutes=60)
    turns = [
        canned_turn(intent=Intent.greeting, reply="Hi, I'm Aisha from Northstar Homes.")
        for _ in range(15)
    ]
    turns[1] = canned_turn(
        intent=Intent.configuration,
        reply="Got it, a 2 BHK. What timeline are you looking at?",
        extracted_fields=ExtractedFields(name="Rahul", configuration="2 BHK"),
    )
    llm = FakeLLMClient(turns=turns)
    engine = ConversationEngine(store=store, llm_client=llm)
    session = store.create("chat")

    for index in range(15):
        message = "My name is Rahul, 2 BHK please" if index == 1 else f"okay note {index}"
        await engine.handle_turn(session.session_id, message)

    memory = store.get(session.session_id, touch=False)
    assert memory.profile.get("name") == "Rahul"
    assert memory.profile.get("configuration") == "2 BHK"
    assert memory.user_turn_count() == 15
    assert memory.rolling_summary
    assert llm.text_calls

    last_prompt = llm.calls[-1][0]
    assert "Rahul" in last_prompt
    assert "2 BHK" in last_prompt
    assert NEVER_REASK_RULE in last_prompt
    assert "Do not re-ask" in last_prompt

    prompt_after_summary = llm.calls[6][0]
    prompt_at_end = last_prompt
    assert len(prompt_at_end) < len(prompt_after_summary) * 1.35


def test_memory_endpoint_and_snapshot_mask_phone(client: TestClient, fake_llm: FakeLLMClient) -> None:
    fake_llm.turn = canned_turn(
        intent=Intent.site_visit,
        extracted_fields=ExtractedFields(name="Rahul", phone="9810012345", configuration="2 BHK"),
        reply="Thanks Rahul, I have your number.",
    )
    created = client.post("/api/session", json={"channel": "chat"})
    session_id = created.json()["session_id"]

    chat = client.post(
        "/api/chat",
        json={"session_id": session_id, "message": "I'm Rahul, 9810012345, 2 BHK"},
    )
    assert chat.status_code == 200
    snapshot = chat.json()["memory_snapshot"]
    assert snapshot["profile"]["phone"]["value"] == MASKED_PHONE
    assert snapshot["profile"]["name"]["value"] == "Rahul"
    assert snapshot["profile"]["configuration"]["value"] == "2 BHK"
    assert "9810012345" not in chat.text

    memory = client.get(f"/api/session/{session_id}/memory")
    assert memory.status_code == 200
    body = memory.json()
    assert set(body) >= {"profile", "state", "intent_history", "objections", "booking", "language"}
    assert body["profile"]["phone"]["value"] == MASKED_PHONE
    assert body["profile"]["name"]["value"] == "Rahul"
    assert body["language"] == "english"


def test_memory_endpoint_unknown_and_expired(client: TestClient) -> None:
    missing = client.get("/api/session/does-not-exist/memory")
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "SESSION_NOT_FOUND"

    created = client.post("/api/session", json={"channel": "chat"})
    session_id = created.json()["session_id"]
    session = get_store().get(session_id, touch=False)
    session.last_active_at = session.last_active_at - timedelta(hours=2)

    expired = client.get(f"/api/session/{session_id}/memory")
    assert expired.status_code == 410
    assert expired.json()["error_code"] == "SESSION_EXPIRED"


def test_pending_confirmation_round_trip_on_session_memory() -> None:
    memory = _memory(
        pending_confirmation=PendingConfirmation(
            field="configuration",
            previous_value="2 BHK",
            proposed_value="3 BHK",
        )
    )
    prompt = render(memory=memory)
    assert "PENDING CONFIRMATION" in prompt
    assert "Confirm naturally" in prompt
