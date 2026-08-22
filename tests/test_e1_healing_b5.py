"""Sourced self-heal rules (E1-b5): Rakan, Sona, Janna, Milio, Taric.

Every heal amount below is computed from data/champions.json — flat
leveling values and % AP ratios for the implemented champions — and the
engine's resolved ability power for the fight.  The other three champions
in the batch have a self-heal component in the Wiki data but no sourced
trigger in the 1v1 fight model, so their rules are deliberately not
authored and the tests pin the absence instead:

- Bard W (Caretaker's Shrine): heals "an ally or Bard himself" only when
  the champion walks over the shrine; the amount depends on how long the
  shrine gathered power (Minimum/Maximum Heal).  Bard's module does not
  declare W, so the fight ledger has no W cast rows, no W damage events,
  and no shrine/walk-over state to trigger the heal from.
- Yuumi P (Feline Friendship): heals Yuumi herself only when the
  periodically-stocked empowerment buff is consumed (empowered basic
  attack, Q hit while buffed, or R ally hit while attached).  The module
  models P as a no-damage slot and the ledger contains no empowerment
  state, so every auto/Q event is an unfaithful trigger.
- Zilean R (Chronoshift): heals the target only upon resurrection after
  fatal damage during the duration (a champion-ability revive, which the
  fight engine does not simulate for abilities); it is not a sustain
  self-heal that fires on cast.
"""

import json
import re
from pathlib import Path

import pytest

from src import app as app_module

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_ENEMY = {
    "champion": "Ahri",
    "level": 18,
    "items": [],
    "role": "mid",
    "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
}
_FULL_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _fight(
    champion: str,
    *,
    ap_item: str | None = None,
    ranks: dict | None = None,
) -> dict:
    payload = {
        "champion": champion,
        "level": 18,
        "items": [ap_item] if ap_item else [],
        "role": "mid",
        "ability_ranks": ranks or _FULL_RANKS,
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": True,
        "enemies": [_ENEMY],
    }
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200
    return response.get_json()["combat"]


def _main_heals(combat: dict) -> list[dict]:
    return [
        event
        for event in combat.get("healing_events", [])
        if event.get("attacker") == "main"
    ]


def _main_ap(combat: dict) -> float:
    row = next(
        participant
        for participant in combat["participants"]
        if participant["participant_id"] == "main"
    )
    return float(row["stats"]["ability_power"])


def _leveling_modifier(
    champion: str, slot: str, attribute: str, rank: int, modifier_index: int
) -> float:
    """Read one modifier's raw value at rank from data/champions.json."""
    ability = _CHAMPION_DATA[champion]["abilities"][slot][0]
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") != attribute:
                continue
            modifiers = leveling.get("modifiers", [])
            if modifier_index >= len(modifiers):
                return 0.0
            values = modifiers[modifier_index].get("values", [])
            if not values:
                return 0.0
            return float(values[min(max(rank, 1) - 1, len(values) - 1)])
    raise AssertionError(f"{champion} {slot} has no leveling attribute {attribute!r}")


def _flat_value(champion: str, slot: str, attribute: str, rank: int) -> float:
    """Flat modifier 0 (the base heal at rank/level)."""
    return _leveling_modifier(champion, slot, attribute, rank, 0)


def _ap_ratio_percent(champion: str, slot: str, attribute: str, rank: int) -> float:
    """Modifier 1, expressed as a percentage of AP (wiki "% AP" unit)."""
    return _leveling_modifier(champion, slot, attribute, rank, 1)


def test_rakan_gleaming_quill_heals_per_level_plus_ap():
    """Q marks a radius on a champion hit; 3s later Rakan heals himself.

    The heal is per-LEVEL (20 entries for levels 1-20), not per rank:
    40 : 230 (+ 55% AP) at level 18 -> 210 (+ 55% AP).
    """
    # Keep the Q heal timing isolated from Rakan's separate R charm.
    combat = _fight(
        "Rakan",
        ap_item="Rabadon's Deathcap",
        ranks={"Q": 5, "W": 5, "E": 5, "R": 0},
    )
    ap = _main_ap(combat)
    flat = _flat_value("Rakan", "Q", "Heal", 18)
    ratio = _ap_ratio_percent("Rakan", "Q", "Heal", 18)
    assert flat == pytest.approx(210.0)
    assert ratio == pytest.approx(55.0)
    heals = [
        event for event in _main_heals(combat) if event["source"] == "Gleaming Quill"
    ]
    assert heals, "Gleaming Quill heal missing"
    # The heal fires 3 seconds after the Q hit (no ally enters the radius
    # in a 1v1) and is inside the 10s window.
    in_window = [event for event in heals if event["time"] <= 10.0]
    assert in_window and in_window[0]["time"] == pytest.approx(3.0)
    expected = flat + ratio / 100.0 * ap
    assert in_window[0]["amount"] == pytest.approx(expected, abs=0.06)


def test_sona_aria_of_perseverance_heals_on_w_cast():
    """W heals Sona herself on cast: 30 : 90 (+ 30% AP) by rank."""
    combat = _fight("Sona", ap_item="Rabadon's Deathcap")
    ap = _main_ap(combat)
    flat = _flat_value("Sona", "W", "Heal", 5)
    ratio = _ap_ratio_percent("Sona", "W", "Heal", 5)
    assert flat == pytest.approx(90.0)
    assert ratio == pytest.approx(30.0)
    heals = [
        event
        for event in _main_heals(combat)
        if event["source"] == "Aria of Perseverance"
    ]
    assert heals, "Aria of Perseverance heal missing"
    expected = flat + ratio / 100.0 * ap
    assert heals[0]["amount"] == pytest.approx(expected, abs=0.06)


