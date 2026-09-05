"""Immutable raw-evidence mapping."""

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from sf6viewer.infrastructure.db.models.base import Base


class RawRecordModel(Base):
    """A captured upstream or legacy payload."""

    __tablename__ = "raw_records"
    __table_args__ = (
        CheckConstraint("ordinal >= 0", name="ck_raw_records_ordinal_nonnegative"),
        CheckConstraint(
            "record_type IN ('PROFILE', 'MATCH', 'LEGACY_PLAYER', 'LEGACY_MATCH')",
            name="ck_raw_records_record_type",
        ),
        CheckConstraint(
            "length(payload_sha256) = 64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'",
            name="ck_raw_records_payload_sha256_lower_hex",
        ),
        CheckConstraint(
            "disposition IN ('PENDING', 'NORMALIZED', 'DUPLICATE', 'QUARANTINED')",
            name="ck_raw_records_disposition",
        ),
        CheckConstraint(
            "(disposition = 'PENDING' AND disposed_at_ms IS NULL) OR "
            "(disposition != 'PENDING' AND disposed_at_ms IS NOT NULL)",
            name="ck_raw_records_disposition_timestamp",
        ),
        UniqueConstraint("ingestion_id", "ordinal", name="uq_raw_records_ingestion_ordinal"),
        Index("ix_raw_records_ingestion_id", "ingestion_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    ingestion_id: Mapped[str] = mapped_column(
        ForeignKey("ingestion_runs.id", name="fk_raw_records_ingestion_id"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    record_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_key: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    disposition: Mapped[str] = mapped_column(Text, nullable=False)
    disposed_at_ms: Mapped[int | None] = mapped_column(Integer)
