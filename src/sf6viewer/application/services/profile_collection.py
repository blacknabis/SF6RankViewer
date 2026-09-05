"""Raw-first persistence for one freshly captured Buckler profile snapshot."""

from __future__ import annotations

import hashlib
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from sf6viewer.application.ports.repositories import (
    ProfileSnapshotRecord,
    QuarantineRecord,
    RawRecord,
)
from sf6viewer.application.ports.unit_of_work import UnitOfWork
from sf6viewer.domain.errors import DomainError, error_from_code
from sf6viewer.domain.match import canonical_json

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]
type IdFactory = Callable[[], str]
type Clock = Callable[[], int]


@dataclass(frozen=True, slots=True)
class CollectedRawProfile:
    """Immutable upstream payload captured before any profile interpretation."""

    raw_payload: Mapping[str, JsonValue]
    fetched_at_ms: int
    source_key: str
    _canonical_payload: bytes = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.fetched_at_ms) is not int or self.fetched_at_ms < 0:
            raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
        if not isinstance(self.source_key, str) or not self.source_key.strip():
            raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
        try:
            payload = _freeze_mapping(self.raw_payload)
            canonical_payload = canonical_json(payload)
        except Exception as error:
            raise error_from_code("UPSTREAM.CONTRACT_CHANGED") from error
        object.__setattr__(self, "raw_payload", payload)
        object.__setattr__(self, "_canonical_payload", canonical_payload)

    @property
    def canonical_payload(self) -> bytes:
        """Return stable uncompressed UTF-8 JSON evidence."""
        return self._canonical_payload


@dataclass(frozen=True, slots=True)
class NormalizedProfile:
    """Safe profile projection returned by a parser after raw persistence."""

    display_name: str | None
    character: str | None
    rank_name: str | None
    mr: int | None
    lp: int | None


type ProfileNormalizer = Callable[[Mapping[str, JsonValue]], NormalizedProfile]


class RawFirstProfileCollectionService:
    """Persist a raw profile as PENDING before profile parsing or projection."""

    def __init__(self, id_factory: IdFactory, clock: Clock) -> None:
        self._id_factory = id_factory
        self._clock = clock

    def persist(
        self,
        uow: UnitOfWork,
        *,
        ingestion_id: str,
        account_id: int,
        captured: CollectedRawProfile,
        normalizer: ProfileNormalizer,
    ) -> bool:
        """Persist a profile and return whether a normalized snapshot was created.

        The caller owns the open write UoW and commits only after this method
        returns.  All outcomes therefore share one transaction: raw evidence is
        flushed PENDING first, then exactly one NORMALIZED or QUARANTINED
        terminal disposition and matching ingestion counts are written.
        """
        if not callable(normalizer) or account_id != 1 or not ingestion_id.strip():
            raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
        raw_record = RawRecord(
            id=self._new_id(),
            ingestion_id=ingestion_id,
            ordinal=0,
            record_type="PROFILE",
            source_key=captured.source_key,
            payload_json=zlib.compress(captured.canonical_payload),
            payload_sha256=hashlib.sha256(captured.canonical_payload).hexdigest(),
            fetched_at_ms=captured.fetched_at_ms,
            disposition="PENDING",
            disposed_at_ms=None,
        )
        # Repository add is contractually a flush boundary.  Never parse before it.
        uow.raw_records.add(raw_record)
        try:
            normalized = normalizer(captured.raw_payload)
            _validate_normalized(normalized)
        except DomainError as error:
            self._quarantine(uow, raw_record, account_id, error.code)
            self._complete(uow, ingestion_id, captured.fetched_at_ms, normalized=0, quarantined=1)
            return False
        except Exception:
            self._quarantine(uow, raw_record, account_id, "UPSTREAM.CONTRACT_CHANGED")
            self._complete(uow, ingestion_id, captured.fetched_at_ms, normalized=0, quarantined=1)
            return False

        uow.profile_snapshots.add(
            ProfileSnapshotRecord(
                id=self._new_id(),
                account_id=account_id,
                ingestion_id=ingestion_id,
                raw_record_id=raw_record.id,
                display_name=normalized.display_name,
                character=normalized.character,
                rank_name=normalized.rank_name,
                mr=normalized.mr,
                lp=normalized.lp,
                observed_at_ms=captured.fetched_at_ms,
            )
        )
        uow.raw_records.set_disposition(
            raw_record.id, "NORMALIZED", disposed_at_ms=captured.fetched_at_ms
        )
        self._complete(uow, ingestion_id, captured.fetched_at_ms, normalized=1, quarantined=0)
        return True

    def _complete(
        self,
        uow: UnitOfWork,
        ingestion_id: str,
        finished_at_ms: int,
        *,
        normalized: int,
        quarantined: int,
    ) -> None:
        uow.ingestions.complete(
            ingestion_id,
            raw_count=1,
            normalized_count=normalized,
            duplicate_count=0,
            quarantine_count=quarantined,
            finished_at_ms=finished_at_ms,
        )

    def _quarantine(
        self, uow: UnitOfWork, raw_record: RawRecord, account_id: int, reason_code: str
    ) -> None:
        uow.quarantines.add(
            QuarantineRecord(
                id=self._new_id(),
                raw_record_id=raw_record.id,
                account_id=account_id,
                reason_code="UPSTREAM.CONTRACT_CHANGED"
                if reason_code not in {"UPSTREAM.CONTRACT_CHANGED"}
                else reason_code,
                field_errors_json=None,
                status="OPEN",
                created_at_ms=self._clock(),
                resolved_at_ms=None,
                resolution_match_id=None,
            )
        )
        uow.raw_records.set_disposition(raw_record.id, "QUARANTINED", disposed_at_ms=self._clock())

    def _new_id(self) -> str:
        identifier = self._id_factory()
        if not isinstance(identifier, str) or not identifier.strip():
            raise RuntimeError("id factory returned an invalid identifier")
        return identifier


def _freeze_mapping(value: object) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError("profile payload must be a mapping")
    frozen: dict[str, JsonValue] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("profile payload keys must be strings")
        frozen[key] = _freeze_value(item)
    return MappingProxyType(frozen)


def _freeze_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    raise TypeError("profile payload contains a non-JSON value")


def _validate_normalized(profile: object) -> None:
    if not isinstance(profile, NormalizedProfile):
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    for value in (profile.display_name, profile.character, profile.rank_name):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    for rating in (profile.mr, profile.lp):
        if rating is not None and (type(rating) is not int or rating < 0):
            raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
