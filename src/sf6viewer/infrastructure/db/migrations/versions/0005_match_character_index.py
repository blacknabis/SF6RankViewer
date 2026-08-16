"""Add composite index for character-based match querying.

Revision ID: 0005_match_character_index
Revises: 0004_auto_collection_control
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_match_character_index"
down_revision: str | None = "0004_auto_collection_control"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add index for fast character-filtered overlay lookups."""
    op.create_index(
        "ix_matches_account_char_occurred_at_ms",
        "matches",
        ["account_id", "my_character", "occurred_at_ms"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the character-filtered match index."""
    op.drop_index("ix_matches_account_char_occurred_at_ms", table_name="matches")
