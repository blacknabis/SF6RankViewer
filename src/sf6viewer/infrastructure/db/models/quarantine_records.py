"""Quarantine-record mapping."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from sf6viewer.infrastructure.db.models.base import Base


class QuarantineRecordModel(Base):
    """A safe, reviewable normalization rejection."""

    __tablename__ = "quarantine_records"
    __table_args__ = (
        CheckConstraint("field_errors_json IS NULL OR json_valid(field_errors_json)", name="ck_quarantine_records_field_errors_json"),
        CheckConstraint("status IN ('OPEN', 'RESOLVED', 'IGNORED')", name="ck_quarantine_records_status"),
        UniqueConstraint("raw_record_id", name="uq_quarantine_records_raw_record_id"),
        Index("ix_quarantine_records_account_id", "account_id"),
        Index("ix_quarantine_records_resolution_match_id", "resolution_match_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    raw_record_id: Mapped[str] = mapped_column(ForeignKey("raw_records.id", name="fk_quarantine_records_raw_record_id"), nullable=False)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", name="fk_quarantine_records_account_id"))
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    field_errors_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    resolved_at_ms: Mapped[int | None] = mapped_column(Integer)
    resolution_match_id: Mapped[str | None] = mapped_column(ForeignKey("matches.id", name="fk_quarantine_records_resolution_match_id"))
