"""Create the v2 Foundation SQLite schema.

Revision ID: 0001_foundation
Revises: None
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0001_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the complete Foundation physical schema without triggers."""
    op.create_table(
        "schema_meta",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("created_at_ms", sa.Integer(), nullable=False),
        sa.Column("updated_at_ms", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_schema_meta_singleton_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_code", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("main_character", sa.Text(), nullable=True),
        sa.Column("rank_name", sa.Text(), nullable=True),
        sa.Column("current_mr", sa.Integer(), nullable=True),
        sa.Column("current_lp", sa.Integer(), nullable=True),
        sa.Column("auth_state", sa.Text(), nullable=False),
        sa.Column("created_at_ms", sa.Integer(), nullable=False),
        sa.Column("updated_at_ms", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_accounts_singleton_id"),
        sa.CheckConstraint(
            "length(user_code) = 10 AND user_code GLOB "
            "'[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]'",
            name="ck_accounts_user_code_canonical",
        ),
        sa.CheckConstraint("current_mr IS NULL OR current_mr >= 0", name="ck_accounts_current_mr_nonnegative"),
        sa.CheckConstraint("current_lp IS NULL OR current_lp >= 0", name="ck_accounts_current_lp_nonnegative"),
        sa.CheckConstraint(
            "auth_state IN ('MISSING', 'VALID', 'EXPIRED', 'MISMATCH')",
            name="ck_accounts_auth_state",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_code", name="uq_accounts_user_code"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=True),
        sa.Column("requested_at_ms", sa.Integer(), nullable=False),
        sa.Column("started_at_ms", sa.Integer(), nullable=True),
        sa.Column("finished_at_ms", sa.Integer(), nullable=True),
        sa.Column("progress_current", sa.Integer(), nullable=True),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("diagnostic_id", sa.Text(), nullable=True),
        sa.Column("summary_json", sa.Text(), nullable=True),
        sa.CheckConstraint("type IN ('LOGIN', 'COLLECT', 'MIGRATE', 'REPROCESS')", name="ck_jobs_type"),
        sa.CheckConstraint("reason IN ('STARTUP', 'MANUAL', 'SCHEDULED', 'RECOVERY')", name="ck_jobs_reason"),
        sa.CheckConstraint(
            "state IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'SUCCEEDED_WITH_WARNINGS', "
            "'FAILED', 'CANCELLED', 'INTERRUPTED')",
            name="ck_jobs_state",
        ),
        sa.CheckConstraint("summary_json IS NULL OR json_valid(summary_json)", name="ck_jobs_summary_json"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_state_requested_at_ms", "jobs", ["state", "requested_at_ms"], unique=False)
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("started_at_ms", sa.Integer(), nullable=False),
        sa.Column("finished_at_ms", sa.Integer(), nullable=True),
        sa.Column("raw_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("normalized_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quarantine_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("diagnostic_id", sa.Text(), nullable=True),
        sa.CheckConstraint("kind IN ('LIVE', 'LEGACY_IMPORT', 'REPROCESS')", name="ck_ingestion_runs_kind"),
        sa.CheckConstraint(
            "state IN ('FETCHING', 'RAW_COMMITTED', 'NORMALIZING', 'COMPLETED', "
            "'COMPLETED_WITH_WARNINGS', 'FAILED', 'INTERRUPTED')",
            name="ck_ingestion_runs_state",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_ingestion_runs_account_id"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name="fk_ingestion_runs_job_id"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_ingestion_runs_job_id"),
    )
    op.create_index("ix_ingestion_runs_account_id", "ingestion_runs", ["account_id"], unique=False)
    op.create_table(
        "raw_records",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("ingestion_id", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("record_type", sa.Text(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.LargeBinary(), nullable=False),
        sa.Column("payload_sha256", sa.Text(), nullable=False),
        sa.Column("fetched_at_ms", sa.Integer(), nullable=False),
        sa.Column("disposition", sa.Text(), nullable=False),
        sa.Column("disposed_at_ms", sa.Integer(), nullable=True),
        sa.CheckConstraint("ordinal >= 0", name="ck_raw_records_ordinal_nonnegative"),
        sa.CheckConstraint(
            "record_type IN ('PROFILE', 'MATCH', 'LEGACY_PLAYER', 'LEGACY_MATCH')",
            name="ck_raw_records_record_type",
        ),
        sa.CheckConstraint(
            "length(payload_sha256) = 64 AND payload_sha256 NOT GLOB '*[^0-9a-f]*'",
            name="ck_raw_records_payload_sha256_lower_hex",
        ),
        sa.CheckConstraint(
            "disposition IN ('PENDING', 'NORMALIZED', 'DUPLICATE', 'QUARANTINED')",
            name="ck_raw_records_disposition",
        ),
        sa.CheckConstraint(
            "(disposition = 'PENDING' AND disposed_at_ms IS NULL) OR "
            "(disposition != 'PENDING' AND disposed_at_ms IS NOT NULL)",
            name="ck_raw_records_disposition_timestamp",
        ),
        sa.ForeignKeyConstraint(["ingestion_id"], ["ingestion_runs.id"], name="fk_raw_records_ingestion_id"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ingestion_id", "ordinal", name="uq_raw_records_ingestion_ordinal"),
    )
    op.create_index("ix_raw_records_ingestion_id", "raw_records", ["ingestion_id"], unique=False)
    op.create_table(
        "profile_snapshots",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("ingestion_id", sa.Text(), nullable=False),
        sa.Column("raw_record_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("character", sa.Text(), nullable=True),
        sa.Column("rank_name", sa.Text(), nullable=True),
        sa.Column("mr", sa.Integer(), nullable=True),
        sa.Column("lp", sa.Integer(), nullable=True),
        sa.Column("observed_at_ms", sa.Integer(), nullable=False),
        sa.CheckConstraint("account_id = 1", name="ck_profile_snapshots_account_id"),
        sa.CheckConstraint("mr IS NULL OR mr >= 0", name="ck_profile_snapshots_mr_nonnegative"),
        sa.CheckConstraint("lp IS NULL OR lp >= 0", name="ck_profile_snapshots_lp_nonnegative"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_profile_snapshots_account_id"),
        sa.ForeignKeyConstraint(["ingestion_id"], ["ingestion_runs.id"], name="fk_profile_snapshots_ingestion_id"),
        sa.ForeignKeyConstraint(["raw_record_id"], ["raw_records.id"], name="fk_profile_snapshots_raw_record_id"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("raw_record_id", name="uq_profile_snapshots_raw_record_id"),
    )
    op.create_index("ix_profile_snapshots_account_id", "profile_snapshots", ["account_id"], unique=False)
    op.create_index("ix_profile_snapshots_ingestion_id", "profile_snapshots", ["ingestion_id"], unique=False)
    op.create_table(
        "matches",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("identity_key", sa.Text(), nullable=False),
        sa.Column("identity_kind", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("occurred_at_ms", sa.Integer(), nullable=False),
        sa.Column("occurred_at_source", sa.Text(), nullable=False),
        sa.Column("my_character", sa.Text(), nullable=False),
        sa.Column("my_mr", sa.Integer(), nullable=True),
        sa.Column("my_lp", sa.Integer(), nullable=True),
        sa.Column("opponent_name", sa.Text(), nullable=False),
        sa.Column("opponent_character", sa.Text(), nullable=False),
        sa.Column("opponent_mr", sa.Integer(), nullable=True),
        sa.Column("opponent_lp", sa.Integer(), nullable=True),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("created_at_ms", sa.Integer(), nullable=False),
        sa.CheckConstraint("account_id = 1", name="ck_matches_account_id"),
        sa.CheckConstraint(
            "identity_kind IN ('SOURCE_ID', 'HYDRATION_KEY', 'FALLBACK_GROUP')",
            name="ck_matches_identity_kind",
        ),
        sa.CheckConstraint("my_mr IS NULL OR my_mr >= 0", name="ck_matches_my_mr_nonnegative"),
        sa.CheckConstraint("my_lp IS NULL OR my_lp >= 0", name="ck_matches_my_lp_nonnegative"),
        sa.CheckConstraint("opponent_mr IS NULL OR opponent_mr >= 0", name="ck_matches_opponent_mr_nonnegative"),
        sa.CheckConstraint("opponent_lp IS NULL OR opponent_lp >= 0", name="ck_matches_opponent_lp_nonnegative"),
        sa.CheckConstraint("result IN ('WIN', 'LOSE', 'DRAW')", name="ck_matches_result"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_matches_account_id"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "identity_key", name="uq_matches_account_identity_key"),
    )
    op.create_index("ix_matches_account_occurred_at_ms", "matches", ["account_id", "occurred_at_ms"], unique=False)
    op.create_table(
        "match_observations",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("match_id", sa.Text(), nullable=False),
        sa.Column("raw_record_id", sa.Text(), nullable=False),
        sa.Column("ingestion_id", sa.Text(), nullable=False),
        sa.Column("observed_content_sha256", sa.Text(), nullable=False),
        sa.Column("observed_at_ms", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["ingestion_id"], ["ingestion_runs.id"], name="fk_match_observations_ingestion_id"),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], name="fk_match_observations_match_id"),
        sa.ForeignKeyConstraint(["raw_record_id"], ["raw_records.id"], name="fk_match_observations_raw_record_id"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("raw_record_id", name="uq_match_observations_raw_record_id"),
    )
    op.create_index("ix_match_observations_match_id", "match_observations", ["match_id"], unique=False)
    op.create_index("ix_match_observations_ingestion_id", "match_observations", ["ingestion_id"], unique=False)
    op.create_table(
        "quarantine_records",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("raw_record_id", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("field_errors_json", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at_ms", sa.Integer(), nullable=False),
        sa.Column("resolved_at_ms", sa.Integer(), nullable=True),
        sa.Column("resolution_match_id", sa.Text(), nullable=True),
        sa.CheckConstraint("field_errors_json IS NULL OR json_valid(field_errors_json)", name="ck_quarantine_records_field_errors_json"),
        sa.CheckConstraint("status IN ('OPEN', 'RESOLVED', 'IGNORED')", name="ck_quarantine_records_status"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_quarantine_records_account_id"),
        sa.ForeignKeyConstraint(["raw_record_id"], ["raw_records.id"], name="fk_quarantine_records_raw_record_id"),
        sa.ForeignKeyConstraint(["resolution_match_id"], ["matches.id"], name="fk_quarantine_records_resolution_match_id"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("raw_record_id", name="uq_quarantine_records_raw_record_id"),
    )
    op.create_index("ix_quarantine_records_account_id", "quarantine_records", ["account_id"], unique=False)
    op.create_index("ix_quarantine_records_resolution_match_id", "quarantine_records", ["resolution_match_id"], unique=False)
    op.create_table(
        "legacy_sources",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("source_logical_sha256", sa.Text(), nullable=False),
        sa.Column("source_schema_signature", sa.Text(), nullable=False),
        sa.Column("source_path_hint", sa.Text(), nullable=True),
        sa.Column("backup_relpath", sa.Text(), nullable=False),
        sa.Column("backup_sha256", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("started_at_ms", sa.Integer(), nullable=True),
        sa.Column("finished_at_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("diagnostic_id", sa.Text(), nullable=True),
        sa.Column("report_json", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "state IN ('DISCOVERED', 'BACKED_UP', 'IMPORTING', 'VERIFIED', 'COMPLETED', 'FAILED')",
            name="ck_legacy_sources_state",
        ),
        sa.CheckConstraint("report_json IS NULL OR json_valid(report_json)", name="ck_legacy_sources_report_json"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_logical_sha256", name="uq_legacy_sources_source_logical_sha256"),
    )
    op.create_table(
        "legacy_rows",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("table_name", sa.Text(), nullable=False),
        sa.Column("legacy_pk", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("raw_payload", sa.LargeBinary(), nullable=False),
        sa.Column("canonical_sha256", sa.Text(), nullable=False),
        sa.Column("disposition", sa.Text(), nullable=False),
        sa.Column("raw_record_id", sa.Text(), nullable=True),
        sa.Column("match_id", sa.Text(), nullable=True),
        sa.Column("quarantine_id", sa.Text(), nullable=True),
        sa.CheckConstraint("table_name IN ('players', 'matches')", name="ck_legacy_rows_table_name"),
        sa.CheckConstraint(
            "disposition IN ('PENDING', 'ACTIVE_ACCOUNT', 'NORMALIZED', 'DUPLICATE', "
            "'QUARANTINED', 'PROVENANCE_ONLY')",
            name="ck_legacy_rows_disposition",
        ),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], name="fk_legacy_rows_match_id"),
        sa.ForeignKeyConstraint(["quarantine_id"], ["quarantine_records.id"], name="fk_legacy_rows_quarantine_id"),
        sa.ForeignKeyConstraint(["raw_record_id"], ["raw_records.id"], name="fk_legacy_rows_raw_record_id"),
        sa.ForeignKeyConstraint(["source_id"], ["legacy_sources.id"], name="fk_legacy_rows_source_id"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "table_name", "legacy_pk", "ordinal", name="uq_legacy_rows_source_table_pk_ordinal"),
    )
    op.create_index("ix_legacy_rows_source_id", "legacy_rows", ["source_id"], unique=False)
    op.create_index("ix_legacy_rows_raw_record_id", "legacy_rows", ["raw_record_id"], unique=False)
    op.create_index("ix_legacy_rows_match_id", "legacy_rows", ["match_id"], unique=False)
    op.create_index("ix_legacy_rows_quarantine_id", "legacy_rows", ["quarantine_id"], unique=False)
    op.create_table(
        "recovery_links",
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("ingestion_id", sa.Text(), nullable=False),
        sa.Column("attempted_at_ms", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["ingestion_id"], ["ingestion_runs.id"], name="fk_recovery_links_ingestion_id"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], name="fk_recovery_links_job_id"),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint("job_id", "ingestion_id", name="uq_recovery_links_job_ingestion"),
    )
    op.create_index("ix_recovery_links_ingestion_id", "recovery_links", ["ingestion_id"], unique=False)
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("auto_collect_enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("collection_interval_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("collection_limit", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("last_window_json", sa.Text(), nullable=True),
        sa.Column("onboarding_step", sa.Text(), nullable=True),
        sa.Column("updated_at_ms", sa.Integer(), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_settings_singleton_id"),
        sa.CheckConstraint(
            "collection_interval_seconds BETWEEN 30 AND 900",
            name="ck_settings_collection_interval_seconds_range",
        ),
        sa.CheckConstraint("collection_limit BETWEEN 1 AND 100", name="ck_settings_collection_limit_range"),
        sa.CheckConstraint("last_window_json IS NULL OR json_valid(last_window_json)", name="ck_settings_last_window_json"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Drop Foundation tables in reverse dependency order."""
    op.drop_table("settings")
    op.drop_index("ix_recovery_links_ingestion_id", table_name="recovery_links")
    op.drop_table("recovery_links")
    op.drop_index("ix_legacy_rows_quarantine_id", table_name="legacy_rows")
    op.drop_index("ix_legacy_rows_match_id", table_name="legacy_rows")
    op.drop_index("ix_legacy_rows_raw_record_id", table_name="legacy_rows")
    op.drop_index("ix_legacy_rows_source_id", table_name="legacy_rows")
    op.drop_table("legacy_rows")
    op.drop_table("legacy_sources")
    op.drop_index("ix_quarantine_records_resolution_match_id", table_name="quarantine_records")
    op.drop_index("ix_quarantine_records_account_id", table_name="quarantine_records")
    op.drop_table("quarantine_records")
    op.drop_index("ix_match_observations_ingestion_id", table_name="match_observations")
    op.drop_index("ix_match_observations_match_id", table_name="match_observations")
    op.drop_table("match_observations")
    op.drop_index("ix_profile_snapshots_ingestion_id", table_name="profile_snapshots")
    op.drop_index("ix_profile_snapshots_account_id", table_name="profile_snapshots")
    op.drop_table("profile_snapshots")
    op.drop_index("ix_matches_account_occurred_at_ms", table_name="matches")
    op.drop_table("matches")
    op.drop_index("ix_raw_records_ingestion_id", table_name="raw_records")
    op.drop_table("raw_records")
    op.drop_index("ix_ingestion_runs_account_id", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
    op.drop_index("ix_jobs_state_requested_at_ms", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("accounts")
    op.drop_table("schema_meta")
