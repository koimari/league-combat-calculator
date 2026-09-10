"""Manual points obey each supported champion's unlocks and free ranks."""

import pytest

from src.calculator.fight_params import FightParams
from src.calculator.fight_request_bounds import rank_allocation_contract
from src.calculator.scenario import ChampionLoadout
from src.calculator.rank_allocation import rank_rules, validate_manual_ranks


@pytest.mark.parametrize("champion", ["Elise", "Karma", "Nidalee", "Jayce"])
def test_free_ultimate_does_not_spend_the_first_point(champion):
    ranks = {"Q": 1, "W": 0, "E": 0, "R": 1}
    params = FightParams.from_request({"ability_ranks": ranks})
    params.validate_for_champion(champion, 1)
    ChampionLoadout.from_request(
        {"champion": champion, "level": 1, "ability_ranks": ranks}, field="ally"
    ).resolve()
    assert params.ability_ranks == ranks


@pytest.mark.parametrize(
    "champion,level,ranks",
    [
        ("Jayce", 11, {"Q": 6, "W": 0, "E": 0, "R": 1}),
        ("Udyr", 16, {"Q": 0, "W": 0, "E": 0, "R": 6}),
        ("Karma", 16, {"Q": 0, "W": 0, "E": 0, "R": 4}),
    ],
)
def test_special_rank_unlock(champion, level, ranks):
    params = FightParams.from_request({"ability_ranks": ranks})
    params.validate_for_champion(champion, level)
    with pytest.raises(ValueError, match="requires champion level"):
        params.validate_for_champion(champion, level - 1)


def test_standard_champion_keeps_rank_caps():
    params = FightParams.from_request(
        {"ability_ranks": {"Q": 6, "W": 0, "E": 0, "R": 0}}
    )
    with pytest.raises(ValueError, match="Q rank must be 0-5"):
        params.validate_for_champion("Ashe", 18)


def test_contract_exposes_manual_point_rules():
    contract = rank_allocation_contract()
    assert set(contract["by_champion"].values()) == {"manual"}
    assert contract["rules_by_champion"]["Udyr"]["rank_unlock_levels"]["R"] == [
        1,
        3,
        5,
        7,
        9,
        16,
    ]
    assert contract["rules_by_champion"]["Jayce"]["free_ranks"]["R"] == 1


def test_rank_rules_are_independent_client_snapshots():
    first = rank_rules("Karma")
    first["free_ranks"]["R"] = 0
    first["rank_unlock_levels"]["Q"].clear()
    assert rank_rules("Karma")["free_ranks"]["R"] == 1
    validate_manual_ranks("Karma", 1, {"Q": 1, "W": 0, "E": 0, "R": 1})
    with pytest.raises(ValueError, match="more skill points"):
        validate_manual_ranks("Karma", 1, {"Q": 1, "W": 1, "E": 0, "R": 1})
