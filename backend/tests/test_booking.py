"""Slot inventory: generation, seeded unavailability, nearest open slots."""

from __future__ import annotations

from datetime import datetime

from app.services.booking import (
    HORIZON_DAYS,
    IST,
    SLOT_HOURS,
    BookingService,
    format_slot_label,
    format_slot_offer,
    generate_inventory,
    is_sunday_morning,
    make_slot_id,
    parse_slot_id,
)

FROZEN = datetime(2026, 9, 2, 9, 0, tzinfo=IST)  # Wednesday morning


def _service() -> BookingService:
    return BookingService(now_fn=lambda: FROZEN)


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
