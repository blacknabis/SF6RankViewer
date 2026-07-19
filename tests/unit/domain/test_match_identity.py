"""Tests for deterministic match identity."""

from dataclasses import FrozenInstanceError, fields, replace

import pytest

from sf6viewer.domain.errors import DomainError
from sf6viewer.domain.match import (
    MatchFacts,
    assign_fallback_keys,
    canonical_json,
    content_sha256,
    fallback_base_sha256,
    identity_key,
)


@pytest.fixture
def facts() -> MatchFacts:
    return MatchFacts(
        account_user_code="1234567890",
        original_date="2026/06/29 21:43",
        occurred_at_ms=1782736980000,
        my_name="LocalHero",
        my_character="Ryu",
        opponent_name="PlayerOne",
        opponent_character="Ken",
        result="WIN",
        my_mr=None,
        my_lp=12345,
        opponent_mr=1510,
        opponent_lp=None,
    )


def test_match_facts_has_exactly_the_required_frozen_slotted_fields(facts: MatchFacts) -> None:
    assert [field.name for field in fields(MatchFacts)] == [
        "account_user_code",
        "original_date",
        "occurred_at_ms",
        "my_name",
        "my_character",
        "opponent_name",
        "opponent_character",
        "result",
        "my_mr",
        "my_lp",
        "opponent_mr",
        "opponent_lp",
    ]
    assert not hasattr(facts, "__dict__")
    with pytest.raises(FrozenInstanceError):
        facts.result = "LOSS"  # type: ignore[misc]


def test_canonical_json_uses_sorted_compact_utf8_and_normalizes_strings() -> None:
    value = {"z": "  e\u0301  ", "a": [None, 7, 2.5, "  x  "]}

    assert canonical_json(value) == b'{"a":[null,7,2.5,"x"],"z":"\xc3\xa9"}'


def test_canonical_json_is_independent_of_dict_insertion_order() -> None:
    first = {"b": "two", "a": "one"}
    second = {"a": "one", "b": "two"}

    assert canonical_json(first) == canonical_json(second)


def test_canonical_json_normalizes_composed_and_decomposed_unicode_equally() -> None:
    assert canonical_json({"name": "Caf\u00e9"}) == canonical_json({"name": "Cafe\u0301"})


def test_canonical_json_normalizes_nested_mapping_keys_and_list_values() -> None:
    value = {" outer ": [{" inner ": "  Cafe\u0301  "}]}

    assert canonical_json(value) == b'{"outer":[{"inner":"Caf\xc3\xa9"}]}'


@pytest.mark.parametrize("value", [{1: "one"}, {" a ": 1, "a": 2}])
def test_canonical_json_rejects_invalid_or_colliding_normalized_mapping_keys(
    value: object,
) -> None:
    with pytest.raises(DomainError) as exc_info:
        canonical_json(value)

    assert exc_info.value.code == "DATA.IDENTITY_COLLISION"


def test_hashes_match_fixed_canonical_vectors(facts: MatchFacts) -> None:
    expected_base = (
        b'{"account_user_code":"1234567890","my_character":"Ryu","my_name":"LocalHero",'
        b'"opponent_character":"Ken","opponent_name":"PlayerOne",'
        b'"original_date":"2026/06/29 21:43","result":"WIN"}'
    )

    assert canonical_json(
        {
            "account_user_code": facts.account_user_code,
            "original_date": facts.original_date,
            "my_name": facts.my_name,
            "my_character": facts.my_character,
            "opponent_name": facts.opponent_name,
            "opponent_character": facts.opponent_character,
            "result": facts.result,
        }
    ) == expected_base
    assert fallback_base_sha256(facts) == (
        "0f5e44f447a5655faa743d40c72999b98e0593aee2a22e2390fcdfbf7d528f6d"
    )
    assert content_sha256(facts) == (
        "119a793ad1bf511be265b98a881f6294c2624185d6c9a42a7dc7235af73a9c59"
    )


def test_hashes_normalize_composed_and_decomposed_unicode(facts: MatchFacts) -> None:
    composed = replace(facts, my_name="Caf\u00e9")
    decomposed = replace(facts, my_name="Cafe\u0301")

    assert fallback_base_sha256(composed) == fallback_base_sha256(decomposed)
    assert content_sha256(composed) == content_sha256(decomposed)


def test_fallback_hash_excludes_timestamp_and_ratings(facts: MatchFacts) -> None:
    changed = MatchFacts(
        account_user_code=facts.account_user_code,
        original_date=facts.original_date,
        occurred_at_ms=1,
        my_name=facts.my_name,
        my_character=facts.my_character,
        opponent_name=facts.opponent_name,
        opponent_character=facts.opponent_character,
        result=facts.result,
        my_mr=2000,
        my_lp=None,
        opponent_mr=None,
        opponent_lp=99999,
    )

    assert fallback_base_sha256(changed) == fallback_base_sha256(facts)
    assert content_sha256(changed) != content_sha256(facts)


