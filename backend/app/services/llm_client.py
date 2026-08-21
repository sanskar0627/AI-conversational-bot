"""OpenRouter HTTP wrapper: retries, timeout, 402/429 mapping."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.exceptions import (
    AppError,
    CreditsExhaustedError,
    LLMRateLimitedError,
    LLMTimeoutError,
)
from app.models.llm_output import (
    AgentAction,
    DetectedLanguage,
    ExtractedFields,
    Intent,
    Sentiment,
    StructuredTurn,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)

REPAIR_INSTRUCTION = (
    "Your previous response was not valid JSON matching the required schema. "
    "Return ONLY valid JSON with keys: reply, detected_language, intent, "
    "extracted_fields, sentiment, action."
)


class LLMClient:
    """Thin OpenRouter chat-completions client that always returns StructuredTurn."""

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self._settings = settings or get_settings()
        self._http_client = http_client
        self._retry_backoff_seconds = retry_backoff_seconds
        self._url = f"{self._settings.openrouter_base_url.rstrip('/')}/chat/completions"

    async def complete_turn(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
    ) -> StructuredTurn:
        payload = self._build_payload(system_prompt, messages)
        raw = await self._complete_raw(payload)
        parsed = self._try_parse(raw)
        if parsed is not None:
            return parsed

        repair_payload = self._build_payload(
            system_prompt,
            [
                *messages,
                {"role": "assistant", "content": raw},
                {"role": "user", "content": REPAIR_INSTRUCTION},
            ],
        )
        repaired_raw = await self._complete_raw(repair_payload)
        repaired = self._try_parse(repaired_raw)
        if repaired is not None:
            return repaired

        logger.warning("LLM JSON parse failed after repair; falling back to raw text")
        return self._fallback_turn(raw)

    async def complete_text(
        self,
        system_prompt: str,
        user_content: str,
        *,
        max_tokens: int = 160,
    ) -> str:
        """Plain-text completion used for rolling summaries (not StructuredTurn)."""
        payload = {
            "model": self._settings.openrouter_model,
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        return (await self._complete_raw(payload)).strip()

    def _build_payload(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
    ) -> dict[str, Any]:
        return {
            "model": self._settings.openrouter_model,
            "temperature": 0.6,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system_prompt}, *messages],
        }

    async def _complete_raw(self, payload: dict[str, Any]) -> str:
        response = await self._request_with_retry(payload)
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise AppError("LLM returned a non-JSON response.") from exc
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AppError("LLM response was missing message content.") from exc
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        return json.dumps(content)

    async def _request_with_retry(self, payload: dict[str, Any]) -> httpx.Response:
        last_timeout: httpx.TimeoutException | None = None
        for attempt in range(2):
            try:
                response = await self._send(payload)
            except httpx.TimeoutException as exc:
                last_timeout = exc
                if attempt == 0:
                    await asyncio.sleep(self._retry_backoff_seconds)
                    continue
                raise LLMTimeoutError() from exc
            except httpx.HTTPError as exc:
                raise AppError("Failed to reach the AI service.") from exc

            if response.status_code == 402:
                raise CreditsExhaustedError()
            if response.status_code == 429:
                if attempt == 0:
                    await asyncio.sleep(self._retry_backoff_seconds)
                    continue
                raise LLMRateLimitedError()
            if response.status_code >= 400:
                logger.warning(
                    "OpenRouter error status=%s body=%s",
                    response.status_code,
                    response.text[:500],
                )
                raise AppError("The AI service returned an unexpected error.")
            return response

        if last_timeout is not None:
            raise LLMTimeoutError() from last_timeout
        raise LLMRateLimitedError()

    async def _send(self, payload: dict[str, Any]) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self._settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:5173",
            "X-Title": "Northstar Homes AI Sales Agent",
        }
        timeout = httpx.Timeout(self._settings.llm_timeout_seconds)
        if self._http_client is not None:
            return await self._http_client.post(
                self._url,
                json=payload,
                headers=headers,
                timeout=timeout,
            )
        if not self._settings.llm_configured:
            raise AppError("OpenRouter API key is not configured.")
        async with httpx.AsyncClient(timeout=timeout) as client:
            return await client.post(self._url, json=payload, headers=headers)

    def _try_parse(self, raw: str) -> StructuredTurn | None:
        data = _extract_json_object(raw)
        if data is None:
            return None
        try:
            return StructuredTurn.model_validate(data)
        except Exception:
            return None

    @staticmethod
    def _fallback_turn(raw: str) -> StructuredTurn:
        data = _extract_json_object(raw) or {}
        reply = data.get("reply") if isinstance(data.get("reply"), str) else raw
        reply = (reply or "").strip() or (
            "Sorry, I had trouble responding. Could you say that again?"
        )
        return StructuredTurn(
            reply=reply,
            detected_language=DetectedLanguage.english,
            intent=Intent.unknown_question,
            extracted_fields=ExtractedFields(),
            sentiment=Sentiment.neutral,
            action=AgentAction.none,
        )


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if not text:
        return None
    text = _FENCE_RE.sub("", text).strip()
    try:
        loaded = json.loads(text)
        if isinstance(loaded, dict):
            return loaded
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        loaded = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None
