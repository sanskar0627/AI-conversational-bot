"""Phone (Indian 10-digit), name, and light input sanitization."""

from __future__ import annotations

import re

PHONE_PATTERN = re.compile(r"^(\+91)?[6-9]\d{9}$")


def sanitize_user_text(text: str) -> str:
    """Strip control characters except newline and tab."""
    return "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)


def normalize_phone(phone: str) -> str:
    """Remove common separators so the canonical regex can match."""
    return re.sub(r"[\s\-()]", "", phone.strip())


def is_valid_phone(phone: str) -> bool:
    if not phone:
        return False
    return PHONE_PATTERN.fullmatch(normalize_phone(phone)) is not None


def is_valid_name(name: str) -> bool:
    return len(name.strip()) >= 2


def is_valid_slot_id(slot_id: str) -> bool:
    return bool(slot_id.strip())
