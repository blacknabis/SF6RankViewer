"""Ingestion invariants."""

from sf6viewer.domain.errors import error_from_code


def ensure_completed_counts(
    raw: int, normalized: int, duplicate: int, quarantined: int
) -> None:
    """Validate that every received record is accounted for exactly once."""
    counts = (raw, normalized, duplicate, quarantined)
    if (
        any(type(count) is not int for count in counts)
        or any(count < 0 for count in counts)
        or raw != normalized + duplicate + quarantined
    ):
        raise error_from_code("INGESTION.COUNT_MISMATCH")
