"""Unending Despair's sourced periodic damage and self-heal ledger."""

import math

from src.calculator.data_fetcher import fetch_item_data, get_champion, get_item_by_name
from src.calculator.interpreters import periodic
from src.calculator.passive_parser import parse_item_effect
from src.calculator.pipeline import FightParams, _item_self_healing_events, run_fight


def _periodic_slots(*owners: str) -> periodic.PeriodicSlots:
    """The periodic strikes a build declares, read through their rules."""
    return periodic.resolve_slots(
        owners,
        level=18,
        fight_duration_seconds=10.0,
        target_bonus_health=0.0,
        holder_is_melee=False,
    )


def _timed_params(duration: float = 8.0) -> FightParams:
    return FightParams(
        target_health=3000.0,
        target_armor=100.0,
        target_magic_resistance=100.0,
        fight_duration_seconds=duration,
        one_rotation=False,
        auto_attack_uptime=0.8,
    )


def test_anguish_parser_reads_post_mitigation_self_heal_multiplier():
    """The cached Anguish branch supplies all periodic and healing values."""
    parsed = dict(parse_item_effect("Unending Despair", fetch_item_data()) or {})
    assert parsed

    assert parsed["interval"] == 4.0
    assert parsed["range_units"] == 650.0
    assert parsed["bonus_hp_ratio"] == 0.03
    assert parsed["self_heal_post_mitigation_multiplier"] == 2.5


def test_anguish_emits_exact_periodic_damage_and_self_healing_events():
    """Each four-second damage pulse creates one post-mitigation heal event."""
    result = run_fight(
        get_champion("Ahri"),
        18,
        [get_item_by_name("Unending Despair")],
        _timed_params(),
    )
    row = result["breakdown"]["periodic_Unending Despair"]
    damage_events = row["damage_events"]
    healing_events = result["self_healing_events"]
    multiplier = (
        _periodic_slots("Unending Despair")
        .intervals[0]
        .self_heal_post_mitigation_multiplier
    )

    assert [event["time"] for event in damage_events] == [4.0, 8.0]
    assert all(event["event_precision"] == "exact" for event in damage_events)
    assert all(event["target_range_units"] == 650.0 for event in damage_events)
    assert all(
        event["target_scope"] == "enemy_champions_within_range"
        for event in damage_events
    )
    # Ahri's E9-2 Essence Theft passive heal (95, 0 AP) lands first in the
    # shared ledger; the Anguish heal events follow the damage pulses.
    item_heals = [
        event for event in healing_events if event["source"] != "Essence Theft"
    ]
    assert [event["time"] for event in item_heals] == [4.0, 8.0]
    assert all(
        event["amount"] == event_damage["damage"] * multiplier
        for event, event_damage in zip(item_heals, damage_events)
    )
    assert result["self_healing"] == sum(event["amount"] for event in healing_events)


def test_anguish_malformed_periodic_rows_are_withheld():
    """Malformed timestamps do not fabricate an item-healing receipt."""
    result = {
        "breakdown": {
            "periodic_Unending Despair": {
                "name": "Unending Despair (Anguish)",
                "self_heal_post_mitigation_multiplier": 2.5,
                "damage_events": [
                    {"time": math.nan, "damage": 10.0},
                    {"time": 2.0, "damage": 5.0},
                ],
            }
        }
    }

    events = _item_self_healing_events(result)

    assert len(events) == 1
    assert events[0]["time"] == 2.0
    assert events[0]["amount"] == 12.5
