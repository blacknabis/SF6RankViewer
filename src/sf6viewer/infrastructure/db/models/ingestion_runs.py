"""Ingestion-run mapping."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from sf6viewer.infrastructure.db.models.base import Base


class IngestionRunModel(Base):
    """One raw-first ingestion attempt."""

    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint("kind IN ('LIVE', 'LEGACY_IMPORT', 'REPROCESS')", name="ck_ingestion_runs_kind"),
        CheckConstraint(
            "state IN ('FETCHING', 'RAW_COMMITTED', 'NORMALIZING', 'COMPLETED', "
            "'COMPLETED_WITH_WARNINGS', 'FAILED', 'INTERRUPTED')",
            name="ck_ingestion_runs_state",
        ),
        UniqueConstraint("job_id", name="uq_ingestion_runs_job_id"),
        Index("ix_ingestion_runs_account_id", "account_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", name="fk_ingestion_runs_job_id"), nullable=False)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", name="fk_ingestion_runs_account_id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    parser_version: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    started_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    finished_at_ms: Mapped[int | None] = mapped_column(Integer)
    raw_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    normalized_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    quarantine_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_code: Mapped[str | None] = mapped_column(Text)
    diagnostic_id: Mapped[str | None] = mapped_column(Text)
