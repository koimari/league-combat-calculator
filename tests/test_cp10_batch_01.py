"""Focused source-contract tests for the first CP10 champion batch."""

import importlib
import json

import pytest

from src.calculator.champions import engine_registration_kind, parse_champion_abilities

BATCH = (
    "Draven",
    "Ekko",
    "Elise",
    "Evelynn",
    "Fiddlesticks",
    "Fiora",
    "Fizz",
    "Gangplank",
    "Garen",
    "Gragas",
    "Graves",
    "Gwen",
)


def _champion(name: str) -> dict:
    with open("data/champions.json", encoding="utf-8") as handle:
        data = json.load(handle)
    return next(value for value in data.values() if value.get("name") == name)


def _parse(name: str, options: dict | None = None) -> dict:
    return parse_champion_abilities(
        _champion(name),
        12,
        200.0,
        ability_ranks={"Q": 4, "W": 3, "E": 3, "R": 2},
        champion_options=options or {},
        champion_stats={
            "attack_damage": 180.0,
            "base_attack_damage": 100.0,
            "bonus_attack_damage": 80.0,
            "ability_power": 200.0,
            "health": 2_000.0,
            "bonus_health": 500.0,
            "attack_speed": 1.0,
            "attack_speed_ratio": 1.0,
            "bonus_attack_speed": 25.0,
        },
        target_stats={
            "target_max_health": 2_500.0,
            "target_current_health": 1_500.0,
            "target_missing_health": 1_000.0,
        },
    )


def test_batch_modules_are_reviewed_and_carry_parent_plus_slot_receipts():
    for name in BATCH:
        module_name = name.lower().replace(" ", "_").replace("'", "")
        module = importlib.import_module(f"src.calculator.champions.{module_name}")
        assert engine_registration_kind(name) == "reviewed_module"
        assert module.REVIEW_STATUS == "reviewed_module"
        assert len(module.SOURCES) == 5
        assert module.SOURCES[0]["url"].endswith(f"/{name.replace(' ', '_')}")
        assert {slot: module.MODULE_COVERAGE[slot] for slot in "PQWER"} == {
            slot: "modeled" for slot in "PQWER"
        }


@pytest.mark.parametrize(
    ("name", "options", "checks"),
    [
        (
            "Draven",
            {"r_passes": 2},
            lambda r: r["Q"]["empowers_next_auto"] and r["R"]["parts"][0].count == 2,
        ),
        (
            "Ekko",
            {"p_procs": 1},
            lambda r: r["Q"]["parts"][1].time_offset == 2.0
            and r["passive"]["proc_count"] == 1,
        ),
        (
            "Elise",
            {"spider_form": True, "q_form": 1},
            lambda r: "on_hit" in r["passive"] and "missing health" in r["Q"]["detail"],
        ),
        (
            "Evelynn",
            {"q_recasts": 3, "e_empowered": True, "r_execute_ready": True},
            lambda r: len(r["Q"]["parts"]) == 4 and r["R"]["total_raw"] > 500,
        ),
        (
            "Fiddlesticks",
            {"w_ticks": 8, "r_ticks": 20},
            lambda r: r["W"]["parts"][0].count == 8 and r["R"]["parts"][0].count == 20,
        ),
        (
            "Fiora",
            {"p_vitals": 2},
            lambda r: r["Q"]["applies_item_on_hits"]["hits"] == 1
            and r["passive"]["proc_count"] == 2,
        ),
        (
            "Fizz",
            {"e_variant": 1, "r_size": 2},
            lambda r: {part.damage_type for part in r["Q"]["parts"]}
            == {"magic", "physical"}
            and r["R"]["total_raw"] > 500,
        ),
        (
            "Gangplank",
            {"p_procs": 1, "r_fire_at_will": True, "r_deaths_daughter": True},
            lambda r: r["passive"]["parts"][0].count == 10
            and len(r["R"]["parts"]) == 2,
        ),
        (
            "Garen",
            {},
            lambda r: r["E"]["parts"][0].count >= 7
            and r["E"]["target_debuff"]["threshold_hits"] == 6,
        ),
        (
            "Gragas",
            {"q_fully_fermented": True},
            lambda r: r["W"]["empowers_next_auto"] and r["Q"]["total_raw"] > 0,
        ),
        (
            "Graves",
            {"p_critical_pellets": True},
            lambda r: r["passive"]["auto_attack_override"]["damage_ratio"] > 2.0
            and len(r["Q"]["parts"]) == 2,
        ),
        (
            "Gwen",
            {"q_snippy_stacks": 4, "q_center": True, "r_casts": 3},
            lambda r: "on_hit" in r["passive"]
            and {part.damage_type for part in r["Q"]["parts"]} == {"magic", "true"}
            and len(r["R"]["parts"]) == 3,
        ),
    ],
)
def test_batch_packets_expose_the_sourced_state_boundary(name, options, checks):
    assert checks(_parse(name, options))
