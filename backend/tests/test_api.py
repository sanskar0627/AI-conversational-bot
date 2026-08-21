"""API contracts: all endpoints, error shape, session lifecycle."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from app.dependencies import get_store
from app.exceptions import CreditsExhaustedError
from app.models.llm_output import ExtractedFields
from tests.conftest import FakeLLMClient, canned_turn

EXPECTED_PATHS = [
    "/api/health",
    "/api/session",
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


def test_openapi_lists_all_seven_endpoints(client: TestClient) -> None:
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
    assert body["memory_snapshot"]["configuration"] == "2 BHK"
    assert fake_llm.calls

    slots = client.get("/api/booking/slots", params={"session_id": session_id})
    assert slots.status_code == 200
    assert slots.json()["slots"]

    booked = client.post(
        "/api/book-site-visit",
        json={
            "session_id": session_id,
            "name": "Rahul",
            "phone": "9810012345",
            "slot_id": "stub-sat-1100",
        },
    )
    assert booked.status_code == 200
    assert booked.json()["success"] is True
    assert booked.json()["confirmation_id"] == "NS-STUB01"

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
            "slot_id": "stub-sat-1100",
        },
    )
    assert response.status_code == 422
    assert _error(response)["error_code"] == "VALIDATION_ERROR"
