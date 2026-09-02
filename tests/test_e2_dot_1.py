"""E2-1: DoT/channel tick-count fixes — batch 1 (14 champions).

Each test drives a /api/calculate fight (level 18, rank 5 / R rank 3,
no items) through the app test client and asserts, for the worklist
ability:

- the number of per-tick damage events equals the sourced tick count
  (Total / PerTick from data/champions.json, or the duration-derived
  count the module documents — Dr. Mundo W),
- the sum of the per-tick raw damage equals the wiki Total row, within
  the response's 1-decimal rounding (raw_damage is rounded per event,
  so a 26-tick beam can drift by ~0.7; abs=1.0 covers every case).

Every expected number is read from data/champions.json leveling rows,
never hardcoded.

Deliberate deviations, both documented in the modules:
- Dr. Mundo W: the JSON "Total Magic Damage" (80..320) is STALE — it
  still prices 16 ticks from W's pre-V12.23 four-second duration. The
  module prices the 3s / 0.25s charge as 12 ticks (game-file verified),
  so the test asserts per-tick x 12 = 240, not the stale 320.
- Aurelion Sol Q: the "Total Maximum Magic Damage" row has only 4 ranks
  (rank 5 has no practical channel cap), so the beam total is the
  per-second row x the sourced 3.25s channel (26 ticks of the per-tick
  row); the three per-second bursts are asserted separately.
- Kayn Q: the worklist's monster-cap rows cross-check the same 2-tick
  cadence (200/400 .. 400/800); the champion-target fight asserts the
  champion rows (195 x 2 = 390).
"""

import json
from pathlib import Path

import pytest

from src import app as app_module

_DATA = json.loads(
    Path(__file__)
    .resolve()
    .parents[1]
    .joinpath("data", "champions.json")
    .read_text(encoding="utf-8")
)

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
    fight_mode: str = "one_rotation",
    duration: int = 10,
    options: dict | None = None,
    ranks: dict | None = _FULL_RANKS,
    role: str = "top",
) -> dict:
    """Run one /api/calculate fight and return the coupled combat ledger."""
    payload = {
        "champion": champion,
        "level": 18,
        "items": [],
        "role": role,
        "ability_ranks": ranks,
        "fight_mode": fight_mode,
        "fight_duration": duration,
        "include_auto_attacks": False,
        "champion_options": options or {},
        "enemies": [_ENEMY],
    }
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200
    return response.get_json()["combat"]


def _value(
    champion: str,
    slot: str,
    attribute: str,
    rank: int,
    modifier_index: int = 0,
) -> float:
    """Read one modifier's raw value at rank from data/champions.json."""
    ability = _DATA[champion]["abilities"][slot][0]
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


def _tick_events(combat: dict, slot: str, per_tick: float) -> list[dict]:
    """The ability's per-tick events: main-actor, slot, raw == per-tick."""
    return [
        event
        for event in combat.get("events", [])
        if event.get("attacker") == "main"
        and event.get("source") == slot
        and abs(float(event.get("raw_damage", 0.0)) - per_tick) < 0.06
    ]


# ---------------------------------------------------------------------------
# Alistar — E Trample: 10 ticks of 8..20 = Total 80..200
# ---------------------------------------------------------------------------


def test_alistar_trample_prices_all_ten_ticks():
    combat = _fight("Alistar")
    per_tick = _value("Alistar", "E", "Magic Damage Per Tick", 5)
    total = _value("Alistar", "E", "Total Magic Damage", 5)
    ticks = 10
    assert total == pytest.approx(per_tick * ticks)
    events = _tick_events(combat, "E", per_tick)
    assert len(events) == ticks
    assert sum(e["raw_damage"] for e in events) == pytest.approx(total, abs=1.0)
    assert all(e["raw_damage"] == pytest.approx(per_tick, abs=0.06) for e in events)


# ---------------------------------------------------------------------------
# Aurelion Sol — Q Breath of Light beam (26 ticks) + 3 bursts; E Singularity
# (20 ticks = Total 50..150)
# ---------------------------------------------------------------------------


