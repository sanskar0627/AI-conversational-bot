"""LLM client: OpenRouter 402/429/timeout mapping, retries, and JSON repair."""

from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.exceptions import AppError, CreditsExhaustedError, LLMRateLimitedError, LLMTimeoutError
from app.services.llm_client import LLMClient

VALID_TURN = {
    "reply": "Hi, I'm Aisha from Northstar Homes.",
    "detected_language": "english",
    "intent": "greeting",
    "extracted_fields": {},
    "sentiment": "positive",
    "action": "none",
}

CREDITS_MESSAGE = (
    "AI service temporarily unavailable. Please recharge the OpenRouter account."
)


def _settings() -> Settings:
    return Settings(
        openrouter_api_key="sk-test",
        openrouter_model="openai/gpt-4o-mini",
        openrouter_base_url="https://openrouter.ai/api/v1",
        llm_timeout_seconds=5,
    )


def _or_response(content: str | dict, status: int = 200) -> httpx.Response:
    if isinstance(content, dict):
        content = json.dumps(content)
    return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})


def _client_for(handler, *, backoff: float = 0) -> LLMClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    return LLMClient(settings=_settings(), http_client=http, retry_backoff_seconds=backoff)


@pytest.mark.asyncio
async def test_402_maps_to_credits_exhausted_without_retry() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.headers["authorization"] == "Bearer sk-test"
        return httpx.Response(402, json={"error": {"message": "Payment required"}})

    client = _client_for(handler)
    with pytest.raises(CreditsExhaustedError) as exc_info:
        await client.complete_turn("system", [{"role": "user", "content": "hi"}])

    assert calls["n"] == 1
    assert exc_info.value.error_code == "CREDITS_EXHAUSTED"
    assert exc_info.value.status_code == 503
    assert exc_info.value.retryable is False
    assert exc_info.value.message == CREDITS_MESSAGE


@pytest.mark.asyncio
async def test_timeout_retries_once_then_maps() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.TimeoutException("timed out")

    client = _client_for(handler)
    with pytest.raises(LLMTimeoutError) as exc_info:
        await client.complete_turn("system", [{"role": "user", "content": "hi"}])

    assert calls["n"] == 2
    assert exc_info.value.error_code == "LLM_TIMEOUT"
    assert exc_info.value.status_code == 503
    assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_429_retries_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return _or_response(VALID_TURN)

    client = _client_for(handler)
    turn = await client.complete_turn("system", [{"role": "user", "content": "hi"}])

    assert calls["n"] == 2
    assert turn.reply.startswith("Hi")
    assert turn.intent.value == "greeting"


@pytest.mark.asyncio
async def test_429_twice_maps_to_rate_limited() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, json={"error": "rate limited"})

    client = _client_for(handler)
    with pytest.raises(LLMRateLimitedError) as exc_info:
        await client.complete_turn("system", [{"role": "user", "content": "hi"}])

    assert calls["n"] == 2
    assert exc_info.value.error_code == "LLM_RATE_LIMITED"
    assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_other_4xx_does_not_retry() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": "bad request"})

    client = _client_for(handler)
    with pytest.raises(AppError) as exc_info:
        await client.complete_turn("system", [{"role": "user", "content": "hi"}])

    assert calls["n"] == 1
    assert exc_info.value.error_code == "INTERNAL_ERROR"


@pytest.mark.asyncio
async def test_malformed_json_is_repaired_on_second_call() -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return _or_response("this is not json")
        return _or_response(VALID_TURN)

    client = _client_for(handler)
    turn = await client.complete_turn("system", [{"role": "user", "content": "hi"}])

    assert calls["n"] == 2
    assert turn.reply.startswith("Hi")


@pytest.mark.asyncio
async def test_null_extracted_fields_are_accepted() -> None:
    payload = {**VALID_TURN, "extracted_fields": None, "action": None}

    def handler(_request: httpx.Request) -> httpx.Response:
        return _or_response(payload)

    client = _client_for(handler)
    turn = await client.complete_turn("system", [{"role": "user", "content": "hi"}])

    assert turn.reply.startswith("Hi")
    assert turn.extracted_fields.model_dump(exclude_none=True) == {}
    assert turn.action.value == "none"


@pytest.mark.asyncio
async def test_parse_failure_after_repair_falls_back_to_raw_text() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return _or_response("still not json")

    client = _client_for(handler)
    turn = await client.complete_turn("system", [{"role": "user", "content": "hi"}])

    assert turn.reply == "still not json"
    assert turn.intent.value == "unknown_question"
    assert turn.action.value == "none"
