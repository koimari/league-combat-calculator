"""Focused full-entry and packet coverage for CP10.4."""

import importlib
import json

import pytest

from src.calculator.champions import (
    engine_registration_kind,
    get_champion_options_meta,
    parse_champion_abilities,
)

BATCH = (
    "Lucian",
    "Lulu",
    "Lux",
    "Malphite",
    "Malzahar",
    "Maokai",
    "Master Yi",
    "Mel",
    "Milio",
    "Miss Fortune",
    "Mordekaiser",
    "Morgana",
)


def _champion(name: str) -> dict:
    with open("data/champions.json", encoding="utf-8") as handle:
        data = json.load(handle)
    return next(value for value in data.values() if value.get("name") == name)


def _parse(name: str) -> dict:
    return parse_champion_abilities(
        _champion(name),
        18,
        200.0,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        champion_options={},
        champion_stats={
            "attack_damage": 200.0,
            "base_attack_damage": 100.0,
            "bonus_attack_damage": 80.0,
            "ability_power": 200.0,
            "health": 2_000.0,
            "bonus_health": 500.0,
            "attack_speed": 1.0,
            "bonus_attack_speed": 25.0,
            "move_speed": 375.0,
        },
        target_stats={
            "target_max_health": 2_500.0,
            "target_current_health": 1_500.0,
            "target_missing_health": 1_000.0,
        },
    )


def test_cp10_4_modules_are_reviewed_and_have_full_entry_receipts():
    manifest = json.load(open("docs/cp10-batch-04.json", encoding="utf-8"))
    assert manifest["full_entry_wiki_audit"]["parent_and_ability_receipts"] == 72
    assert manifest["full_entry_wiki_audit"]["ability_template_receipts"] == 60
    assert manifest["full_entry_wiki_audit"]["status"] == "ready"
    assert tuple(manifest["scope"]) == BATCH
    for name in BATCH:
        module_name = {
            "Master Yi": "master_yi",
            "Miss Fortune": "miss_fortune",
        }.get(name, name.lower())
        module = importlib.import_module(f"src.calculator.champions.{module_name}")
        assert engine_registration_kind(name) == "reviewed_module"
        assert len(module.SLOTS) == 5
        assert len(module.SOURCES) >= 1


@pytest.mark.parametrize("name", BATCH)
def test_cp10_4_parses_every_passive_and_ability_slot(name):
    result = _parse(name)
    assert set(result) >= {"passive", "Q", "W", "E", "R"}
    assert all("parts" in row and "damage_type" in row for row in result.values())


def test_cp10_4_options_and_provenance_are_exposed():
    for name in BATCH:
        metadata = get_champion_options_meta(name)
        assert isinstance(metadata["sources"], list)
        assert metadata["sources"]
