"""Read-only local HTTP API used by the desktop UI and OBS browser sources.

``create_read_api`` deliberately accepts an already-configured SQLAlchemy session
factory.  The process bootstrap is responsible for binding its ASGI server only to
the IPv4/IPv6 loopback interfaces; this module does not configure CORS or provide
any mutation endpoints.  Responses intentionally exclude raw evidence, job
summaries, and authentication material so an OBS browser source can safely read
this API without gaining access to private captured payloads.
"""

from collections.abc import Callable, Iterator
from typing import Annotated, Literal, cast

from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sf6viewer.infrastructure.db.models import (
    IngestionRunModel,
    JobModel,
    MatchModel,
    ProfileSnapshotModel,
    QuarantineRecordModel,
)

SessionFactory = Callable[[], Session]

PageNumber = Annotated[int, Query(ge=1, le=1_000, description="One-based page number.")]
PageSize = Annotated[int, Query(ge=1, le=100, description="Maximum records returned per page.")]

MatchResult = Literal["WIN", "LOSE", "DRAW"]
JobState = Literal[
    "QUEUED",
    "RUNNING",
    "SUCCEEDED",
    "SUCCEEDED_WITH_WARNINGS",
    "FAILED",
    "CANCELLED",
    "INTERRUPTED",
]
IngestionState = Literal[
    "FETCHING",
    "RAW_COMMITTED",
    "NORMALIZING",
    "COMPLETED",
    "COMPLETED_WITH_WARNINGS",
    "FAILED",
    "INTERRUPTED",
]
QuarantineStatus = Literal["OPEN", "RESOLVED", "IGNORED"]


