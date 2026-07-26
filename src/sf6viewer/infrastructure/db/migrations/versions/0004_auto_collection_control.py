"""Make automatic ranked-match collection opt-in and persist its interval.

Revision ID: 0004_auto_collection_control
Revises: 0003_match_reset_baseline
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_auto_collection_control"
down_revision: str | None = "0003_match_reset_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Disable the previously unused automatic setting for existing installs.

    V2 exposed no control for this field before this revision, so existing
    ``true`` values do not represent an explicit user choice.  Turning it off
    prevents a newly updated app from unexpectedly opening Chrome or polling
    Buckler before the player starts a ranked-game collection session.
    """
    with op.batch_alter_table("settings") as batch_op:
        batch_op.alter_column(
            "auto_collect_enabled",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.text("0"),
        )
        batch_op.alter_column(
            "collection_interval_seconds",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default=sa.text("30"),
        )
    op.execute(
        sa.text(
            "UPDATE settings "
            "SET auto_collect_enabled = 0, collection_interval_seconds = 30"
        )
    )


def downgrade() -> None:
    """Restore only the historical schema defaults, never user state."""
    with op.batch_alter_table("settings") as batch_op:
        batch_op.alter_column(
            "auto_collect_enabled",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.text("1"),
        )
        batch_op.alter_column(
            "collection_interval_seconds",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default=sa.text("60"),
        )
