"""Job lifecycle rules."""

from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType

from sf6viewer.domain.errors import error_from_code


class JobState(Enum):
    """The lifecycle states for an import job."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    SUCCEEDED_WITH_WARNINGS = "SUCCEEDED_WITH_WARNINGS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


ALLOWED_TRANSITIONS: Mapping[JobState, frozenset[JobState]] = MappingProxyType({
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
})


def ensure_transition(current: JobState, target: JobState) -> None:
    """Ensure a job lifecycle transition is permitted."""
    if target not in ALLOWED_TRANSITIONS[current]:
        raise error_from_code("JOB.INVALID_TRANSITION")
