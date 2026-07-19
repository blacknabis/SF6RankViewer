"""Normalized match mapping."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from sf6viewer.infrastructure.db.models.base import Base


class MatchModel(Base):
    """An insert-only canonical match fact."""

    __tablename__ = "matches"
    __table_args__ = (
        CheckConstraint("account_id = 1", name="ck_matches_account_id"),
        CheckConstraint(
            "identity_kind IN ('SOURCE_ID', 'HYDRATION_KEY', 'FALLBACK_GROUP')",
            name="ck_matches_identity_kind",
        ),
        CheckConstraint("my_mr IS NULL OR my_mr >= 0", name="ck_matches_my_mr_nonnegative"),
        CheckConstraint("my_lp IS NULL OR my_lp >= 0", name="ck_matches_my_lp_nonnegative"),
        CheckConstraint("opponent_mr IS NULL OR opponent_mr >= 0", name="ck_matches_opponent_mr_nonnegative"),
        CheckConstraint("opponent_lp IS NULL OR opponent_lp >= 0", name="ck_matches_opponent_lp_nonnegative"),
        CheckConstraint("result IN ('WIN', 'LOSE', 'DRAW')", name="ck_matches_result"),
        UniqueConstraint("account_id", "identity_key", name="uq_matches_account_identity_key"),
        Index("ix_matches_account_occurred_at_ms", "account_id", "occurred_at_ms"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", name="fk_matches_account_id"), nullable=False)
    identity_key: Mapped[str] = mapped_column(Text, nullable=False)
    identity_kind: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at_source: Mapped[str] = mapped_column(Text, nullable=False)
    my_character: Mapped[str] = mapped_column(Text, nullable=False)
    my_mr: Mapped[int | None] = mapped_column(Integer)
    my_lp: Mapped[int | None] = mapped_column(Integer)
    opponent_name: Mapped[str] = mapped_column(Text, nullable=False)
    opponent_character: Mapped[str] = mapped_column(Text, nullable=False)
    opponent_mr: Mapped[int | None] = mapped_column(Integer)
    opponent_lp: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[str] = mapped_column(Text, nullable=False)
    created_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
