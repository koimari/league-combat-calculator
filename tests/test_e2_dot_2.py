"""E2 DoT/channel tick-count fixes (batch 2).

One test per champion pins the fixed multi-tick ability against the wiki
Total row in ``data/champions.json`` via an ``/api/calculate`` fight at
level 18 (basic abilities rank 5, ultimates rank 3, no items).  Target
armor/MR are zeroed so post-mitigation damage equals the raw wiki values,
and the expected per-tick amount is recomputed from the cached leveling
rows plus the fight's own champion stats — every number traces to
``data/champions.json`` (or the E2 worklist ``data/worklists/e2-dot-ticks.json``).

Fixed abilities (per-tick x count == Total at every rank):

- Milio        W Cozy Campfire         25 heal ticks   (Total Heal)
- Miss Fortune E Make It Rain           8 ticks        (Total Magic Damage)
- Wukong       R Cyclone                8 ticks        (Total Physical Damage)
- Naafiri      Q Darkin Daggers        10 bleed ticks  (Total Bleed Physical Damage)
- Nami         E Tidecaller's Blessing  3 empowered hits (Total Bonus Magic Damage)
- Nasus        E Spirit Fire           10 zone ticks   (Total Magic Damage)
- Nasus        R Fury of the Sands     30 ticks        (Total Magic Damage)
- Nidalee      W Bushwhack              4 trap ticks   (Total Magic Damage)
- Nilah        R Apotheosis             4 ticks        (Total Physical Damage)
- Nocturne     E Unspeakable Horror     4 tether ticks (Total Magic Damage)
- Nunu & Willump E Snowball Barrage     3 snowball hits (Total Magic Damage)
- Ornn         W Bellows Breath         5 fire ticks   (Total Magic Damage)
- Rell         R Magnet Storm           8 ticks        (Total Magic Damage)
- Renekton     W Ruthless Predator      2 strikes      (Total Physical Damage)
- Renekton     R Dominus               30 ticks        (Total Magic Damage)
- Samira       W Blade Whirl            2 slashes      (Total Physical Damage)
- Samira       R Inferno Trigger       10 shots        (Total Physical Damage)
"""

import json
import re
from pathlib import Path

import pytest

from src import app as app_module

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
# data/champions.json keys are the scraper slugs ("MissFortune", "Nunu");
# the public display names ("Miss Fortune", "Nunu & Willump") differ.
_CACHE_KEY_BY_DISPLAY = {
    str(value.get("name", "")): key
    for key, value in _CHAMPION_DATA.items()
    if isinstance(value, dict) and str(value.get("name", "")).strip()
}
_FULL_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
# Nidalee is a transformation kit: manual rank allocations are unavailable,
# so its fight uses the level-18 skill-order ranks.
_NO_RANKS_CHAMPIONS = {"Nidalee"}


def _fight(
    champion: str,
    *,
    duration: float = 10.0,
    ranks: dict | None = None,
) -> dict:
    payload = {
        "champion": champion,
        "level": 18,
        "items": [],
        "role": "mid",
        "ability_ranks": ranks,
        "fight_mode": "time_based",
        "fight_duration": duration,
        "include_auto_attacks": False,
        "target_health": 1000,
        "target_armor": 0,
        "target_mr": 0,
    }
    if champion in _NO_RANKS_CHAMPIONS:
        payload["ability_ranks"] = None
    app_module.app.config["TESTING"] = True
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _leveling(champion: str, slot: str, attribute: str) -> dict:
    """Return one leveling entry from data/champions.json, failing loudly."""
    ability = _CHAMPION_DATA[_CACHE_KEY_BY_DISPLAY[champion]]["abilities"][slot][0]
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") == attribute:
                return leveling
    raise AssertionError(f"{champion} {slot} has no leveling attribute {attribute!r}")


def _modifier_value(leveling: dict, modifier_index: int, rank: int) -> float:
    """Raw value of one modifier at rank (the E1 heal-test pattern)."""
    modifiers = leveling.get("modifiers", [])
    if modifier_index >= len(modifiers):
        return 0.0
    values = modifiers[modifier_index].get("values", [])
    if not values:
        return 0.0
    return float(values[min(max(rank, 1) - 1, len(values) - 1)])


