"""Focused regression coverage for the CP10.2 full-entry modules."""

import pytest

from src.calculator.champions import get_champion_options_meta, parse_champion_abilities
from src.calculator.data_fetcher import get_champion

BATCH = (
    ("Hecarim", "Hecarim"),
    ("Heimerdinger", "Heimerdinger"),
    ("Hwei", "Hwei"),
    ("Illaoi", "Illaoi"),
    ("Irelia", "Irelia"),
    ("Ivern", "Ivern"),
    ("Janna", "Janna"),
    ("Jax", "Jax"),
    ("Jhin", "Jhin"),
    ("K'Sante", "KSante"),
    ("Karma", "Karma"),
    ("Kassadin", "Kassadin"),
)


@pytest.mark.parametrize("display_name,data_key", BATCH)
def test_batch_modules_parse_all_slots_with_revision_receipts(display_name, data_key):
    data = get_champion(data_key)
    abilities = parse_champion_abilities(
        data,
        18,
        200.0,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        champion_stats={
            "attack_damage": 200.0,
            "bonus_attack_damage": 100.0,
            "ability_power": 200.0,
            "move_speed": 375.0,
        },
        champion_options={
            "p_triggers": 2,
            "q_stacks": 3,
            "q_turrets": 3,
            "q_turret_attacks": 3,
            "q_beams": 1,
            "w_ticks": 4,
            "w_rockets": 5,
            "w_in_brush": True,
            "e_charge": 1.0,
        },
    )
    assert set(abilities) >= {"passive", "Q", "W", "E", "R"}
    for row in abilities.values():
        assert "parts" in row
        assert "damage_type" in row
    sources = get_champion_options_meta(display_name)["sources"]
    assert len(sources) >= 5
    assert all(source["revision_id"] > 0 for source in sources)


def test_hwei_signature_is_not_silently_dropped():
    abilities = parse_champion_abilities(
        get_champion("Hwei"),
        18,
        200.0,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        champion_stats={"attack_damage": 100.0, "ability_power": 200.0},
        champion_options={"p_triggers": 2},
    )
    assert abilities["passive"]["proc_count"] == 2
    assert abilities["passive"]["damage_events"]


def test_heimer_turret_packet_includes_pet_damage_and_cadence():
    abilities = parse_champion_abilities(
        get_champion("Heimerdinger"),
        18,
        200.0,
        ability_ranks={"Q": 5, "W": 5, "E": 5, "R": 3},
        champion_stats={"attack_damage": 100.0, "ability_power": 200.0},
        champion_options={"q_turrets": 3, "q_turret_attacks": 3, "q_beams": 1},
    )
    assert abilities["Q"]["total_raw"] > 0
    assert abilities["Q"]["event_order_certified"]
    assert len(abilities["Q"]["parts"]) == 2
