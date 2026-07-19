"""Tests for safe, typed domain errors."""

from dataclasses import fields
from http import HTTPStatus
from types import MappingProxyType

import pytest

from sf6viewer.domain.errors import ERROR_SPECS, DomainError, ErrorSpec, error_from_code

EXPECTED_CODES = {
    "VALIDATION.USER_CODE",
    "VALIDATION.LIMIT",
    "SESSION.MISSING",
    "SESSION.EXPIRED",
    "SESSION.ACCOUNT_MISMATCH",
    "UPSTREAM.TIMEOUT",
    "UPSTREAM.UNAVAILABLE",
    "UPSTREAM.RATE_LIMITED",
    "UPSTREAM.CONTRACT_CHANGED",
    "DATA.IDENTITY_GROUP_INCOMPLETE",
    "DATA.IDENTITY_COLLISION",
    "STORAGE.LOCKED",
    "STORAGE.FULL",
    "STORAGE.CORRUPT",
    "MIGRATION.UNSUPPORTED_SCHEMA",
    "MIGRATION.SOURCE_BUSY",
    "MIGRATION.BACKUP_FAILED",
    "MIGRATION.INVARIANT_FAILED",
    "JOB.CONFLICT",
    "JOB.QUEUE_FULL",
    "JOB.INVALID_TRANSITION",
    "INGESTION.COUNT_MISMATCH",
    "INTERNAL.UNEXPECTED",
}

EXPECTED_STATUS_AND_RETRYABILITY = {
    "VALIDATION.USER_CODE": (422, False),
    "VALIDATION.LIMIT": (422, False),
    "SESSION.MISSING": (401, False),
    "SESSION.EXPIRED": (401, False),
    "SESSION.ACCOUNT_MISMATCH": (409, False),
    "UPSTREAM.TIMEOUT": (503, True),
    "UPSTREAM.UNAVAILABLE": (503, True),
    "UPSTREAM.RATE_LIMITED": (429, True),
    "UPSTREAM.CONTRACT_CHANGED": (502, False),
    "DATA.IDENTITY_GROUP_INCOMPLETE": (409, True),
    "DATA.IDENTITY_COLLISION": (409, False),
    "STORAGE.LOCKED": (503, True),
    "STORAGE.FULL": (507, False),
    "STORAGE.CORRUPT": (500, False),
    "MIGRATION.UNSUPPORTED_SCHEMA": (422, False),
    "MIGRATION.SOURCE_BUSY": (409, True),
    "MIGRATION.BACKUP_FAILED": (500, True),
    "MIGRATION.INVARIANT_FAILED": (409, False),
    "JOB.CONFLICT": (409, True),
    "JOB.QUEUE_FULL": (429, True),
    "JOB.INVALID_TRANSITION": (409, False),
    "INGESTION.COUNT_MISMATCH": (500, False),
    "INTERNAL.UNEXPECTED": (500, False),
}


def test_error_spec_has_only_its_three_positional_fields() -> None:
    assert [field.name for field in fields(ErrorSpec)] == ["status", "retryable", "action"]
    assert ErrorSpec(503, True, "RETRY") == ErrorSpec(503, True, "RETRY")


def test_error_catalog_has_exactly_the_required_codes_and_entries() -> None:
    assert set(ERROR_SPECS) == EXPECTED_CODES
    assert ERROR_SPECS["UPSTREAM.TIMEOUT"] == ErrorSpec(503, True, "RETRY")
    assert ERROR_SPECS["SESSION.EXPIRED"] == ErrorSpec(401, False, "LOGIN")
    assert ERROR_SPECS["STORAGE.FULL"] == ErrorSpec(507, False, "FREE_SPACE")
    assert ERROR_SPECS["DATA.IDENTITY_COLLISION"] == ErrorSpec(
        409, False, "REVIEW_QUARANTINE"
    )
    assert ERROR_SPECS["JOB.INVALID_TRANSITION"] == ErrorSpec(
        409, False, "COPY_DIAGNOSTICS"
    )
    assert ERROR_SPECS["INGESTION.COUNT_MISMATCH"] == ErrorSpec(
        500, False, "RUN_RECOVERY"
    )


def test_error_catalog_uses_safe_http_metadata() -> None:
    for code, spec in ERROR_SPECS.items():
        assert HTTPStatus(spec.status).value == spec.status, code
        assert 400 <= spec.status < 600, code
        assert spec.action
        assert spec.action == spec.action.upper()
        assert all(character.isupper() or character == "_" for character in spec.action)


def test_error_catalog_is_read_only() -> None:
    assert isinstance(ERROR_SPECS, MappingProxyType)

    with pytest.raises(TypeError):
        ERROR_SPECS["VALIDATION.USER_CODE"] = ErrorSpec(500, False, "RETRY")  # type: ignore[index]


def test_error_catalog_matches_foundation_status_and_retryability_policy() -> None:
    assert {
        code: (spec.status, spec.retryable) for code, spec in ERROR_SPECS.items()
    } == EXPECTED_STATUS_AND_RETRYABILITY


def test_domain_error_exposes_only_safe_catalog_metadata() -> None:
    diagnostic_id = "01arz3ndektsv4rrffq69g5fav"

    error = error_from_code("UPSTREAM.TIMEOUT", diagnostic_id=diagnostic_id)

    assert isinstance(error, DomainError)
    assert error.code == "UPSTREAM.TIMEOUT"
    assert error.spec == ErrorSpec(503, True, "RETRY")
    assert error.status == 503
    assert error.retryable is True
    assert error.action == "RETRY"
    assert error.diagnostic_id == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
    assert str(error) == "UPSTREAM.TIMEOUT: The upstream service did not respond in time."


def test_domain_error_strips_and_uppercases_a_valid_diagnostic_id() -> None:
    error = error_from_code(
        "UPSTREAM.TIMEOUT", diagnostic_id="  01arz3ndektsv4rrffq69g5fav\n"
    )

    assert error.diagnostic_id == "01ARZ3NDEKTSV4RRFFQ69G5FAV"


def test_error_from_unknown_code_rejects_without_echoing_raw_input() -> None:
    raw_code = "SELECT cookie FROM sessions WHERE token = 'secret'"

    with pytest.raises(ValueError, match="^Unknown error code\\.$") as exc_info:
        error_from_code(raw_code, diagnostic_id="diag_02")

    assert raw_code not in str(exc_info.value)


def test_direct_domain_error_construction_rejects_unknown_code_without_echoing_input() -> None:
    raw_code = "token=top-secret"

    with pytest.raises(ValueError, match="^Unknown error code\\.$") as exc_info:
        DomainError(raw_code)

    assert raw_code not in str(exc_info.value)


@pytest.mark.parametrize(
    "diagnostic_id",
    [
        "token=top-secret",
        "C:/private/session",
        "cookie=session-id",
        "01IRZ3NDEKTSV4RRFFQ69G5FAV",
        "81ARZ3NDEKTSV4RRFFQ69G5FAV",
    ],
)
def test_domain_error_rejects_invalid_diagnostic_id_without_echoing_input(
    diagnostic_id: str,
) -> None:
    with pytest.raises(ValueError, match="^Invalid diagnostic ID\\.$") as exc_info:
        error_from_code("UPSTREAM.TIMEOUT", diagnostic_id=diagnostic_id)

    assert diagnostic_id not in str(exc_info.value)


def test_error_factory_does_not_accept_a_caller_supplied_public_message() -> None:
    with pytest.raises(TypeError):
        error_from_code("UPSTREAM.TIMEOUT", "do not expose this")  # type: ignore[call-arg]