def _normalize_unit(unit: str) -> str:
    return re.sub(r"\s+", " ", unit.strip())


def _resolve(
    champion: str,
    slot: str,
    attribute: str,
    rank: int,
    stats: dict,
    target_max_health: float,
) -> float:
    """Sum one leveling entry at rank against the fight's own stats.

    Handles exactly the unit vocabularies the fixed abilities use; an
    unexpected unit fails loudly so the test cannot silently pass with a
    dropped term.
    """
    total = 0.0
    for modifier in _leveling(champion, slot, attribute).get("modifiers", []):
        values = modifier.get("values", [])
        units = modifier.get("units", [])
        if not values:
            continue
        idx = min(max(rank, 1) - 1, len(values) - 1)
        value = float(values[idx])
        unit = _normalize_unit(units[idx]) if idx < len(units) else ""
        if unit in ("", "%"):
            total += value
        elif unit == "% AP":
            total += value / 100.0 * float(stats.get("ability_power", 0.0))
        elif unit == "% AD":
            total += value / 100.0 * float(stats.get("attack_damage", 0.0))
        elif unit == "% bonus AD":
            total += value / 100.0 * float(stats.get("bonus_attack_damage", 0.0))
        elif unit == "% of target's maximum health":
            total += value / 100.0 * target_max_health
        elif unit == "% per 100 AP":
            total += value * float(stats.get("ability_power", 0.0)) / 100.0
        else:
            raise AssertionError(
                f"unhandled unit {unit!r} for {champion} {slot} {attribute}"
            )
    return total


def _assert_ticked_ability(
    champion: str,
    slot: str,
    *,
    per_tick_attr: str,
    count: int,
    duration: float = 10.0,
    initial_attr: str | None = None,
    ranks: dict | None = None,
    recast_attr: str | None = None,
) -> None:
    """Fight one champion and pin total damage + per-tick event count.

    Expected per-cast damage is recomputed from the cached leveling rows:
    ``initial_attr`` (when given) plus ``per_tick_attr`` x ``count``, so
    the assertion verifies per-tick x ticks == the wiki Total independently
    of the module.  ``recast_attr`` names the recast's fresh-target row
    (Naafiri's Minimum Bonus Physical Damage): each cast adds that row,
    and later casts interpolate up to the Maximum row as the target's
    missing health grows, so the row total is bounded by
    ``(initial + ticks + minimum) x casts`` and
    ``(initial + ticks + maximum) x casts``.
    """
    data = _fight(champion, duration=duration, ranks=ranks)
    stats = data["champion_stats"]
    rank = 5 if slot != "R" else 3
    per_tick = _resolve(
        champion, slot, per_tick_attr, rank, stats, data["target_effective_max_health"]
    )
    fixed_per_cast = per_tick * count
    if initial_attr is not None:
        fixed_per_cast += _resolve(
            champion,
            slot,
            initial_attr,
            rank,
            stats,
            data["target_effective_max_health"],
        )
    recast_min = 0.0
    recast_max = 0.0
    if recast_attr is not None:
        recast_min = _resolve(
            champion,
            slot,
            recast_attr,
            rank,
            stats,
            data["target_effective_max_health"],
        )
        recast_max = _resolve(
            champion,
            slot,
            recast_attr.replace("Minimum", "Maximum"),
            rank,
            stats,
            data["target_effective_max_health"],
        )
    row = data["breakdown"][slot]
    casts = max(1, int(row.get("casts", 1)))
    expected_min = (fixed_per_cast + recast_min) * casts
    expected_max = (fixed_per_cast + recast_max) * casts
    assert row["total_damage"] >= expected_min - 1e-6
    assert row["total_damage"] <= expected_max + 1e-6
    # One event per tick (plus the initial hit when the ability has one,
    # plus the recast hit) for every cast the fight schedules.
    expected_events = (
        count
        + (1 if initial_attr is not None else 0)
        + (1 if recast_attr is not None else 0)
    ) * casts
    events = [
        event
        for event in data["damage_events"]
        if event.get("source") == slot and event.get("damage", 0.0) > 0
    ]
    assert len(events) == expected_events, (
        f"{champion} {slot}: expected {expected_events} tick events, "
        f"got {len(events)}"
    )


