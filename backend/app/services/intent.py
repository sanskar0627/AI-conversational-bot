"""Intent enum plus deterministic stop/abuse regex overrides."""

from __future__ import annotations

import re
from enum import Enum


class Intent(str, Enum):
    greeting = "greeting"
    pricing = "pricing"
    location = "location"
    amenities = "amenities"
    availability = "availability"
    configuration = "configuration"
    budget_inquiry = "budget_inquiry"
    site_visit = "site_visit"
    reschedule = "reschedule"
    cancel_booking = "cancel_booking"
    busy = "busy"
    call_later = "call_later"
    not_interested = "not_interested"
    stop_communication = "stop_communication"
    unknown_question = "unknown_question"
    human_agent = "human_agent"
    objection = "objection"
    thank_you = "thank_you"
    goodbye = "goodbye"
    abusive_offtopic = "abusive_offtopic"


# English + Hindi + Hinglish opt-out phrases. Compliance must not depend on the LLM.
_STOP_RE = re.compile(
    r"""
    (?:
        stop\s+messaging
        | stop\s+(?:texting|calling|contacting|emailing)
        | stop\s+communicating
        | don'?t\s+call(?:\s+me)?(?:\s+again)?(?=\s*$|[!.?,])
        | do\s+not\s+call(?:\s+me)?(?:\s+again)?(?=\s*$|[!.?,])
        | don'?t\s+(?:message|text|contact)(?:\s+me)?
        | do\s+not\s+(?:message|text|contact)(?:\s+me)?
        | never\s+contact\s+me
        | leave\s+me\s+alone
        | unsubscribe
        | opt[-\s]?out
        | remove\s+me\s+(?:from|off)
        | dobara\s+mat(?:\s+(?:karna|karo|call|message|karna))?
        | band\s+kar(?:o|do|\s+do|\s+dena)
        | (?:message|call|contact)\s+mat\s+kar(?:o|na)
        | mat\s+(?:call|message)\s+kar(?:o|na)
        | pareshan\s+mat\s+karo
        | rok\s+do
        | दोबारा\s+मत
        | बंद\s+कर
        | मैसेज\s+मत
        | कॉल\s+मत
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_HINGLISH_STOP_RE = re.compile(
    r"dobara\s+mat|band\s+kar|mat\s+(?:call|message)|pareshan\s+mat|rok\s+do",
    re.IGNORECASE,
)

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

# Objection subtypes from Master Plan Section 10.
_OBJECTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"expensive|costly|pricey|meheng|mehng|mehang|"
            r"out of budget|can't afford|budget nahi|zyada (hai|ho)",
            re.IGNORECASE,
        ),
        "price",
    ),
    (
        re.compile(
            r"family|ghar wal|wife|husband|parents|discuss|"
            r"soch(?:ke| kar)|baat karke",
            re.IGNORECASE,
        ),
        "decision_delay",
    ),
    (
        re.compile(r"\bloan\b|\bemi\b|financ|mortgage|udhaar", re.IGNORECASE),
        "financing",
    ),
    (
        re.compile(
            r"other builder|dusre builder|competitor|compare|"
            r"aur jagah|dlf|godrej|tata housing",
            re.IGNORECASE,
        ),
        "competitor",
    ),
    (
        re.compile(r"\bscam\b|\bbot\b|fake hai|trust|real hai kya", re.IGNORECASE),
        "trust",
    ),
)


def is_stop_request(text: str) -> bool:
    """True when the raw customer text is an opt-out, independent of the LLM."""
    return bool(text and _STOP_RE.search(text.strip()))


def infer_language(text: str, fallback: str = "english") -> str:
    """Lightweight script/phrase hint used for canned stop replies."""
    if text and _DEVANAGARI_RE.search(text):
        return "hindi"
    if text and _HINGLISH_STOP_RE.search(text):
        return "hinglish"
    if fallback in {"english", "hindi", "hinglish"}:
        return fallback
    return "english"


def classify_objection(text: str) -> str:
    """Map free text to an objection subtype; default `other`."""
    if not text:
        return "other"
    for pattern, subtype in _OBJECTION_PATTERNS:
        if pattern.search(text):
            return subtype
    return "other"


def consecutive_intent_count(intent_history: list[dict], intent: Intent | str) -> int:
    """Count how many of the latest intents equal `intent` (streak from the end)."""
    target = intent.value if isinstance(intent, Intent) else intent
    count = 0
    for item in reversed(intent_history):
        if item.get("intent") == target:
            count += 1
        else:
            break
    return count
