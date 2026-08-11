"""Shared service singletons wired through FastAPI Depends."""

from __future__ import annotations

from app.memory.store import SessionStore
from app.services.booking import BookingService
from app.services.conversation_engine import ConversationEngine
from app.services.escalation import EscalationService
from app.services.llm_client import LLMClient
from app.utils.rate_limit import RateLimiter

_store: SessionStore | None = None
_llm_client: LLMClient | None = None
_booking: BookingService | None = None
_escalation: EscalationService | None = None
_engine: ConversationEngine | None = None
_rate_limiter: RateLimiter | None = None


def get_store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore()
    return _store


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


def get_booking_service() -> BookingService:
    global _booking
    if _booking is None:
        _booking = BookingService()
    return _booking


def get_escalation_service() -> EscalationService:
    global _escalation
    if _escalation is None:
        _escalation = EscalationService()
    return _escalation


def get_engine() -> ConversationEngine:
    global _engine
    if _engine is None:
        _engine = ConversationEngine(
            store=get_store(),
            llm_client=get_llm_client(),
            booking=get_booking_service(),
            escalation=get_escalation_service(),
        )
    return _engine


def get_rate_limiter() -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


def reset_singletons() -> None:
    """Drop cached instances so tests start from a clean slate."""
    global _store, _llm_client, _booking, _escalation, _engine, _rate_limiter
    _store = None
    _llm_client = None
    _booking = None
    _escalation = None
    _engine = None
    _rate_limiter = None
