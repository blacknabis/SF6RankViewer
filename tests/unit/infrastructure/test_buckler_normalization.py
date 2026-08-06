from collections.abc import Mapping
from typing import cast

import pytest

from sf6viewer.application.services.raw_collection import JsonValue
from sf6viewer.domain.errors import DomainError
from sf6viewer.infrastructure.buckler.battlelog_capture import normalize_battlelog_match
from sf6viewer.infrastructure.buckler.profile_capture import normalize_profile


def test_profile_treats_unavailable_rating_sentinel_as_missing() -> None:
    normalized = normalize_profile(
        {
            "fighter_banner_info": {
                "personal_info": {"fighter_id": "BLACKNABIS"},
                "favorite_character_alpha": "YASMINE",
                "favorite_character_league_info": {
                    "league_rank_info": {"league_rank_name": "New Challenger"},
                    "master_rating": 0,
                    "league_point": -1,
                },
            }
        }
    )

    assert normalized.character == "YASMINE"
    assert normalized.rank_name == "New Challenger"
    assert normalized.mr == 0
    assert normalized.lp is None


def test_battlelog_treats_unavailable_rating_sentinel_as_missing() -> None:
    normalized = normalize_battlelog_match(
        cast(Mapping[str, JsonValue], _battle_payload(my_league_point=-1)),
        account_user_code="4285684297",
        own_display_name="BLACKNABIS",
    )

    assert normalized.facts.my_character == "야스민"
    assert normalized.facts.my_mr is None
    assert normalized.facts.my_lp is None
    assert normalized.facts.opponent_lp == 19_001
    assert normalized.facts.result == "WIN"


@pytest.mark.parametrize("invalid_value", [-2, "-1", 1.5, True])
def test_profile_rejects_values_other_than_the_known_missing_sentinel(
    invalid_value: object,
) -> None:
    payload = {
        "fighter_banner_info": {
            "personal_info": {"fighter_id": "BLACKNABIS"},
            "favorite_character_alpha": "YASMINE",
            "favorite_character_league_info": {
                "league_rank_info": {"league_rank_name": "New Challenger"},
                "master_rating": 0,
                "league_point": invalid_value,
            },
        }
    }

    with pytest.raises(DomainError) as exc_info:
        normalize_profile(payload)  # type: ignore[arg-type]

    assert exc_info.value.code == "UPSTREAM.CONTRACT_CHANGED"


@pytest.mark.parametrize("invalid_value", [-2, "-1", 1.5, True, None])
def test_battlelog_rejects_values_other_than_the_known_missing_sentinel(
    invalid_value: object,
) -> None:
    payload = _battle_payload(my_league_point=19_001)
    player1 = payload["player1_info"]
    assert isinstance(player1, dict)
    player1["league_point"] = invalid_value

    with pytest.raises(DomainError) as exc_info:
        normalize_battlelog_match(
            cast(Mapping[str, JsonValue], payload),
            account_user_code="4285684297",
            own_display_name="BLACKNABIS",
        )

    assert exc_info.value.code == "UPSTREAM.CONTRACT_CHANGED"


def _battle_payload(*, my_league_point: int) -> dict[str, object]:
    return {
        "replay_id": "L3EHPMYNE",
        "uploaded_at": 1_786_029_816,
        "player1_info": {
            "player": {"fighter_id": "BLACKNABIS", "short_id": 4_285_684_297},
            "playing_character_name": "야스민",
            "master_rating": 0,
            "league_point": my_league_point,
            "round_results": [1, 1],
        },
        "player2_info": {
            "player": {"fighter_id": "OPPONENT", "short_id": 1_234_567_890},
            "playing_character_name": "야스민",
            "master_rating": 0,
            "league_point": 19_001,
            "round_results": [0, 0],
        },
    }
