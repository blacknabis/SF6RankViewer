"""Store a non-destructive match-history reset baseline.

Revision ID: 0003_match_reset_baseline
Revises: 0002_immutability_triggers
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_match_reset_baseline"
down_revision: str | None = "0002_immutability_triggers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the timestamp after which matches are visible in user-facing views."""
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("match_reset_at_ms", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            "ck_settings_match_reset_at_ms_nonnegative",
            "match_reset_at_ms IS NULL OR match_reset_at_ms >= 0",
        )


def downgrade() -> None:
    """Remove the optional match-history reset baseline."""
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_constraint("ck_settings_match_reset_at_ms_nonnegative", type_="check")
        batch_op.drop_column("match_reset_at_ms")
