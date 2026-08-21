"""P1 Package 3Z — Heimerdinger W/E degraded multi-part rocket + grenade
behavior (test-matrix owner: RLM-2 C).

Focused TDD matrix for Heimerdinger's W (Hextech Micro-Rockets) and E
(CH-2 Electron Storm Grenade) multi-part behavior.  CURRENT RUNTIME FACTS
(pinned below, verify-before-pin completed):

- The module (``src/calculator/champions/heimerdinger.py``) reads the
  DEGRADED wiki rows via ``extract_named``: W prices
  "Initial Rocket Magic Damage" (first) + "Subsequent Rocket Magic
  Damage" (later) with the ``w_rockets`` option (default 5, 1..5) as
  ``DamagePart(magic, first, time_offset=0.25)`` +
  ``DamagePart(magic, later, count=rockets-1, time_offset=0.35,
  hit_interval=0.08)``; E prices the base "Magic Damage" row
  (``e_upgrade`` 0) or the upgraded branch (``e_upgrade`` 1:
  100/200/300 by R rank + 60% AP — the module's hardcoded tuple beside
  the degraded attribute row ``"100 / 200 / 300 (+ 60% AP)"`` whose
  modifiers are empty) as one ``DamagePart(magic, value,
  time_offset=0.6)``; R is an empowerment toggle (``no_damage``).
- The known-degraded parse: the W/E leveling rows' ``units`` arrays come
  back empty where the value lives, and the upgraded-E/swarm values
  survive only as attribute TEXT with empty modifiers — the module names
  the explicit rows instead of trusting the generic path.
- The W/E public receipts (the parts) are present in the parse and the
  fight result; W/E cooldowns (7/11) and mana (90/85) come from the
  cached rows; the upgraded E keeps the base grenade's 11s cooldown and
  the engine stamps the base entry's 85 mana (the wiki R prose says
  empowered abilities have "no mana cost" — divergence flagged for the
  coordinator).
- Verified boundary (pinned actual): the parse path clamps
  ``w_rockets`` to [1,5] and ``e_upgrade`` to [0,1] and ``int()``s float
  seeds (2.5 == 2); the strict 1..5 / 0..1 boundary lives at the API
  (named 400 receipts).  R rank clamps to 1..3, so ``e_upgrade=1`` with
  R unlearned prices the R1 value (100).
- The options carry NO ``state`` receipt today and there is NO W/E
  documentary walk or denial surface (no resource_ledger sub-account,
  no informational breakdown row, empty notes); missing W/E leveling
  rows today yield a SILENT zero-total_raw entry (pinned actual,
  flagged).  Genuinely-absent mechanics are ``xfail`` with reason
  "awaiting P3-3Z ...": the coordinator's completion mirrors the
  3W/3X/3Y pattern (typed W/E declarations + option state receipts, a
  documentary post-rotation walk over the accepted engine-priced
  stream, named fail-closed denials for the unsupported multi-target
  claims — rocket fan spread, grenade bounces, stun/slow control,
  1000-range fan, turret targeting/beam charge, the upgraded-W swarm)
  WITHOUT re-pricing mid-fight (stats stay parse-time; the walk
  documents).

Contract sections (numbered as in the RLM-2 C brief):
  S1  Source evidence + typed values (W first/subsequent + E base rows
      recomputed from ``data/champions.json`` — no literal damage
      constants except the module's hardcoded upgraded-E tuple and the
      authored timing pins; W/E public receipts in parse + fight result).
  S2  W first-vs-subsequent (rocket count = w_rockets; 1 = first only,
      5 = 1 first + 4 later; per-part amounts; total = first +
      later x (n-1)).
  S3  Rocket timing (0.25 first / 0.35 subsequent @ 0.08 — the
      damage_events' times in the fight result).
  S4  E variants (base e_upgrade 0 from the cached "Magic Damage" row;
      upgraded e_upgrade 1 = 100/200/300 + 60% AP by R rank; the
      grenade one-instance pin).
  S5  Options (w_rockets 1..5 default 5; e_upgrade 0..1 default 0;
      metadata; API 0/6/2/non-numeric named 400s; parse-path behavior).
  S6  Target policy (the multi-target claims — rocket fan spread,
      grenade bounce multi-hit, 1000-range fan, turret targeting —
      are named unmodeled assumptions today with NO invented multi-
      target damage; the coordinator's named fail-closed denials are
      xfailed).
  S7  Malformed inputs (bad options fail closed today; missing rows are
      a silent zero today — the fail-closed contract is xfailed).
  S8  Unchanged boundaries (Q turret shots/beams/cadence/variants, the
      R toggle, the P, the W/E cooldowns, the existing options).
  S9  Score/receipt parity (W/E surface byte-identical under
      score_only; the upgraded branch is never re-priced mid-fight).
  S10 Regression surface: the mandated sanity list plus every test that
      touches heimerdinger (grep tests/) stays green (run list in the
      module footer).

Expected damage values are recomputed from ``data/champions.json``
leveling rows against the fight's own stats — no literal damage
constants.  The upgraded-E tuple (100/200/300 + 60% AP) and the timing
pins (0.25 / 0.35 @ 0.08 / 0.6) ARE the values under test (the module
itself hardcodes them beside the degraded wiki rows).
"""

import copy
import json
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions import (
    get_champion_options_meta,
    parse_champion_abilities,
)
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
# The exact cached champion name (dispatcher and data-file key agree here).
_HEIMER_DATA = _CHAMPION_DATA["Heimerdinger"]
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_LEVEL = 18
_TARGET_MAX_HP = 2000.0
# The P3-3Z coordinator wires the typed W/E declarations and the
# documentary walk; genuinely-absent mechanics are xfailed with this reason.
_AWAIT = "awaiting P3-3Z wiring"

# Contract constants under test (module-authored beside the degraded wiki
# rows; the values the option state receipts will publish).
_W_FIRST_TIME_OFFSET = 0.25
_W_LATER_TIME_OFFSET = 0.35
_W_HIT_INTERVAL = 0.08
_E_TIME_OFFSET = 0.6
_E_UPGRADED_VALUES = (100.0, 200.0, 300.0)
_E_UPGRADED_AP_RATIO = 0.60


