"""Background job mapping."""

from sqlalchemy import CheckConstraint, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from sf6viewer.infrastructure.db.models.base import Base


class JobModel(Base):
    """A durable orchestration job."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("type IN ('LOGIN', 'COLLECT', 'MIGRATE', 'REPROCESS')", name="ck_jobs_type"),
        CheckConstraint(
            "reason IN ('STARTUP', 'MANUAL', 'SCHEDULED', 'RECOVERY')", name="ck_jobs_reason"
        ),
        CheckConstraint(
            "state IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'SUCCEEDED_WITH_WARNINGS', "
            "'FAILED', 'CANCELLED', 'INTERRUPTED')",
            name="ck_jobs_state",
        ),
        CheckConstraint("summary_json IS NULL OR json_valid(summary_json)", name="ck_jobs_summary_json"),
        Index("ix_jobs_state_requested_at_ms", "state", "requested_at_ms"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[str | None] = mapped_column(Text)
    requested_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at_ms: Mapped[int | None] = mapped_column(Integer)
    finished_at_ms: Mapped[int | None] = mapped_column(Integer)
    progress_current: Mapped[int | None] = mapped_column(Integer)
    progress_total: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(Text)
    diagnostic_id: Mapped[str | None] = mapped_column(Text)
    summary_json: Mapped[str | None] = mapped_column(Text)
