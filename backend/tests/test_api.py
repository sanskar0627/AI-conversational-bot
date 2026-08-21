"""API contracts: all endpoints, error shape, session lifecycle."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_booking_service, get_engine, get_store, reset_singletons
from app.exceptions import CreditsExhaustedError
from app.main import app
from app.models.llm_output import ExtractedFields
from app.services.booking import IST, BookingService, is_sunday_morning
from app.services.conversation_engine import ConversationEngine
from tests.conftest import FakeLLMClient, canned_turn

EXPECTED_PATHS = [
    "/api/health",
    "/api/session",
    "/api/session/{session_id}/memory",
    "/api/chat",
    "/api/booking/slots",
    "/api/book-site-visit",
    "/api/end-session",
    "/api/analytics/{session_id}",
]

CREDITS_MESSAGE = (
    "AI service temporarily unavailable. Please recharge the OpenRouter account."
)


def _error(response) -> dict:
    body = response.json()
    assert set(body) == {"error_code", "message", "retryable"}
    return body


def test_openapi_lists_all_endpoints(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    for path in EXPECTED_PATHS:
        assert path in spec["paths"], f"missing {path}"


def test_health_ok(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "model" in body
    assert "llm_configured" in body


def test_session_chat_booking_analytics_round_trip(client: TestClient, fake_llm: FakeLLMClient) -> None:
    fake_llm.turn = canned_turn(
        reply="2 BHK starts from 1.35 crore onwards.",
        intent="pricing",
        extracted_fields=ExtractedFields(configuration="2 BHK"),
    )
    created = client.post("/api/session", json={"channel": "chat"})
    assert created.status_code == 200
    session_id = created.json()["session_id"]
    assert created.json()["greeting"]

    chat = client.post("/api/chat", json={"session_id": session_id, "message": "2 BHK price?"})
    assert chat.status_code == 200
    body = chat.json()
    assert body["reply"] == "2 BHK starts from 1.35 crore onwards."
    assert body["state"] == "FAQ"
    assert body["language"] == "english"
    assert body["memory_snapshot"]["profile"]["configuration"]["value"] == "2 BHK"
    assert fake_llm.calls

    slots = client.get("/api/booking/slots", params={"session_id": session_id})
    assert slots.status_code == 200
    offered = slots.json()["slots"]
    assert offered
    slot_id = offered[0]["slot_id"]

    booked = client.post(
        "/api/book-site-visit",
        json={
            "session_id": session_id,
            "name": "Rahul",
            "phone": "9810012345",
            "slot_id": slot_id,
        },
    )
    assert booked.status_code == 200
    assert booked.json()["success"] is True
    confirmation_id = booked.json()["confirmation_id"]
    assert confirmation_id.startswith("NS-")
    assert len(confirmation_id) == 9

    ended = client.post("/api/end-session", json={"session_id": session_id})
    assert ended.status_code == 200
    assert ended.json()["session_id"] == session_id
    assert "Stub analytics" in ended.json()["summary"]

    analytics = client.get(f"/api/analytics/{session_id}")
    assert analytics.status_code == 200
    assert analytics.json()["session_id"] == session_id


def test_unknown_session_returns_404_error_shape(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={"session_id": "does-not-exist", "message": "hello"},
    )
    assert response.status_code == 404
    body = _error(response)
    assert body["error_code"] == "SESSION_NOT_FOUND"
    assert body["retryable"] is False


def test_expired_session_returns_410_error_shape(client: TestClient) -> None:
    created = client.post("/api/session", json={"channel": "chat"})
    session_id = created.json()["session_id"]
    session = get_store().get(session_id, touch=False)
    session.last_active_at = session.last_active_at - timedelta(hours=2)

    response = client.post("/api/chat", json={"session_id": session_id, "message": "hello"})
    assert response.status_code == 410
    body = _error(response)
    assert body["error_code"] == "SESSION_EXPIRED"
    assert body["retryable"] is False


def test_empty_message_returns_validation_error_shape(client: TestClient) -> None:
    created = client.post("/api/session", json={"channel": "chat"})
    session_id = created.json()["session_id"]

    empty = client.post("/api/chat", json={"session_id": session_id, "message": ""})
    assert empty.status_code == 422
    body = _error(empty)
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["retryable"] is False

    blank = client.post("/api/chat", json={"session_id": session_id, "message": "   "})
    assert blank.status_code == 422
    assert _error(blank)["error_code"] == "VALIDATION_ERROR"


def test_credits_exhausted_returns_503_with_recharge_message(
    client: TestClient,
    fake_llm: FakeLLMClient,
) -> None:
    created = client.post("/api/session", json={"channel": "chat"})
    session_id = created.json()["session_id"]
    fake_llm.error = CreditsExhaustedError()

    response = client.post("/api/chat", json={"session_id": session_id, "message": "hi"})
    assert response.status_code == 503
    body = _error(response)
    assert body["error_code"] == "CREDITS_EXHAUSTED"
    assert body["message"] == CREDITS_MESSAGE
    assert body["retryable"] is False


def test_analytics_on_active_session_returns_409(client: TestClient) -> None:
    created = client.post("/api/session", json={"channel": "chat"})
    session_id = created.json()["session_id"]
    response = client.get(f"/api/analytics/{session_id}")
    assert response.status_code == 409
    body = _error(response)
    assert body["error_code"] == "SESSION_ACTIVE"


def test_chat_after_end_session_skips_llm(client: TestClient, fake_llm: FakeLLMClient) -> None:
    created = client.post("/api/session", json={"channel": "chat"})
    session_id = created.json()["session_id"]
    client.post("/api/end-session", json={"session_id": session_id})
    fake_llm.calls.clear()

    response = client.post("/api/chat", json={"session_id": session_id, "message": "hello again"})
    assert response.status_code == 200
    assert fake_llm.calls == []
    assert "ended" in response.json()["reply"].lower()


def test_invalid_booking_phone_is_validation_error(client: TestClient) -> None:
    created = client.post("/api/session", json={"channel": "chat"})
    session_id = created.json()["session_id"]
    response = client.post(
        "/api/book-site-visit",
        json={
            "session_id": session_id,
            "name": "Rahul",
            "phone": "12345",
            "slot_id": "not-a-slot",
        },
    )
    assert response.status_code == 422
    assert _error(response)["error_code"] == "VALIDATION_ERROR"


FROZEN = datetime(2026, 9, 2, 9, 0, tzinfo=IST)


@pytest.fixture
def frozen_client(fake_llm: FakeLLMClient):
    reset_singletons()
    booking = BookingService(now_fn=lambda: FROZEN, failure_mode="deterministic")
    engine = ConversationEngine(store=get_store(), llm_client=fake_llm, booking=booking)
    app.dependency_overrides[get_engine] = lambda: engine
    app.dependency_overrides[get_booking_service] = lambda: booking
    with TestClient(app) as test_client:
        yield test_client, booking
    app.dependency_overrides.clear()
    reset_singletons()


def test_ui_booking_confirms_and_blocks_the_taken_slot(frozen_client) -> None:
    client, booking = frozen_client
    created = client.post("/api/session", json={"channel": "chat"})
    session_id = created.json()["session_id"]

    slots = client.get("/api/booking/slots", params={"session_id": session_id})
    assert slots.status_code == 200
    offered = slots.json()["slots"]
    assert offered
    assert all("slot_id" in item and "label" in item for item in offered)
    open_slot = next(
        item
        for item in offered
        if not is_sunday_morning(booking.get_slot(item["slot_id"]).starts_at)
    )

    booked = client.post(
        "/api/book-site-visit",
        json={
            "session_id": session_id,
            "name": "Rahul",
            "phone": "9810012345",
            "slot_id": open_slot["slot_id"],
        },
    )
    body = booked.json()
    assert booked.status_code == 200
    assert body["success"] is True
    assert body["confirmation_id"].startswith("NS-")
    assert len(body["confirmation_id"]) == 9
    assert body["slot"] == open_slot["slot_id"]

    memory = client.get(f"/api/session/{session_id}/memory").json()
    assert memory["booking"]["status"] == "confirmed"
    assert memory["booking"]["confirmation_id"] == body["confirmation_id"]

    other = client.post("/api/session", json={"channel": "chat"}).json()["session_id"]
    taken = client.post(
        "/api/book-site-visit",
        json={
            "session_id": other,
            "name": "Priya",
            "phone": "9876543210",
            "slot_id": open_slot["slot_id"],
        },
    ).json()
    assert taken["success"] is False
    assert taken["reason"] == "slot_taken"
    assert taken["alternatives"]
    assert len(taken["alternatives"]) == 3


def test_sunday_morning_ui_booking_returns_alternatives(frozen_client) -> None:
    client, booking = frozen_client
    session_id = client.post("/api/session", json={"channel": "chat"}).json()["session_id"]
    sunday = next(slot for slot in booking.list_inventory() if is_sunday_morning(slot.starts_at))

    failed = client.post(
        "/api/book-site-visit",
        json={
            "session_id": session_id,
            "name": "Rahul",
            "phone": "9810012345",
            "slot_id": sunday.slot_id,
        },
    )
    body = failed.json()
    assert failed.status_code == 200
    assert body["success"] is False
    assert body["reason"] == "slot_taken"
    assert body["alternatives"]
    assert len(body["alternatives"]) == 3
    memory = client.get(f"/api/session/{session_id}/memory").json()
    assert memory["booking"]["failure_count"] == 1
    assert memory["booking"]["status"] == "failed"


def test_ui_reschedule_issues_a_new_confirmation_id(frozen_client) -> None:
    client, booking = frozen_client
    session_id = client.post("/api/session", json={"channel": "chat"}).json()["session_id"]
    open_slots = [
        slot
        for slot in booking.list_inventory()
        if slot.available and not is_sunday_morning(slot.starts_at)
    ]
    first, second = open_slots[0], open_slots[1]

    original = client.post(
        "/api/book-site-visit",
        json={
            "session_id": session_id,
            "name": "Rahul",
            "phone": "9810012345",
            "slot_id": first.slot_id,
        },
    ).json()
    moved = client.post(
        "/api/book-site-visit",
        json={
            "session_id": session_id,
            "name": "Rahul",
            "phone": "9810012345",
            "slot_id": second.slot_id,
        },
    ).json()
    assert moved["success"] is True
    assert moved["confirmation_id"] != original["confirmation_id"]
    assert moved["slot"] == second.slot_id
    assert booking.get_slot(first.slot_id).available is True
    assert booking.get_slot(second.slot_id).available is False
    memory = client.get(f"/api/session/{session_id}/memory").json()
    assert memory["booking"]["status"] == "confirmed"
    events = [item.get("event") for item in memory["booking"]["history"]]
    assert "rescheduled" in events