def _stats() -> dict:
    return {
        "ability_haste": 0.0,
        "armor_penetration_bonus_percent": 0.0,
        "armor_penetration_percent": 0.0,
        "basic_ability_haste": 0.0,
        "bonus_health": 0.0,
        "bonus_mana": 0.0,
        "critical_strike_chance": 0.0,
        "flat_armor_penetration": 0.0,
        "health": 0.0,
        "is_melee": True,
        "lethality": 0.0,
        "magic_penetration_flat": 0.0,
        "magic_penetration_percent": 0.0,
        "move_speed": 0.0,
        "omnivamp_percent": 0.0,
        "ultimate_haste": 0.0,
        "attack_damage": 100.0,
        "ability_power": 0.0,
        "base_attack_damage": 60.0,
        "bonus_attack_damage": 40.0,
        "attack_speed": 0.8,
        "attack_speed_ratio": 0.625,
        "bonus_attack_speed": 0.0,
        "max_mana": 300.0,
        "resource_regen_per_second": 0.0,
        "level": _LEVEL,
    }


def _parse(option: dict | None, *, ap: float = 0.0, ranks: dict | None = None):
    stats = dict(_stats(), ability_power=ap)
    return stats, parse_champion_abilities(
        get_champion("Heimerdinger"),
        _LEVEL,
        ap,
        ability_ranks=ranks or _RANKS,
        champion_stats=stats,
        target_stats={"target_max_health": _TARGET_MAX_HP},
        champion_options=option,
    )


def _fight(
    option: dict,
    *,
    duration: float = 10.0,
    uptime: float = 1.0,
    score_only: bool = False,
    one_rotation: bool = False,
    ap: float = 0.0,
    ranks: dict | None = None,
    items: list[dict] | None = None,
    cast_order: list[str] | None = None,
    target_health: float = _TARGET_MAX_HP,
) -> dict:
    stats, abilities = _parse(option, ap=ap, ranks=ranks)
    return calculate_fight_damage(
        stats,
        abilities,
        items or [],
        FightConfig(
            target_health=target_health,
            target_armor=50,
            target_magic_resistance=40,
            fight_duration_seconds=duration,
            auto_attack_uptime=uptime,
            one_rotation=one_rotation,
            deterministic=True,
            enforce_resource_limits=True,
            cast_order=(cast_order if cast_order is not None else ["Q", "W", "E", "R"]),
        ),
        score_only=score_only,
        champion_options=dict(option),
    )


def _api(option: dict):
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "Heimerdinger",
            "level": _LEVEL,
            "items": [],
            "role": "mid",
            "ability_ranks": _RANKS,
            "fight_mode": "one_rotation",
            "fight_duration": 10,
            "include_auto_attacks": False,
            "target_health": _TARGET_MAX_HP,
            "target_armor": 50,
            "target_mr": 40,
            "champion_options": option,
        },
    )


def _leveling(slot: str, attribute: str, index: int = 0) -> dict:
    """The first leveling row named *attribute* in one ability entry."""
    ability = _HEIMER_DATA["abilities"][slot][index]
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") == attribute:
                return leveling
    raise AssertionError(f"Heimerdinger {slot}[{index}] has no leveling {attribute!r}")


def _resolve(
    slot: str, attribute: str, rank: int, stats: dict, index: int = 0
) -> float:
    """Recompute one slot value from the cached leveling rows (flat + % AP).

    The degraded W/E rows carry the values with empty/descriptive units;
    the only units these packets use are "" (flat) and "% AP".
    """
    total = 0.0
    for modifier in _leveling(slot, attribute, index).get("modifiers", []):
        values = modifier.get("values", [])
        units = modifier.get("units", [])
        if not values:
            continue
        idx = min(rank - 1, len(values) - 1)
        value = float(values[idx])
        unit = str(units[idx]).strip() if idx < len(units) else ""
        if unit == "":
            total += value
        elif unit == "% AP":
            total += value / 100.0 * stats["ability_power"]
        else:
            raise AssertionError(f"unhandled unit {unit!r} in {slot} {attribute}")
    return total


def _parse_with_stripped_rows(slot: str, option: dict | None = None) -> dict:
    """Parse a deep copy of the cached data with one slot's rows removed."""
    data = copy.deepcopy(get_champion("Heimerdinger"))
    for entry in data["abilities"][slot]:
        for effect in entry.get("effects", []):
            effect["leveling"] = []
    return parse_champion_abilities(
        data,
        _LEVEL,
        0.0,
        ability_ranks=_RANKS,
        champion_stats=_stats(),
        target_stats={"target_max_health": _TARGET_MAX_HP},
        champion_options=option or {},
    )


def _we_walk(result: dict) -> dict | None:
    """The P3-3Z documentary W/E walk wherever the coordinator lands it.

    Pinned contract (S6): either an informational breakdown row (the 3V
    ferocity shape), or a resource_ledger sub-account (the 3W souls / 3X
    stardust / 3Y chimes shape), or a notes entry.  Returns None while
    the P3-3Z wiring is absent.
    """
    for key in ("rockets", "grenade", "w_e", "we_walk"):
        row = result.get("breakdown", {}).get(key)
        if isinstance(row, dict):
            return row
    section = result.get("resource_ledger")
    if isinstance(section, dict):
        for key in ("rockets", "grenade", "w_e"):
            sub = section.get(key)
            if isinstance(sub, dict):
                return sub
    notes = result.get("notes")
    if notes:
        joined = json.dumps(notes).lower()
        if "rocket" in joined or "grenade" in joined:
            return {"notes": notes}
    return None


def _denial_reasons(result: dict) -> list[str]:
    """Fail-closed denial reasons anywhere the walk may receipt them."""
    reasons: list[str] = []
    walk = _we_walk(result)
    if walk:
        receipts = walk.get("receipts", [])
        if isinstance(receipts, list):
            for row in receipts:
                if not row.get("accepted", True):
                    reasons.append(str(row.get("reason", "")))
    for row in result.get("resource_ledger", {}).get("receipts", []):
        if not row.get("accepted", True):
            reasons.append(str(row.get("reason", "")))
    for note in result.get("notes") or []:
        if isinstance(note, dict):
            reasons.append(str(note.get("reason", note.get("message", ""))))
    return reasons


# ---------------------------------------------------------------------------
# S1 — Source evidence + typed values
# ---------------------------------------------------------------------------


