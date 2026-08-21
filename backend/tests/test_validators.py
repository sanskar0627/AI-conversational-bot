"""Unit tests for Indian phone and name validators."""

from app.utils.validators import is_valid_name, is_valid_phone, is_valid_slot_id, normalize_phone


def test_valid_ten_digit_phones() -> None:
    assert is_valid_phone("9810012345")
    assert is_valid_phone("6789012345")
    assert is_valid_phone("7999999999")


def test_valid_phone_with_country_code() -> None:
    assert is_valid_phone("+919810012345")


def test_valid_phone_strips_separators() -> None:
    assert is_valid_phone("98100 12345")
    assert is_valid_phone("+91-98100-12345")
    assert normalize_phone("+91 98100 12345") == "+919810012345"


def test_invalid_phones() -> None:
    assert not is_valid_phone("")
    assert not is_valid_phone("12345")
    assert not is_valid_phone("5810012345")  # must start 6–9
    assert not is_valid_phone("981001234")  # 9 digits
    assert not is_valid_phone("98100123456")  # 11 digits without +91
    assert not is_valid_phone("+911234567890")  # starts with 1
    assert not is_valid_phone("abcdefghij")


def test_valid_names() -> None:
    assert is_valid_name("Jo")
    assert is_valid_name("Rahul")
    assert is_valid_name("  Aisha  ")


def test_invalid_names() -> None:
    assert not is_valid_name("")
    assert not is_valid_name("A")
    assert not is_valid_name("  x  ")


def test_valid_slot_ids() -> None:
    assert is_valid_slot_id("2026-08-23-1100")
    assert is_valid_slot_id("2026-09-06-1000")
    assert is_valid_slot_id("2026-09-06-1630")


def test_invalid_slot_ids() -> None:
    assert not is_valid_slot_id("")
    assert not is_valid_slot_id("stub-sat-1100")
    assert not is_valid_slot_id("2026-08-23")
    assert not is_valid_slot_id("2026-08-23-2460")
    assert not is_valid_slot_id("2026-08-23-1159")
