"""Fail-closed timestamp contracts for ally support packets."""

import math

import pytest

from src.calculator.data_fetcher import get_champion
from src.calculator.support_effects import _support_profile, derive_ally_effects


def _sona_effects(cast_timeline):
    return derive_ally_effects(
        get_champion("Sona"),
        18,
        {"ability_power": 0.0},
        cast_timeline,
    )


def test_support_packet_preserves_sourced_cast_time():
    effects = _sona_effects([{"slot": "W", "time": 2.5}])

    assert effects
    assert {effect["time"] for effect in effects} == {2.5}


def test_morgana_black_shield_uses_typed_magic_pool_and_duration_atoms():
    effects = derive_ally_effects(
        get_champion("Morgana"),
        18,
        {"ability_power": 50.0},
        [{"slot": "E", "time": 1.25}],
        {"E": 5},
    )

    assert len(effects) == 1
    shield = effects[0]
    assert shield["amount"] == pytest.approx(355.0)
    assert shield["duration"] == pytest.approx(5.0)
    assert shield["shield_pool"] == "magic"
    assert shield["crowd_control_immunity_while_shield"] is True
    assert shield["target_selection_key"] == "shield:E:0"
    assert shield["source_atom"]["hash"] == "797fffe3046f726e"
    assert shield["duration_atom"]["hash"] == "106f001ee676d9f2"


@pytest.mark.parametrize(
    ("champion", "slot", "duration", "effect_index"),
    [
        ("Jarvan IV", "W", 4.0, 1),
        ("Olaf", "W", 2.5, 1),
        ("Renata Glasc", "E", 3.0, 1),
        ("Thresh", "W", 4.0, 1),
    ],
)
def test_support_shield_duration_uses_the_typed_shield_sentence(
    champion, slot, duration, effect_index
):
    effects = derive_ally_effects(
        get_champion(champion),
        18,
        {"ability_power": 0.0, "bonus_attack_damage": 0.0},
        [{"slot": slot, "time": 1.0}],
    )

    shield = next(effect for effect in effects if effect["kind"] == "shield")
    assert shield["duration"] == pytest.approx(duration)
    assert shield["duration_atom"]["atom_id"] == "timing.shield_duration"
    assert shield["duration_atom"]["source"].endswith(
        f".effects[{effect_index}].description"
    )


def test_taric_bastion_uses_the_protected_units_max_health_atom():
    effects = derive_ally_effects(
        get_champion("Taric"),
        18,
        {"ability_power": 0.0, "bonus_attack_damage": 0.0, "health": 2000.0},
        [{"slot": "W", "time": 1.0}],
        {"W": 5},
    )

    shield = effects[0]
    assert shield["amount"] == 0.0
    assert shield["amount_formula"](0.0, 2000.0) == pytest.approx(220.0)
    assert shield["amount_formula"](0.0, 2500.0) == pytest.approx(275.0)
    assert shield["amount_formula_atom"]["source"] == (
        "Taric.W[0].effects[1].leveling[0].modifiers[0]"
    )
    assert shield["duration"] == pytest.approx(2.5)


def test_taric_cosmic_radiance_emits_a_delayed_typed_state_packet():
    effects = derive_ally_effects(
        get_champion("Taric"),
        18,
        {"ability_power": 0.0},
        [{"slot": "R", "time": 1.0}],
        {"R": 3},
    )

    assert len(effects) == 1
    state = effects[0]
    assert state["time"] == pytest.approx(3.5)
    assert state["kind"] == "invulnerability"
    assert state["duration"] == pytest.approx(2.5)
    assert state["activation_delay"] == pytest.approx(2.5)
    assert state["target_self"] is True
    assert state["target_scope"] == "self_and_all_teammates"
    assert state["target_selection_key"] == "state:R:0"
    assert state["activation_delay_atom"]["atom_id"] == ("timing.invulnerability_delay")
    assert state["duration_atom"]["atom_id"] == ("timing.invulnerability_duration")
    assert state["activation_delay_atom"]["source"] == (
        "Taric.R[0].effects[0].description"
    )


