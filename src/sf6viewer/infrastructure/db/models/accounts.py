"""Account projection mapping."""

from sqlalchemy import CheckConstraint, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from sf6viewer.infrastructure.db.models.base import Base


class AccountModel(Base):
    """The one local account and its current projection."""

    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_accounts_singleton_id"),
        CheckConstraint(
            "length(user_code) = 10 AND user_code GLOB "
            "'[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'",
            name="ck_accounts_user_code_canonical",
        ),
        CheckConstraint(
            "current_mr IS NULL OR current_mr >= 0", name="ck_accounts_current_mr_nonnegative"
        ),
        CheckConstraint(
            "current_lp IS NULL OR current_lp >= 0", name="ck_accounts_current_lp_nonnegative"
        ),
        CheckConstraint(
            "auth_state IN ('MISSING', 'VALID', 'EXPIRED', 'MISMATCH')",
            name="ck_accounts_auth_state",
        ),
        UniqueConstraint("user_code", name="uq_accounts_user_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_code: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    main_character: Mapped[str | None] = mapped_column(Text)
    rank_name: Mapped[str | None] = mapped_column(Text)
    current_mr: Mapped[int | None] = mapped_column(Integer)
    current_lp: Mapped[int | None] = mapped_column(Integer)
    auth_state: Mapped[str] = mapped_column(Text, nullable=False)
    created_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at_ms: Mapped[int] = mapped_column(Integer, nullable=False)