class TestSourceAndTypedValues:
    def test_w_values_recomputed_from_cached_rows(self):
        # The typed parse path prices W from the cached leveling rows:
        # "Initial Rocket Magic Damage" 50..150 + 55% AP, "Subsequent
        # Rocket Magic Damage" 10..30 + 12% AP.
        for rank in range(1, 6):
            stats, abilities = _parse({}, ranks={**_RANKS, "W": rank})
            first = _resolve("W", "Initial Rocket Magic Damage", rank, stats)
            later = _resolve("W", "Subsequent Rocket Magic Damage", rank, stats)
            w = abilities["W"]
            assert w["parts"][0].amount == pytest.approx(first)
            assert w["parts"][1].amount == pytest.approx(later)
            assert w["total_raw"] == pytest.approx(first + later * 4)
        stats, abilities = _parse({}, ap=100.0)
        first = _resolve("W", "Initial Rocket Magic Damage", 5, stats)
        later = _resolve("W", "Subsequent Rocket Magic Damage", 5, stats)
        assert abilities["W"]["parts"][0].amount == pytest.approx(first)
        assert abilities["W"]["parts"][1].amount == pytest.approx(later)
        assert abilities["W"]["total_raw"] == pytest.approx(first + later * 4)

    def test_e_base_value_recomputed_from_cached_row(self):
        # The base grenade (e_upgrade 0) prices the cached "Magic Damage"
        # row: 60..220 + 60% AP.
        for rank in range(1, 6):
            stats, abilities = _parse({"e_upgrade": 0}, ranks={**_RANKS, "E": rank})
            want = _resolve("E", "Magic Damage", rank, stats)
            assert abilities["E"]["parts"][0].amount == pytest.approx(want)
            assert abilities["E"]["total_raw"] == pytest.approx(want)
        stats, abilities = _parse({"e_upgrade": 0}, ap=100.0)
        assert abilities["E"]["total_raw"] == pytest.approx(
            _resolve("E", "Magic Damage", 5, stats)
        )

    def test_upgraded_e_tuple_pinned_by_r_rank(self):
        # The upgraded branch is the module's hardcoded tuple beside the
        # degraded attribute row: 100/200/300 + 60% AP by R rank.  R rank
        # clamps to 1..3, so R 0 prices the R1 value and R 4 the R3 value.
        for r_rank, want in ((1, 100.0), (2, 200.0), (3, 300.0)):
            _, abilities = _parse({"e_upgrade": 1}, ranks={**_RANKS, "R": r_rank})
            assert abilities["E"]["total_raw"] == pytest.approx(want)
        _, abilities = _parse({"e_upgrade": 1}, ranks={**_RANKS, "R": 0})
        assert abilities["E"]["total_raw"] == pytest.approx(100.0)
        _, abilities = _parse({"e_upgrade": 1}, ranks={**_RANKS, "R": 4})
        assert abilities["E"]["total_raw"] == pytest.approx(300.0)
        _, abilities = _parse({"e_upgrade": 1}, ap=100.0)
        assert abilities["E"]["total_raw"] == pytest.approx(360.0)

    def test_w_e_public_receipts_present_in_parse(self):
        # The W/E public receipts (the parts) at parse level: names,
        # ranks, cooldowns, per-part amounts/counts/timing, totals.
        _, abilities = _parse({})
        w, e = abilities["W"], abilities["E"]
        assert w["name"] == "Hextech Micro-Rockets"
        assert w["rank"] == 5
        assert w["cooldown"] == pytest.approx(7.0)
        assert w["damage_type"] == "magic"
        assert len(w["parts"]) == 2
        first, later = w["parts"]
        assert (first.amount, first.count, first.time_offset) == pytest.approx(
            (150.0, 1, 0.25)
        )
        assert (later.amount, later.count) == pytest.approx((30.0, 4))
        assert later.time_offset == pytest.approx(0.35)
        assert later.hit_interval == pytest.approx(0.08)
        assert w["total_raw"] == pytest.approx(270.0)
        assert "reduced champion damage row" in w["detail"]
        assert e["name"] == "CH-2 Electron Storm Grenade"
        assert e["rank"] == 5
        assert e["cooldown"] == pytest.approx(11.0)
        assert len(e["parts"]) == 1
        assert e["parts"][0].amount == pytest.approx(220.0)
        assert e["parts"][0].time_offset == pytest.approx(0.6)
        assert e["total_raw"] == pytest.approx(220.0)
        assert "One champion damage instance" in e["detail"]

    def test_w_e_public_receipts_present_in_fight_result_and_api(self):
        # The W/E receipt surface is visible in the fight result and the
        # API payload: names, details, casts, totals.
        result = _fight({"w_rockets": 5, "e_upgrade": 1}, one_rotation=True)
        assert result["breakdown"]["W"]["name"] == "Hextech Micro-Rockets"
        assert result["breakdown"]["W"]["total_raw"] == pytest.approx(270.0)
        assert result["breakdown"]["E"]["name"] == "CH-3X Lightning Grenade"
        assert result["breakdown"]["E"]["total_raw"] == pytest.approx(300.0)
        assert "One champion damage instance" in result["breakdown"]["E"]["detail"]
        response = _api({"w_rockets": 5, "e_upgrade": 1})
        assert response.status_code == 200
        body = response.get_json()
        assert body["breakdown"]["W"]["name"] == "Hextech Micro-Rockets"
        assert body["breakdown"]["E"]["name"] == "CH-3X Lightning Grenade"
        assert body["breakdown"]["W"]["total_damage"] == pytest.approx(
            270.0 * 100 / 140, abs=0.1
        )
        assert body["breakdown"]["E"]["total_damage"] == pytest.approx(
            300.0 * 100 / 140, abs=0.1
        )

    def test_wiki_prose_and_degraded_rows_pin_the_numbers(self):
        # The numbers are the cached leveling rows (empty units = the
        # degraded parse) plus module-authored prose pins; the upgraded
        # values survive only as attribute TEXT with empty modifiers.
        w = _HEIMER_DATA["abilities"]["W"][0]
        first = _leveling("W", "Initial Rocket Magic Damage")
        assert first["modifiers"][0]["values"] == [50, 75, 100, 125, 150]
        assert first["modifiers"][1]["values"] == [55]
        later = _leveling("W", "Subsequent Rocket Magic Damage")
        assert later["modifiers"][0]["values"] == [10, 15, 20, 25, 30]
        assert later["modifiers"][1]["values"] == [12]
        assert later["modifiers"][1]["units"] == ["% AP"]
        e = _HEIMER_DATA["abilities"]["E"][0]
        base = _leveling("E", "Magic Damage")
        assert base["modifiers"][0]["values"] == [60, 100, 140, 180, 220]
        assert base["modifiers"][1]["values"] == [60]
        assert base["modifiers"][1]["units"] == ["% AP"]
        e_upgraded = _HEIMER_DATA["abilities"]["E"][1]
        e_prose = " ".join(
            effect.get("description", "") for effect in e_upgraded.get("effects", [])
        )
        assert "bounces a fixed distance 3 times" in e_prose
        assert "slow them by 35% for 2 seconds" in e_prose
        assert "additionally stunned for 1.5 seconds" in e_prose
        assert "Enemy champions can only be damaged once per cast" in e_prose
        degraded_attrs = [
            leveling["attribute"]
            for effect in e_upgraded.get("effects", [])
            for leveling in effect.get("leveling", [])
        ]
        assert "100 / 200 / 300 (+ 60% AP)" in degraded_attrs
        for effect in e_upgraded.get("effects", []):
            for leveling in effect.get("leveling", []):
                if leveling["attribute"] == "100 / 200 / 300 (+ 60% AP)":
                    assert leveling["modifiers"] == []
        w_prose = " ".join(
            effect.get("description", "") for effect in w.get("effects", [])
        )
        assert (
            "Enemies can be hit by multiple rockets, but receive less damage "
            "from ones beyond the first" in w_prose
        )
        assert "grants 20% beam charge to all turrets within 1000 range" in w_prose
        # The R-upgraded W swarm rows survive as degraded text/rows the
        # module never reads (W prices entry 0 only).
        swarm_attrs = [
            leveling["attribute"]
            for effect in _HEIMER_DATA["abilities"]["W"][1].get("effects", [])
            for leveling in effect.get("leveling", [])
        ]
        assert "135 / 180 / 225 (+ 45% AP)" in swarm_attrs
        assert "Rockets 2:5 Magic Damage" in swarm_attrs
        # Source receipts pin the wiki revisions.
        sources = {
            row["label"]: row
            for row in get_champion_options_meta("Heimerdinger")["sources"]
        }
        assert sources["Heimerdinger parent entry"]["url"].endswith(
            "/en-us/Heimerdinger"
        )
        assert sources["Heimerdinger parent entry"]["revision_id"] == 4025016
        assert sources["Heimerdinger W template"]["revision_id"] == 2864243
        assert sources["Heimerdinger E template"]["revision_id"] == 2864389


