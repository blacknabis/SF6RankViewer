"""Typed, safe domain errors."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class ErrorSpec:
    """Public metadata for a domain error."""

    status: int
    retryable: bool
    action: str


ERROR_SPECS: Mapping[str, ErrorSpec] = MappingProxyType({
    "VALIDATION.USER_CODE": ErrorSpec(422, False, "CORRECT_INPUT"),
    "VALIDATION.LIMIT": ErrorSpec(422, False, "REDUCE_REQUEST"),
    "SESSION.MISSING": ErrorSpec(401, False, "LOGIN"),
    "SESSION.EXPIRED": ErrorSpec(401, False, "LOGIN"),
    "SESSION.ACCOUNT_MISMATCH": ErrorSpec(409, False, "SWITCH_ACCOUNT"),
    "UPSTREAM.TIMEOUT": ErrorSpec(503, True, "RETRY"),
    "UPSTREAM.UNAVAILABLE": ErrorSpec(503, True, "RETRY"),
    "UPSTREAM.RATE_LIMITED": ErrorSpec(429, True, "RETRY"),
    "UPSTREAM.CONTRACT_CHANGED": ErrorSpec(502, False, "COPY_DIAGNOSTICS"),
    "DATA.IDENTITY_GROUP_INCOMPLETE": ErrorSpec(409, True, "REVIEW_SOURCE"),
    "DATA.IDENTITY_COLLISION": ErrorSpec(409, False, "REVIEW_QUARANTINE"),
    "STORAGE.LOCKED": ErrorSpec(503, True, "RETRY"),
    "STORAGE.FULL": ErrorSpec(507, False, "FREE_SPACE"),
    "STORAGE.CORRUPT": ErrorSpec(500, False, "RUN_RECOVERY"),
    "MIGRATION.UNSUPPORTED_SCHEMA": ErrorSpec(422, False, "UPDATE_APP"),
    "MIGRATION.SOURCE_BUSY": ErrorSpec(409, True, "RETRY"),
    "MIGRATION.BACKUP_FAILED": ErrorSpec(500, True, "RETRY"),
    "MIGRATION.INVARIANT_FAILED": ErrorSpec(409, False, "RUN_RECOVERY"),
    "JOB.CONFLICT": ErrorSpec(409, True, "REFRESH"),
    "JOB.QUEUE_FULL": ErrorSpec(429, True, "RETRY"),
    "JOB.INVALID_TRANSITION": ErrorSpec(409, False, "COPY_DIAGNOSTICS"),
    "INGESTION.COUNT_MISMATCH": ErrorSpec(500, False, "RUN_RECOVERY"),
    "INTERNAL.UNEXPECTED": ErrorSpec(500, False, "COPY_DIAGNOSTICS"),
})

_SAFE_MESSAGES: dict[str, str] = {
    "VALIDATION.USER_CODE": "Enter a valid ten-digit user code.",
    "VALIDATION.LIMIT": "Reduce the request and try again.",
    "SESSION.MISSING": "Sign in to continue.",
    "SESSION.EXPIRED": "Your session has expired. Sign in again.",
    "SESSION.ACCOUNT_MISMATCH": "Switch to the account that started this operation.",
    "UPSTREAM.TIMEOUT": "The upstream service did not respond in time.",
    "UPSTREAM.UNAVAILABLE": "The upstream service is currently unavailable.",
    "UPSTREAM.RATE_LIMITED": "The upstream service is busy. Try again later.",
    "UPSTREAM.CONTRACT_CHANGED": "The upstream service response needs attention.",
    "DATA.IDENTITY_GROUP_INCOMPLETE": "The source data is incomplete for this operation.",
    "DATA.IDENTITY_COLLISION": "Conflicting identities require review.",
    "STORAGE.LOCKED": "The local storage is currently in use.",
    "STORAGE.FULL": "Free storage space and try again.",
    "STORAGE.CORRUPT": "Local storage needs recovery.",
    "MIGRATION.UNSUPPORTED_SCHEMA": "Update the application before migrating this data.",
    "MIGRATION.SOURCE_BUSY": "The migration source is currently in use.",
    "MIGRATION.BACKUP_FAILED": "The migration backup could not be completed.",
    "MIGRATION.INVARIANT_FAILED": "The migration needs recovery before continuing.",
    "JOB.CONFLICT": "Refresh the job status and try again.",
    "JOB.QUEUE_FULL": "The job queue is full. Try again later.",
    "JOB.INVALID_TRANSITION": "This job state change is not allowed.",
    "INGESTION.COUNT_MISMATCH": "The imported data needs recovery.",
    "INTERNAL.UNEXPECTED": "An unexpected internal error occurred.",
}

_CROCKFORD_ULID_ALPHABET = frozenset("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


class DomainError(Exception):
    """A domain failure safe for presentation to users."""

    def __init__(self, code: str, *, diagnostic_id: str | None = None) -> None:
        if code not in ERROR_SPECS:
            raise ValueError("Unknown error code.")
        self.code = code
        self.spec = ERROR_SPECS[code]
        self.status = self.spec.status
        self.retryable = self.spec.retryable
        self.action = self.spec.action
        self.diagnostic_id = _canonical_diagnostic_id(diagnostic_id)
        super().__init__(f"{code}: {_SAFE_MESSAGES[code]}")


def error_from_code(code: str, *, diagnostic_id: str | None = None) -> DomainError:
    """Create a safe error from a known catalog code."""
    if code not in ERROR_SPECS:
        raise ValueError("Unknown error code.")
    return DomainError(code, diagnostic_id=diagnostic_id)


def _canonical_diagnostic_id(diagnostic_id: str | None) -> str | None:
    if diagnostic_id is None:
        return None
    if not isinstance(diagnostic_id, str):
        raise ValueError("Invalid diagnostic ID.")

    canonical_id = diagnostic_id.strip().upper()
    if (
        len(canonical_id) != 26
        or canonical_id[0] not in "01234567"
        or any(character not in _CROCKFORD_ULID_ALPHABET for character in canonical_id)
    ):
        raise ValueError("Invalid diagnostic ID.") from None
    return canonical_id
