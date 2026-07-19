"""Tests for domain value objects."""

from dataclasses import FrozenInstanceError

import pytest

from sf6viewer.domain.errors import DomainError
from sf6viewer.domain.value_objects import UserCode


def test_user_code_trims_outer_whitespace() -> None:
    assert UserCode.parse("  1234567890\t") == UserCode("1234567890")


@pytest.mark.parametrize(
    "raw",
    [
        None,
        1234567890,
        "123456789",
        "12345678901",
        "１２３４５６７８９０",
        "12345abc90",
        "12345 6789",
    ],
)
def test_user_code_rejects_invalid_input_with_typed_error(raw: object) -> None:
    with pytest.raises(DomainError) as exc_info:
        UserCode.parse(raw)

    assert exc_info.value.code == "VALIDATION.USER_CODE"


def test_user_code_is_frozen_and_slotted() -> None:
    user_code = UserCode("1234567890")

    with pytest.raises(FrozenInstanceError):
        user_code.value = "0987654321"  # type: ignore[misc]

    assert not hasattr(user_code, "__dict__")


@pytest.mark.parametrize(
    "value",
    ["abc", "12345678901", "１２３４５６７８９０", " 1234567890 "],
)
def test_user_code_direct_construction_rejects_noncanonical_values(value: str) -> None:
    with pytest.raises(DomainError) as exc_info:
        UserCode(value)

    assert exc_info.value.code == "VALIDATION.USER_CODE"