class ApiModel(BaseModel):
    """Strict, JSON-only API base model that rejects accidental extra output fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PageMetadata(ApiModel):
    """Bounded offset-page metadata shared by historical read endpoints."""

    page: int = Field(ge=1, le=1_000)
    page_size: int = Field(ge=1, le=100)
    total: int = Field(ge=0)


class MatchResponse(ApiModel):
    """Public normalized match fields; canonical hashes and raw payloads stay private."""

    id: str
    occurred_at_ms: int
    occurred_at_source: str
    my_character: str
    my_mr: int | None
    my_lp: int | None
    opponent_name: str
    opponent_character: str
    opponent_mr: int | None
    opponent_lp: int | None
    result: MatchResult


class ProfileSnapshotResponse(ApiModel):
    """A normalized player profile observation without its raw source record."""

    id: str
    display_name: str | None
    character: str | None
    rank_name: str | None
    mr: int | None
    lp: int | None
    observed_at_ms: int


class IngestionRunResponse(ApiModel):
    """Progress and safe aggregate counts for a raw-first collection attempt."""

    id: str
    job_id: str
    kind: Literal["LIVE", "LEGACY_IMPORT", "REPROCESS"]
    parser_version: str
    state: IngestionState
    started_at_ms: int
    finished_at_ms: int | None
    raw_count: int
    normalized_count: int
    duplicate_count: int
    quarantine_count: int
    error_code: str | None
    diagnostic_id: str | None


class JobResponse(ApiModel):
    """Durable job state without its unbounded or potentially private summary payload."""

    id: str
    type: Literal["LOGIN", "COLLECT", "MIGRATE", "REPROCESS"]
    reason: Literal["STARTUP", "MANUAL", "SCHEDULED", "RECOVERY"]
    state: JobState
    phase: str | None
    requested_at_ms: int
    started_at_ms: int | None
    finished_at_ms: int | None
    progress_current: int | None
    progress_total: int | None
    error_code: str | None
    diagnostic_id: str | None


class QuarantineResponse(ApiModel):
    """Review-safe quarantine metadata without raw record references or field values."""

    id: str
    reason_code: str
    status: QuarantineStatus
    created_at_ms: int
    resolved_at_ms: int | None
    resolution_match_id: str | None


class MatchPage(ApiModel):
    """Page of matches ordered newest first, then by immutable identifier."""

    items: tuple[MatchResponse, ...]
    page: PageMetadata


class ProfileSnapshotPage(ApiModel):
    """Page of profile snapshots ordered by observation recency."""

    items: tuple[ProfileSnapshotResponse, ...]
    page: PageMetadata


class IngestionRunPage(ApiModel):
    """Page of ingestion runs ordered by start time."""

    items: tuple[IngestionRunResponse, ...]
    page: PageMetadata


class JobPage(ApiModel):
    """Page of durable jobs ordered by request time."""

    items: tuple[JobResponse, ...]
    page: PageMetadata


class QuarantinePage(ApiModel):
    """Page of quarantine metadata ordered by creation time."""

    items: tuple[QuarantineResponse, ...]
    page: PageMetadata


class HealthResponse(ApiModel):
    """Minimal liveness/readiness response that exposes no environment details."""

    status: Literal["ok"] = "ok"
    service: Literal["sf6viewer"] = "sf6viewer"


class SystemResponse(ApiModel):
    """Safe local overview for desktop UI startup and empty-state decisions."""

    status: Literal["ok"] = "ok"
    match_count: int = Field(ge=0)
    profile_snapshot_count: int = Field(ge=0)
    open_quarantine_count: int = Field(ge=0)
    running_job_count: int = Field(ge=0)


class ObsResponse(ApiModel):
    """Versioned, stable-shape overlay payload for OBS browser sources.

    Optional sections remain present as ``null`` when no collection data exists,
    allowing an OBS template to bind once and survive first-run empty databases.
    """

    schema_version: Literal["1"] = "1"
    status: Literal["ok"] = "ok"
    profile: ProfileSnapshotResponse | None
    latest_match: MatchResponse | None
    latest_job: JobResponse | None


def _page_metadata(total: int | None, page: int, page_size: int) -> PageMetadata:
    """Return bounded page metadata from a table-specific count query."""

    return PageMetadata(page=page, page_size=page_size, total=int(total or 0))


def _match_response(model: MatchModel) -> MatchResponse:
    return MatchResponse(
        id=model.id,
        occurred_at_ms=model.occurred_at_ms,
        occurred_at_source=model.occurred_at_source,
        my_character=model.my_character,
        my_mr=model.my_mr,
        my_lp=model.my_lp,
        opponent_name=model.opponent_name,
        opponent_character=model.opponent_character,
        opponent_mr=model.opponent_mr,
        opponent_lp=model.opponent_lp,
        result=cast(MatchResult, model.result),
    )


def _profile_response(model: ProfileSnapshotModel) -> ProfileSnapshotResponse:
    return ProfileSnapshotResponse(
        id=model.id,
        display_name=model.display_name,
        character=model.character,
        rank_name=model.rank_name,
        mr=model.mr,
        lp=model.lp,
        observed_at_ms=model.observed_at_ms,
    )


def _ingestion_response(model: IngestionRunModel) -> IngestionRunResponse:
    return IngestionRunResponse(
        id=model.id,
        job_id=model.job_id,
        kind=cast(Literal["LIVE", "LEGACY_IMPORT", "REPROCESS"], model.kind),
        parser_version=model.parser_version,
        state=cast(IngestionState, model.state),
        started_at_ms=model.started_at_ms,
        finished_at_ms=model.finished_at_ms,
        raw_count=model.raw_count,
        normalized_count=model.normalized_count,
        duplicate_count=model.duplicate_count,
        quarantine_count=model.quarantine_count,
        error_code=model.error_code,
        diagnostic_id=model.diagnostic_id,
    )


def _job_response(model: JobModel) -> JobResponse:
    return JobResponse(
        id=model.id,
        type=cast(Literal["LOGIN", "COLLECT", "MIGRATE", "REPROCESS"], model.type),
        reason=cast(Literal["STARTUP", "MANUAL", "SCHEDULED", "RECOVERY"], model.reason),
        state=cast(JobState, model.state),
        phase=model.phase,
        requested_at_ms=model.requested_at_ms,
        started_at_ms=model.started_at_ms,
        finished_at_ms=model.finished_at_ms,
        progress_current=model.progress_current,
        progress_total=model.progress_total,
        error_code=model.error_code,
        diagnostic_id=model.diagnostic_id,
    )


def _quarantine_response(model: QuarantineRecordModel) -> QuarantineResponse:
    return QuarantineResponse(
        id=model.id,
        reason_code=model.reason_code,
        status=cast(QuarantineStatus, model.status),
        created_at_ms=model.created_at_ms,
        resolved_at_ms=model.resolved_at_ms,
        resolution_match_id=model.resolution_match_id,
    )


def create_read_api(session_factory: SessionFactory) -> FastAPI:
    """Create the v2 local read API.

    The caller must serve this ASGI application on a loopback address only.  No
    write route, raw-evidence route, authentication route, CORS middleware, or
    interactive documentation endpoint is registered here by design.
    """

    app = FastAPI(
        title="SF6Viewer Local Read API",
        version="1",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        debug=False,
    )

    def get_session() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    @app.get("/api/v1/health", response_model=HealthResponse)
    def health(session: Annotated[Session, Depends(get_session)]) -> HealthResponse:
        """Verify the injected database session can execute a harmless read query."""

        session.scalar(select(1))
        return HealthResponse()

    @app.get("/api/v1/system", response_model=SystemResponse)
    def system_status(session: Annotated[Session, Depends(get_session)]) -> SystemResponse:
        """Provide aggregate safe state for the desktop application start screen."""

        return SystemResponse(
            match_count=int(session.scalar(select(func.count()).select_from(MatchModel)) or 0),
            profile_snapshot_count=int(
                session.scalar(select(func.count()).select_from(ProfileSnapshotModel)) or 0
            ),
            open_quarantine_count=int(
                session.scalar(
                    select(func.count())
                    .select_from(QuarantineRecordModel)
                    .where(QuarantineRecordModel.status == "OPEN")
                )
                or 0
            ),
            running_job_count=int(
                session.scalar(
                    select(func.count())
                    .select_from(JobModel)
                    .where(JobModel.state.in_(("QUEUED", "RUNNING")))
                )
                or 0
            ),
        )

    @app.get("/api/v1/matches/latest", response_model=MatchPage)
    def latest_matches(
        session: Annotated[Session, Depends(get_session)],
        page: PageNumber = 1,
        page_size: PageSize = 25,
    ) -> MatchPage:
        """List canonical matches, newest first, with deterministic tie-breaking."""

        statement = select(MatchModel).order_by(MatchModel.occurred_at_ms.desc(), MatchModel.id.desc())
        records = session.scalars(
            statement.limit(page_size).offset((page - 1) * page_size)
        ).all()
        return MatchPage(
            items=tuple(_match_response(record) for record in records),
            page=_page_metadata(
                session.scalar(select(func.count()).select_from(MatchModel)), page, page_size
            ),
        )

    @app.get("/api/v1/profile-snapshots", response_model=ProfileSnapshotPage)
    def profile_snapshots(
        session: Annotated[Session, Depends(get_session)],
        page: PageNumber = 1,
        page_size: PageSize = 25,
    ) -> ProfileSnapshotPage:
        """List player profile observations from newest to oldest."""

        statement = select(ProfileSnapshotModel).order_by(
            ProfileSnapshotModel.observed_at_ms.desc(), ProfileSnapshotModel.id.desc()
        )
        records = session.scalars(
            statement.limit(page_size).offset((page - 1) * page_size)
        ).all()
        return ProfileSnapshotPage(
            items=tuple(_profile_response(record) for record in records),
            page=_page_metadata(
                session.scalar(select(func.count()).select_from(ProfileSnapshotModel)), page, page_size
            ),
        )

    @app.get("/api/v1/ingestion-runs", response_model=IngestionRunPage)
    def ingestion_runs(
        session: Annotated[Session, Depends(get_session)],
        page: PageNumber = 1,
        page_size: PageSize = 25,
    ) -> IngestionRunPage:
        """List collection/import attempts with safe aggregate disposition counts."""

        statement = select(IngestionRunModel).order_by(
            IngestionRunModel.started_at_ms.desc(), IngestionRunModel.id.desc()
        )
        records = session.scalars(
            statement.limit(page_size).offset((page - 1) * page_size)
        ).all()
        return IngestionRunPage(
            items=tuple(_ingestion_response(record) for record in records),
            page=_page_metadata(
                session.scalar(select(func.count()).select_from(IngestionRunModel)), page, page_size
            ),
        )

    @app.get("/api/v1/jobs", response_model=JobPage)
    def jobs(
        session: Annotated[Session, Depends(get_session)],
        page: PageNumber = 1,
        page_size: PageSize = 25,
    ) -> JobPage:
        """List durable background job history without exposing summary JSON."""

        statement = select(JobModel).order_by(JobModel.requested_at_ms.desc(), JobModel.id.desc())
        records = session.scalars(
            statement.limit(page_size).offset((page - 1) * page_size)
        ).all()
        return JobPage(
            items=tuple(_job_response(record) for record in records),
            page=_page_metadata(
                session.scalar(select(func.count()).select_from(JobModel)), page, page_size
            ),
        )

    @app.get("/api/v1/quarantine", response_model=QuarantinePage)
    def quarantine_records(
        session: Annotated[Session, Depends(get_session)],
        page: PageNumber = 1,
        page_size: PageSize = 25,
    ) -> QuarantinePage:
        """List safe rejection metadata for review; raw values and field error JSON stay private."""

        statement = select(QuarantineRecordModel).order_by(
            QuarantineRecordModel.created_at_ms.desc(), QuarantineRecordModel.id.desc()
        )
        records = session.scalars(
            statement.limit(page_size).offset((page - 1) * page_size)
        ).all()
        return QuarantinePage(
            items=tuple(_quarantine_response(record) for record in records),
            page=_page_metadata(
                session.scalar(select(func.count()).select_from(QuarantineRecordModel)),
                page,
                page_size,
            ),
        )

    @app.get("/api/v1/obs", response_model=ObsResponse)
    def obs_overlay(session: Annotated[Session, Depends(get_session)]) -> ObsResponse:
        """Return a stable-shape, overlay-safe snapshot for a local OBS browser source."""

        latest_profile = session.scalar(
            select(ProfileSnapshotModel).order_by(
                ProfileSnapshotModel.observed_at_ms.desc(), ProfileSnapshotModel.id.desc()
            ).limit(1)
        )
        latest_match = session.scalar(
            select(MatchModel).order_by(MatchModel.occurred_at_ms.desc(), MatchModel.id.desc()).limit(1)
        )
        latest_job = session.scalar(
            select(JobModel).order_by(JobModel.requested_at_ms.desc(), JobModel.id.desc()).limit(1)
        )
        return ObsResponse(
            profile=_profile_response(latest_profile) if latest_profile is not None else None,
            latest_match=_match_response(latest_match) if latest_match is not None else None,
            latest_job=_job_response(latest_job) if latest_job is not None else None,
        )

    return app