# ---------------------------------------------------------------------------
# S2 — W first-vs-subsequent
# ---------------------------------------------------------------------------


class TestRocketFirstVsSubsequent:
    def test_default_five_rockets_one_first_four_later(self):
        # rocket count = the w_rockets option (default 5): 1 first +
        # 4 subsequent; per-part amounts 150/30 at rank 5, 0 AP.
        _, abilities = _parse({})
        first, later = abilities["W"]["parts"]
        assert (first.amount, first.count) == (150.0, 1)
        assert (later.amount, later.count) == (30.0, 4)
        assert abilities["W"]["total_raw"] == pytest.approx(150.0 + 30.0 * 4)

    def test_one_rocket_is_first_only(self):
        # w_rockets=1 prices the first row only: one part, one event.
        _, abilities = _parse({"w_rockets": 1})
        assert len(abilities["W"]["parts"]) == 1
        assert abilities["W"]["parts"][0].amount == pytest.approx(150.0)
        assert abilities["W"]["parts"][0].count == 1
        assert abilities["W"]["total_raw"] == pytest.approx(150.0)
        result = _fight({"w_rockets": 1}, one_rotation=True)
        row = result["breakdown"]["W"]
        assert len(row["damage_events"]) == 1
        assert row["damage_events"][0]["raw_damage"] == pytest.approx(150.0)
        assert row["total_raw"] == pytest.approx(150.0)
        assert "1 authored rockets" in row["detail"]

    def test_every_rocket_count_prices_first_plus_later(self):
        # n rockets = 1 first + (n-1) subsequent, total = first + later x
        # (n-1), for every count in 1..5.
        stats, _ = _parse({})
        first = _resolve("W", "Initial Rocket Magic Damage", 5, stats)
        later = _resolve("W", "Subsequent Rocket Magic Damage", 5, stats)
        for n in range(1, 6):
            _, abilities = _parse({"w_rockets": n})
            parts = abilities["W"]["parts"]
            assert len(parts) == (1 if n == 1 else 2)
            assert parts[0].amount == pytest.approx(first)
            if n > 1:
                assert parts[1].amount == pytest.approx(later)
                assert parts[1].count == n - 1
            assert abilities["W"]["total_raw"] == pytest.approx(first + later * (n - 1))
            result = _fight({"w_rockets": n}, one_rotation=True)
            row = result["breakdown"]["W"]
            assert len(row["damage_events"]) == n
            raws = [event["raw_damage"] for event in row["damage_events"]]
            assert raws[0] == pytest.approx(first)
            assert all(raw == pytest.approx(later) for raw in raws[1:])
            assert row["total_raw"] == pytest.approx(first + later * (n - 1))

    def test_rank_and_ap_scale_both_rows(self):
        # Both rows scale per rank and AP: rank 1 first 50/later 10;
        # rank 5 + 100 AP first 205/later 42.
        for rank, first_want, later_want in ((1, 50.0, 10.0), (5, 150.0, 30.0)):
            stats, abilities = _parse({"w_rockets": 5}, ranks={**_RANKS, "W": rank})
            assert abilities["W"]["parts"][0].amount == pytest.approx(first_want)
            assert abilities["W"]["parts"][1].amount == pytest.approx(later_want)
        stats, abilities = _parse({"w_rockets": 5}, ap=100.0)
        assert abilities["W"]["parts"][0].amount == pytest.approx(205.0)
        assert abilities["W"]["parts"][1].amount == pytest.approx(42.0)
        assert abilities["W"]["total_raw"] == pytest.approx(205.0 + 42.0 * 4)


# ---------------------------------------------------------------------------
# S3 — Rocket timing
# ---------------------------------------------------------------------------


class TestRocketTiming:
    def test_part_timing_pins(self):
        # The parts declare 0.25 first / 0.35 subsequent @ 0.08.
        _, abilities = _parse({})
        first, later = abilities["W"]["parts"]
        assert first.time_offset == pytest.approx(_W_FIRST_TIME_OFFSET)
        assert first.hit_interval is None
        assert later.time_offset == pytest.approx(_W_LATER_TIME_OFFSET)
        assert later.hit_interval == pytest.approx(_W_HIT_INTERVAL)

    def test_damage_event_times_one_rotation(self):
        # One-rotation casts land at 0.0: first rocket at 0.25, then
        # 0.35/0.43/0.51/0.59 (0.35 + 0.08 steps); E at 0.6.
        result = _fight({"w_rockets": 5, "e_upgrade": 1}, one_rotation=True)
        times = [event["time"] for event in result["breakdown"]["W"]["damage_events"]]
        assert times == pytest.approx([0.25, 0.35, 0.43, 0.51, 0.59])
        e_times = [event["time"] for event in result["breakdown"]["E"]["damage_events"]]
        assert e_times == pytest.approx([0.6])

    def test_damage_event_times_timed_fight(self):
        # Timed fight: the W cast starts at 0.25 (Q's cast time), so the
        # rockets land at cast + offset: 0.5, then 0.6/0.68/0.76/0.84; E
        # casts at 0.5 and lands at 1.1.
        result = _fight({"w_rockets": 5, "e_upgrade": 1}, duration=10.0)
        times = [event["time"] for event in result["breakdown"]["W"]["damage_events"]]
        assert times == pytest.approx([0.5, 0.6, 0.68, 0.76, 0.84])
        e_times = [event["time"] for event in result["breakdown"]["E"]["damage_events"]]
        assert e_times == pytest.approx([1.1])