def test_seraphine_surround_sound_heal_uses_a_typed_live_missing_health_atom():
    effects = derive_ally_effects(
        get_champion("Seraphine"),
        18,
        {"ability_power": 0.0},
        [{"slot": "W", "time": 1.0}],
        {"W": 5},
    )

    heal = next(effect for effect in effects if effect["kind"] == "heal")
    assert heal["time"] == pytest.approx(3.5)
    assert heal["amount"] == 0.0
    assert heal["amount_formula"](1000.0, 2000.0) == pytest.approx(160.0)
    assert heal["amount_formula_atom"] == {
        "atom_id": "ability.heal",
        "behavior": "ability",
        "source": ("Seraphine.W[0].effects[1].leveling[0].modifiers[0]"),
        "values": [8.0, 10.0, 12.0, 14.0, 16.0],
        "units": ["% of target's missing health"] * 5,
        "evidence": ["Heal@effects[1]"],
        "hash": "0327af5b8159cf32",
    }
    assert heal["requires_existing_shield"] is True
    assert heal["shield_gate_target"] == "attacker"
    assert heal["shield_gate_time"] == pytest.approx(1.0)


def test_seraphine_first_pulse_can_use_the_explicit_shield_option():
    effects = derive_ally_effects(
        get_champion("Seraphine"),
        18,
        {"ability_power": 0.0},
        [{"slot": "W", "time": 1.0}],
        {"W": 5},
        champion_options={"w_already_shielded": True},
    )

    heal = next(effect for effect in effects if effect["kind"] == "heal")
    assert heal["requires_existing_shield"] is False
    assert heal["shield_gate_assumed"] is True


@pytest.mark.parametrize(
    ("champion", "slot", "scope"),
    [
        ("Ekko", "W", "self"),
        ("K'Sante", "E", "one_teammate"),
        ("Kassadin", "Q", "self"),
        ("Lee Sin", "W", "self_and_one_teammate"),
        ("Rumble", "W", "self"),
    ],
)
def test_reviewed_self_or_ally_shields_expose_their_target_scope(champion, slot, scope):
    effects = derive_ally_effects(
        get_champion(champion),
        18,
        {"ability_power": 0.0, "bonus_attack_damage": 0.0, "health": 2000.0},
        [{"slot": slot, "time": 1.0}],
        {slot: 5},
    )

    shield = next(effect for effect in effects if effect["kind"] == "shield")
    assert shield["target_scope"] == scope


def test_self_granted_shield_targets_the_caster_without_a_teammate():
    effects = derive_ally_effects(
        get_champion("Annie"),
        12,
        {"ability_power": 0.0},
        [{"slot": "E", "time": 0.0}],
    )

    assert effects == [
        {
            "time": 0.0,
            "kind": "shield",
            "amount": 60.0,
            "source": "Molten Shield · Shield Strength",
            "slot": "E",
            "target_self": True,
            "target_scope": "one_teammate",
            "rank": 1,
            "target_selection_key": "shield:E:0",
            "duration": 3.0,
            "duration_atom": {
                "atom_id": "timing.active_duration",
                "behavior": "timing",
                "source": "Annie.E[0].effects[0].description",
                "values": [3.0],
                "units": ["s"],
                "evidence": ["active duration@effects[0].description"],
                "hash": "cf4f073d11dc6fc7",
            },
        }
    ]


@pytest.mark.parametrize(
    ("champion", "slot"),
    [("Janna", "E"), ("Milio", "E"), ("Zilean", "R")],
)
def test_self_or_target_support_packets_mark_caster_scope(champion, slot):
    ability = get_champion(champion)["abilities"][slot][0]

    _shield, _heal, target_self, target_scope = _support_profile(ability)

    assert target_self is True
    assert target_scope == "one_teammate"


@pytest.mark.parametrize("bad_time", [None, "unknown", True, math.inf, -math.inf])
def test_support_packet_missing_or_invalid_cast_time_fails_closed(bad_time):
    cast = {"slot": "W"}
    if bad_time is not None:
        cast["time"] = bad_time

    with pytest.raises(
        ValueError, match="Support cast W time|missing its sourced time"
    ):
        _sona_effects([cast])
