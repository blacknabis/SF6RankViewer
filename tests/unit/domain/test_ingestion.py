"""Tests for ingestion invariants."""

import pytest

from sf6viewer.domain.errors import DomainError
from sf6viewer.domain.ingestion import ensure_completed_counts


@pytest.mark.parametrize("counts", [(0, 0, 0, 0), (10, 7, 2, 1)])
def test_completed_counts_accept_exact_equality(counts: tuple[int, int, int, int]) -> None:
    ensure_completed_counts(*counts)


@pytest.mark.parametrize("counts", [(9, 7, 2, 1), (1, -1, 2, 0), (-1, 0, 0, 0)])
def test_completed_counts_rejects_mismatch_or_negative_values(
    counts: tuple[int, int, int, int],
) -> None:
    with pytest.raises(DomainError) as exc_info:
        ensure_completed_counts(*counts)

    assert exc_info.value.code == "INGESTION.COUNT_MISMATCH"


@pytest.mark.parametrize("counts", [(True, 1, 0, 0), (1.0, 1, 0, 0), (1, 1, 0.0, 0)])
def test_completed_counts_rejects_non_integer_counts(
    counts: tuple[object, object, object, object],
) -> None:
    with pytest.raises(DomainError) as exc_info:
        ensure_completed_counts(*counts)  # type: ignore[arg-type]

    assert exc_info.value.code == "INGESTION.COUNT_MISMATCH"