# ---------------------------------------------------------------------------
# S4 — E variants
# ---------------------------------------------------------------------------


class TestGrenadeVariants:
    def test_base_variant_sources_cached_row(self):
        # e_upgrade 0 (default): CH-2 Electron Storm Grenade, the cached
        # "Magic Damage" row (220 at rank 5, 0 AP), one damage part.
        _, abilities = _parse({"e_upgrade": 0})
        e = abilities["E"]
        assert e["name"] == "CH-2 Electron Storm Grenade"
        assert e["total_raw"] == pytest.approx(
            _resolve("E", "Magic Damage", 5, _stats())
        )
        assert len(e["parts"]) == 1
        result = _fight({"e_upgrade": 0}, one_rotation=True)
        assert result["breakdown"]["E"]["name"] == "CH-2 Electron Storm Grenade"
        assert len(result["breakdown"]["E"]["damage_events"]) == 1

    def test_upgraded_variant_prices_r_scaled_tuple(self):
        # e_upgrade 1: CH-3X Lightning Grenade, 100/200/300 + 60% AP by
        # R rank (module hardcoded tuple beside the degraded attribute
        # row), still ONE damage part and ONE damage event.
        for r_rank, want in ((1, 100.0), (2, 200.0), (3, 300.0)):
            _, abilities = _parse({"e_upgrade": 1}, ranks={**_RANKS, "R": r_rank})
            e = abilities["E"]
            assert e["name"] == "CH-3X Lightning Grenade"
            assert e["total_raw"] == pytest.approx(want)
            assert len(e["parts"]) == 1
        _, abilities = _parse({"e_upgrade": 1}, ap=100.0)
        assert abilities["E"]["total_raw"] == pytest.approx(
            _E_UPGRADED_VALUES[2] + _E_UPGRADED_AP_RATIO * 100.0
        )
        result = _fight({"e_upgrade": 1}, one_rotation=True)
        assert len(result["breakdown"]["E"]["damage_events"]) == 1
        assert result["breakdown"]["E"]["total_raw"] == pytest.approx(300.0)

    def test_grenade_one_instance_pin(self):
        # The grenade prices exactly one champion damage instance in both
        # variants: bounces, stun and slow are control state, never extra
        # damage.  The upgraded E's "damaged once per cast" wiki prose is
        # the source for the single hit.
        for option in ({"e_upgrade": 0}, {"e_upgrade": 1}):
            result = _fight(option, one_rotation=True)
            row = result["breakdown"]["E"]
            assert len(row["damage_events"]) == 1
            assert row["casts"] == 1
            assert "One champion damage instance" in row["detail"]
        e_upgraded = _HEIMER_DATA["abilities"]["E"][1]
        assert "Enemy champions can only be damaged once per cast" in " ".join(
            effect.get("description", "") for effect in e_upgraded.get("effects", [])
        )

    def test_upgraded_e_keeps_base_cooldown_and_mana_pinned_actual(self):
        # Pinned actual: the upgraded branch reads the base grenade's
        # cooldown (11) and the engine stamps the base entry's 85 mana
        # (E[1].cost is null).  The wiki R prose says empowered abilities
        # "do not have a mana cost" — divergence flagged for the
        # coordinator's typed E declaration.
        _, base = _parse({"e_upgrade": 0})
        _, upgraded = _parse({"e_upgrade": 1})
        assert upgraded["E"]["cooldown"] == pytest.approx(base["E"]["cooldown"])
        assert upgraded["E"]["cooldown"] == pytest.approx(11.0)
        assert upgraded["E"]["resource_cost"] == pytest.approx(85.0)
        result = _fight({"e_upgrade": 1}, one_rotation=True)
        e_spend = [
            row
            for row in result["resource_ledger"]["receipts"]
            if row["source"] == "ability E cast"
        ]
        assert len(e_spend) == 1
        assert e_spend[0]["amount"] == pytest.approx(85.0)
        r_prose = " ".join(
            effect.get("description", "")
            for effect in _HEIMER_DATA["abilities"]["R"][0].get("effects", [])
        )
        assert "do not have a mana cost" in r_prose


# ---------------------------------------------------------------------------
# S5 — Options
# ---------------------------------------------------------------------------


