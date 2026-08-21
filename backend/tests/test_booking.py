"""Slot inventory: generation, seeded unavailability, nearest open slots."""

from __future__ import annotations

from datetime import datetime

from app.memory.schemas import SessionMemory
from app.models.responses import BookingResponse
from app.services.booking import (
    FOLLOW_UP_CANCELLED,
    HORIZON_DAYS,
    IST,
    SLOT_HOURS,
    BookingService,
    apply_booking_result,
    format_slot_label,
    format_slot_offer,
    generate_inventory,
    is_sunday_morning,
    make_slot_id,
    parse_slot_id,
)

FROZEN = datetime(2026, 9, 2, 9, 0, tzinfo=IST)  # Wednesday morning


def _service(*, failure_mode: str = "deterministic") -> BookingService:
    return BookingService(now_fn=lambda: FROZEN, failure_mode=failure_mode)


def _open_slot(service: BookingService):
    return next(
        slot
        for slot in service.list_inventory()
        if slot.available and not is_sunday_morning(slot.starts_at)
    )


def _sunday_morning_slot(service: BookingService):
    return next(slot for slot in service.list_inventory() if is_sunday_morning(slot.starts_at))


def test_inventory_covers_next_seven_days_in_two_hour_slots() -> None:
    slots = generate_inventory(FROZEN)
    assert slots
    first = slots[0]
    last = slots[-1]
    assert first.starts_at > FROZEN
    assert (last.starts_at.date() - FROZEN.date()).days == HORIZON_DAYS - 1
    hours = {slot.starts_at.hour for slot in slots}
    assert hours <= set(SLOT_HOURS)
    assert all(slot.starts_at.minute == 0 for slot in slots)
    assert all(slot.slot_id == make_slot_id(slot.starts_at) for slot in slots)


def test_slot_ids_and_labels_are_stable() -> None:
    starts = datetime(2026, 9, 5, 10, 0, tzinfo=IST)
    assert make_slot_id(starts) == "2026-09-05-1000"
    assert parse_slot_id("2026-09-05-1000") == starts
    assert format_slot_label(starts) == "Sat 10 AM"
    assert parse_slot_id("not-a-slot") is None


def test_seeded_unavailability_is_reproducible_and_skips_sunday_morning() -> None:
    first = generate_inventory(FROZEN, seed=79)
    second = generate_inventory(FROZEN, seed=79)
    assert [slot.slot_id for slot in first] == [slot.slot_id for slot in second]
    assert [slot.available for slot in first] == [slot.available for slot in second]
    assert any(not slot.available for slot in first)

    sunday_morning = next(slot for slot in first if is_sunday_morning(slot.starts_at))
    assert sunday_morning.available is True
    assert sunday_morning.slot_id == "2026-09-06-1000"


def test_get_available_slots_returns_nearest_open_only() -> None:
    service = _service()
    offered = service.get_available_slots(limit=3)
    assert len(offered) == 3
    assert all(slot.available for slot in offered)
    inventory = {slot.slot_id: slot for slot in service.list_inventory()}
    for info in offered:
        assert inventory[info.slot_id].available is True
    assert format_slot_offer(offered).startswith("Available: ")


def test_past_slots_on_the_same_day_are_omitted() -> None:
    afternoon = datetime(2026, 9, 2, 13, 0, tzinfo=IST)
    slots = generate_inventory(afternoon)
    today_hours = [
        slot.starts_at.hour for slot in slots if slot.starts_at.date() == afternoon.date()
    ]
    assert 10 not in today_hours
    assert 12 not in today_hours
    assert today_hours[0] == 14


def test_happy_path_returns_confirmation_id_and_removes_slot() -> None:
    service = _service()
    slot = _open_slot(service)
    result = service.attempt_booking(
        session_id="sess-ok",
        name="Rahul",
        phone="9810012345",
        slot_id=slot.slot_id,
    )
    assert result.success is True
    assert result.confirmation_id is not None
    assert result.confirmation_id.startswith("NS-")
    assert len(result.confirmation_id) == 9
    assert result.slot == slot.slot_id
    assert result.slot_label == slot.label
    taken = service.get_slot(slot.slot_id)
    assert taken is not None and taken.available is False
    assert slot.slot_id not in {item.slot_id for item in service.get_available_slots(limit=20)}


def test_sunday_morning_fails_deterministically_with_three_alternatives() -> None:
    service = _service()
    sunday = _sunday_morning_slot(service)
    result = service.attempt_booking(
        session_id="sess-sun",
        name="Rahul",
        phone="9810012345",
        slot_id=sunday.slot_id,
    )
    assert result.success is False
    assert result.reason == "slot_taken"
    assert result.alternatives is not None
    assert len(result.alternatives) == 3
    assert sunday.slot_id not in {item.slot_id for item in result.alternatives}
    assert service.get_slot(sunday.slot_id) is not None
    assert sunday.slot_id not in service._taken


