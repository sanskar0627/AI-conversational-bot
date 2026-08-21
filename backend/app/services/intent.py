"""Intent enum plus deterministic stop/abuse regex overrides (Stage 04)."""

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