class TestOptions:
    def test_w_rockets_metadata(self):
        meta = get_champion_options_meta("Heimerdinger")
        option = next(o for o in meta["options"] if o["key"] == "w_rockets")
        assert option["type"] == "int"
        assert option["default"] == 5
        assert option["min"] == 1
        assert option["max"] == 5
        assert option["label"] == "Rockets hitting the target"

    def test_e_upgrade_metadata(self):
        meta = get_champion_options_meta("Heimerdinger")
        option = next(o for o in meta["options"] if o["key"] == "e_upgrade")
        assert option["type"] == "int"
        assert option["default"] == 0
        assert option["min"] == 0
        assert option["max"] == 1
        assert option["label"] == "Grenade variant"

    def test_options_served_by_config_endpoint(self):
        app_module.app.config["TESTING"] = True
        response = app_module.app.test_client().get("/api/config")
        assert response.status_code == 200
        options = response.get_json()["champion_options"]["Heimerdinger"]["options"]
        by_key = {option["key"]: option for option in options}
        assert by_key["w_rockets"]["default"] == 5
        assert by_key["w_rockets"]["min"] == 1
        assert by_key["w_rockets"]["max"] == 5
        assert by_key["e_upgrade"]["default"] == 0
        assert by_key["e_upgrade"]["min"] == 0
        assert by_key["e_upgrade"]["max"] == 1

    def test_api_rejects_out_of_range_named_400s(self):
        # The brief's named 400s: w_rockets 0/6 and e_upgrade 2 (and -1).
        for bad, message in (
            ({"w_rockets": 0}, "champion_options.w_rockets must be between 1 and 5"),
            ({"w_rockets": 6}, "champion_options.w_rockets must be between 1 and 5"),
            ({"e_upgrade": 2}, "champion_options.e_upgrade must be between 0 and 1"),
            ({"e_upgrade": -1}, "champion_options.e_upgrade must be between 0 and 1"),
        ):
            response = _api(bad)
            assert response.status_code == 400
            assert response.get_json()["error"] == message
        # Boundaries pass.
        for good in (
            {"w_rockets": 1},
            {"w_rockets": 5},
            {"e_upgrade": 0},
            {"e_upgrade": 1},
        ):
            response = _api(good)
            assert response.status_code == 200

    def test_api_rejects_malformed_named_400s(self):
        for bad, message in (
            ({"w_rockets": "abc"}, "champion_options.w_rockets must be a number"),
            ({"w_rockets": True}, "champion_options.w_rockets must be a number"),
            ({"w_rockets": 2.5}, "champion_options.w_rockets must be an integer"),
            ({"e_upgrade": "x"}, "champion_options.e_upgrade must be a number"),
        ):
            response = _api(bad)
            assert response.status_code == 400
            assert response.get_json()["error"] == message
        response = _api({"bogus": 1})
        assert response.status_code == 400
        assert (
            response.get_json()["error"]
            == "champion_options contains unknown option bogus"
        )

    def test_parse_path_clamps_and_truncates_pinned_actual(self):
        # Pinned actual: the parse path clamps ONLY to the module bounds
        # and int()s float seeds — 6 -> 5 rockets, 0/-3 -> 1 (first
        # only), 2.5 -> 2; e_upgrade 2 -> upgraded, -1 -> base.  The
        # strict bounds live at the API boundary only.
        _, six = _parse({"w_rockets": 6})
        assert six["W"]["total_raw"] == pytest.approx(270.0)
        _, zero = _parse({"w_rockets": 0})
        assert zero["W"]["total_raw"] == pytest.approx(150.0)
        _, negative = _parse({"w_rockets": -3})
        assert negative["W"]["total_raw"] == pytest.approx(150.0)
        _, truncated = _parse({"w_rockets": 2.5})
        _, integer = _parse({"w_rockets": 2})
        assert truncated["W"]["total_raw"] == integer["W"]["total_raw"]
        assert truncated["W"]["total_raw"] == pytest.approx(180.0)
        _, e_two = _parse({"e_upgrade": 2})
        assert e_two["E"]["name"] == "CH-3X Lightning Grenade"
        _, e_negative = _parse({"e_upgrade": -1})
        assert e_negative["E"]["name"] == "CH-2 Electron Storm Grenade"

    def test_parse_path_non_numeric_fails_closed(self):
        # Non-numeric options raise at the parse path (no invented
        # rockets/grenades).
        for option in ({"w_rockets": "abc"}, {"e_upgrade": "x"}):
            with pytest.raises(ValueError):
                _parse(option)

    def test_unlearned_slots_absent(self):
        # A slot at rank 0 is not emitted (fail closed, no zero rows).
        _, abilities = _parse({}, ranks={**_RANKS, "W": 0})
        assert "W" not in abilities
        _, abilities = _parse({}, ranks={**_RANKS, "E": 0})
        assert "E" not in abilities


# ---------------------------------------------------------------------------
# S6 — Target policy (multi-target claims)
# ---------------------------------------------------------------------------


class TestTargetPolicy:
    def test_breakdown_surface_single_target_only(self):
        # No multi-target damage rows exist today: the breakdown is
        # exactly Q/W/E/R + autos for both grenade variants; W/E price
        # single-target values only.
        for option in ({}, {"e_upgrade": 1}, {"w_rockets": 5, "e_upgrade": 1}):
            result = _fight(option, one_rotation=True)
            assert set(result["breakdown"]) == {
                "Q",
                "W",
                "E",
                "R",
                "auto_attacks",
            }

    def test_no_invented_multi_target_damage(self):
        # The rocket fan / grenade bounce / turret targeting claims add
        # nothing: W prices first + later x 4, E prices one instance, R
        # prices zero, and total_damage is exactly the engine rows' sum.
        result = _fight({"w_rockets": 5, "e_upgrade": 1}, one_rotation=True)
        assert result["breakdown"]["W"]["total_raw"] == pytest.approx(270.0)
        assert result["breakdown"]["E"]["total_raw"] == pytest.approx(300.0)
        assert result["breakdown"]["R"]["total_damage"] == 0.0
        assert result["total_damage"] == pytest.approx(
            sum(row["total_damage"] for row in result["breakdown"].values())
        )
        _, abilities = _parse({"w_rockets": 5, "e_upgrade": 1})
        assert result["breakdown"]["W"]["total_raw"] == pytest.approx(
            abilities["W"]["total_raw"]
        )
        assert result["breakdown"]["E"]["total_raw"] == pytest.approx(
            abilities["E"]["total_raw"]
        )

    def test_module_assumptions_name_unmodeled_claims(self):
        # The named unmodeled claims live in the module ASSUMPTIONS today.
        assumptions = get_champion_options_meta("Heimerdinger")["assumptions"]
        assert any(
            "Rocket multi-hit reduction uses the explicit first/subsequent rows" in text
            and "only one champion hit is counted for the upgraded grenade" in text
            for text in assumptions
        )
        assert any(
            "UPGRADE!!!, stuns, slows, turret targeting and vision are "
            "state/utility, not extra direct champion damage" in text
            for text in assumptions
        )

    def test_w_rockets_option_state_receipt_declares_rocket_rule(self):
        # Mirrors the 3W/3X/3Y option state receipts: w_rockets carries a
        # typed public receipt declaring the rocket rule — the explicit
        # first/subsequent row attributes, the timing pins, the bounds.
        meta = get_champion_options_meta("Heimerdinger")
        option = next(o for o in meta["options"] if o["key"] == "w_rockets")
        state = option["state"]
        assert state["first_row_attribute"] == "Initial Rocket Magic Damage"
        assert state["subsequent_row_attribute"] == "Subsequent Rocket Magic Damage"
        assert state["first_time_offset"] == pytest.approx(_W_FIRST_TIME_OFFSET)
        assert state["subsequent_time_offset"] == pytest.approx(_W_LATER_TIME_OFFSET)
        assert state["hit_interval"] == pytest.approx(_W_HIT_INTERVAL)
        assert state["default"] == 5
        assert state["min"] == 1
        assert state["max"] == 5
        assert state["source"]  # provenance on the declaration

    def test_e_upgrade_option_state_receipt_declares_grenade_rule(self):
        # e_upgrade carries a typed public receipt: the base row, the
        # upgraded tuple + AP ratio, the one-instance rule, the timing.
        meta = get_champion_options_meta("Heimerdinger")
        option = next(o for o in meta["options"] if o["key"] == "e_upgrade")
        state = option["state"]
        assert state["base_row_attribute"] == "Magic Damage"
        assert list(state["upgraded_values"]) == list(_E_UPGRADED_VALUES)
        assert state["upgraded_ap_ratio"] == pytest.approx(_E_UPGRADED_AP_RATIO)
        assert state["time_offset"] == pytest.approx(_E_TIME_OFFSET)
        assert state["one_instance"] is True
        assert state["source"]  # provenance on the declaration

    def test_multi_target_claims_named_fail_closed_denials(self):
        # The unsupported multi-target claims receipt named fail-closed
        # denials: the rocket fan spread, the grenade bounces, the
        # stun/slow control, the turret targeting/beam charge — and the
        # denials invent no damage (total_damage stays the engine sum).
        result = _fight({"w_rockets": 5, "e_upgrade": 1}, one_rotation=True)
        reasons = " ".join(_denial_reasons(result)).lower()
        assert any(keyword in reasons for keyword in ("fan", "spread", "multi-target"))
        assert any(keyword in reasons for keyword in ("bounce", "bounces"))
        assert any(keyword in reasons for keyword in ("stun", "slow"))
        assert "turret" in reasons
        assert result["total_damage"] == pytest.approx(
            sum(row["total_damage"] for row in result["breakdown"].values())
        )

    def test_upgraded_w_swarm_not_priced_named_denial(self):
        # The R-upgraded W swarm (W[1] rows "Rockets 2:5 Magic Damage" /
        # "135 / 180 / 225 (+ 45% AP)") is not priced — R is a toggle —
        # and the walk receipts a named denial instead of inventing the
        # 4-wave multi-target swarm.
        result = _fight({"w_rockets": 5, "e_upgrade": 1}, one_rotation=True)
        reasons = " ".join(_denial_reasons(result)).lower()
        assert "swarm" in reasons
        assert result["breakdown"]["R"]["total_damage"] == 0.0
        assert result["breakdown"]["W"]["total_raw"] == pytest.approx(270.0)

    def test_denials_visible_in_api_payload(self):
        # The denial surface is visible in the API payload (the fight
        # result the frontend consumes), not only the direct parse.  The
        # module's E detail today merely NAMES the control state
        # ("bounces, stun and slow are sourced control state") — the
        # contract is an explicit fail-closed denial receipt, never a
        # bare keyword in the damage detail.
        response = _api({"w_rockets": 5, "e_upgrade": 1})
        assert response.status_code == 200
        blob = json.dumps(response.get_json()).lower()
        assert any(
            marker in blob
            for marker in ("denied", "not modeled", "fail-closed", "unsupported")
        )
        assert any(keyword in blob for keyword in ("fan", "bounce", "turret"))


