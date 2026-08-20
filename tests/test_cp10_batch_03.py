"""Focused full-entry and ordered-packet coverage for CP10.3."""

import importlib
import json

import pytest

from src.calculator.champions import (
    engine_registration_kind,
    get_champion_module_contract,
    get_champion_options_meta,
    parse_champion_abilities,
)

BATCH = (
    "Katarina",
    "Kayle",
    "Kayn",
    "Kennen",
    "Kha'Zix",
    "Kindred",
    "Kled",
    "LeBlanc",
    "Lee Sin",
    "Leona",
    "Lillia",
    "Locke",
)


def _champion(name: str) -> dict:
    with open("data/champions.json", encoding="utf-8") as handle:
        data = json.load(handle)
    return next(value for value in data.values() if value.get("name") == name)


def _parse(name: str, options: dict | None = None) -> dict:
    return parse_champion_abilities(
        _champion(name),
        18,
        200.0,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        champion_options=options or {},
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


def test_batch_modules_are_reviewed_and_carry_full_parent_slot_receipts():
    for name in BATCH:
        module_name = {
            "Kha'Zix": "khazix",
            "Lee Sin": "lee_sin",
            "LeBlanc": "leblanc",
        }.get(name, name.lower())
        module = importlib.import_module(f"src.calculator.champions.{module_name}")
        assert engine_registration_kind(name) == "reviewed_module"
        assert len(module.SOURCES) == 6
        assert module.SOURCES[0]["revision_id"] > 0
        assert set(get_champion_module_contract(name).coverage) == set("PQWER")


@pytest.mark.parametrize("name", BATCH)
def test_batch_parses_all_five_slots(name):
    result = _parse(
        name,
        {
            "p_daggers": 2,
            "r_daggers": 15,
            "p_exalted": True,
            "form": "darkin",
            "w_empowered": True,
            "r_bolts": 6,
            "q_isolated": True,
            "marks": 4,
            "w_attacks": 3,
            "e_stacks": 3,
            "q_pull": True,
            "charge_fraction": 1.0,
            "q_consume": True,
            "e_chain_complete": True,
            "r_mimic": "Q",
            "p_marks": 2,
            "p_ticks": 6,
            "q_outer_edge": True,
            "w_epicenter": True,
            "r_wake": True,
            "q_casts": 3,
            "soul_nails": 2,
            "e_dash": True,
        },
    )
    assert set(result) >= {"passive", "Q", "W", "E", "R"}
    assert all("parts" in row and "damage_type" in row for row in result.values())


def test_cp10_3_ordered_variants_are_not_dropped():
    assert _parse("Katarina", {"p_daggers": 2, "r_daggers": 15})["R"][
        "event_order_certified"
    ]
    assert _parse("Kennen", {"r_bolts": 6})["R"]["event_order_certified"]
    assert (
        len(_parse("LeBlanc", {"q_consume": True, "r_mimic": "Q"})["Q"]["parts"]) == 1
    )
    assert _parse("Lillia", {"p_ticks": 6})["passive"]["target_max_health_sensitive"]
    assert _parse("Locke", {"q_casts": 3, "soul_nails": 3})["Q"]["total_raw"] > 0


def test_cp10_3_options_are_exposed_with_revision_sources():
    for name in BATCH:
        metadata = get_champion_options_meta(name)
        assert metadata["sources"]
        assert len(metadata["sources"]) >= 6
