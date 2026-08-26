"""Shared pytest fixtures: fake LLM and session factory."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_engine, get_store, reset_singletons
from app.main import app
from app.models.llm_output import (
    AgentAction,
    DetectedLanguage,
    ExtractedFields,
    Intent,
    Sentiment,
    StructuredTurn,
)
from app.services.conversation_engine import ConversationEngine


def canned_turn(**overrides: object) -> StructuredTurn:
    payload = {
        "reply": "Hello from Northstar Homes.",
        "detected_language": DetectedLanguage.english,
        "intent": Intent.greeting,
        "extracted_fields": ExtractedFields(),
        "sentiment": Sentiment.positive,
        "action": AgentAction.none,
    }
    payload.update(overrides)
    return StructuredTurn.model_validate(payload)


class FakeLLMClient:
    """Scripted LLM used by API tests so they never hit OpenRouter."""

    def __init__(
        self,
        turn: StructuredTurn | None = None,
        error: Exception | None = None,
        turns: list[StructuredTurn] | None = None,
    ) -> None:
        self.turn = turn or canned_turn()
        self.turns = turns
        self.error = error
        self.calls: list[tuple[str, list[dict[str, str]]]] = []
        self.summaries: list[str] | None = None
        self.summary_error: Exception | None = None
        self.text_calls: list[tuple[str, str]] = []

    async def complete_turn(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
    ) -> StructuredTurn:
        self.calls.append((system_prompt, messages))
        if self.error is not None:
            raise self.error
        if self.turns:
            index = min(len(self.calls) - 1, len(self.turns) - 1)
            return self.turns[index]
        return self.turn

    async def complete_text(
        self,
        system_prompt: str,
        user_content: str,
        *,
        max_tokens: int = 160,
    ) -> str:
        self.text_calls.append((system_prompt, user_content))
        if self.summary_error is not None:
            raise self.summary_error
        if self.summaries:
            index = min(len(self.text_calls) - 1, len(self.summaries) - 1)
            return self.summaries[index]
        return "Customer discussed Northstar One and shared qualification details."


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    return FakeLLMClient()


@pytest.fixture
def client(fake_llm: FakeLLMClient):
    reset_singletons()
    engine = ConversationEngine(store=get_store(), llm_client=fake_llm)
    app.dependency_overrides[get_engine] = lambda: engine
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    reset_singletons()
