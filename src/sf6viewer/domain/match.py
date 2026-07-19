"""Match identity primitives."""

import hashlib
import json
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from sf6viewer.domain.errors import error_from_code


@dataclass(frozen=True, slots=True)
class MatchFacts:
    """The fields used to identify a match."""

    account_user_code: str
    original_date: str
    occurred_at_ms: int
    my_name: str
    my_character: str
    opponent_name: str
    opponent_character: str
    result: str
    my_mr: int | None
    my_lp: int | None
    opponent_mr: int | None
    opponent_lp: int | None


def canonical_json(value: object) -> bytes:
    """Return a stable UTF-8 JSON representation for identity inputs."""
    normalized = _normalize_json_strings(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def fallback_base_sha256(facts: MatchFacts) -> str:
    """Hash the stable fields shared by possible fallback rematches."""
    return _sha256(_fallback_base_payload(facts))


def content_sha256(facts: MatchFacts) -> str:
    """Hash every match field, including timing and ratings."""
    return _sha256({
        "account_user_code": facts.account_user_code,
        "original_date": facts.original_date,
        "occurred_at_ms": facts.occurred_at_ms,
        "my_name": facts.my_name,
        "my_character": facts.my_character,
        "opponent_name": facts.opponent_name,
        "opponent_character": facts.opponent_character,
        "result": facts.result,
        "my_mr": facts.my_mr,
        "my_lp": facts.my_lp,
        "opponent_mr": facts.opponent_mr,
        "opponent_lp": facts.opponent_lp,
    })


def identity_key(
    facts: MatchFacts,
    *,
    source_id: str | None = None,
    hydration_key: str | None = None,
    fallback_ordinal: int | None = None,
) -> str:
    """Choose the most authoritative available match identity."""
    normalized_source_id = _normalize_optional_identifier(source_id)
    normalized_hydration_key = _normalize_optional_identifier(hydration_key)
    _validate_fallback_ordinal(fallback_ordinal)

    if normalized_source_id is not None:
        return f"src:{normalized_source_id}"
    if normalized_hydration_key is not None:
        return f"hyd:{normalized_hydration_key}"
    if fallback_ordinal is not None:
        raise error_from_code("DATA.IDENTITY_GROUP_INCOMPLETE")
    raise error_from_code("DATA.IDENTITY_COLLISION")


def assign_fallback_keys(
    oldest_to_newest: list[MatchFacts], *, boundary_complete: bool
) -> list[str]:
    """Assign stable, chronological fallback identity ordinals to one base group."""
    if type(boundary_complete) is not bool or boundary_complete is not True:
        raise error_from_code("DATA.IDENTITY_GROUP_INCOMPLETE")
    if not oldest_to_newest:
        raise error_from_code("DATA.IDENTITY_COLLISION")

    base_hash = fallback_base_sha256(oldest_to_newest[0])
    if any(fallback_base_sha256(facts) != base_hash for facts in oldest_to_newest[1:]):
        raise error_from_code("DATA.IDENTITY_COLLISION")

    return [f"fb:{base_hash}:{ordinal}" for ordinal in range(1, len(oldest_to_newest) + 1)]


def _normalize_json_strings(value: object) -> object:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value.strip())
    if isinstance(value, list):
        return [_normalize_json_strings(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_json_strings(item) for item in value]
    if isinstance(value, Mapping):
        normalized_mapping: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise error_from_code("DATA.IDENTITY_COLLISION")
            normalized_key = unicodedata.normalize("NFC", key.strip())
            if normalized_key in normalized_mapping:
                raise error_from_code("DATA.IDENTITY_COLLISION")
            normalized_mapping[normalized_key] = _normalize_json_strings(item)
        return normalized_mapping
    return value


def _fallback_base_payload(facts: MatchFacts) -> dict[str, str]:
    return {
        "account_user_code": facts.account_user_code,
        "original_date": facts.original_date,
        "my_name": facts.my_name,
        "my_character": facts.my_character,
        "opponent_name": facts.opponent_name,
        "opponent_character": facts.opponent_character,
        "result": facts.result,
    }


def _sha256(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _normalize_optional_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise error_from_code("DATA.IDENTITY_COLLISION")
    normalized_value = unicodedata.normalize("NFC", value.strip())
    if not normalized_value:
        raise error_from_code("DATA.IDENTITY_COLLISION")
    return normalized_value


def _validate_fallback_ordinal(value: int | None) -> None:
    if value is not None and (
        not isinstance(value, int) or isinstance(value, bool) or value < 1
    ):
        raise error_from_code("DATA.IDENTITY_COLLISION")