def test_aurelion_sol_breath_of_light_beam_is_twenty_six_ticks():
    """Rank 5: the beam is 26 x per-tick = per-second x 3.25s channel.

    The JSON "Total Maximum Magic Damage" stops at rank 4, so the rank-5
    beam total is the per-second row times the sourced channel ratio
    (Total/per-second == 3.25 at ranks 1-4).
    """
    combat = _fight("AurelionSol")
    per_second = _value("AurelionSol", "Q", "Magic Damage per Second", 5)
    per_tick = _value("AurelionSol", "Q", "Magic Damage per Tick", 5)
    channel_seconds = _value(
        "AurelionSol", "Q", "Total Maximum Magic Damage", 4
    ) / _value("AurelionSol", "Q", "Magic Damage per Second", 4)
    assert channel_seconds == pytest.approx(3.25)
    ticks = round(channel_seconds / (per_tick / per_second))
    assert ticks == 26
    assert per_second * channel_seconds == pytest.approx(per_tick * ticks)
    events = _tick_events(combat, "Q", per_tick)
    assert len(events) == ticks
    assert sum(e["raw_damage"] for e in events) == pytest.approx(
        per_second * channel_seconds, abs=1.0
    )
    # The three per-second bursts are separate sourced events.
    bursts = [
        event
        for event in combat.get("events", [])
        if event.get("attacker") == "main"
        and event.get("source") == "Q"
        and abs(float(event.get("raw_damage", 0.0)) - 100.0) < 0.06
    ]
    assert len(bursts) == 3


def test_aurelion_sol_singularity_prices_all_twenty_ticks():
    combat = _fight("AurelionSol")
    per_tick = _value("AurelionSol", "E", "Magic Damage per Tick", 5)
    total = _value("AurelionSol", "E", "Total Magic Damage", 5)
    ticks = 20
    assert total == pytest.approx(per_tick * ticks)
    events = _tick_events(combat, "E", per_tick)
    assert len(events) == ticks
    assert sum(e["raw_damage"] for e in events) == pytest.approx(total, abs=1.0)


# ---------------------------------------------------------------------------
# Cassiopeia — Q Noxious Blast (7 ticks = Total 75..215); W Miasma
# (5 per-second ticks = Total 100..200)
# ---------------------------------------------------------------------------


def test_cassiopeia_noxious_blast_prices_the_full_poison():
    combat = _fight("Cassiopeia")
    per_tick = _value("Cassiopeia", "Q", "Magic Damage Per Tick", 5)
    total = _value("Cassiopeia", "Q", "Total Magic Damage", 5)
    ticks = 7
    assert total == pytest.approx(per_tick * ticks, abs=0.05)
    events = _tick_events(combat, "Q", total / ticks)
    assert len(events) == ticks
    assert sum(e["raw_damage"] for e in events) == pytest.approx(total, abs=1.0)


def test_cassiopeia_miasma_prices_the_full_zone():
    """Five per-second ticks: Total is exactly 5x the per-second row."""
    combat = _fight("Cassiopeia")
    per_second = _value("Cassiopeia", "W", "Magic Damage Per Second", 5)
    total = _value("Cassiopeia", "W", "Total Magic Damage", 5)
    ticks = 5
    assert total == pytest.approx(per_second * ticks)
    events = _tick_events(combat, "W", total / ticks)
    assert len(events) == ticks
    assert sum(e["raw_damage"] for e in events) == pytest.approx(total, abs=1.0)


# ---------------------------------------------------------------------------
# Corki — W Valkyrie (5 ticks = Total 150..450); E Gatling Gun
# (16 ticks = Total 80..280)
# ---------------------------------------------------------------------------


def test_corki_valkyrie_prices_all_five_patch_ticks():
    combat = _fight("Corki")
    per_tick = _value("Corki", "W", "Magic Damage Per Tick", 5)
    total = _value("Corki", "W", "Total Magic Damage", 5)
    ticks = 5
    assert total == pytest.approx(per_tick * ticks)
    events = _tick_events(combat, "W", total / ticks)
    assert len(events) == ticks
    assert sum(e["raw_damage"] for e in events) == pytest.approx(total, abs=1.0)


def test_corki_gatling_gun_prices_all_sixteen_ticks():
    combat = _fight("Corki")
    per_tick = _value("Corki", "E", "Physical Damage Per Tick", 5)
    total = _value("Corki", "E", "Total Physical Damage", 5)
    ticks = 16
    assert total == pytest.approx(per_tick * ticks)
    events = _tick_events(combat, "E", total / ticks)
    assert len(events) == ticks
    assert sum(e["raw_damage"] for e in events) == pytest.approx(total, abs=1.0)


# ---------------------------------------------------------------------------
# Dr. Mundo — W Heart Zapper: 12 charge ticks (3s @ 0.25s), NOT the stale
# 16-tick Total row
# ---------------------------------------------------------------------------