# ---------------------------------------------------------------------------
# Milio — W Cozy Campfire (heal)
# ---------------------------------------------------------------------------


def test_milio_cozy_campfire_heals_twenty_five_sourced_ticks():
    """W rank 5: "Heal per Tick" 6 (+ 0.6% AP), "Total Heal" 150
    (+ 15% AP) -> 25 ticks of 6 over the 6-second duration."""
    data = _fight("Milio", duration=10, ranks=_FULL_RANKS)
    stats = data["champion_stats"]
    per_tick = _resolve("Milio", "W", "Heal per Tick", 5, stats, 1000)
    total = _resolve("Milio", "W", "Total Heal", 5, stats, 1000)
    assert total / per_tick == pytest.approx(25.0)
    heals = [
        event
        for event in data["self_healing_events"]
        if event.get("source") == "Cozy Campfire"
    ]
    assert len(heals) == 25
    assert all(event["amount"] == pytest.approx(per_tick, rel=1e-6) for event in heals)
    assert sum(event["amount"] for event in heals) == pytest.approx(total, rel=1e-6)


# ---------------------------------------------------------------------------
# Miss Fortune — E Make It Rain
# ---------------------------------------------------------------------------


def test_miss_fortune_make_it_rain_prices_eight_ticks():
    """E rank 5: "Magic Damage Per Tick" 23.75 (+ 15% AP), "Total Magic
    Damage" 190 (+ 120% AP) -> 8 ticks at 0.25s over 2 seconds."""
    _assert_ticked_ability(
        "Miss Fortune",
        "E",
        per_tick_attr="Magic Damage Per Tick",
        count=8,
        ranks=_FULL_RANKS,
    )


# ---------------------------------------------------------------------------
# MonkeyKing — R Cyclone
# ---------------------------------------------------------------------------


def test_monkeyking_cyclone_prices_eight_ticks():
    """R rank 3: "Physical Damage Per Tick" 2 (% max health) + 34.375% AD,
    "Total Physical Damage" 16 (% max health) + 275% AD -> 8 ticks at
    0.25s over the 2-second spin."""
    _assert_ticked_ability(
        "Wukong",
        "R",
        per_tick_attr="Physical Damage Per Tick",
        count=8,
        ranks=_FULL_RANKS,
    )


# ---------------------------------------------------------------------------
# Naafiri — Q Darkin Daggers (initial hit + 10-tick bleed)
# ---------------------------------------------------------------------------


def test_naafiri_darkin_daggers_prices_initial_hit_plus_ten_bleed_ticks():
    """Q rank 5: initial 55 (+ 20% bonus AD) plus "Bleed Physical Damage
    per Tick" 13.5 (+ 8% bonus AD) x10 == "Total Bleed Physical Damage"
    135 (+ 80% bonus AD).  The E9-2 recast bonus (Minimum/Maximum Bonus
    Physical Damage rows interpolated by target missing health) rides the
    same row: the first cast's recast is the fresh-target minimum (80 +
    40% bonus AD) and later casts interpolate up to the maximum as the
    target's health drops, so the row prices the bleed ticks and the
    recast over every scheduled cast (2 casts x 12 events)."""
    _assert_ticked_ability(
        "Naafiri",
        "Q",
        per_tick_attr="Bleed Physical Damage per Tick",
        count=10,
        initial_attr="Initial Physical Damage",
        ranks=_FULL_RANKS,
        recast_attr="Minimum Bonus Physical Damage",
    )


# ---------------------------------------------------------------------------
# Nami — E Tidecaller's Blessing
# ---------------------------------------------------------------------------


def test_nami_tidecallers_blessing_prices_three_empowered_hits():
    """E rank 5: "Bonus Magic Damage Per Hit" 80 (+ 20% AP), "Total Bonus
    Magic Damage" 240 (+ 60% AP) -> 3 empowered hits."""
    _assert_ticked_ability(
        "Nami",
        "E",
        per_tick_attr="Bonus Magic Damage Per Hit",
        count=3,
        ranks=_FULL_RANKS,
    )


