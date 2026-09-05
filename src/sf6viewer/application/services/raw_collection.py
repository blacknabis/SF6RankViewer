"""Raw-first persistence for a freshly collected set of match payloads.

The caller owns the write unit of work and decides when to commit it.  This
service deliberately has no browser, HTTP, or web-framework dependency.
"""

from __future__ import annotations

import hashlib
import re
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from sf6viewer.application.ports.repositories import (
    InsertOutcome,
    MatchRecord,
    ObservationRecord,
    QuarantineRecord,
    QuarantineRepository,
    RawRecord,
    RawRecordRepository,
)
from sf6viewer.application.ports.unit_of_work import UnitOfWork
from sf6viewer.domain.errors import DomainError, error_from_code
from sf6viewer.domain.ingestion import ensure_completed_counts
from sf6viewer.domain.match import MatchFacts, canonical_json, content_sha256, identity_key

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]
type IdFactory = Callable[[], str]
type Clock = Callable[[], int]

_FALLBACK_KEY = re.compile(r"fb:[0-9a-f]{64}:[1-9][0-9]*\Z")


@dataclass(frozen=True, slots=True)
class CollectedRawMatch:
    """One immutable raw match payload and collection-time provenance.

    This type intentionally contains no normalized match facts.  Its payload
    is stored (and flushed) as ``PENDING`` before a caller-provided normalizer
    is allowed to inspect it.
    """

    raw_payload: Mapping[str, JsonValue]
    ordinal: int
    fetched_at_ms: int
    source_key: str | None = None
    _canonical_payload: bytes = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
        if type(self.fetched_at_ms) is not int:
            raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
        try:
            frozen_payload = _freeze_json_mapping(self.raw_payload)
            canonical_payload = canonical_json(frozen_payload)
        except Exception as exc:
            # Raw payloads are evidence, never safe diagnostic text.
            raise error_from_code("UPSTREAM.CONTRACT_CHANGED") from exc
        object.__setattr__(self, "raw_payload", frozen_payload)
        object.__setattr__(self, "_canonical_payload", canonical_payload)

    @property
    def canonical_payload(self) -> bytes:
        """Return the canonical uncompressed JSON bytes prepared at construction."""
        return self._canonical_payload


@dataclass(frozen=True, slots=True)
class NormalizedMatch:
    """A normalizer's safe interpretation of one persisted raw payload.

    ``fallback_identity_key`` is accepted only when the normalizer has already
    completed fallback grouping.  This layer never derives fallback keys from
    an ordinal or from other raw records.
    """

    facts: MatchFacts
    source_id: str | None = None
    hydration_key: str | None = None
    fallback_identity_key: str | None = None
    # Buckler's old parser hashed the current profile name instead of the
    # replay player's name. Only that parser opts into evidence-backed repair.
    allow_legacy_profile_name: bool = False


type Normalizer = Callable[[Mapping[str, JsonValue]], NormalizedMatch]


@dataclass(frozen=True, slots=True)
class CollectionIngestion:
    """The active ingestion run and its durable account scope."""

    ingestion_id: str
    account_id: int

    def __post_init__(self) -> None:
        if not isinstance(self.ingestion_id, str) or not self.ingestion_id.strip():
            raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
        if type(self.account_id) is not int or self.account_id != 1:
            raise error_from_code("UPSTREAM.CONTRACT_CHANGED")


@dataclass(frozen=True, slots=True)
class CollectionPersistResult:
    """The accounted-for terminal disposition counts for one ingestion run."""

    raw_count: int
    normalized_count: int
    duplicate_count: int
    quarantine_count: int


