"""E4-2: summoned-unit damage — Yorick, Zyra, Ivern, Kindred, Maokai.

Each test drives a /api/calculate one-rotation fight (level 18, basic
abilities rank 5, ultimates rank 3, no items, enemy Ahri) and asserts
the sourced pet damage through the combat ledger:

- Yorick: 4 Mist Walkers x 5 attacks of (15 : 100 by level x stat
  progression + 20% AD) physical, plus the Maiden of the Mist 5 attacks
  of (50/100/150 by R rank + 30% AD) magic — game-file constants, not
  in data/champions.json (the ability text points to "See Pets").
- Zyra: 1 plant x 4 attacks of (15 : 75 by level + 20% AP) magic —
  game-file constant (ZyraP PlantDamage).
- Ivern: Daisy 6 attacks = 4 basics of (70/100/130 by R rank + 15% AP)
  physical + 2 Daisy Smash of (90/140/190 by R rank + 50% AP) magic —
  game-file constant (IvernR DataValues).
- Kindred: Wolf 3 attacks of the W "Magic Damage" row (25 : 45 by rank
  + 20% bonus AD + 20% AP + 1.5% (+ 1% per Mark) of current health) —
  read from data/champions.json leveling like every other ability.
- Maokai: brush-empowered Sapling Toss = explosion at 66.7% (1 x "Magic
  Damage per Instance") + 2 attached-Sapling burn ticks — the sourced
  "Total Magic Damage" row, read from data/champions.json.

Expected per-attack values are recomputed from the fight's own
champion_stats (never literal numbers); the pet constants that live
only in the game files are imported from the champion modules, the
single home that documents them.
"""

import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions.ivern import (
    _DAISY_AD_AP_RATIO,
    _DAISY_AD_BY_RANK,
    _DAISY_SMASH_AP_RATIO,
    _DAISY_SMASH_BY_RANK,
)
from src.calculator.champions.yorick import (
    _MAIDEN_AD_RATIO,
    _MAIDEN_BASE_BY_RANK,
    _MIST_WALKER_AD_RATIO,
    _MIST_WALKER_DAMAGE_END,
    _MIST_WALKER_DAMAGE_START,
)
from src.calculator.champions.zyra import (
    _PLANT_AP_RATIO,
    _PLANT_DAMAGE_END,
    _PLANT_DAMAGE_START,
)
from src.calculator.data_fetcher import get_champion
from src.calculator.stats import calculate_total_stats

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
_ENEMY = {
    "champion": "Ahri",
    "level": 18,
    "items": [],
    "role": "mid",
    "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
}
_FULL_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}


def _fight(champion: str, *, options: dict | None = None) -> dict:
    """One /api/calculate one-rotation fight (5s window) at level 18."""
    payload = {
        "champion": champion,
        "level": 18,
        "items": [],
        "role": "top",
        "ability_ranks": dict(_FULL_RANKS),
        "fight_mode": "one_rotation",
        "fight_duration": 10,
        "include_auto_attacks": False,
        "champion_options": options or {},
        "enemies": [_ENEMY],
    }
    app_module.app.config["TESTING"] = True
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _pet_events(data: dict, source: str, per_attack: float) -> list[dict]:
    """The pet's attack events: main-actor, source slot, raw == per-attack."""
    return [
        event
        for event in data["combat"]["events"]
        if event.get("attacker") == "main"
        and event.get("source") == source
        and abs(float(event.get("raw_damage", 0.0)) - per_attack) < 0.06
    ]


def _value(champion: str, slot: str, attribute: str, rank: int) -> float:
    """Sum one leveling row at rank from data/champions.json (rank arrays)."""
    ability = _CHAMPION_DATA[champion]["abilities"][slot][0]
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") != attribute:
                continue
            total = 0.0
            for modifier in leveling.get("modifiers", []):
                values = modifier.get("values", [])
                units = modifier.get("units", [])
                if not values:
                    continue
                idx = min(max(rank, 1) - 1, len(values) - 1)
                unit = units[idx] if idx < len(units) else ""
                if unit in ("", "%"):
                    total += float(values[idx])
                elif unit in ("% bonus AD", "% AP", "% bonus health"):
                    # No items: every scaling stat is 0, so these terms are 0.
                    total += 0.0
                else:
                    raise AssertionError(f"unexpected unit {unit!r} in {attribute}")
            return total
    raise AssertionError(f"{champion} {slot} has no leveling attribute {attribute!r}")


# ---------------------------------------------------------------------------
# Yorick — Mist Walkers (P) + Maiden of the Mist (R)
# ---------------------------------------------------------------------------


