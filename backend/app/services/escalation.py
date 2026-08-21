"""Escalation trigger detection and payload builder (Stage 04)."""

from __future__ import annotations

from typing import Any

from app.memory.schemas import SessionMemory


class EscalationService:
    """No-op until Stage 04 wires triggers and payload construction."""

    def should_escalate(self, memory: SessionMemory, turn: Any) -> str | None:
        return None

    def build_payload(self, memory: SessionMemory, reason: str) -> dict[str, Any]:
        return {
            "session_id": memory.session_id,
            "reason": reason,
            "urgency": "normal",
        }