# ---------------------------------------------------------------------------
# Nasus — E Spirit Fire (initial hit + 10 zone ticks)
# ---------------------------------------------------------------------------


def test_nasus_spirit_fire_prices_initial_hit_plus_ten_zone_ticks():
    """E rank 5: initial "Magic Damage" 170 (+ 60% AP) plus "Magic Damage
    Per Tick" 34 (+ 12% AP) x10 == "Total Magic Damage" 340 (+ 120% AP)."""
    _assert_ticked_ability(
        "Nasus",
        "E",
        per_tick_attr="Magic Damage Per Tick",
        count=10,
        initial_attr="Magic Damage",
        ranks=_FULL_RANKS,
    )


def test_nasus_fury_of_the_sands_prices_thirty_ticks():
    """R rank 3: "Magic Damage Per Tick" 2.5 (% max health) + 0.5% per 100
    AP, "Total Magic Damage" 75 (% max health) + 15% per 100 AP -> 30
    ticks at 0.5s over the 15-second duration."""
    _assert_ticked_ability(
        "Nasus",
        "R",
        per_tick_attr="Magic Damage Per Tick",
        count=30,
        duration=20.0,
        ranks=_FULL_RANKS,
    )


# ---------------------------------------------------------------------------
# Nidalee — W Bushwhack (human-form trap)
# ---------------------------------------------------------------------------


def test_nidalee_bushwhack_prices_four_trap_ticks():
    """W (level-18 rank 5): "Magic Damage Per Tick" 50 (+ 5% AP), "Total
    Magic Damage" 200 (+ 20% AP) -> 4 ticks at 1s over 4 seconds.  The
    cougar Pounce variant must stay a single hit."""
    _assert_ticked_ability(
        "Nidalee",
        "W",
        per_tick_attr="Magic Damage Per Tick",
        count=4,
    )
    # Pounce variant untouched: one hit, no tick count (level-18 W rank
    # clamps the 4-value Pounce base to its max 190).
    payload = {
        "champion": "Nidalee",
        "level": 18,
        "items": [],
        "role": "mid",
        "ability_ranks": None,
        "champion_options": {"w_variant": 1},
        "fight_mode": "time_based",
        "fight_duration": 10,
        "include_auto_attacks": False,
        "target_health": 1000,
        "target_armor": 0,
        "target_mr": 0,
    }
    app_module.app.config["TESTING"] = True
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_json()
    data = response.get_json()
    row = data["breakdown"]["W"]
    casts = max(1, int(row.get("casts", 1)))
    # Pounce is one hit per cast (6s cooldown -> two casts in 10s).
    assert row["total_damage"] == pytest.approx(190.0 * casts, rel=1e-6)
    pounce_events = [
        event
        for event in data["damage_events"]
        if event.get("source") == "W" and event.get("damage", 0.0) > 0
    ]
    assert len(pounce_events) == casts


# ---------------------------------------------------------------------------
# Nilah — R Apotheosis
# ---------------------------------------------------------------------------


def test_nilah_apotheosis_prices_four_ticks():
    """R rank 3: "Physical Damage per Tick" 35 (+ 10% bonus AD), "Total
    Physical Damage" 140 (+ 40% bonus AD) -> 4 ticks at 0.25s over 1s."""
    _assert_ticked_ability(
        "Nilah",
        "R",
        per_tick_attr="Physical Damage per Tick",
        count=4,
        ranks=_FULL_RANKS,
    )


# ---------------------------------------------------------------------------
# Nocturne — E Unspeakable Horror
# ---------------------------------------------------------------------------


def test_nocturne_unspeakable_horror_prices_four_tether_ticks():
    """E rank 5: "Magic Damage per Tick" 65 (+ 25% AP), "Total Magic
    Damage" 260 (+ 100% AP) -> 4 ticks at 0.5s over the 2-second tether."""
    _assert_ticked_ability(
        "Nocturne",
        "E",
        per_tick_attr="Magic Damage per Tick",
        count=4,
        ranks=_FULL_RANKS,
    )


