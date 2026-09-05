"""Recovery-attempt linkage mapping."""

from sqlalchemy import ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from sf6viewer.infrastructure.db.models.base import Base


class RecoveryLinkModel(Base):
    """Links a REPROCESS job to its original ingestion run."""

    __tablename__ = "recovery_links"
    __table_args__ = (
        UniqueConstraint("job_id", "ingestion_id", name="uq_recovery_links_job_ingestion"),
        Index("ix_recovery_links_ingestion_id", "ingestion_id"),
    )

    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.id", name="fk_recovery_links_job_id"), primary_key=True
    )
    ingestion_id: Mapped[str] = mapped_column(
        ForeignKey("ingestion_runs.id", name="fk_recovery_links_ingestion_id"), nullable=False
    )
    attempted_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
