"""StructuredTurn schema the LLM must return each chat turn."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.intent import Intent


class DetectedLanguage(str, Enum):
    english = "english"
    hindi = "hindi"
    hinglish = "hinglish"


class AgentAction(str, Enum):
    none = "none"
    propose_slots = "propose_slots"
    confirm_booking = "confirm_booking"
    escalate = "escalate"
    close = "close"
    stop = "stop"


class Sentiment(str, Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"


class ExtractedFields(BaseModel):
    """Lead fields extracted this turn. Empty keys are omitted; extra keys ignored."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    phone: str | None = None
    budget: str | None = None
    budget_min: Any | None = None
    budget_max: Any | None = None
    configuration: str | None = None
    timeline: str | None = None
    purpose: str | None = None
    financing: str | None = None
    city: str | None = None
    visit_interest: Any | None = None
    field_confidence: dict[str, str] | None = None


class StructuredTurn(BaseModel):
    """Closed JSON contract produced by one LLM call per turn."""

    model_config = ConfigDict(extra="ignore")

    reply: str
    detected_language: DetectedLanguage
    intent: Intent
    extracted_fields: ExtractedFields = Field(default_factory=ExtractedFields)
    sentiment: Sentiment = Sentiment.neutral
    action: AgentAction = AgentAction.none

    @field_validator("extracted_fields", mode="before")
    @classmethod
    def empty_fields_if_null(cls, value: object) -> object:
        return {} if value is None else value

    @field_validator("sentiment", mode="before")
    @classmethod
    def default_sentiment_if_null(cls, value: object) -> object:
        return Sentiment.neutral if value in (None, "") else value

    @field_validator("action", mode="before")
    @classmethod
    def default_action_if_null(cls, value: object) -> object:
        return AgentAction.none if value in (None, "") else value
