"""Profile-snapshot mapping."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from sf6viewer.infrastructure.db.models.base import Base


class ProfileSnapshotModel(Base):
    """An insert-only normalized profile observation."""

    __tablename__ = "profile_snapshots"
    __table_args__ = (
        CheckConstraint("account_id = 1", name="ck_profile_snapshots_account_id"),
        CheckConstraint("mr IS NULL OR mr >= 0", name="ck_profile_snapshots_mr_nonnegative"),
        CheckConstraint("lp IS NULL OR lp >= 0", name="ck_profile_snapshots_lp_nonnegative"),
        UniqueConstraint("raw_record_id", name="uq_profile_snapshots_raw_record_id"),
        Index("ix_profile_snapshots_account_id", "account_id"),
        Index("ix_profile_snapshots_ingestion_id", "ingestion_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", name="fk_profile_snapshots_account_id"), nullable=False
    )
    ingestion_id: Mapped[str] = mapped_column(
        ForeignKey("ingestion_runs.id", name="fk_profile_snapshots_ingestion_id"), nullable=False
    )
    raw_record_id: Mapped[str] = mapped_column(
        ForeignKey("raw_records.id", name="fk_profile_snapshots_raw_record_id"), nullable=False
    )
    display_name: Mapped[str | None] = mapped_column(Text)
    character: Mapped[str | None] = mapped_column(Text)
    rank_name: Mapped[str | None] = mapped_column(Text)
    mr: Mapped[int | None] = mapped_column(Integer)
    lp: Mapped[int | None] = mapped_column(Integer)
    observed_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