# ---------------------------------------------------------------------------
# S7 — Malformed inputs fail closed
# ---------------------------------------------------------------------------


class TestMalformedInputs:
    def test_missing_w_row_fails_closed_not_silent_zero(self):
        # Pinned contract: a missing/degraded W row must never price a
        # silent zero-damage W — the typed declaration either raises or
        # emits a named fail-closed receipt.  TODAY the module emits a
        # zero-total_raw entry (pinned actual, flagged to the
        # coordinator); this test flips when the P3-3Z completion lands.
        try:
            abilities = _parse_with_stripped_rows("W")
        except (ValueError, KeyError, AssertionError):
            return  # fail-closed raise is contract-compliant
        w = abilities.get("W")
        assert w is None or w["total_raw"] != 0.0

    def test_missing_e_row_fails_closed_not_silent_zero(self):
        # Same contract for the E base row.
        try:
            abilities = _parse_with_stripped_rows("E")
        except (ValueError, KeyError, AssertionError):
            return
        e = abilities.get("E")
        assert e is None or e["total_raw"] != 0.0

    def test_accepted_engine_priced_stream_documented_with_identity(self):
        # The coordinator's documentary walk receipts the accepted
        # engine-priced stream (1 first + 4 subsequent rockets + 1
        # grenade hit) with ownership + event identity, amounts matching
        # the engine's raw values — never re-pricing mid-fight.
        result = _fight({"w_rockets": 5, "e_upgrade": 1}, one_rotation=True)
        walk = _we_walk(result)
        assert walk is not None
        accepted = [r for r in walk.get("receipts", []) if r.get("accepted")]
        assert accepted
        assert all(r.get("owner") == "main" for r in accepted)
        assert all(
            r.get("source") or (r.get("detail") or {}).get("event_id") for r in accepted
        )
        amounts = sorted(float(r["amount"]) for r in accepted)
        assert amounts == sorted([150.0] + [30.0] * 4 + [300.0])


# ---------------------------------------------------------------------------
# S8 — Unchanged boundaries
# ---------------------------------------------------------------------------