def test_janna_monsoon_heals_in_sourced_ticks_on_r_channel():
    """R channels 3s, healing every 0.25s: 12 ticks of 25 : 50 (+ 12.5% AP)."""
    combat = _fight("Janna", ap_item="Rabadon's Deathcap")
    ap = _main_ap(combat)
    per_tick = _flat_value("Janna", "R", "Heal Per Tick", 3)
    ratio = _ap_ratio_percent("Janna", "R", "Heal Per Tick", 3)
    total_flat = _flat_value("Janna", "R", "Total Heal", 3)
    assert per_tick == pytest.approx(50.0)
    assert ratio == pytest.approx(12.5)
    assert total_flat == pytest.approx(600.0)
    heals = [event for event in _main_heals(combat) if event["source"] == "Monsoon"]
    assert heals, "Monsoon heal missing"
    assert len(heals) == 12
    expected_per_tick = per_tick + ratio / 100.0 * ap
    assert all(
        event["amount"] == pytest.approx(expected_per_tick, abs=0.06) for event in heals
    )
    assert sum(event["amount"] for event in heals) == pytest.approx(
        total_flat + 150.0 / 100.0 * ap, abs=0.6
    )


def test_milio_breath_of_life_heals_on_r_cast():
    """R heals Milio himself and nearby allies on cast: 150 : 350 (+ 50% AP)."""
    combat = _fight("Milio", ap_item="Rabadon's Deathcap")
    ap = _main_ap(combat)
    flat = _flat_value("Milio", "R", "Heal", 3)
    ratio = _ap_ratio_percent("Milio", "R", "Heal", 3)
    assert flat == pytest.approx(350.0)
    assert ratio == pytest.approx(50.0)
    heals = [
        event for event in _main_heals(combat) if event["source"] == "Breath of Life"
    ]
    assert heals, "Breath of Life heal missing"
    expected = flat + ratio / 100.0 * ap
    assert heals[0]["amount"] == pytest.approx(expected, abs=0.06)


def test_taric_starlights_touch_heals_per_stocked_charge():
    """Q heals Taric himself per charge: 25 (+ 15% AP) (+ 1% max health).

    The stock is the rank-scaled "Maximum Charges" leveling attribute
    (1 : 5 by rank); the per-charge and maximum formulas are wiki
    description text in data/champions.json.
    """
    combat = _fight("Taric", ap_item="Rabadon's Deathcap")
    row = next(
        participant
        for participant in combat["participants"]
        if participant["participant_id"] == "main"
    )
    ap = float(row["stats"]["ability_power"])
    max_health = float(row["stats"]["health"])
    charges = _flat_value("Taric", "Q", "Maximum Charges", 5)
    assert charges == pytest.approx(5.0)
    descriptions = " ".join(
        effect.get("description", "")
        for effect in _CHAMPION_DATA["Taric"]["abilities"]["Q"][0].get("effects", [])
    )
    per_charge_match = re.search(
        r"for\s+(\d+(?:\.\d+)?)\s*\(\+\s*(\d+(?:\.\d+)?)%\s*AP\)"
        r"\s*\(\+\s*(\d+(?:\.\d+)?)%\s*of his maximum health\)\s*per charge",
        descriptions,
        flags=re.IGNORECASE,
    )
    assert per_charge_match is not None
    per_charge = (
        float(per_charge_match.group(1))
        + ap * float(per_charge_match.group(2)) / 100.0
        + max_health * float(per_charge_match.group(3)) / 100.0
    )
    heals = [
        event for event in _main_heals(combat) if event["source"] == "Starlight's Touch"
    ]
    assert heals, "Starlight's Touch heal missing"
    assert heals[0]["amount"] == pytest.approx(charges * per_charge, abs=0.06)


def test_bard_caretakers_shrine_has_no_sourced_fight_trigger():
    """Bard W heals himself only by walking over a placed shrine.

    The module does not declare W, so no cast/damage event can source the
    heal; asserting absence pins that the rule is not fabricated.
    """
    combat = _fight("Bard")
    assert not [
        event
        for event in _main_heals(combat)
        if "Shrine" in event["source"] or event["source"] == "Caretaker's Shrine"
    ]


def test_yuumi_feline_friendship_has_no_sourced_fight_trigger():
    """Yuumi P heals only when the periodic empowerment buff is consumed.

    The model carries no empowerment state (P is a no-damage slot), so
    every Q/auto event would be an unfaithful trigger.
    """
    combat = _fight("Yuumi")
    assert not [
        event for event in _main_heals(combat) if event["source"] == "Feline Friendship"
    ]


def test_zilean_chronoshift_has_no_sourced_fight_trigger():
    """Zilean R heals only upon resurrection after fatal damage.

    Champion-ability revives are not simulated by the fight engine, and
    casting R is not itself a heal, so no sourced self-heal is authored.
    """
    combat = _fight("Zilean")
    assert not [
        event for event in _main_heals(combat) if event["source"] == "Chronoshift"
    ]
