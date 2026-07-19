"""Legacy-row provenance mapping."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, LargeBinary, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from sf6viewer.infrastructure.db.models.base import Base


class LegacyRowModel(Base):
    """One immutable v1 row retained for migration provenance."""

    __tablename__ = "legacy_rows"
    __table_args__ = (
        CheckConstraint("table_name IN ('players', 'matches')", name="ck_legacy_rows_table_name"),
        CheckConstraint(
            "disposition IN ('PENDING', 'ACTIVE_ACCOUNT', 'NORMALIZED', 'DUPLICATE', "
            "'QUARANTINED', 'PROVENANCE_ONLY')",
            name="ck_legacy_rows_disposition",
        ),
        UniqueConstraint("source_id", "table_name", "legacy_pk", "ordinal", name="uq_legacy_rows_source_table_pk_ordinal"),
        Index("ix_legacy_rows_source_id", "source_id"),
        Index("ix_legacy_rows_raw_record_id", "raw_record_id"),
        Index("ix_legacy_rows_match_id", "match_id"),
        Index("ix_legacy_rows_quarantine_id", "quarantine_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("legacy_sources.id", name="fk_legacy_rows_source_id"), nullable=False)
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    legacy_pk: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    canonical_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    disposition: Mapped[str] = mapped_column(Text, nullable=False)
    raw_record_id: Mapped[str | None] = mapped_column(ForeignKey("raw_records.id", name="fk_legacy_rows_raw_record_id"))
    match_id: Mapped[str | None] = mapped_column(ForeignKey("matches.id", name="fk_legacy_rows_match_id"))
    quarantine_id: Mapped[str | None] = mapped_column(ForeignKey("quarantine_records.id", name="fk_legacy_rows_quarantine_id"))
