"""Legacy-source mapping."""

from sqlalchemy import CheckConstraint, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from sf6viewer.infrastructure.db.models.base import Base


class LegacySourceModel(Base):
    """One read-only v1 source snapshot and its backup evidence."""

    __tablename__ = "legacy_sources"
    __table_args__ = (
        CheckConstraint(
            "state IN ('DISCOVERED', 'BACKED_UP', 'IMPORTING', 'VERIFIED', 'COMPLETED', 'FAILED')",
            name="ck_legacy_sources_state",
        ),
        CheckConstraint("report_json IS NULL OR json_valid(report_json)", name="ck_legacy_sources_report_json"),
        UniqueConstraint("source_logical_sha256", name="uq_legacy_sources_source_logical_sha256"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_logical_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    source_schema_signature: Mapped[str] = mapped_column(Text, nullable=False)
    source_path_hint: Mapped[str | None] = mapped_column(Text)
    backup_relpath: Mapped[str] = mapped_column(Text, nullable=False)
    backup_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    started_at_ms: Mapped[int | None] = mapped_column(Integer)
    finished_at_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(Text)
    diagnostic_id: Mapped[str | None] = mapped_column(Text)
    report_json: Mapped[str | None] = mapped_column(Text)
