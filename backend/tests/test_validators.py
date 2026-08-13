"""Unit tests for Indian phone and name validators."""

from app.utils.validators import is_valid_name, is_valid_phone, normalize_phone


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
