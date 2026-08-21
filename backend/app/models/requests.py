"""Inbound API request models."""

from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.utils.validators import is_valid_name, is_valid_phone, sanitize_user_text


class Channel(str, Enum):
    chat = "chat"
    voice = "voice"


class CreateSessionRequest(BaseModel):
    channel: Channel = Channel.chat


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def message_must_be_non_blank(cls, value: str) -> str:
        cleaned = sanitize_user_text(value).strip()
        if not cleaned:
            raise ValueError("message must not be empty")
        return cleaned


class BookingRequest(BaseModel):
    session_id: str = Field(min_length=1)
    name: str = Field(min_length=2)
    phone: str
    slot_id: str = Field(min_length=1)

    @field_validator("name")
    @classmethod
    def name_must_be_valid(cls, value: str) -> str:
        cleaned = value.strip()
        if not is_valid_name(cleaned):
            raise ValueError("name must be at least 2 characters")
        return cleaned

    @field_validator("phone")
    @classmethod
    def phone_must_be_indian(cls, value: str) -> str:
        if not is_valid_phone(value):
            raise ValueError("phone must be a valid Indian 10-digit number")
        return value.strip()


class EndSessionRequest(BaseModel):
    session_id: str = Field(min_length=1)