def test_dr_mundo_heart_zapper_prices_the_game_file_twelve_ticks():
    from src.calculator.champions.dr_mundo import W_CHARGE_TICKS

    combat = _fight("DrMundo")
    per_tick = _value("DrMundo", "W", "Magic Damage per Tick", 5)
    ticks = W_CHARGE_TICKS
    stale_total = _value("DrMundo", "W", "Total Magic Damage", 5)
    # The cached Total (320 = 16 x 20) is stale from the pre-V12.23
    # four-second duration; the game file says 3s / 0.25s = 12 ticks.
    assert stale_total == pytest.approx(per_tick * 16)
    events = _tick_events(combat, "W", per_tick)
    assert len(events) == ticks
    assert sum(e["raw_damage"] for e in events) == pytest.approx(
        per_tick * ticks, abs=1.0
    )
    # The automatic detonation is one separate sourced event.
    detonations = [
        event
        for event in combat.get("events", [])
        if event.get("attacker") == "main"
        and event.get("source") == "W"
        and abs(float(event.get("raw_damage", 0.0)) - 80.0) < 0.06
    ]
    assert len(detonations) == 1


# ---------------------------------------------------------------------------
# Fiddlesticks — R Crowstorm: 20 ticks = Total 750..1750
# ---------------------------------------------------------------------------


def test_fiddlesticks_crowstorm_prices_all_twenty_ticks():
    # Time-based window (10s) so every crow tick lands inside the fight.
    combat = _fight("Fiddlesticks", fight_mode="time_based")
    per_tick = _value("Fiddlesticks", "R", "Magic Damage per Tick", 3)
    total = _value("Fiddlesticks", "R", "Total Magic Damage", 3)
    ticks = 20
    assert total == pytest.approx(per_tick * ticks)
    events = _tick_events(combat, "R", per_tick)
    assert len(events) == ticks
    assert sum(e["raw_damage"] for e in events) == pytest.approx(total, abs=1.0)


# ---------------------------------------------------------------------------
# Fizz — W Seastone Trident passive: 6 ticks = Total Passive 30..90
# ---------------------------------------------------------------------------


def test_fizz_seastone_trident_prices_the_six_tick_passive_burn():
    combat = _fight("Fizz")
    per_tick = _value("Fizz", "W", "Passive Magic Damage per Tick", 5)
    total = _value("Fizz", "W", "Total Passive Magic Damage", 5)
    ticks = 6
    assert total == pytest.approx(per_tick * ticks)
    events = _tick_events(combat, "W", per_tick)
    assert len(events) == ticks
    assert sum(e["raw_damage"] for e in events) == pytest.approx(total, abs=1.0)
    assert all(e["raw_damage"] == pytest.approx(per_tick, abs=0.06) for e in events)


# ---------------------------------------------------------------------------
# Gangplank — R Cannon Barrage: 12 waves = Total 480..1200
# ---------------------------------------------------------------------------


def test_gangplank_cannon_barrage_prices_all_twelve_waves():
    # Time-based window (10s) so every cannon wave lands inside the fight.
    combat = _fight("Gangplank", fight_mode="time_based")
    per_wave = _value("Gangplank", "R", "Magic Damage Per Wave", 3)
    total = _value("Gangplank", "R", "Total Magic Damage", 3)
    ticks = 12
    assert total == pytest.approx(per_wave * ticks)
    events = _tick_events(combat, "R", per_wave)
    assert len(events) == ticks
    assert sum(e["raw_damage"] for e in events) == pytest.approx(total, abs=1.0)


# ---------------------------------------------------------------------------
# Hecarim — W Spirit of Dread: 5 ticks = Total 100..300
# ---------------------------------------------------------------------------


def test_hecarim_spirit_of_dread_prices_all_five_ticks():
    combat = _fight("Hecarim")
    per_tick = _value("Hecarim", "W", "Magic Damage Per Tick", 5)
    total = _value("Hecarim", "W", "Total Magic Damage", 5)
    ticks = 5
    assert total == pytest.approx(per_tick * ticks)
    events = _tick_events(combat, "W", per_tick)
    assert len(events) == ticks
    assert sum(e["raw_damage"] for e in events) == pytest.approx(total, abs=1.0)


# ---------------------------------------------------------------------------
# Hwei — R Spiraling Despair: 12 ticks = Total 30..90, plus the explosion
# ---------------------------------------------------------------------------