# ---------------------------------------------------------------------------
# Nunu & Willump — E Snowball Barrage
# ---------------------------------------------------------------------------


def test_nunu_snowball_barrage_prices_three_snowball_hits():
    """E rank 5: "Magic Damage Per Hit" 45 (+ 12% AP), "Total Magic
    Damage" 135 (+ 36% AP) -> 3 snowballs in the volley.  The pinned
    packet previously priced the Snowbound root row (20-60 + 80% AP);
    the per-hit row is sourced from the same ability entry."""
    _assert_ticked_ability(
        "Nunu & Willump",
        "E",
        per_tick_attr="Magic Damage Per Hit",
        count=3,
        ranks=_FULL_RANKS,
    )


# ---------------------------------------------------------------------------
# Ornn — W Bellows Breath
# ---------------------------------------------------------------------------


def test_ornn_bellows_breath_prices_five_fire_ticks():
    """W rank 5: "Magic Damage Per Tick" 3.2 (% max health), "Total Magic
    Damage" 16 (% max health) -> 5 ticks at 0.15s over the 0.75s march."""
    _assert_ticked_ability(
        "Ornn",
        "W",
        per_tick_attr="Magic Damage Per Tick",
        count=5,
        ranks=_FULL_RANKS,
    )


# ---------------------------------------------------------------------------
# Rell — R Magnet Storm
# ---------------------------------------------------------------------------


def test_rell_magnet_storm_prices_eight_ticks():
    """R rank 3: "Magic Damage Per Tick" 43.75 (+ 13.75% AP), "Total Magic
    Damage" 350 (+ 110% AP) -> 8 ticks at 0.25s over 2 seconds."""
    _assert_ticked_ability(
        "Rell",
        "R",
        per_tick_attr="Magic Damage Per Tick",
        count=8,
        ranks=_FULL_RANKS,
    )


# ---------------------------------------------------------------------------
# Renekton — W Ruthless Predator and R Dominus
# ---------------------------------------------------------------------------


def test_renekton_ruthless_predator_prices_two_strikes():
    """W rank 5: "Physical Damage Per Hit" 65 (+ 75% AD), "Total Physical
    Damage" 130 (+ 150% AD) -> 2 strikes."""
    _assert_ticked_ability(
        "Renekton",
        "W",
        per_tick_attr="Physical Damage Per Hit",
        count=2,
        ranks=_FULL_RANKS,
    )


def test_renekton_dominus_prices_thirty_ticks():
    """R rank 3: "Magic Damage Per Tick" 120 (+ 5% bonus AD + 5% AP),
    "Total Magic Damage" 3600 (+ 150% bonus AD + 150% AP) -> 30 ticks at
    0.5s over the 15-second duration."""
    _assert_ticked_ability(
        "Renekton",
        "R",
        per_tick_attr="Magic Damage Per Tick",
        count=30,
        duration=20.0,
        ranks=_FULL_RANKS,
    )


# ---------------------------------------------------------------------------
# Samira — W Blade Whirl and R Inferno Trigger
# ---------------------------------------------------------------------------


def test_samira_blade_whirl_prices_two_slashes():
    """W rank 5: "Physical Damage per Hit" 80 (+ 50% bonus AD), "Total
    Physical Damage" 160 (+ 100% bonus AD) -> 2 slashes."""
    _assert_ticked_ability(
        "Samira",
        "W",
        per_tick_attr="Physical Damage per Hit",
        count=2,
        ranks=_FULL_RANKS,
    )


def test_samira_inferno_trigger_prices_ten_shots():
    """R rank 3: "Physical Damage Per Shot" 60 (+ 30% AD), "Total Physical
    Damage" 600 (+ 300% AD) -> 10 shots at 0.2s intervals.  The minion
    row ("Minion Damage Per Shot" x10 == "Total Minion Damage") is the
    75%-reduced minion branch and does not apply to a champion duel."""
    _assert_ticked_ability(
        "Samira",
        "R",
        per_tick_attr="Physical Damage Per Shot",
        count=10,
        ranks=_FULL_RANKS,
    )
