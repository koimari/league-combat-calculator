"""Focused BIS prices its swaps on the same rune page the fight uses."""

from src.calculator.bis import bis_main_request
from src.calculator.scenario import parse_scenario_request


def _stats(**page):
    data = {
        "champion": "Ahri",
        "level": 9,
        "items": ["Needlessly Large Rod"],  # AP > bonus AD: adaptive resolves to AP
        "boots": "",
        "fight_mode": "one_rotation",
        **page,
    }
    request = parse_scenario_request(data, deterministic=True, parse_crossover=False)
    return bis_main_request(request, data).resolve().stats


def test_the_main_loadout_carries_the_rune_page():
    """Two adaptive shards on an AP build are +18 AP (65 -> 83) in the BIS main loadout."""
    bare = _stats()
    paged = _stats(stat_shards=["Adaptive Force", "Adaptive Force", "Health"])
    assert paged["ability_power"] - bare["ability_power"] == 18.0
    assert paged["health"] - bare["health"] == 65.0
