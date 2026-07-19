"""Enforce immutable evidence and one-way evidence dispositions.

Revision ID: 0002_immutability_triggers
Revises: 0001_foundation
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0002_immutability_triggers"
down_revision: str | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Install SQLite guards for immutable evidence rows."""
    op.execute(
        """
        CREATE TRIGGER trg_raw_no_delete
        BEFORE DELETE ON raw_records
        BEGIN
            SELECT RAISE(ABORT, 'RAW_DELETE_FORBIDDEN');
        END;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_raw_single_disposition
        BEFORE UPDATE OF disposition, disposed_at_ms ON raw_records
        WHEN NEW.disposition IS NOT OLD.disposition
          OR NEW.disposed_at_ms IS NOT OLD.disposed_at_ms
        BEGIN
            SELECT CASE
                WHEN OLD.disposition = 'PENDING'
                 AND OLD.disposed_at_ms IS NULL
                 AND NEW.disposition IN ('NORMALIZED', 'DUPLICATE', 'QUARANTINED')
                 AND NEW.disposed_at_ms IS NOT NULL
                THEN NULL
                ELSE RAISE(ABORT, 'RAW_DISPOSITION_INVALID')
            END;
        END;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_raw_immutable_fields
        BEFORE UPDATE OF id, ingestion_id, ordinal, record_type, source_key,
                         payload_json, payload_sha256, fetched_at_ms ON raw_records
        WHEN NEW.id IS NOT OLD.id
          OR NEW.ingestion_id IS NOT OLD.ingestion_id
          OR NEW.ordinal IS NOT OLD.ordinal
          OR NEW.record_type IS NOT OLD.record_type
          OR NEW.source_key IS NOT OLD.source_key
          OR NEW.payload_json IS NOT OLD.payload_json
          OR NEW.payload_sha256 IS NOT OLD.payload_sha256
          OR NEW.fetched_at_ms IS NOT OLD.fetched_at_ms
        BEGIN
            SELECT RAISE(ABORT, 'RAW_IMMUTABLE_FIELD');
        END;
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_match_immutable
        BEFORE UPDATE ON matches
        BEGIN
            SELECT RAISE(ABORT, 'MATCH_IMMUTABLE');
        END;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_match_no_delete
        BEFORE DELETE ON matches
        BEGIN
            SELECT RAISE(ABORT, 'MATCH_IMMUTABLE');
        END;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_profile_snapshot_immutable
        BEFORE UPDATE ON profile_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'PROFILE_SNAPSHOT_IMMUTABLE');
        END;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_profile_snapshot_no_delete
        BEFORE DELETE ON profile_snapshots
        BEGIN
            SELECT RAISE(ABORT, 'PROFILE_SNAPSHOT_IMMUTABLE');
        END;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_observation_immutable
        BEFORE UPDATE ON match_observations
        BEGIN
            SELECT RAISE(ABORT, 'MATCH_OBSERVATION_IMMUTABLE');
        END;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_observation_no_delete
        BEFORE DELETE ON match_observations
        BEGIN
            SELECT RAISE(ABORT, 'MATCH_OBSERVATION_IMMUTABLE');
        END;
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_legacy_row_no_delete
        BEFORE DELETE ON legacy_rows
        BEGIN
            SELECT RAISE(ABORT, 'LEGACY_ROW_DELETE_FORBIDDEN');
        END;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_legacy_row_transition
        BEFORE UPDATE ON legacy_rows
        WHEN NEW.disposition IS NOT OLD.disposition
          OR NEW.raw_record_id IS NOT OLD.raw_record_id
          OR NEW.match_id IS NOT OLD.match_id
          OR NEW.quarantine_id IS NOT OLD.quarantine_id
        BEGIN
            SELECT CASE
                WHEN OLD.disposition = 'PENDING'
                 AND OLD.raw_record_id IS NULL
                 AND OLD.match_id IS NULL
                 AND OLD.quarantine_id IS NULL
                 AND NEW.raw_record_id IS NOT NULL
                 AND (
                    (
                        NEW.table_name = 'players'
                        AND NEW.disposition = 'ACTIVE_ACCOUNT'
                        AND NEW.match_id IS NULL
                        AND NEW.quarantine_id IS NULL
                    )
                    OR (
                        NEW.table_name = 'players'
                        AND NEW.disposition = 'PROVENANCE_ONLY'
                        AND NEW.match_id IS NULL
                        AND NEW.quarantine_id IS NOT NULL
                        AND EXISTS (
                            SELECT 1
                            FROM quarantine_records
                            WHERE id = NEW.quarantine_id
                              AND reason_code = 'LEGACY_NON_ACTIVE_ACCOUNT'
                        )
                    )
                    OR (
                        NEW.table_name = 'players'
                        AND NEW.disposition = 'QUARANTINED'
                        AND NEW.match_id IS NULL
                        AND NEW.quarantine_id IS NOT NULL
                    )
                    OR (
                        NEW.table_name = 'matches'
                        AND NEW.disposition IN ('NORMALIZED', 'DUPLICATE')
                        AND NEW.match_id IS NOT NULL
                        AND NEW.quarantine_id IS NULL
                    )
                    OR (
                        NEW.table_name = 'matches'
                        AND NEW.disposition = 'QUARANTINED'
                        AND NEW.match_id IS NULL
                        AND NEW.quarantine_id IS NOT NULL
                    )
                 )
                THEN NULL
                ELSE RAISE(ABORT, 'LEGACY_ROW_TRANSITION_INVALID')
            END;
        END;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_legacy_row_immutable_fields
        BEFORE UPDATE OF id, source_id, table_name, legacy_pk, ordinal, raw_payload,
                         canonical_sha256 ON legacy_rows
        WHEN NEW.id IS NOT OLD.id
          OR NEW.source_id IS NOT OLD.source_id
          OR NEW.table_name IS NOT OLD.table_name
          OR NEW.legacy_pk IS NOT OLD.legacy_pk
          OR NEW.ordinal IS NOT OLD.ordinal
          OR NEW.raw_payload IS NOT OLD.raw_payload
          OR NEW.canonical_sha256 IS NOT OLD.canonical_sha256
        BEGIN
            SELECT RAISE(ABORT, 'LEGACY_ROW_IMMUTABLE_FIELD');
        END;
        """
    )

    op.execute(
        """
        CREATE TRIGGER trg_quarantine_no_delete
        BEFORE DELETE ON quarantine_records
        BEGIN
            SELECT RAISE(ABORT, 'QUARANTINE_DELETE_FORBIDDEN');
        END;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_quarantine_resolution
        BEFORE UPDATE ON quarantine_records
        WHEN NEW.status IS NOT OLD.status
          OR NEW.resolved_at_ms IS NOT OLD.resolved_at_ms
          OR NEW.resolution_match_id IS NOT OLD.resolution_match_id
        BEGIN
            SELECT CASE
                WHEN OLD.status = 'OPEN'
                 AND OLD.resolved_at_ms IS NULL
                 AND OLD.resolution_match_id IS NULL
                 AND (
                    (
                        NEW.status = 'RESOLVED'
                        AND NEW.resolved_at_ms IS NOT NULL
                        AND NEW.resolution_match_id IS NOT NULL
                    )
                    OR (
                        NEW.status = 'IGNORED'
                        AND NEW.resolved_at_ms IS NOT NULL
                        AND NEW.resolution_match_id IS NULL
                    )
                 )
                THEN NULL
                ELSE RAISE(ABORT, 'QUARANTINE_TRANSITION_INVALID')
            END;
        END;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_quarantine_immutable_fields
        BEFORE UPDATE OF id, raw_record_id, account_id, reason_code, field_errors_json,
                         created_at_ms ON quarantine_records
        WHEN NEW.id IS NOT OLD.id
          OR NEW.raw_record_id IS NOT OLD.raw_record_id
          OR NEW.account_id IS NOT OLD.account_id
          OR NEW.reason_code IS NOT OLD.reason_code
          OR NEW.field_errors_json IS NOT OLD.field_errors_json
          OR NEW.created_at_ms IS NOT OLD.created_at_ms
        BEGIN
            SELECT RAISE(ABORT, 'QUARANTINE_IMMUTABLE_FIELD');
        END;
        """
    )


def downgrade() -> None:
    """Drop immutability triggers before returning to the Foundation schema."""
    op.execute("DROP TRIGGER trg_quarantine_immutable_fields")
    op.execute("DROP TRIGGER trg_quarantine_resolution")
    op.execute("DROP TRIGGER trg_quarantine_no_delete")
    op.execute("DROP TRIGGER trg_legacy_row_immutable_fields")
    op.execute("DROP TRIGGER trg_legacy_row_transition")
    op.execute("DROP TRIGGER trg_legacy_row_no_delete")
    op.execute("DROP TRIGGER trg_observation_no_delete")
    op.execute("DROP TRIGGER trg_observation_immutable")
    op.execute("DROP TRIGGER trg_profile_snapshot_no_delete")
    op.execute("DROP TRIGGER trg_profile_snapshot_immutable")
    op.execute("DROP TRIGGER trg_match_no_delete")
    op.execute("DROP TRIGGER trg_match_immutable")
    op.execute("DROP TRIGGER trg_raw_immutable_fields")
    op.execute("DROP TRIGGER trg_raw_single_disposition")
    op.execute("DROP TRIGGER trg_raw_no_delete")