def test_identity_key_prefers_source_then_hydration_then_fallback(facts: MatchFacts) -> None:
    assert (
        identity_key(
            facts,
            source_id="source-7",
            hydration_key="hydrate-2",
            fallback_ordinal=3,
        )
        == "src:source-7"
    )
    assert identity_key(facts, hydration_key="hydrate-2", fallback_ordinal=3) == "hyd:hydrate-2"


def test_identity_key_rejects_caller_issued_fallback_ordinals(facts: MatchFacts) -> None:
    with pytest.raises(DomainError) as exc_info:
        identity_key(facts, fallback_ordinal=2)

    assert exc_info.value.code == "DATA.IDENTITY_GROUP_INCOMPLETE"


def test_identity_key_normalizes_source_and_hydration_identifiers(facts: MatchFacts) -> None:
    assert identity_key(facts, source_id="  Cafe\u0301\t") == "src:Caf\u00e9"
    assert identity_key(facts, hydration_key="\nCafe\u0301  ") == "hyd:Caf\u00e9"
    assert identity_key(facts, source_id="Caf\u00e9") == identity_key(
        facts, source_id="Cafe\u0301"
    )


@pytest.mark.parametrize(
    ("kwargs"),
    [
        {"source_id": ""},
        {"source_id": "  "},
        {"hydration_key": ""},
        {"hydration_key": "\t"},
        {"fallback_ordinal": 0},
        {"fallback_ordinal": -1},
        {},
    ],
)
def test_identity_key_rejects_invalid_or_missing_identity_inputs(
    facts: MatchFacts, kwargs: dict[str, str | int]
) -> None:
    with pytest.raises(DomainError) as exc_info:
        identity_key(facts, **kwargs)

    assert exc_info.value.code == "DATA.IDENTITY_COLLISION"


def test_assign_fallback_keys_requires_complete_single_base_group(facts: MatchFacts) -> None:
    with pytest.raises(DomainError) as exc_info:
        assign_fallback_keys([facts], boundary_complete=False)
    assert exc_info.value.code == "DATA.IDENTITY_GROUP_INCOMPLETE"

    different = MatchFacts(
        account_user_code=facts.account_user_code,
        original_date=facts.original_date,
        occurred_at_ms=facts.occurred_at_ms,
        my_name="Other",
        my_character=facts.my_character,
        opponent_name=facts.opponent_name,
        opponent_character=facts.opponent_character,
        result=facts.result,
        my_mr=facts.my_mr,
        my_lp=facts.my_lp,
        opponent_mr=facts.opponent_mr,
        opponent_lp=facts.opponent_lp,
    )
    with pytest.raises(DomainError) as exc_info:
        assign_fallback_keys([facts, different], boundary_complete=True)
    assert exc_info.value.code == "DATA.IDENTITY_COLLISION"


@pytest.mark.parametrize("boundary_complete", [False, "false", 1, None])
def test_assign_fallback_keys_requires_literal_true_boundary_flag(
    facts: MatchFacts, boundary_complete: object
) -> None:
    with pytest.raises(DomainError) as exc_info:
        assign_fallback_keys([facts], boundary_complete=boundary_complete)  # type: ignore[arg-type]

    assert exc_info.value.code == "DATA.IDENTITY_GROUP_INCOMPLETE"


def test_assign_fallback_keys_preserves_old_prefix_when_a_newest_rematch_arrives(
    facts: MatchFacts,
) -> None:
    second = MatchFacts(
        account_user_code=facts.account_user_code,
        original_date=facts.original_date,
        occurred_at_ms=facts.occurred_at_ms + 1,
        my_name=facts.my_name,
        my_character=facts.my_character,
        opponent_name=facts.opponent_name,
        opponent_character=facts.opponent_character,
        result=facts.result,
        my_mr=1600,
        my_lp=facts.my_lp,
        opponent_mr=facts.opponent_mr,
        opponent_lp=facts.opponent_lp,
    )
    third = MatchFacts(
        account_user_code=facts.account_user_code,
        original_date=facts.original_date,
        occurred_at_ms=facts.occurred_at_ms + 2,
        my_name=facts.my_name,
        my_character=facts.my_character,
        opponent_name=facts.opponent_name,
        opponent_character=facts.opponent_character,
        result=facts.result,
        my_mr=facts.my_mr,
        my_lp=1,
        opponent_mr=facts.opponent_mr,
        opponent_lp=facts.opponent_lp,
    )

    before = assign_fallback_keys([facts, second], boundary_complete=True)
    after = assign_fallback_keys([facts, second, third], boundary_complete=True)

    assert after[:2] == before
    assert after[2].endswith(":3")
