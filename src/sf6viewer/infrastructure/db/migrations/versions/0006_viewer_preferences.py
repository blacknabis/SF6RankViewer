"""Persist in-app viewer display preferences.

Revision ID: 0006_viewer_preferences
Revises: 0005_match_character_index
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_viewer_preferences"
down_revision: str | None = "0005_match_character_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add constrained defaults for the viewer's delta mode and chart range."""
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "viewer_delta_mode",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'session'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "viewer_chart_limit",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("50"),
            )
        )
        batch_op.create_check_constraint(
            "ck_settings_viewer_delta_mode",
            "viewer_delta_mode IN ('session', 'range')",
        )
        batch_op.create_check_constraint(
            "ck_settings_viewer_chart_limit",
            "viewer_chart_limit IN (20, 50, 100)",
        )


def downgrade() -> None:
    """Remove preference checks before dropping their columns."""
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_constraint("ck_settings_viewer_delta_mode", type_="check")
        batch_op.drop_constraint("ck_settings_viewer_chart_limit", type_="check")

    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("viewer_delta_mode")
        batch_op.drop_column("viewer_chart_limit")
