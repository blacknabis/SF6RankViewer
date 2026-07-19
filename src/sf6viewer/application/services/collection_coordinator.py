"""In-memory single-flight admission for collection-related jobs.

The coordinator deliberately owns no persistence, browser, or authentication
objects.  Its caller supplies an already-canonical request key and an executor
that performs the actual work after a request has been admitted.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from threading import Lock

from sf6viewer.domain.errors import error_from_code


class CollectionRequestKind(str, Enum):
    """Kinds of work serialized by the collection coordinator."""

    LOGIN = "LOGIN"
    COLLECT = "COLLECT"
    MIGRATE = "MIGRATE"
    REPROCESS = "REPROCESS"


class CollectionAdmission(str, Enum):
    """The outcome of admitting a request."""

    STARTED = "STARTED"
    QUEUED = "QUEUED"
    COALESCED = "COALESCED"


@dataclass(frozen=True, slots=True)
class CanonicalRequestKey:
    """An immutable, caller-produced key used only for request equivalence.

    Callers must derive this from safe canonical inputs, for example a bounded
    collection limit and reason.  Opaque auth or storage values do not belong
    in this value object.
    """

    value: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.value, str)
            or not self.value
            or self.value != self.value.strip()
        ):
            raise ValueError("Request key must be a non-empty canonical string.")


@dataclass(frozen=True, slots=True)
class CollectionRequest:
    """A typed request that can be admitted by the coordinator."""

    job_id: str
    kind: CollectionRequestKind
    key: CanonicalRequestKey

    def __post_init__(self) -> None:
        if (
            not isinstance(self.job_id, str)
            or not self.job_id
            or self.job_id != self.job_id.strip()
        ):
            raise ValueError("Job ID must be a non-empty canonical string.")
        if not isinstance(self.kind, CollectionRequestKind):
            raise TypeError("kind must be a CollectionRequestKind.")
        if not isinstance(self.key, CanonicalRequestKey):
            raise TypeError("key must be a CanonicalRequestKey.")

    def is_equivalent_to(self, other: CollectionRequest) -> bool:
        """Return whether two requests may share a single admitted job."""
        return self.kind is other.kind and self.key == other.key


@dataclass(frozen=True, slots=True)
class CollectionCoordinatorStatus:
    """An immutable snapshot of coordinator-owned request state."""

    active_job_id: str | None
    active_kind: CollectionRequestKind | None
    pending_job_id: str | None
    pending_kind: CollectionRequestKind | None


@dataclass(frozen=True, slots=True)
class CollectionAdmissionResult:
    """The admitted job identity, outcome, and resulting coordinator state."""

    admission: CollectionAdmission
    job_id: str
    status: CollectionCoordinatorStatus


CollectionExecutor = Callable[[CollectionRequest], None]


class CollectionCoordinator:
    """Serialize collection work with one active and one pending request.

    State is protected by a standard lock.  The executor is always invoked
    after that lock has been released, so an executor can safely call
    :meth:`complete` itself and never blocks unrelated status reads.
    """

    def __init__(self, executor: CollectionExecutor) -> None:
        if not callable(executor):
            raise TypeError("executor must be callable.")
        self._executor = executor
        self._lock = Lock()
        self._active: CollectionRequest | None = None
        self._pending: CollectionRequest | None = None

    def admit(self, request: CollectionRequest) -> CollectionAdmissionResult:
        """Start, queue, or coalesce ``request`` without executing under the lock."""
        if not isinstance(request, CollectionRequest):
            raise TypeError("request must be a CollectionRequest.")

        request_to_start: CollectionRequest | None = None
        with self._lock:
            active = self._active
            pending = self._pending
            if active is not None and active.is_equivalent_to(request):
                return self._result(CollectionAdmission.COALESCED, active.job_id)
            if pending is not None and pending.is_equivalent_to(request):
                return self._result(CollectionAdmission.COALESCED, pending.job_id)
            if self._contains_job_id(request.job_id):
                raise ValueError("Job ID is already active or pending.")
            if active is not None and active.kind is CollectionRequestKind.LOGIN:
                if request.kind is CollectionRequestKind.COLLECT:
                    raise error_from_code("JOB.CONFLICT")
            if active is None:
                self._active = request
                request_to_start = request
                result = self._result(CollectionAdmission.STARTED, request.job_id)
            elif pending is None:
                self._pending = request
                result = self._result(CollectionAdmission.QUEUED, request.job_id)
            else:
                raise error_from_code("JOB.QUEUE_FULL")

        if request_to_start is not None:
            self._execute_started(request_to_start)
        return result

    def complete(self, job_id: str) -> CollectionCoordinatorStatus:
        """Complete the active job and atomically promote pending work, if any."""
        job_id = _canonical_job_id(job_id)
        request_to_start: CollectionRequest | None = None
        with self._lock:
            if self._active is None or self._active.job_id != job_id:
                raise ValueError("Unknown or inactive job ID.")
            self._active = self._pending
            self._pending = None
            request_to_start = self._active
            status = self._status()

        if request_to_start is not None:
            self._execute_started(request_to_start)
        return status

    def fail_to_start(self, job_id: str) -> CollectionCoordinatorStatus:
        """Remove a job that could not start and promote its successor safely."""
        job_id = _canonical_job_id(job_id)
        request_to_start: CollectionRequest | None = None
        with self._lock:
            if self._active is not None and self._active.job_id == job_id:
                self._active = self._pending
                self._pending = None
                request_to_start = self._active
            elif self._pending is not None and self._pending.job_id == job_id:
                self._pending = None
            else:
                raise ValueError("Unknown or inactive job ID.")
            status = self._status()

        if request_to_start is not None:
            self._execute_started(request_to_start)
        return status

    def status(self) -> CollectionCoordinatorStatus:
        """Return the current immutable state snapshot."""
        with self._lock:
            return self._status()

    def _execute_started(self, request: CollectionRequest) -> None:
        """Run an admitted request and release it if its executor cannot start."""
        try:
            self._executor(request)
        except Exception:
            try:
                self.fail_to_start(request.job_id)
            except ValueError:
                # A synchronous executor may have completed the job before it failed.
                pass
            raise

    def _contains_job_id(self, job_id: str) -> bool:
        return (self._active is not None and self._active.job_id == job_id) or (
            self._pending is not None and self._pending.job_id == job_id
        )

    def _result(self, admission: CollectionAdmission, job_id: str) -> CollectionAdmissionResult:
        return CollectionAdmissionResult(
            admission=admission,
            job_id=job_id,
            status=self._status(),
        )

    def _status(self) -> CollectionCoordinatorStatus:
        return CollectionCoordinatorStatus(
            active_job_id=self._active.job_id if self._active is not None else None,
            active_kind=self._active.kind if self._active is not None else None,
            pending_job_id=self._pending.job_id if self._pending is not None else None,
            pending_kind=self._pending.kind if self._pending is not None else None,
        )


def _canonical_job_id(job_id: str) -> str:
    if (
        not isinstance(job_id, str)
        or not job_id
        or job_id != job_id.strip()
    ):
        raise ValueError("Job ID must be a non-empty canonical string.")
    return job_id