def _bonus_ad(data: dict) -> float:
    """The fight response exposes bonus AD; pets price BONUS AD (pass 35)."""
    stats = data["champion_stats"]
    return float(stats.get("bonus_attack_damage", 0.0) or 0.0)


def test_yorick_mist_walkers_attack_in_the_window():
    """4 walkers x 5 attacks = 20 hits of (15 : 100 by level x stat
    progression + 20% BONUS AD) physical; level-18 constant = 100 + 20% bAD."""
    data = _fight("Yorick")
    bad = _bonus_ad(data)
    span = _MIST_WALKER_DAMAGE_END - _MIST_WALKER_DAMAGE_START
    per = (_MIST_WALKER_DAMAGE_START + span * 17 / 17) * (
        0.7025 + 0.0175 * 17
    ) + _MIST_WALKER_AD_RATIO * bad
    assert per == pytest.approx(100.0 + 0.20 * bad)
    events = _pet_events(data, "passive", per)
    assert len(events) == 20
    assert sum(e["raw_damage"] for e in events) == pytest.approx(per * 20, abs=1.0)
    row = data["breakdown"]["passive"]
    assert row["count"] == 20
    assert row["total_damage"] == pytest.approx(
        round(sum(e["damage"] for e in events), 1), abs=1.0
    )


def test_yorick_maiden_attacks_in_the_window():
    """R rank 3: 5 Maiden attacks of (100 + 30% BONUS AD) magic at 1.0 AS."""
    data = _fight("Yorick")
    bad = _bonus_ad(data)
    per = _MAIDEN_BASE_BY_RANK[2] + _MAIDEN_AD_RATIO * bad
    assert per == pytest.approx(100.0 + 0.30 * bad)
    events = _pet_events(data, "R", per)
    assert len(events) == 5
    assert sum(e["raw_damage"] for e in events) == pytest.approx(per * 5, abs=1.0)
    assert data["breakdown"]["R"]["total_damage"] == pytest.approx(
        round(sum(e["damage"] for e in events), 1), abs=0.2
    )


def test_yorick_pet_options_scale_the_counts():
    """mist_walkers / mist_walker_attacks / maiden_attacks are explicit."""
    data = _fight(
        "Yorick",
        options={"mist_walkers": 2, "mist_walker_attacks": 3, "maiden_attacks": 2},
    )
    bad = _bonus_ad(data)
    per_walker = 100.0 + _MIST_WALKER_AD_RATIO * bad
    per_maiden = _MAIDEN_BASE_BY_RANK[2] + _MAIDEN_AD_RATIO * bad
    assert len(_pet_events(data, "passive", per_walker)) == 6
    assert len(_pet_events(data, "R", per_maiden)) == 2


# ---------------------------------------------------------------------------
# Zyra — Thorn Spitter / Vine Lasher plants (W)
# ---------------------------------------------------------------------------


def test_zyra_plant_attacks_in_the_window():
    """1 plant x 4 attacks of (15 : 75 by level + 20% AP) magic at 0.8 AS."""
    data = _fight("Zyra")
    ap = data["champion_stats"]["ability_power"]
    span = _PLANT_DAMAGE_END - _PLANT_DAMAGE_START
    per = _PLANT_DAMAGE_START + span * 17 / 17 + _PLANT_AP_RATIO * ap
    assert per == pytest.approx(75.0 + 0.20 * ap)
    events = _pet_events(data, "W", per)
    assert len(events) == 4
    assert sum(e["raw_damage"] for e in events) == pytest.approx(per * 4, abs=1.0)
    row = data["breakdown"]["W"]
    assert row["total_damage"] == pytest.approx(
        round(sum(e["damage"] for e in events), 1), abs=1.0
    )


def test_zyra_plant_count_multiplies_attacks():
    """Two plants attacking double the priced hits (player-controlled)."""
    data = _fight("Zyra", options={"plant_count": 2, "plant_attacks": 5})
    per = 75.0  # level 18, 0 AP
    assert len(_pet_events(data, "W", per)) == 10


# ---------------------------------------------------------------------------
# Ivern — Daisy (R): basics + third-hit Daisy Smash
# ---------------------------------------------------------------------------