class RawFirstCollectionService:
    """Persist fresh collection results as raw evidence before normalization."""

    def __init__(self, id_factory: IdFactory, clock: Clock) -> None:
        if not callable(id_factory) or not callable(clock):
            raise TypeError("id_factory and clock must be callable")
        self._id_factory = id_factory
        self._clock = clock

    def persist(
        self,
        uow: UnitOfWork,
        raw_records: RawRecordRepository,
        quarantines: QuarantineRepository,
        ingestion: CollectionIngestion,
        collected_matches: Sequence[CollectedRawMatch],
        normalizer: Normalizer,
    ) -> CollectionPersistResult:
        """Persist and fully account for a collection in the caller's UoW.

        No repository commits here.  A caller must provide repositories bound
        to the same open write UoW session, so raw evidence,
        normalization/quarantine, dispositions, and final run counts remain
        one transaction.
        """
        if not isinstance(ingestion, CollectionIngestion):
            raise TypeError("ingestion must be a CollectionIngestion")
        if not isinstance(collected_matches, Sequence) or isinstance(
            collected_matches, (bytes, str)
        ):
            raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
        matches = tuple(collected_matches)
        if any(not isinstance(match, CollectedRawMatch) for match in matches):
            raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
        if len({match.ordinal for match in matches}) != len(matches):
            raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
        if not callable(normalizer):
            raise TypeError("normalizer must be callable")

        normalized_count = 0
        duplicate_count = 0
        quarantine_count = 0

        for collected in matches:
            raw_record = self._raw_record(ingestion, collected)
            # RawRecordRepository.add must flush the PENDING row before it
            # returns.  No parser or normalizer has run before this boundary.
            raw_records.add(raw_record)

            try:
                _validate_source_key(collected.source_key)
                normalized = normalizer(collected.raw_payload)
                match = self._match_record(ingestion, collected, normalized)
            except DomainError as exc:
                self._quarantine(
                    quarantines,
                    raw_records,
                    raw_record,
                    ingestion.account_id,
                    exc.code,
                )
                quarantine_count += 1
                continue
            except (KeyError, TypeError, ValueError):
                self._quarantine(
                    quarantines,
                    raw_records,
                    raw_record,
                    ingestion.account_id,
                    "UPSTREAM.CONTRACT_CHANGED",
                )
                quarantine_count += 1
                continue
            except Exception:
                # A parser implementation may fail in an unanticipated way.
                # The PENDING evidence is already durable in this transaction,
                # so preserve it and expose only the stable contract code.
                self._quarantine(
                    quarantines,
                    raw_records,
                    raw_record,
                    ingestion.account_id,
                    "UPSTREAM.CONTRACT_CHANGED",
                )
                quarantine_count += 1
                continue

            outcome = uow.matches.insert_or_compare(match)
            if outcome is InsertOutcome.IDENTITY_COLLISION and normalized.allow_legacy_profile_name:
                compatible = self._legacy_profile_name_match(
                    uow, raw_records, raw_record, collected, normalized, match
                )
                if compatible is not None:
                    # Keep the canonical legacy interpretation and its hash immutable.
                    # The new raw observation retains the exact replay evidence.
                    match = replace(match, content_sha256=compatible.content_sha256)
                    outcome = InsertOutcome.SAME_CONTENT
            if outcome is InsertOutcome.IDENTITY_COLLISION:
                self._quarantine(
                    quarantines,
                    raw_records,
                    raw_record,
                    ingestion.account_id,
                    "DATA.IDENTITY_COLLISION",
                )
                quarantine_count += 1
                continue

            persisted_match_id = match.id
            disposition = "NORMALIZED"
            if outcome is InsertOutcome.SAME_CONTENT:
                existing = uow.matches.get_by_identity(match.account_id, match.identity_key)
                if existing is None:
                    raise RuntimeError("persisted match identity was not found")
                persisted_match_id = existing.id
                disposition = "DUPLICATE"
                duplicate_count += 1
            elif outcome is InsertOutcome.NEW:
                normalized_count += 1
            else:
                raise RuntimeError("unknown match insert outcome")

            uow.matches.add_observation(
                ObservationRecord(
                    id=self._new_id(),
                    match_id=persisted_match_id,
                    raw_record_id=raw_record.id,
                    ingestion_id=ingestion.ingestion_id,
                    observed_content_sha256=match.content_sha256,
                    observed_at_ms=collected.fetched_at_ms,
                )
            )
            raw_records.set_disposition(
                raw_record.id, disposition, disposed_at_ms=collected.fetched_at_ms
            )

        result = CollectionPersistResult(
            raw_count=len(matches),
            normalized_count=normalized_count,
            duplicate_count=duplicate_count,
            quarantine_count=quarantine_count,
        )
        ensure_completed_counts(
            result.raw_count,
            result.normalized_count,
            result.duplicate_count,
            result.quarantine_count,
        )
        uow.ingestions.complete(
            ingestion.ingestion_id,
            raw_count=result.raw_count,
            normalized_count=result.normalized_count,
            duplicate_count=result.duplicate_count,
            quarantine_count=result.quarantine_count,
            finished_at_ms=self._clock(),
        )
        return result

    @staticmethod
    def _legacy_profile_name_match(
        uow: UnitOfWork,
        raw_records: RawRecordRepository,
        raw_record: RawRecord,
        collected: CollectedRawMatch,
        normalized: NormalizedMatch,
        match: MatchRecord,
    ) -> MatchRecord | None:
        """Prove an old hash differs only by a preserved profile display name.

        A matching replay ID or matching projected fields alone is insufficient:
        the original normalized raw evidence must be byte-for-byte identical,
        and substituting only a known account name must reproduce the old hash.
        No stored match, hash, or original observation is rewritten.
        """
        existing = uow.matches.get_by_identity(match.account_id, match.identity_key)
        if existing is None:
            return None
        original = raw_records.get_original_for_match(existing.id)
        if original is None or original.payload_sha256 != raw_record.payload_sha256:
            return None
        try:
            if zlib.decompress(original.payload_json) != collected.canonical_payload:
                return None
        except zlib.error:
            return None
        for name in uow.profile_snapshots.list_display_names(match.account_id):
            legacy_facts = replace(normalized.facts, my_name=name)
            if content_sha256(legacy_facts) == existing.content_sha256:
                return existing
        return None

    def _raw_record(
        self, ingestion: CollectionIngestion, collected: CollectedRawMatch
    ) -> RawRecord:
        return RawRecord(
            id=self._new_id(),
            ingestion_id=ingestion.ingestion_id,
            ordinal=collected.ordinal,
            record_type="MATCH",
            source_key=_persisted_source_key(collected.source_key),
            payload_json=zlib.compress(collected.canonical_payload),
            payload_sha256=hashlib.sha256(collected.canonical_payload).hexdigest(),
            fetched_at_ms=collected.fetched_at_ms,
            disposition="PENDING",
            disposed_at_ms=None,
        )

    def _match_record(
        self,
        ingestion: CollectionIngestion,
        collected: CollectedRawMatch,
        normalized: NormalizedMatch,
    ) -> MatchRecord:
        if not isinstance(normalized, NormalizedMatch):
            raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
        _validate_facts(normalized.facts)
        resolved_key, identity_kind = _resolve_identity(normalized)
        facts = normalized.facts
        return MatchRecord(
            id=self._new_id(),
            account_id=ingestion.account_id,
            identity_key=resolved_key,
            identity_kind=identity_kind,
            content_sha256=content_sha256(facts),
            occurred_at_ms=facts.occurred_at_ms,
            occurred_at_source=facts.original_date,
            my_character=facts.my_character,
            my_mr=facts.my_mr,
            my_lp=facts.my_lp,
            opponent_name=facts.opponent_name,
            opponent_character=facts.opponent_character,
            opponent_mr=facts.opponent_mr,
            opponent_lp=facts.opponent_lp,
            result=facts.result,
            created_at_ms=collected.fetched_at_ms,
        )

    def _quarantine(
        self,
        quarantines: QuarantineRepository,
        raw_records: RawRecordRepository,
        raw_record: RawRecord,
        account_id: int,
        reason_code: str,
    ) -> None:
        quarantines.add(
            QuarantineRecord(
                id=self._new_id(),
                raw_record_id=raw_record.id,
                account_id=account_id,
                reason_code=_safe_reason_code(reason_code),
                field_errors_json=None,
                status="OPEN",
                created_at_ms=self._clock(),
                resolved_at_ms=None,
                resolution_match_id=None,
            )
        )
        raw_records.set_disposition(raw_record.id, "QUARANTINED", disposed_at_ms=self._clock())

    def _new_id(self) -> str:
        value = self._id_factory()
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError("id factory returned an invalid identifier")
        return value


