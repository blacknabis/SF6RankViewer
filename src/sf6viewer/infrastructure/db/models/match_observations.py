"""Match-observation mapping."""

from sqlalchemy import ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from sf6viewer.infrastructure.db.models.base import Base


class MatchObservationModel(Base):
    """A raw source observation of a canonical match."""

    __tablename__ = "match_observations"
    __table_args__ = (
        UniqueConstraint("raw_record_id", name="uq_match_observations_raw_record_id"),
        Index("ix_match_observations_match_id", "match_id"),
        Index("ix_match_observations_ingestion_id", "ingestion_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    match_id: Mapped[str] = mapped_column(
        ForeignKey("matches.id", name="fk_match_observations_match_id"), nullable=False
    )
    raw_record_id: Mapped[str] = mapped_column(
        ForeignKey("raw_records.id", name="fk_match_observations_raw_record_id"), nullable=False
    )
    ingestion_id: Mapped[str] = mapped_column(
        ForeignKey("ingestion_runs.id", name="fk_match_observations_ingestion_id"), nullable=False
    )
    observed_content_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