def test_ivern_daisy_attacks_and_knockup_smash_in_the_window():
    """R rank 3: 6 attacks = 4 basics of (130 + 15% AP) physical + 2 Daisy
    Smashes of (190 + 50% AP) magic (every third attack is empowered)."""
    data = _fight("Ivern")
    ap = data["champion_stats"]["ability_power"]
    per_basic = _DAISY_AD_BY_RANK[2] + _DAISY_AD_AP_RATIO * ap
    per_smash = _DAISY_SMASH_BY_RANK[2] + _DAISY_SMASH_AP_RATIO * ap
    assert per_basic == pytest.approx(130.0)
    assert per_smash == pytest.approx(190.0)
    basics = _pet_events(data, "R", per_basic)
    smashes = _pet_events(data, "R", per_smash)
    assert len(basics) == 4
    assert len(smashes) == 2
    assert len(basics) + len(smashes) == 6
    row = data["breakdown"]["R"]
    assert row["total_damage"] == pytest.approx(
        round(sum(e["damage"] for e in basics) + sum(e["damage"] for e in smashes), 1),
        abs=1.0,
    )


def test_ivern_daisy_attack_option_scales_the_count():
    data = _fight("Ivern", options={"daisy_attacks": 3})
    assert len(_pet_events(data, "R", 130.0)) == 2
    assert len(_pet_events(data, "R", 190.0)) == 1


# ---------------------------------------------------------------------------
# Kindred — Wolf's Frenzy (W)
# ---------------------------------------------------------------------------


def test_kindred_wolf_attacks_in_the_window():
    """3 Wolf attacks of the sourced W Magic Damage row; the per-Mark
    current-health term (1.5% + 1% per Mark) resolves exactly."""
    data = _fight("Kindred", options={"marks": 4, "w_attacks": 3})
    enemy_health = calculate_total_stats(get_champion("Ahri"), 18, [])["health"]
    per = 45.0 + (1.5 + 4.0) / 100.0 * enemy_health  # rank 5, 0 bonus AD/AP
    assert per == pytest.approx(45.0 + 0.055 * enemy_health)
    events = _pet_events(data, "W", per)
    assert len(events) == 3
    assert sum(e["raw_damage"] for e in events) == pytest.approx(per * 3, abs=1.0)
    row = data["breakdown"]["W"]
    assert row["total_damage"] == pytest.approx(
        round(sum(e["damage"] for e in events), 1), abs=1.0
    )


def test_kindred_wolf_marks_scale_the_current_health_term():
    """0 marks price only the base 1.5% current-health term; the wiki
    row's per-Mark rider adds 1% per Mark."""
    plain = _fight("Kindred", options={"w_attacks": 1, "marks": 0})
    marked = _fight("Kindred", options={"w_attacks": 1, "marks": 4})
    enemy_health = calculate_total_stats(get_champion("Ahri"), 18, [])["health"]
    per_plain = 45.0 + 0.015 * enemy_health
    per_marked = 45.0 + 0.055 * enemy_health
    assert len(_pet_events(plain, "W", per_plain)) == 1
    assert len(_pet_events(marked, "W", per_marked)) == 1


# ---------------------------------------------------------------------------
# Maokai — Sapling Toss (E): explosion + brush-empowered burn
# ---------------------------------------------------------------------------


def test_maokai_empowered_sapling_prices_explosion_and_burn():
    """Brush-empowered Sapling (default): explosion at 66.7% (1 x Magic
    Damage per Instance) + 2 attached-Sapling burn ticks every 0.75s ==
    the sourced Total Magic Damage row (3 x per-instance at rank 5)."""
    data = _fight("Maokai")
    per_instance = _value("Maokai", "E", "Magic Damage per Instance", 5)
    assert per_instance == pytest.approx(100.0)
    events = _pet_events(data, "E", per_instance)
    assert len(events) == 3
    assert sum(e["raw_damage"] for e in events) == pytest.approx(
        per_instance * 3, abs=1.0
    )
    row = data["breakdown"]["E"]
    assert row["total_damage"] == pytest.approx(
        round(sum(e["damage"] for e in events), 1), abs=1.0
    )
    # The sourced totals: Total Attached Sapling Damage == 2 x per-instance,
    # Total Magic Damage == 3 x per-instance.
    assert _value("Maokai", "E", "Total Attached Sapling Damage", 5) == pytest.approx(
        per_instance * 2
    )
    assert _value("Maokai", "E", "Total Magic Damage", 5) == pytest.approx(
        per_instance * 3
    )


def test_maokai_unempowered_sapling_prices_the_plain_explosion():
    """sapling_empowered=False keeps the reviewed single-explosion packet."""
    data = _fight("Maokai", options={"sapling_empowered": False})
    explosion = _value("Maokai", "E", "Magic Damage", 5)
    assert explosion == pytest.approx(150.0)
    events = _pet_events(data, "E", explosion)
    assert len(events) == 1
    assert data["breakdown"]["E"]["total_damage"] == pytest.approx(
        round(events[0]["damage"], 1), abs=1.0
    )