def _freeze_json_mapping(value: object) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError("raw payload must be a mapping")
    frozen: dict[str, JsonValue] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError("raw payload keys must be strings")
        frozen[key] = _freeze_json_value(item)
    return MappingProxyType(frozen)


def _freeze_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return _freeze_json_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json_value(item) for item in value)
    raise TypeError("raw payload contains a non-JSON value")


def _resolve_identity(normalized: NormalizedMatch) -> tuple[str, str]:
    if normalized.source_id is not None:
        return identity_key(normalized.facts, source_id=normalized.source_id), "SOURCE_ID"
    if normalized.hydration_key is not None:
        return (
            identity_key(normalized.facts, hydration_key=normalized.hydration_key),
            "HYDRATION_KEY",
        )
    fallback_key = normalized.fallback_identity_key
    if not isinstance(fallback_key, str) or not _FALLBACK_KEY.fullmatch(fallback_key):
        raise error_from_code("DATA.IDENTITY_GROUP_INCOMPLETE")
    return fallback_key, "FALLBACK_GROUP"


def _validate_source_key(source_key: object) -> None:
    """Reject malformed provenance only after its payload has been persisted."""
    if source_key is not None and (not isinstance(source_key, str) or not source_key.strip()):
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")


def _persisted_source_key(source_key: object) -> str | None:
    """Keep malformed provenance from blocking the initial raw-evidence flush."""
    return source_key if isinstance(source_key, str) and source_key.strip() else None


def _validate_facts(facts: object) -> None:
    if not isinstance(facts, MatchFacts):
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    required_strings = (
        facts.account_user_code,
        facts.original_date,
        facts.my_name,
        facts.my_character,
        facts.opponent_name,
        facts.opponent_character,
    )
    if any(not isinstance(value, str) or not value.strip() for value in required_strings):
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    if type(facts.occurred_at_ms) is not int or facts.occurred_at_ms < 0:
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    if not isinstance(facts.result, str) or facts.result not in {"WIN", "LOSE", "DRAW"}:
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")
    ratings = (facts.my_mr, facts.my_lp, facts.opponent_mr, facts.opponent_lp)
    if any(value is not None and (type(value) is not int or value < 0) for value in ratings):
        raise error_from_code("UPSTREAM.CONTRACT_CHANGED")


def _safe_reason_code(reason_code: str) -> str:
    if reason_code in {"DATA.IDENTITY_COLLISION", "DATA.IDENTITY_GROUP_INCOMPLETE"}:
        return reason_code
    return "UPSTREAM.CONTRACT_CHANGED"
