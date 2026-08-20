"""Every Section 6 state-diagram edge, plus terminal-state behaviour."""

from __future__ import annotations

import pytest

from app.memory.schemas import ConversationState
from app.models.llm_output import AgentAction
from app.services.conversation_engine import next_state
from app.services.intent import Intent

GREETING = ConversationState.GREETING
DISCOVERY = ConversationState.DISCOVERY
QUALIFICATION = ConversationState.QUALIFICATION
FAQ = ConversationState.FAQ
OBJECTION = ConversationState.OBJECTION_HANDLING
BOOKING = ConversationState.BOOKING
BOOKING_FAILED = ConversationState.BOOKING_FAILED
FOLLOW_UP = ConversationState.FOLLOW_UP
NOT_INTERESTED = ConversationState.NOT_INTERESTED
ESCALATED = ConversationState.ESCALATED
STOPPED = ConversationState.STOPPED
CLOSED = ConversationState.CLOSED


@pytest.mark.parametrize(
    ("state", "intent", "expected", "label"),
    [
        (GREETING, Intent.greeting, DISCOVERY, "Greeting → Discovery: customer engages"),
        (GREETING, Intent.not_interested, NOT_INTERESTED, "Greeting → NotInterested: rejects immediately"),
        (GREETING, Intent.stop_communication, STOPPED, "Greeting → Stopped: stop request"),
        (GREETING, Intent.human_agent, ESCALATED, "Greeting → Escalated: demands human"),
        (DISCOVERY, Intent.budget_inquiry, QUALIFICATION, "Discovery → Qualification: needs understood"),
        (DISCOVERY, Intent.pricing, FAQ, "Discovery → FAQ: asks questions"),
        (DISCOVERY, Intent.stop_communication, STOPPED, "Discovery → Stopped: stop request"),
        (FAQ, Intent.thank_you, DISCOVERY, "FAQ → Discovery: answered"),
        (QUALIFICATION, Intent.objection, OBJECTION, "Qualification → ObjectionHandling: raises objection"),
        (QUALIFICATION, Intent.site_visit, BOOKING, "Qualification → Booking: visit interest"),
        (QUALIFICATION, Intent.stop_communication, STOPPED, "Qualification → Stopped: stop request"),
        (OBJECTION, Intent.budget_inquiry, QUALIFICATION, "ObjectionHandling → Qualification: resolved"),
        (OBJECTION, Intent.call_later, FOLLOW_UP, "ObjectionHandling → FollowUp: call later"),
        (OBJECTION, Intent.busy, FOLLOW_UP, "ObjectionHandling → FollowUp: busy"),
        (OBJECTION, Intent.not_interested, NOT_INTERESTED, "ObjectionHandling → NotInterested: firm no"),
        (BOOKING_FAILED, Intent.site_visit, BOOKING, "BookingFailed → Booking: retry alternative"),
        (FOLLOW_UP, Intent.goodbye, CLOSED, "FollowUp → Closed: follow-up captured"),
        (NOT_INTERESTED, Intent.goodbye, CLOSED, "NotInterested → Closed: polite close"),
        (ESCALATED, Intent.goodbye, CLOSED, "Escalated → Closed: handoff confirmed"),
    ],
)
def test_diagram_intent_edges(
    state: ConversationState,
    intent: Intent,
    expected: ConversationState,
    label: str,
) -> None:
    assert next_state(state, intent) == expected, label


def test_faq_unknown_x2_escalates() -> None:
    assert (
        next_state(FAQ, Intent.unknown_question, consecutive_unknowns=2)
        == ESCALATED
    )


def test_discovery_unknown_x2_escalates() -> None:
    assert (
        next_state(DISCOVERY, Intent.unknown_question, consecutive_unknowns=2)
        == ESCALATED
    )


def test_faq_sensitive_escalates() -> None:
    assert next_state(FAQ, Intent.unknown_question, escalate=True) == ESCALATED


def test_booking_slot_failure_enters_booking_failed() -> None:
    assert (
        next_state(BOOKING, Intent.site_visit, booking_event="failed")
        == BOOKING_FAILED
    )


def test_booking_failed_x2_escalates() -> None:
    assert (
        next_state(
            BOOKING_FAILED,
            Intent.site_visit,
            booking_failure_count=2,
        )
        == ESCALATED
    )


def test_booking_confirmed_plus_closing_goes_closed() -> None:
    assert (
        next_state(
            BOOKING,
            Intent.goodbye,
            booking_event="confirmed",
        )
        == CLOSED
    )
    assert next_state(BOOKING, Intent.thank_you, action=AgentAction.close) == CLOSED


def test_propose_slots_enters_booking() -> None:
    assert next_state(QUALIFICATION, Intent.site_visit, action=AgentAction.propose_slots) == BOOKING
    assert next_state(BOOKING_FAILED, Intent.site_visit, action=AgentAction.propose_slots) == BOOKING


def test_stopped_and_closed_are_terminal() -> None:
    assert next_state(STOPPED, Intent.pricing) == STOPPED
    assert next_state(STOPPED, Intent.greeting, action=AgentAction.close) == STOPPED
    assert next_state(CLOSED, Intent.site_visit) == CLOSED
    assert next_state(CLOSED, Intent.human_agent) == CLOSED


def test_stop_action_and_intent_always_win() -> None:
    assert next_state(QUALIFICATION, Intent.pricing, action=AgentAction.stop) == STOPPED
    assert next_state(BOOKING, Intent.stop_communication) == STOPPED
