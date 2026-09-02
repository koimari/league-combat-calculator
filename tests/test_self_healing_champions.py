"""Self-healing audit batch: Sett P (Pit Grit regen) and Maokai P (Sap Magic).

Every asserted number traces to ``data/champions.json``:

- Sett P (Pit Grit): the cached description prose "regenerates an
  additional 0.075 / 0.25 / 0.5 / 1 / 1.025 / 1.05 (based on level) health
  every 0.5 seconds per 5% of his missing health" with the sourced maximum
  row (1.425 / 4.75 / 9.5 / 19 / 19.475 / 19.95, exactly 19x the base row)
  "reached at the threshold of 95% missing health".  The 6-value rows use
  the wiki's standard 1 / 6 / 11 / 16 / 17 / 18 breakpoints (Jax P
  convention).  The regen is always active, so the survival walk re-prices
  each 0.5 s tick from the fighter's live health.
- Maokai P (Sap Magic): "Periodically, Maokai empowers his next basic
  attack ... to heal him for 4% : 12.8% (based on level) maximum health
  after a 0.25-second delay" (cached P).  The P cooldown (30 : 20 seconds
  by level, the cached cooldown array, affectedByCdr: false) is reduced by
  4 seconds per ability cast / sapling champion hit (cached prose); the
  1v1 ledger counts Maokai's own casts plus one sapling hit per E cast and
  does not see incoming enemy strikes (a conservative undercount).  The
  heal fires on the first basic attack after the cooldown completes
  (+0.25s) and does not trigger above 95% maximum health.

The heal amounts are live formulas evaluated by the survival walk, so the
public ``raw_amount`` carries the formula output at each timestamp.
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
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_ENEMY_RANKS = {"Q": 5, "W": 5, "E": 0, "R": 3}


def _fight(
    champion: str,
    *,
    level: int = 18,
    duration: int = 10,
    ranks: dict | None = None,
    autos: bool = True,
    enemy: str = "Ahri",
    enemy_ranks: dict | None = None,
) -> dict:
    payload = {
        "champion": champion,
        "level": level,
        "items": [],
        "role": "top",
        "ability_ranks": ranks or dict(_RANKS),
        "fight_mode": "time_based",
        "fight_duration": duration,
        "include_auto_attacks": autos,
        "champion_options": {},
        "enemies": [
            {
                "champion": enemy,
                "level": 18,
                "items": [],
                "role": "mid",
                "ability_ranks": enemy_ranks or dict(_ENEMY_RANKS),
            }
        ],
    }
    response = app_module.app.test_client().post("/api/calculate", json=payload)
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    return response.get_json()


def _main_heals(data: dict, source: str) -> list[dict]:
    return [
        event
        for event in data["combat"]["healing_events"]
        if event.get("attacker") == "main" and event.get("source") == source
    ]


def _main_incoming(data: dict) -> list[dict]:
    return [e for e in data["combat"]["events"] if e.get("target") == "main"]


def _main_autos(data: dict) -> list[dict]:
    return [
        e
        for e in data["combat"]["events"]
        if e.get("attacker") == "main" and e.get("source") == "auto_attacks"
    ]


def _sett_pit_grit_prose() -> tuple[list[float], list[float]]:
    """Parse the cached Pit Grit regen rows from the P description prose."""
    p_text = (
        " ".join(
            effect.get("description", "")
            for effect in _DATA["Sett"]["abilities"]["P"][0].get("effects", [])
        )
        .replace("[", " ")
        .replace("]", " ")
    )
    import re

    base_match = re.search(
        r"regenerates\s+an additional\s+([\d.\s/]+?)\s*\(based on level\)"
        r"\s*health every 0\.5 seconds per 5% of his missing health",
        p_text,
        flags=re.IGNORECASE,
    )
    max_match = re.search(
        r"up-to an additional\s+([\d.\s/]+?)\s*\(based on level\)"
        r"\s*health per 0\.5 seconds",
        p_text,
        flags=re.IGNORECASE,
    )
    assert base_match
    assert max_match
    return (
        [float(v) for v in re.findall(r"\d+(?:\.\d+)?", base_match.group(1))],
        [float(v) for v in re.findall(r"\d+(?:\.\d+)?", max_match.group(1))],
    )


def _sett_base_at_level(level: int) -> float:
    """Resolve the 6-value Pit Grit base row at the wiki breakpoints."""
    base_values, max_values = _sett_pit_grit_prose()
    breakpoints = (1, 6, 11, 16, 17, 18)
    for index in range(len(breakpoints) - 1, -1, -1):
        if level >= breakpoints[index]:
            base = base_values[index]
            assert max_values[index] == pytest.approx(19 * base)
            return base
    return base_values[0]


# ---------------------------------------------------------------------------
# Sett P — Pit Grit always-on missing-health regen
# ---------------------------------------------------------------------------


def test_sett_pit_grit_ticks_every_half_second_scaled_by_live_missing_health():
    """20 ticks in a 10 s fight; each amount = floor(missing% / 5) x 1.05."""
    data = _fight("Sett")
    heals = _main_heals(data, "Pit Grit")
    assert heals, "Pit Grit regen missing"
    assert len(heals) == 20
    assert [round(h["time"], 1) for h in heals] == pytest.approx(
        [0.5 + 0.5 * i for i in range(20)]
    )
    max_health = data["champion_stats"]["health"]
    base = _sett_base_at_level(18)
    assert base == pytest.approx(1.05)
    incoming = sorted(_main_incoming(data), key=lambda e: e["time"])
    incoming_cum = 0.0
    heal_cum = 0.0
    for heal in heals:
        tick = heal["time"]
        while incoming and incoming[0]["time"] <= tick + 1e-9:
            incoming_cum += incoming.pop(0)["damage"]
        health = max_health - incoming_cum + heal_cum
        missing_pct = max(0.0, max_health - health) / max_health * 100.0
        expected = min(19, int(missing_pct // 5.0)) * base
        assert heal["raw_amount"] == pytest.approx(
            expected, abs=0.15
        ), f"tick {tick}: health {health:.1f}, missing {missing_pct:.1f}%"
        assert heal["applied_amount"] == pytest.approx(expected, abs=0.15)
        heal_cum += heal["applied_amount"]
    # The fighter takes real damage, so later ticks must exceed the opener.
    assert heals[-1]["raw_amount"] > heals[0]["raw_amount"]


def test_sett_pit_grit_base_row_scales_with_level():
    """Level 6 uses the 0.25 base row; every tick stays inside 19x it."""
    data = _fight("Sett", level=6, ranks={"Q": 3, "W": 3, "E": 0, "R": 0})
    heals = _main_heals(data, "Pit Grit")
    assert heals, "Pit Grit regen missing at level 6"
    base = _sett_base_at_level(6)
    assert base == pytest.approx(0.25)
    for heal in heals:
        assert 0.0 <= heal["raw_amount"] <= 19 * base + 0.15
    # Every tick is a whole number of 5% segments of the live missing
    # health: raw / base must be an integer in [0, 19].
    for heal in heals:
        segments = heal["raw_amount"] / base
        assert segments == pytest.approx(round(segments), abs=0.25), heal
        assert 0 <= round(segments) <= 19


def test_sett_pit_grit_is_an_actor_wide_regen_stream():
    """The regen is a fight-wide stream, not tied to one damage packet."""
    data = _fight("Sett")
    heals = _main_heals(data, "Pit Grit")
    assert len(heals) == 20
    assert all(h["time"] == pytest.approx(0.5 + 0.5 * i) for i, h in enumerate(heals))


# ---------------------------------------------------------------------------
# Maokai P — Sap Magic cooldown-driven empowered-attack heal
# ---------------------------------------------------------------------------


def _maokai_sap_magic_expected(data: dict) -> tuple[float, float]:
    """Recompute the Sap Magic heal (time, amount) from cached data and the
    fight's own ledger: cooldown (level) - 4 s per outgoing trigger, first
    auto after completion + 0.25 s, % max health by level."""

    level = int(data["champion_stats"]["level"])
    p = _DATA["Maokai"]["abilities"]["P"][0]
    cooldown_values = [float(v) for v in p["cooldown"]["modifiers"][0]["values"]]
    cooldown = cooldown_values[min(level - 1, len(cooldown_values) - 1)]
    pct = 0.0
    for effect in p.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") != "Max Health Damage":
                continue
            values = leveling["modifiers"][0]["values"]
            pct = float(values[min(level - 1, len(values) - 1)])
    triggers: dict[float, int] = {}
    for cast in data.get("cast_timeline", []):
        slot = cast.get("slot")
        if slot not in {"Q", "W", "E", "R"}:
            continue
        triggers[float(cast["time"])] = triggers.get(float(cast["time"]), 0) + (
            2 if slot == "E" else 1
        )
    auto_times = sorted(e["time"] for e in _main_autos(data))
    # Completion time: smallest t with t + 4 x triggers(<=t) >= cooldown.
    trigger_count = 0
    previous = 0.0
    completed = None
    for trigger_time in sorted(triggers):
        trigger_count += triggers[trigger_time]
        candidate = cooldown - 4.0 * trigger_count
        if candidate <= trigger_time + 1e-9:
            earlier = cooldown - 4.0 * (trigger_count - triggers[trigger_time])
            completed = (
                max(previous, earlier)
                if earlier <= trigger_time + 1e-9
                else trigger_time
            )
            break
        previous = trigger_time
    if completed is None:
        completed = cooldown - 4.0 * trigger_count
    next_auto = next((t for t in auto_times if t >= completed - 1e-9), None)
    assert next_auto is not None, "expected an empowered attack"
    heal_time = next_auto + 0.25
    max_health = data["champion_stats"]["health"]
    return heal_time, pct / 100.0 * max_health


def test_maokai_sap_magic_heals_sourced_percent_after_cooldown_completes():
    """Level 18: one heal at first auto after completion (+0.25s), 12.8%."""
    data = _fight("Maokai")
    heals = _main_heals(data, "Sap Magic")
    assert heals, "Sap Magic heal missing"
    expected_time, expected_amount = _maokai_sap_magic_expected(data)
    assert len(heals) == 1
    assert heals[0]["time"] == pytest.approx(expected_time, abs=0.01)
    assert heals[0]["raw_amount"] == pytest.approx(expected_amount, abs=0.15)
    assert heals[0]["applied_amount"] == pytest.approx(expected_amount, abs=0.15)
    # The heal is anchored to the empowered basic attack.
    assert heals[0]["trigger_event_id"] is not None
    # 12.8% of 2518 health at level 18.
    assert expected_amount == pytest.approx(0.128 * data["champion_stats"]["health"])


def test_maokai_sap_magic_without_ultimate_delays_the_proc():
    """R rank 0 removes one trigger: real time must carry the cooldown."""
    data = _fight("Maokai", ranks={"Q": 5, "W": 5, "E": 5})
    heals = _main_heals(data, "Sap Magic")
    assert heals, "Sap Magic heal missing without R"
    expected_time, expected_amount = _maokai_sap_magic_expected(data)
    assert len(heals) == 1
    assert heals[0]["time"] == pytest.approx(expected_time, abs=0.01)
    assert heals[0]["raw_amount"] == pytest.approx(expected_amount, abs=0.15)


def test_maokai_sap_magic_does_not_trigger_above_95_percent_health():
    """A damage-free enemy leaves Maokai above 95%: the proc pays zero."""
    # Zilean with no ability ranks deals only basic-attack damage (~50),
    # so at the first empowered attack Maokai is still above 95% health
    # and Sap Magic's live gate returns 0.
    data = _fight(
        "Maokai",
        enemy="Zilean",
        enemy_ranks={"Q": 0, "W": 0, "E": 0, "R": 0},
    )
    heals = _main_heals(data, "Sap Magic")
    assert heals, "expected a gated Sap Magic receipt"
    assert len(heals) == 1
    assert heals[0]["raw_amount"] == pytest.approx(0.0, abs=0.05)
    assert heals[0]["applied_amount"] == pytest.approx(0.0, abs=0.05)


def test_maokai_sap_magic_requires_a_basic_attack():
    """With auto attacks disabled the empowered attack never happens."""
    data = _fight("Maokai", autos=False)
    assert not _main_heals(data, "Sap Magic")


def test_maokai_sap_magic_second_proc_in_a_longer_fight():
    """The cooldown restarts after a proc; a 20 s fight pays two heals."""
    data = _fight("Maokai", duration=20)
    heals = _main_heals(data, "Sap Magic")
    assert len(heals) == 2
    first_time, first_amount = _maokai_sap_magic_expected(data)
    assert heals[0]["time"] == pytest.approx(first_time, abs=0.01)
    assert heals[0]["raw_amount"] == pytest.approx(first_amount, abs=0.15)
    assert heals[1]["time"] > heals[0]["time"]
    assert heals[1]["raw_amount"] == pytest.approx(first_amount, abs=0.15)
