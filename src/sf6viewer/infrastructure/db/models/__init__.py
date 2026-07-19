"""SQLAlchemy model metadata and mappings."""

from sf6viewer.infrastructure.db.models.accounts import AccountModel
from sf6viewer.infrastructure.db.models.base import Base
from sf6viewer.infrastructure.db.models.ingestion_runs import IngestionRunModel
from sf6viewer.infrastructure.db.models.jobs import JobModel
from sf6viewer.infrastructure.db.models.legacy_rows import LegacyRowModel
from sf6viewer.infrastructure.db.models.legacy_sources import LegacySourceModel
from sf6viewer.infrastructure.db.models.match_observations import MatchObservationModel
from sf6viewer.infrastructure.db.models.matches import MatchModel
from sf6viewer.infrastructure.db.models.profile_snapshots import ProfileSnapshotModel
from sf6viewer.infrastructure.db.models.quarantine_records import QuarantineRecordModel
from sf6viewer.infrastructure.db.models.raw_records import RawRecordModel
from sf6viewer.infrastructure.db.models.recovery_links import RecoveryLinkModel
from sf6viewer.infrastructure.db.models.schema_meta import SchemaMetaModel
from sf6viewer.infrastructure.db.models.settings import SettingsModel

__all__ = [
    "AccountModel",
    "Base",
    "IngestionRunModel",
    "JobModel",
    "LegacyRowModel",
    "LegacySourceModel",
    "MatchModel",
    "MatchObservationModel",
    "ProfileSnapshotModel",
    "QuarantineRecordModel",
    "RawRecordModel",
    "RecoveryLinkModel",
    "SchemaMetaModel",
    "SettingsModel",
]
