"""Tests for job lifecycle transitions."""

from itertools import product
from types import MappingProxyType

import pytest

from sf6viewer.domain.errors import DomainError
from sf6viewer.domain.job import ALLOWED_TRANSITIONS, JobState, ensure_transition

EXPECTED_TRANSITIONS = {
    JobState.QUEUED: frozenset({JobState.RUNNING, JobState.INTERRUPTED}),
    JobState.RUNNING: frozenset(
        {
            JobState.SUCCEEDED,
            JobState.SUCCEEDED_WITH_WARNINGS,
            JobState.FAILED,
            JobState.CANCELLED,
            JobState.INTERRUPTED,
        }
    ),
    JobState.SUCCEEDED: frozenset(),
    JobState.SUCCEEDED_WITH_WARNINGS: frozenset(),
    JobState.FAILED: frozenset(),
    JobState.CANCELLED: frozenset(),
    JobState.INTERRUPTED: frozenset(),
}


def test_job_state_has_exactly_the_defined_lifecycle_values() -> None:
    assert list(JobState) == [
        JobState.QUEUED,
        JobState.RUNNING,
        JobState.SUCCEEDED,
        JobState.SUCCEEDED_WITH_WARNINGS,
        JobState.FAILED,
        JobState.CANCELLED,
        JobState.INTERRUPTED,
    ]


def test_transition_table_is_explicit_and_complete() -> None:
    assert ALLOWED_TRANSITIONS == EXPECTED_TRANSITIONS
    assert all(isinstance(targets, frozenset) for targets in ALLOWED_TRANSITIONS.values())


def test_transition_table_is_read_only() -> None:
    assert isinstance(ALLOWED_TRANSITIONS, MappingProxyType)

    with pytest.raises(TypeError):
        ALLOWED_TRANSITIONS[JobState.QUEUED] = frozenset()  # type: ignore[index]


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (current, target)
        for current, target in product(JobState, repeat=2)
        if target in EXPECTED_TRANSITIONS[current]
    ],
)
def test_ensure_transition_allows_every_permitted_pair(
    current: JobState, target: JobState
) -> None:
    assert ensure_transition(current, target) is None


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (current, target)
        for current, target in product(JobState, repeat=2)
        if target not in EXPECTED_TRANSITIONS[current]
    ],
)
def test_ensure_transition_rejects_every_other_pair(current: JobState, target: JobState) -> None:
    with pytest.raises(DomainError) as exc_info:
        ensure_transition(current, target)

    assert exc_info.value.code == "JOB.INVALID_TRANSITION"