class TestUnchangedBoundaries:
    def test_q_turret_unchanged(self):
        # Q: 3 turrets x 3 shots x 23 (level 18) + 1 beam x 120 = 327;
        # apex variant 1260; optioned 92; one deploy per 20s window.
        _, abilities = _parse({})
        q = abilities["Q"]
        assert q["name"] == "H-28G Evolution Turret"
        assert q["total_raw"] == pytest.approx(327.0)
        assert len(q["parts"]) == 2
        assert q["parts"][0].amount == pytest.approx(23.0)
        assert q["parts"][0].count == 9
        assert q["parts"][1].amount == pytest.approx(120.0)
        assert q["cooldown"] == pytest.approx(20.0)
        assert q["event_order_certified"]
        _, apex = _parse({"q_variant": 1})
        assert apex["Q"]["total_raw"] == pytest.approx(1260.0)
        _, optioned = _parse({"q_turrets": 2, "q_turret_attacks": 2, "q_beams": 0})
        assert optioned["Q"]["total_raw"] == pytest.approx(92.0)
        result = _fight({}, duration=10.0)
        assert result["breakdown"]["Q"]["casts"] == 1

    def test_r_toggle_unchanged(self):
        # R is the empowerment toggle: zero damage, no events, name and
        # detail intact, cooldown 85 at rank 3.
        _, abilities = _parse({})
        r = abilities["R"]
        assert r["name"] == "UPGRADE!!!"
        assert r["total_raw"] == 0.0
        assert r["parts"] == ()
        assert r["cooldown"] == pytest.approx(85.0)
        assert "empowerment toggle" in r["detail"]
        result = _fight({"e_upgrade": 1}, one_rotation=True)
        assert result["breakdown"]["R"]["total_damage"] == 0.0

    def test_p_unchanged(self):
        # P (Hextech Affinity) stays a no-damage state row.
        _, abilities = _parse({})
        assert abilities["passive"]["name"] == "Hextech Affinity"
        assert abilities["passive"]["total_raw"] == 0.0
        result = _fight({}, one_rotation=True)
        assert "passive" not in result["breakdown"]

    def test_w_e_cooldowns_and_costs_unchanged(self):
        # W cooldown 11..7 and cost 50..90 by rank; E cooldown 11 and
        # cost 85 flat.
        for rank, cd, cost in (
            (1, 11.0, 50.0),
            (5, 7.0, 90.0),
        ):
            _, abilities = _parse({}, ranks={**_RANKS, "W": rank})
            assert abilities["W"]["cooldown"] == pytest.approx(cd)
            assert abilities["W"]["resource_cost"] == pytest.approx(cost)
        _, abilities = _parse({})
        assert abilities["E"]["cooldown"] == pytest.approx(11.0)
        assert abilities["E"]["resource_cost"] == pytest.approx(85.0)

    def test_existing_options_unchanged(self):
        meta = get_champion_options_meta("Heimerdinger")
        by_key = {option["key"]: option for option in meta["options"]}
        assert by_key["q_variant"] == {
            "key": "q_variant",
            "type": "int",
            "default": 0,
            "min": 0,
            "max": 1,
            "label": "Turret variant (Evolution/Apex)",
        }
        assert by_key["q_turrets"]["default"] == 3
        assert by_key["q_turrets"]["min"] == 1
        assert by_key["q_turrets"]["max"] == 3
        assert by_key["q_turret_attacks"]["default"] == 3
        assert by_key["q_turret_attacks"]["min"] == 1
        assert by_key["q_turret_attacks"]["max"] == 12
        assert by_key["q_beams"]["default"] == 1
        assert by_key["q_beams"]["min"] == 0
        assert by_key["q_beams"]["max"] == 3

    def test_mana_ledger_coexists_with_w_e_casts(self):
        # The real mana ledger books the W/E casts (90/85) beside the Q
        # and R spends — the P3-3Z walk must coexist with it unchanged.
        result = _fight({"e_upgrade": 1}, one_rotation=True)
        ledger = result["resource_ledger"]
        assert ledger["kind"] == "mana"
        spends = {
            row["source"]: row
            for row in ledger["receipts"]
            if row["operation"] == "spend"
        }
        assert spends["ability W cast"]["amount"] == pytest.approx(90.0)
        assert spends["ability E cast"]["amount"] == pytest.approx(85.0)
        assert spends["ability Q cast"]["amount"] == pytest.approx(20.0)
        assert spends["ability R cast"]["amount"] == pytest.approx(100.0)
        assert result["resource_spent"] == pytest.approx(295.0)
        assert result["resource_remaining"] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# S9 — Score/receipt parity + no re-pricing
# ---------------------------------------------------------------------------


class TestScoreReceiptParity:
    def test_w_e_surface_byte_identical_under_score_only(self):
        # The seeded W/E surface (breakdown, totals, ledger) is identical
        # between the full walk and the compiled score path, for every
        # rocket count and grenade variant, in one-rotation and timed
        # fights.  The score-only cast_timeline carries the cast
        # projection (time/slot/name/ordinal/resource_cost); the full
        # walk adds resource-before/restored/after on top — the shared
        # rows agree.
        for option in (
            {},
            {"w_rockets": 1},
            {"w_rockets": 3},
            {"w_rockets": 5},
            {"e_upgrade": 1},
            {"w_rockets": 3, "e_upgrade": 1},
        ):
            for one_rotation in (True, False):
                full = _fight(option, one_rotation=one_rotation)
                scored = _fight(option, one_rotation=one_rotation, score_only=True)
                assert full["breakdown"] == scored["breakdown"]
                assert full["total_damage"] == scored["total_damage"]
                assert full["resource_spent"] == scored["resource_spent"]
                assert full["resource_remaining"] == scored["resource_remaining"]
                assert full["resource_ledger"] == scored["resource_ledger"]
                assert full["breakdown"]["W"] == scored["breakdown"]["W"]
                assert full["breakdown"]["E"] == scored["breakdown"]["E"]
                shared = ("time", "slot", "name", "ordinal", "resource_cost")
                for full_row, scored_row in zip(
                    full["cast_timeline"], scored["cast_timeline"]
                ):
                    assert {k: full_row[k] for k in shared} == {
                        k: scored_row[k] for k in shared
                    }

    def test_upgraded_branch_never_re_priced_mid_fight(self):
        # The upgraded branch is priced at parse time only: the fight's
        # E raw equals the seeded parse raw at every R rank, and W equals
        # its parse raw at every rocket count — the coordinator's walk
        # must document without re-pricing.
        for r_rank in (1, 2, 3):
            _, abilities = _parse({"e_upgrade": 1}, ranks={**_RANKS, "R": r_rank})
            result = _fight(
                {"e_upgrade": 1}, one_rotation=True, ranks={**_RANKS, "R": r_rank}
            )
            assert result["breakdown"]["E"]["total_raw"] == pytest.approx(
                abilities["E"]["total_raw"]
            )
        for n in (1, 2, 3, 4, 5):
            _, abilities = _parse({"w_rockets": n})
            result = _fight({"w_rockets": n}, one_rotation=True)
            assert result["breakdown"]["W"]["total_raw"] == pytest.approx(
                abilities["W"]["total_raw"]
            )


# ---------------------------------------------------------------------------
# S10 — Regression surface (kept green; run list)
# ---------------------------------------------------------------------------
# Run ONLY this file plus the mandated sanity list (contract 10):
#   .venv/bin/python -m pytest tests/test_heimerdinger_multihit.py \
#     tests/test_aurelion_sol_stardust_ledger.py tests/test_senna_souls_ledger.py \
#     tests/test_bard_chimes_ledger.py tests/test_rengar_ferocity_ledger.py \
#     tests/test_state_lifecycle.py tests/test_state_lifecycle_consumers.py \
#     tests/test_resource_ledger.py tests/test_resource_ledger_consumers.py \
#     tests/test_resource_ledger_champion_consumers.py \
#     tests/test_catalyst_resource_ledger.py tests/test_item_sustain.py \
#     tests/test_mana_restore_refund.py tests/test_app.py
# Heimerdinger grep surface (contract 10), run separately:
#   tests/test_e4_summon_1.py tests/test_cp10_batch_02.py \
#     tests/test_wiki_parser.py
