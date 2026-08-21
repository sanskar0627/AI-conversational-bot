"""Structured logging helpers with phone-number masking."""

from __future__ import annotations

import logging
import re

_PHONE_IN_TEXT = re.compile(r"(\+91)?[6-9]\d{9}")
MASKED_PHONE = "+91XXXXX*****"


def mask_phone(value: str) -> str:
    """Mask an Indian phone as +91XXXXX***** (never log the raw number)."""
    if not value:
        return value
    return MASKED_PHONE


def mask_pii(text: str) -> str:
    """Replace phone-like spans in free text before logging."""
    return _PHONE_IN_TEXT.sub(MASKED_PHONE, text)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
