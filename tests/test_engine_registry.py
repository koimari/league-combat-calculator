"""Contracts for the complete runnable champion registration surface."""

import json

from src.calculator.champions import (
    engine_registration_kind,
    parse_champion_abilities,
    registered_champion_names,
    registered_engine_champion_names,
)


def _champions() -> dict:
    with open("data/champions.json", encoding="utf-8") as handle:
        return json.load(handle)


def test_every_cached_champion_has_an_importable_engine_registration():
    champions = _champions()
    names = {champion["name"] for champion in champions.values()}
    registered = set(registered_engine_champion_names())

    assert names == registered
    assert len(registered) == 173
    assert len(registered_champion_names()) == 45
    assert sum(
        engine_registration_kind(name) == "reviewed_module" for name in registered
    ) == 45
    assert sum(
        engine_registration_kind(name) == "wiki_generic_module" for name in registered
    ) == 128


def test_generic_registration_runs_through_the_same_validated_parser():
    champions = _champions()
    stats = {
        "attack_damage": 100.0,
        "bonus_attack_damage": 50.0,
        "base_attack_damage": 100.0,
        "ability_power": 100.0,
        "health": 1_000.0,
        "bonus_health": 500.0,
        "armor": 50.0,
        "magic_resistance": 50.0,
    }
    target = {
        "target_max_health": 1_000.0,
        "target_current_health": 1_000.0,
        "target_missing_health": 0.0,
    }

    for champion in champions.values():
        if engine_registration_kind(champion["name"]) != "wiki_generic_module":
            continue
        result = parse_champion_abilities(
            champion,
            6,
            100.0,
            champion_stats=stats,
            target_stats=target,
        )
        assert isinstance(result, dict), champion["name"]