def test_hwei_spiraling_despair_prices_all_twelve_ticks():
    combat = _fight("Hwei")
    per_tick = _value("Hwei", "R", "Magic Damage per Tick", 3)
    total = _value("Hwei", "R", "Total Magic Damage", 3)
    ticks = 12
    assert total == pytest.approx(per_tick * ticks)
    events = _tick_events(combat, "R", per_tick)
    assert len(events) == ticks
    assert sum(e["raw_damage"] for e in events) == pytest.approx(total, abs=1.0)
    # The terminal explosion is one separate sourced event.
    explosions = [
        event
        for event in combat.get("events", [])
        if event.get("attacker") == "main"
        and event.get("source") == "R"
        and abs(float(event.get("raw_damage", 0.0)) - 450.0) < 0.06
    ]
    assert len(explosions) == 1


# ---------------------------------------------------------------------------
# Janna — R Monsoon: 12 heal ticks = Total Heal 300..600
# ---------------------------------------------------------------------------


def test_janna_monsoon_heals_in_twelve_sourced_ticks():
    combat = _fight("Janna")
    per_tick = _value("Janna", "R", "Heal Per Tick", 3)
    total = _value("Janna", "R", "Total Heal", 3)
    ticks = 12
    assert total == pytest.approx(per_tick * ticks)
    heals = [
        event
        for event in combat.get("healing_events", [])
        if event.get("attacker") == "main" and event.get("source") == "Monsoon"
    ]
    assert len(heals) == ticks
    assert sum(e["raw_amount"] for e in heals) == pytest.approx(total, abs=1.0)
    assert all(e["raw_amount"] == pytest.approx(per_tick, abs=0.06) for e in heals)


# ---------------------------------------------------------------------------
# Jayce — W Hammer Lightning Field: 4 ticks = Total 140..440 (rank 6)
# ---------------------------------------------------------------------------


def test_jayce_lightning_field_prices_all_four_ticks():
    # Jayce's Q/W/E have six ranks from the skill order (no rank override).
    combat = _fight("Jayce", options={"hammer_stance": True}, ranks=None)
    per_tick = _value("Jayce", "W", "Magic Damage Per Tick", 6)
    total = _value("Jayce", "W", "Total Magic Damage", 6)
    ticks = 4
    assert total == pytest.approx(per_tick * ticks)
    events = _tick_events(combat, "W", total / ticks)
    assert len(events) == ticks
    assert sum(e["raw_damage"] for e in events) == pytest.approx(total, abs=1.0)


# ---------------------------------------------------------------------------
# Kayn — Q Reaping Slash: 2 hits = Total 150..390 (the monster-cap rows
# cross-check the same cadence: 200/400 .. 400/800)
# ---------------------------------------------------------------------------


def test_kayn_reaping_slash_prices_both_hits():
    combat = _fight("Kayn")
    per_hit = _value("Kayn", "Q", "Physical Damage", 5)
    total = _value("Kayn", "Q", "Total Physical Damage", 5)
    monster_per_hit = _value("Kayn", "Q", "Capped Monster Damage per Hit", 5)
    monster_total = _value("Kayn", "Q", "Total Capped Monster Damage", 5)
    ticks = 2
    assert total == pytest.approx(per_hit * ticks)
    assert monster_total == pytest.approx(monster_per_hit * ticks)
    events = _tick_events(combat, "Q", total / ticks)
    assert len(events) == ticks
    assert sum(e["raw_damage"] for e in events) == pytest.approx(total, abs=1.0)


# ---------------------------------------------------------------------------
# Malzahar — E Malefic Visions (16 ticks = Total 80..220); R Nether Grasp
# (10 ticks = Total 125..275)
# ---------------------------------------------------------------------------


def test_malzahar_malefic_visions_prices_all_sixteen_ticks():
    combat = _fight("Malzahar")
    per_tick = _value("Malzahar", "E", "Magic Damage Per Tick", 5)
    total = _value("Malzahar", "E", "Total Magic Damage", 5)
    ticks = 16
    assert total == pytest.approx(per_tick * ticks)
    events = _tick_events(combat, "E", total / ticks)
    assert len(events) == ticks
    assert sum(e["raw_damage"] for e in events) == pytest.approx(total, abs=1.0)
    assert all(e["raw_damage"] == pytest.approx(per_tick, abs=0.06) for e in events)


def test_malzahar_nether_grasp_prices_all_ten_ticks():
    combat = _fight("Malzahar")
    per_tick = _value("Malzahar", "R", "Magic Damage Per Tick", 3)
    total = _value("Malzahar", "R", "Total Magic Damage", 3)
    ticks = 10
    assert total == pytest.approx(per_tick * ticks)
    events = _tick_events(combat, "R", total / ticks)
    assert len(events) == ticks
    assert sum(e["raw_damage"] for e in events) == pytest.approx(total, abs=1.0)
    assert all(e["raw_damage"] == pytest.approx(per_tick, abs=0.06) for e in events)
