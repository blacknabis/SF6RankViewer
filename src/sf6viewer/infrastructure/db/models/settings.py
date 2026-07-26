"""Singleton user-settings mapping."""

from sqlalchemy import Boolean, CheckConstraint, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from sf6viewer.infrastructure.db.models.base import Base


class SettingsModel(Base):
    """Locally stored collection preferences."""

    __tablename__ = "settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_settings_singleton_id"),
        CheckConstraint(
            "collection_interval_seconds BETWEEN 30 AND 900",
            name="ck_settings_collection_interval_seconds_range",
        ),
        CheckConstraint(
            "collection_limit BETWEEN 1 AND 100", name="ck_settings_collection_limit_range"
        ),
        CheckConstraint(
            "match_reset_at_ms IS NULL OR match_reset_at_ms >= 0",
            name="ck_settings_match_reset_at_ms_nonnegative",
        ),
        CheckConstraint(
            "last_window_json IS NULL OR json_valid(last_window_json)",
            name="ck_settings_last_window_json",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    auto_collect_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    collection_interval_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("30")
    )
    collection_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("20")
    )
    last_window_json: Mapped[str | None] = mapped_column(Text)
    onboarding_step: Mapped[str | None] = mapped_column(Text)
    match_reset_at_ms: Mapped[int | None] = mapped_column(Integer)
    updated_at_ms: Mapped[int | None] = mapped_column(Integer)