def test_always_fail_once_returns_system_error_then_succeeds() -> None:
    service = _service(failure_mode="always_fail_once")
    slot = _open_slot(service)
    first = service.attempt_booking(
        session_id="sess-glitch",
        name="Rahul",
        phone="9810012345",
        slot_id=slot.slot_id,
    )
    assert first.success is False
    assert first.reason == "system_error"
    assert first.alternatives is not None
    assert len(first.alternatives) == 3

    second = service.attempt_booking(
        session_id="sess-glitch",
        name="Rahul",
        phone="9810012345",
        slot_id=slot.slot_id,
    )
    assert second.success is True
    assert second.confirmation_id is not None


def test_invalid_name_and_phone_never_take_a_slot() -> None:
    service = _service()
    slot = _open_slot(service)
    bad_phone = service.attempt_booking(
        session_id="sess-bad",
        name="Rahul",
        phone="12345",
        slot_id=slot.slot_id,
    )
    assert bad_phone.success is False
    assert bad_phone.reason == "invalid_phone"
    bad_name = service.attempt_booking(
        session_id="sess-bad",
        name="R",
        phone="9810012345",
        slot_id=slot.slot_id,
    )
    assert bad_name.success is False
    assert bad_name.reason == "invalid_name"
    still_open = service.get_slot(slot.slot_id)
    assert still_open is not None and still_open.available is True


def test_reschedule_issues_new_id_and_frees_the_old_slot() -> None:
    service = _service()
    first = _open_slot(service)
    booked = service.attempt_booking(
        session_id="sess-move",
        name="Rahul",
        phone="9810012345",
        slot_id=first.slot_id,
    )
    second = next(
        slot
        for slot in service.list_inventory()
        if slot.available and not is_sunday_morning(slot.starts_at)
    )
    moved = service.reschedule(
        session_id="sess-move",
        name="Rahul",
        phone="9810012345",
        old_slot_id=first.slot_id,
        new_slot_id=second.slot_id,
    )
    assert moved.success is True
    assert moved.confirmation_id != booked.confirmation_id
    assert moved.slot == second.slot_id
    freed = service.get_slot(first.slot_id)
    held = service.get_slot(second.slot_id)
    assert freed is not None and freed.available is True
    assert held is not None and held.available is False


def test_failed_reschedule_keeps_the_original_slot() -> None:
    service = _service()
    first = _open_slot(service)
    booked = service.attempt_booking(
        session_id="sess-keep",
        name="Rahul",
        phone="9810012345",
        slot_id=first.slot_id,
    )
    sunday = _sunday_morning_slot(service)
    failed = service.reschedule(
        session_id="sess-keep",
        name="Rahul",
        phone="9810012345",
        old_slot_id=first.slot_id,
        new_slot_id=sunday.slot_id,
    )
    assert failed.success is False
    assert failed.reason == "slot_taken"
    still_held = service.get_slot(first.slot_id)
    assert still_held is not None and still_held.available is False
    assert booked.slot == first.slot_id


def test_cancel_frees_slot_and_sets_follow_up() -> None:
    service = _service()
    slot = _open_slot(service)
    booked = service.attempt_booking(
        session_id="sess-cancel",
        name="Rahul",
        phone="9810012345",
        slot_id=slot.slot_id,
    )
    memory = SessionMemory(
        session_id="sess-cancel",
        channel="chat",
        booking={
            "status": "confirmed",
            "slot": booked.slot,
            "confirmation_id": booked.confirmation_id,
            "failure_count": 0,
            "history": [],
        },
    )
    result = service.cancel(slot_id=booked.slot)
    apply_booking_result(memory, result, event="cancelled")
    freed = service.get_slot(slot.slot_id)
    assert freed is not None and freed.available is True
    assert memory.booking["status"] == "cancelled"
    assert memory.booking["follow_up_required"] is True
    assert memory.booking["follow_up_reason"] == FOLLOW_UP_CANCELLED
    assert memory.booking["confirmation_id"] is None


def test_apply_result_counts_failures_but_not_validation_errors() -> None:
    memory = SessionMemory(session_id="sess-count", channel="chat")
    apply_booking_result(
        memory,
        BookingResponse(success=False, reason="invalid_phone"),
        event="validation",
    )
    assert memory.booking["failure_count"] == 0
    assert memory.booking["validation_attempts"] == 1
    apply_booking_result(
        memory,
        BookingResponse(success=False, reason="slot_taken", alternatives=[]),
        event="failed",
        requested_slot="2026-09-06-1000",
    )
    apply_booking_result(
        memory,
        BookingResponse(success=False, reason="system_error", alternatives=[]),
        event="failed",
        requested_slot="2026-09-05-1000",
    )
    assert memory.booking["failure_count"] == 2
    assert memory.booking["status"] == "failed"
