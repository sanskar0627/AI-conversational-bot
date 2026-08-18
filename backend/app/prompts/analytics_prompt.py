"""End-of-session summarization and sentiment prompt.

Consumed in Stage 08: one LLM call over the transcript + profile returns
`{sentiment, summary}` JSON. On failure the analytics service falls back to
heuristics — this module only supplies the prompt text.
"""

from __future__ import annotations

from typing import Any

ANALYTICS_SYSTEM_PROMPT = """You summarize a completed Northstar Homes sales conversation.

Return JSON ONLY with exactly these keys:
{
  "sentiment": "positive" | "neutral" | "negative",
  "summary": "<plain text, ≤ 60 words>"
}

Rules:
- sentiment is the customer's overall tone by the end of the conversation, not the agent's.
- summary is factual: what they wanted, key objections, booking/escalation/stop outcome, and agreed next step.
- Do not invent prices, discounts, slots, confirmation IDs, or commitments that are not in the transcript.
- No markdown, no extra keys, no commentary outside the JSON object.
"""

ANALYTICS_OUTPUT_HEADER = "## ANALYTICS OUTPUT CONTRACT"


def render_analytics_user_message(
    transcript: str,
    profile: dict[str, Any] | None = None,
) -> str:
    """User-role payload: known profile + full transcript."""
    profile = profile or {}
    if profile:
        lines = [f"- {key}: {value}" for key, value in profile.items() if value not in (None, "")]
        profile_block = "\n".join(lines) if lines else "(none captured)"
    else:
        profile_block = "(none captured)"
    body = (transcript or "").strip() or "(empty transcript)"
    return (
        f"{ANALYTICS_OUTPUT_HEADER}\n"
        f"KNOWN PROFILE:\n{profile_block}\n\n"
        f"TRANSCRIPT:\n{body}\n"
    )


def render_analytics_prompt(
    transcript: str,
    profile: dict[str, Any] | None = None,
) -> str:
    """Full prompt (system instructions + user payload) for the summarization call."""
    return f"{ANALYTICS_SYSTEM_PROMPT}\n\n{render_analytics_user_message(transcript, profile)}"
