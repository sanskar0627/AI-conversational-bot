"""Rolling conversation summary: cheap LLM call with a deterministic fallback."""

from __future__ import annotations

from typing import Any, Protocol

from app.memory.schemas import (
    HISTORY_WINDOW,
    SUMMARY_RECOMPUTE_EVERY,
    SessionMemory,
    TurnRecord,
)

SUMMARY_SYSTEM_PROMPT = (
    "Summarize this Northstar Homes sales conversation so far in at most 80 words. "
    "Cover known customer facts, questions they asked, objections, and any commitments. "
    "Do not invent prices, slots, or facts that are not in the transcript."
)


class TextCompleter(Protocol):
    async def complete_text(
        self,
        system_prompt: str,
        user_content: str,
        *,
        max_tokens: int = 160,
    ) -> str: ...


def should_refresh_summary(memory: SessionMemory) -> bool:
    """True when the transcript is past the short-term window and due for a refresh.

    First run at len(turns) > 10; then every 5 turns after the last computation.
    """
    turn_count = len(memory.turns)
    if turn_count <= HISTORY_WINDOW:
        return False
    last = memory.summary_updated_at_len
    if last == 0:
        return True
    return turn_count - last >= SUMMARY_RECOMPUTE_EVERY


def deterministic_summary(memory: SessionMemory, old_turns: list[TurnRecord] | None = None) -> str:
    """Template fallback: key facts + intents + a snippet of compressed turns."""
    facts = [f"{name}={field.value}" for name, field in memory.profile.populated_fields()]
    intents = [
        str(item.get("intent"))
        for item in memory.intent_history
        if isinstance(item, dict) and item.get("intent")
    ]
    compressed = old_turns if old_turns is not None else memory.turns[:-HISTORY_WINDOW]
    snippets: list[str] = []
    for record in compressed[:6]:
        text = (record.text or "").strip().replace("\n", " ")
        if text:
            snippets.append(f"{record.role}: {text[:48]}")
    parts = [
        f"Known: {', '.join(facts) or 'none'}.",
        f"Intents: {', '.join(intents[-8:]) or 'none'}.",
    ]
    if snippets:
        parts.append("Earlier: " + " | ".join(snippets))
    return " ".join(parts)


def summary_user_payload(memory: SessionMemory) -> str:
    old_turns = memory.turns[:-HISTORY_WINDOW]
    lines = [f"{record.role}: {record.text}" for record in old_turns if record.text]
    profile_bits = [f"{name}={field.value}" for name, field in memory.profile.populated_fields()]
    known = ", ".join(profile_bits) or "(none)"
    transcript = "\n".join(lines) if lines else "(none)"
    return f"KNOWN FACTS: {known}\n\nTURNS TO COMPRESS:\n{transcript}"


async def refresh_rolling_summary(memory: SessionMemory, llm: Any | None) -> None:
    """Update rolling_summary from turns 1..N-10. LLM errors fall back to the template."""
    if not should_refresh_summary(memory):
        return
    old_turns = memory.turns[:-HISTORY_WINDOW]
    summary = ""
    completer = getattr(llm, "complete_text", None)
    if completer is not None:
        try:
            summary = (await completer(SUMMARY_SYSTEM_PROMPT, summary_user_payload(memory))).strip()
        except Exception:
            summary = ""
    if not summary:
        summary = deterministic_summary(memory, old_turns)
    memory.rolling_summary = summary
    memory.summary_updated_at_len = len(memory.turns)
