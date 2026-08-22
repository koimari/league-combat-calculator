"""P1 Package 4A — K'Sante W Path Maker bonus-resistance / state behavior
(test-matrix owner: RLM-2 C).

Focused TDD matrix for K'Sante's W (Path Maker) bonus-resistance / state
behavior.  CURRENT RUNTIME FACTS (verified before pinning):

- The module (``src/calculator/champions/ksante.py``) prices the W
  physical packet from the cached "Physical Damage" row via the typed
  extractor (``extract_named``) and, with ``all_out`` True, additionally
  prices the All Out true-damage range ("Minimum Bonus True Damage" ->
  "Maximum Bonus True Damage") interpolated by the ``w_charge`` float
  0..1 (default 1.0): parts (physical) + (true, time_offset=charge);
  without All Out the W is ONE physical part with time_offset=charge.
  ``total_raw`` = physical + interpolated true in All Out, physical
  only otherwise.  The R ``_all_out`` entry carries a ``stat_buff``
  (attack speed from the cached "Bonus Attack Speed" row, 50% armor
  penetration, 20% omnivamp — the 50/20 are module constants) when the
  ``all_out`` option is set, and names the 65% health threshold / resist
  conversion as "state" in its detail; the module ASSUMPTIONS say the
  threshold / conversion "remain visible state rather than hidden
  arithmetic".
- The known-degraded parser case (K'Sante W bonus resistances):
  VERDICT — the resist-scaling rows ARE in ``data/champions.json`` with
  VALUES AND NON-EMPTY descriptive units (they are NOT empty-unit
  rows): "Physical Damage" mod[1] 8% (+2% per 100 bonus armor) (+2% per
  100 bonus magic resistance) of target's maximum health; "Minimum
  Bonus True Damage" mod[1] 0.8% (+0.2%...); "Maximum Bonus True
  Damage" mod[1] 6.4% (+1.6%...); "Total Maximum Mixed Damage" mod[1]
  14.4% (+3.6%...).  The generic compound-unit resolver HALF-PARSES
  them: it resolves the embedded "+N% per 100 bonus armor / bonus magic
  resistance" against TOTAL armor / TOTAL magic resistance
  (``scaling._normalize_per_100_stat`` maps "bonus armor"->"armor"),
  so the current W price includes a misattributed %maxHP term (pinned
  actual, flagged; overstates whenever bonus resist != total resist).
- The W rows are priced at parse time only; the fight engine never
  re-prices them.  Missing/degraded W rows today yield a SILENT
  zero-total_raw entry (pinned actual, flagged).  The options carry NO
  ``state`` receipt today and there is NO documentary walk or denial
  surface for the resistance conversion / missing state.
- Genuinely-absent mechanics are ``xfail`` with reason "awaiting
  P3-4A ...": the coordinator's completion mirrors the P3-3Z
  Heimerdinger pattern (typed W declaration + ``w_charge`` option state
  receipt, a documentary post-rotation walk over the accepted
  engine-priced stream, named fail-closed denials for the unsupported
  resistance conversion / missing state) WITHOUT re-pricing mid-fight.

Contract sections (numbered as in the RLM-2 C brief):
  S1  Source evidence + typed values (the W physical + true-range
      values discoverable through the module's typed path, recomputed
      from ``data/champions.json`` leveling rows — no literal damage
      constants; the W public receipt in parse + fight result + API;
      the resist-scaling rows' presence/absence pinned exactly).
  S2  W physical/true damage (base physical per rank; All Out true
      range min/max by rank; charge interpolation 0->min, 1->max,
      0.5->midpoint; parts (physical) + (true, time_offset=charge);
      total = physical + interpolated true in All Out, physical only
      otherwise).
  S3  Charge timing (w_charge 0..1 default 1.0; parts' time_offset =
      charge; damage_events' times in one-rotation + timed fights).
  S4  All Out branching (all_out False -> physical only; True ->
      + true part; r_terrain unchanged — R two strikes; stat_buff
      presence in the R entry when all_out).
  S5  Options (w_charge metadata float/default 1.0/0..1/step 0.25;
      p_marks/r_terrain/all_out unchanged; API named 400s; parse-path
      clamps/coercion).
  S6  Resistance state (rows' values + units pinned as source evidence;
      the misattributed total-armor resolution pinned actual; the
      fail-closed denial + no-invented-stats contract xfailed).
  S7  Malformed inputs + missing rows (bad options fail closed today;
      stripped W rows silent-zero today — fail-closed contract xfailed;
      the documentary walk xfailed).
  S8  Unchanged boundaries (P/Q/R/E, mana/cooldowns, the existing
      options byte-identical, the 65% health threshold stays named
      state, never priced).
  S9  Score/receipt parity (W surface byte-identical under score_only;
      the charge branch never re-priced mid-fight; the All Out
      auto-count divergence pinned actual).
  S10 Regression surface: the mandated sanity list plus every test that
      touches ksante/K'Sante (grep tests/) stays green (run list in the
      module footer).

Expected damage values are recomputed from ``data/champions.json``
leveling rows through the module's own typed extractor — no literal
damage constants.  The module-authored constants under test are the
charge bounds/step, the R strike timing pins (0.3 / 0.432), the All Out
armor pen (50%) and omnivamp (20%) values, and the parse/API boundary
messages.
"""

import copy
import json
import re
from pathlib import Path

import pytest

from src import app as app_module
from src.calculator.champions import (
    get_champion_options_meta,
    parse_champion_abilities,
)
from src.calculator.champions.slotlib import (
    extract_named,
    extract_value,
    find_named_leveling,
)
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion

_CHAMPION_DATA = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
# The data-file cache key is "KSante"; the dispatcher/module name is "K'Sante".
_KSANTE_DATA = _CHAMPION_DATA["KSante"]
_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
_LEVEL = 18
_TARGET_MAX_HP = 2000.0
# The P1-4A coordinator wires the typed W declaration, the option state
# receipt and the documentary walk; genuinely-absent mechanics are xfailed
# with this reason.
_AWAIT = "awaiting P3-4A wiring"

# Module-authored constants under test (declared beside the cached rows /
# in the module; the values the typed W declaration will publish).
_CHARGE_DEFAULT = 1.0
_CHARGE_MIN = 0.0
_CHARGE_MAX = 1.0
_CHARGE_STEP = 0.25
_R_STRIKE_FIRST_TIME_OFFSET = 0.3
_R_STRIKE_SECOND_TIME_OFFSET = 0.432
_ALLOUT_ARMOR_PEN_PERCENT = 50.0
_ALLOUT_OMNIVAMP_PERCENT = 20.0


def _stats() -> dict:
    # armor/magic_resistance are the keys the compound-unit resolver reads
    # for the W resist rows (misattributed total instead of bonus — the
    # pinned-actual degradation); bonus_* are the keys the P All Out bonus
    # reads.  target_max_health is passed via target_stats below.
    return {
        "ability_haste": 0.0,
        "armor_penetration_bonus_percent": 0.0,
        "armor_penetration_percent": 0.0,
        "basic_ability_haste": 0.0,
        "bonus_mana": 0.0,
        "critical_strike_chance": 0.0,
        "flat_armor_penetration": 0.0,
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
        "armor": 50.0,
        "magic_resistance": 40.0,
        "bonus_armor": 20.0,
        "bonus_magic_resistance": 10.0,
        "health": 2000.0,
        "bonus_health": 500.0,
    }


def _parse(option: dict | None, *, ranks: dict | None = None):
    stats = _stats()
    return stats, parse_champion_abilities(
        get_champion("K'Sante"),
        _LEVEL,
        0.0,
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
    ranks: dict | None = None,
) -> dict:
    stats, abilities = _parse(option, ranks=ranks)
    return calculate_fight_damage(
        stats,
        abilities,
        [],
        FightConfig(
            target_health=_TARGET_MAX_HP,
            target_armor=50,
            target_magic_resistance=40,
            fight_duration_seconds=duration,
            auto_attack_uptime=uptime,
            one_rotation=one_rotation,
            deterministic=True,
            enforce_resource_limits=True,
            cast_order=["Q", "W", "E", "R"],
        ),
        score_only=score_only,
        champion_options=dict(option),
    )


def _api(option: dict):
    return app_module.app.test_client().post(
        "/api/calculate",
        json={
            "champion": "K'Sante",
            "level": _LEVEL,
            "items": [],
            "role": "top",
            "ability_ranks": {"Q": 5, "W": 5, "E": 5, "R": 3},
            "fight_mode": "one_rotation",
            "fight_duration": 10,
            "include_auto_attacks": False,
            "target_health": _TARGET_MAX_HP,
            "target_armor": 50,
            "target_mr": 40,
            "champion_options": option,
        },
    )


def _ability(slot: str, index: int = 0) -> dict:
    return _KSANTE_DATA["abilities"][slot][index]


def _leveling(slot: str, attribute: str, index: int = 0) -> dict:
    """The first leveling row named *attribute* in one ability entry."""
    ability = _ability(slot, index)
    leveling = find_named_leveling(ability, attribute)
    if leveling is None:
        raise AssertionError(f"KSante {slot}[{index}] has no leveling {attribute!r}")
    return leveling


def _extract(slot: str, attribute: str, rank: int, stats: dict) -> float:
    """Recompute one slot value through the module's OWN typed extractor."""
    return extract_named(
        _ability(slot), attribute, rank, stats, {"target_max_health": _TARGET_MAX_HP}
    )


def _resist_term(attribute: str, rank: int, stats: dict) -> float:
    """The half-parsed %maxHP term of one W row.

    Mirrors the generic compound-unit resolver exactly: the base percent
    comes from the cached modifier value and the embedded "+N% per 100
    bonus armor / bonus magic resistance" factors are parsed from the
    cached unit string — but resolved against TOTAL armor / TOTAL magic
    resistance (the pinned misattribution, S6), never bonus.
    """
    leveling = _leveling("W", attribute)
    modifier = leveling["modifiers"][1]
    values = modifier["values"]
    value = float(values[min(rank - 1, len(values) - 1)])
    unit = modifier["units"][0]
    per100 = [float(x) for x in re.findall(r"\+\s*(\d+(?:\.\d+)?)%\s+per\s+100", unit)]
    assert len(per100) == 2, unit
    total_percent = (
        value
        + per100[0] * float(stats.get("armor", 0.0)) / 100.0
        + per100[1] * float(stats.get("magic_resistance", 0.0)) / 100.0
    )
    return total_percent / 100.0 * _TARGET_MAX_HP


def _typed_w(attribute: str, rank: int, stats: dict) -> float:
    """The P1-4A typed Path Maker formula (the coordinator's declaration).

    flat + (base_pct + RATIO*(bonus_armor/100) + RATIO*(bonus_mr/100))/100
    x max health — the ratios are the game-verified per-100 bonus
    armor/MR terms (2.0 physical / 0.2 min true / 1.6 max true percent),
    attributed to the CASTER's bonus stats (never the totals or the
    target's).  Mirrors the module's typed reads exactly.
    """
    flat = float(_leveling("W", attribute)["modifiers"][0]["values"][rank - 1])
    base_pct = float(_leveling("W", attribute)["modifiers"][1]["values"][rank - 1])
    ratio = {
        "Physical Damage": 2.0,
        "Minimum Bonus True Damage": 0.2,
        "Maximum Bonus True Damage": 1.6,
    }[attribute]
    pct = (
        base_pct
        + ratio * (stats.get("bonus_armor", 0.0) / 100.0)
        + ratio * (stats.get("bonus_magic_resistance", 0.0) / 100.0)
    )
    return flat + pct / 100.0 * _TARGET_MAX_HP


def _strip_rows(slot: str, option: dict | None = None) -> dict:
    """Parse a deep copy of the cached data with one slot's rows removed."""
    data = copy.deepcopy(get_champion("K'Sante"))
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


def _w_walk(result: dict) -> dict | None:
    """The P1-4A documentary W walk wherever the coordinator lands it.

    Pinned contract (S6/S7): either an informational breakdown row, or a
    resource_ledger sub-account (the P3-3Z w_e shape), or a notes entry.
    Returns None while the P1-4A wiring is absent.
    """
    for key in ("w_state", "path_maker", "ksante_w", "w_charge", "w"):
        row = result.get("breakdown", {}).get(key)
        if isinstance(row, dict):
            return row
    section = result.get("resource_ledger")
    if isinstance(section, dict):
        for key in ("w_state", "path_maker", "ksante_w", "w"):
            sub = section.get(key)
            if isinstance(sub, dict):
                return sub
    notes = result.get("notes")
    if notes:
        joined = json.dumps(notes).lower()
        if "path maker" in joined or "charge" in joined:
            return {"notes": notes}
    return None


def _denial_reasons(result: dict) -> list[str]:
    """Fail-closed denial reasons anywhere the walk may receipt them."""
    reasons: list[str] = []
    walk = _w_walk(result)
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
    def test_w_rows_pinned_in_cache_with_values_and_units(self):
        # The W rows the module reads ARE in the cache.  "Physical Damage"
        # is the flat physical packet; "Minimum/Maximum Bonus True Damage"
        # are the All Out range; each carries a SECOND modifier whose unit
        # is a NON-EMPTY descriptive compound string (the known-degraded
        # K'Sante W bonus-resistance case — values survive, units survive
        # as prose, and the generic resolver misattributes them, see S6).
        physical = _leveling("W", "Physical Damage")
        assert physical["modifiers"][0]["values"] == [45, 75, 105, 135, 165]
        assert physical["modifiers"][1]["values"] == [8, 8, 8, 8, 8]
        assert (
            physical["modifiers"][1]["units"]
            == [
                "% (+ 2% per 100 bonus armor) (+ 2% per 100 bonus magic "
                "resistance) of target's maximum health"
            ]
            * 5
        )
        low = _leveling("W", "Minimum Bonus True Damage")
        assert low["modifiers"][0]["values"] == [4.5, 7.5, 10.5, 13.5, 16.5]
        assert low["modifiers"][1]["values"] == [0.8, 0.8, 0.8, 0.8, 0.8]
        assert (
            low["modifiers"][1]["units"]
            == [
                "% (+ 0.2% per 100 bonus armor) (+ 0.2% per 100 bonus magic "
                "resistance) of target's maximum health"
            ]
            * 5
        )
        high = _leveling("W", "Maximum Bonus True Damage")
        assert high["modifiers"][0]["values"] == [36, 60, 84, 108, 132]
        assert high["modifiers"][1]["values"] == [6.4, 6.4, 6.4, 6.4, 6.4]
        assert (
            high["modifiers"][1]["units"]
            == [
                "% (+ 1.6% per 100 bonus armor) (+ 1.6% per 100 bonus magic "
                "resistance) of target's maximum health"
            ]
            * 5
        )
        # The authored total row and the monster cap are pinned too.
        total = _leveling("W", "Total Maximum Mixed Damage")
        assert total["modifiers"][0]["values"] == [81, 135, 189, 243, 297]
        assert total["modifiers"][1]["values"] == [14.4] * 5
        cap = _leveling("W", "Monster Damage Cap")
        assert cap["modifiers"][0]["values"] == [180, 260, 340, 420, 500]
        # Cross-check: Total Maximum Mixed flat == physical flat + max true
        # flat at every rank (45+36, 75+60, ...), and 14.4 == 8 + 6.4.
        for rank, p, h, t in zip(
            range(1, 6),
            physical["modifiers"][0]["values"],
            high["modifiers"][0]["values"],
            total["modifiers"][0]["values"],
        ):
            assert t == p + h
        assert total["modifiers"][1]["values"][0] == (
            physical["modifiers"][1]["values"][0] + high["modifiers"][1]["values"][0]
        )

    def test_w_values_recomputed_through_module_typed_path(self):
        # The module prices W from the cached rows via extract_named — the
        # typed path.  For every rank the W physical part equals the typed
        # extraction of "Physical Damage", and the All Out true range the
        # extractions of "Minimum/Maximum Bonus True Damage" (these include
        # the half-parsed %maxHP resist term — pinned actual, S6).
        for rank in range(1, 6):
            stats, abilities = _parse({}, ranks={**_RANKS, "W": rank})
            physical = _typed_w("Physical Damage", rank, stats)
            assert abilities["W"]["parts"][0].amount == pytest.approx(physical)
            assert abilities["W"]["total_raw"] == pytest.approx(physical)
            low = _typed_w("Minimum Bonus True Damage", rank, stats)
            high = _typed_w("Maximum Bonus True Damage", rank, stats)
            _, abilities = _parse({"all_out": True}, ranks={**_RANKS, "W": rank})
            parts = abilities["W"]["parts"]
            assert parts[0].amount == pytest.approx(physical)
            assert parts[1].amount == pytest.approx(low + (high - low) * 1.0)
            assert abilities["W"]["total_raw"] == pytest.approx(physical + high)

    def test_w_public_receipt_present_in_parse(self):
        # The W public receipt (the parts) at parse level: name, rank,
        # cooldown, per-part amounts/counts/timing, totals, area flag.
        _, abilities = _parse({})
        w = abilities["W"]
        assert w["name"] == "Path Maker"
        assert w["rank"] == 5
        assert w["cooldown"] == pytest.approx(10.0)
        assert w["damage_type"] == "physical"
        assert w["area_damage"] is True
        assert w["resource_type"] == "MANA"
        assert w["resource_cost"] == pytest.approx(60.0)
        assert len(w["parts"]) == 1
        part = w["parts"][0]
        assert part.damage_type == "physical"
        assert part.amount == pytest.approx(_typed_w("Physical Damage", 5, _stats()))
        assert part.time_offset == pytest.approx(_CHARGE_DEFAULT)
        assert w["total_raw"] == pytest.approx(part.amount)
        assert "1.00 charge" in w["detail"]
        assert "All Out true damage is False" in w["detail"]
        _, abilities = _parse({"all_out": True})
        w = abilities["W"]
        assert len(w["parts"]) == 2
        assert w["parts"][0].damage_type == "physical"
        assert w["parts"][1].damage_type == "true"
        assert w["parts"][1].time_offset == pytest.approx(_CHARGE_DEFAULT)
        assert w["total_raw"] == pytest.approx(
            w["parts"][0].amount + w["parts"][1].amount
        )
        assert "All Out true damage is True" in w["detail"]

    def test_w_public_receipt_present_in_fight_result_and_api(self):
        # The W receipt surface is visible in the fight result and the API
        # payload: names, details, casts, totals, the All Out damage split.
        result = _fight({"all_out": True}, one_rotation=True)
        row = result["breakdown"]["W"]
        assert row["name"] == "Path Maker"
        assert row["casts"] == 1
        assert row["total_raw"] == pytest.approx(
            _typed_w("Physical Damage", 5, _stats())
            + _typed_w("Maximum Bonus True Damage", 5, _stats())
        )
        assert row["damage_by_type"]["physical"] > 0.0
        assert row["damage_by_type"]["true"] > 0.0
        assert "charge" in row["detail"]
        response = _api({"all_out": True})
        assert response.status_code == 200
        body = response.get_json()
        assert body["breakdown"]["W"]["name"] == "Path Maker"
        assert "charge" in body["breakdown"]["W"]["detail"]
        # The API path uses the champion's real computed stats (armor 124 /
        # MR 66 at level 18 top, no items); the W price must equal the same
        # typed-path recomputation from THOSE stats (including the
        # half-parsed resist term), mitigated at the API's effective armor
        # (the R buff resolves after W in the rotation).
        champ_stats = body["champion_stats"]
        bonus_armor = float(champ_stats["bonus_armor"])
        bonus_mr = float(champ_stats["bonus_magic_resistance"])
        physical_raw = (
            165.0
            + (8.0 + 2.0 * bonus_armor / 100.0 + 2.0 * bonus_mr / 100.0)
            / 100.0
            * _TARGET_MAX_HP
        )
        true_raw = (
            132.0
            + (6.4 + 1.6 * bonus_armor / 100.0 + 1.6 * bonus_mr / 100.0)
            / 100.0
            * _TARGET_MAX_HP
        )
        assert body["effective_armor"] == pytest.approx(50.0)
        assert body["breakdown"]["W"]["total_damage"] == pytest.approx(
            physical_raw * 100.0 / 150.0 + true_raw, abs=0.1
        )

    def test_source_receipts_pin_wiki_revisions(self):
        # Source receipts pin the wiki revisions the cached rows came from.
        sources = {
            row["label"]: row for row in get_champion_options_meta("K'Sante")["sources"]
        }
        assert sources["K'Sante parent entry"]["url"].endswith("/en-us/K%27Sante")
        assert sources["K'Sante parent entry"]["revision_id"] == 4011715
        assert sources["K'Sante W template"]["revision_id"] == 3471720
        assert sources["K'Sante R template"]["revision_id"] == 3471724


# ---------------------------------------------------------------------------
# S2 — W physical/true damage
# ---------------------------------------------------------------------------


class TestPhysicalAndTrueDamage:
    def test_base_physical_per_rank_from_cached_row(self):
        # "base physical per rank": the flat packet from the cached
        # "Physical Damage" row (45/75/105/135/165) — the module's typed
        # extraction equals the flat row PLUS the half-parsed %maxHP term
        # (pinned actual; the flat-only contract is S6/xfail).
        stats, _ = _parse({})
        for rank in range(1, 6):
            _, abilities = _parse({}, ranks={**_RANKS, "W": rank})
            assert abilities["W"]["parts"][0].amount == pytest.approx(
                _typed_w("Physical Damage", rank, stats)
            )

    def test_all_out_true_range_by_rank(self):
        # The All Out true range min/max by rank comes from the cached
        # "Minimum/Maximum Bonus True Damage" rows through the typed path.
        stats, _ = _parse({})
        for rank in range(1, 6):
            low = _typed_w("Minimum Bonus True Damage", rank, stats)
            high = _typed_w("Maximum Bonus True Damage", rank, stats)
            _, abilities = _parse({"all_out": True}, ranks={**_RANKS, "W": rank})
            parts = abilities["W"]["parts"]
            assert parts[1].amount == pytest.approx(high)  # default charge 1
            _, abilities = _parse(
                {"all_out": True, "w_charge": 0.0}, ranks={**_RANKS, "W": rank}
            )
            assert abilities["W"]["parts"][1].amount == pytest.approx(low)

    def test_charge_interpolation(self):
        # charge 0 -> min, 1 -> max, 0.5 -> midpoint, 0.25 -> quarter.
        stats, _ = _parse({})
        low = _typed_w("Minimum Bonus True Damage", 5, stats)
        high = _typed_w("Maximum Bonus True Damage", 5, stats)
        for charge, want in (
            (0.0, low),
            (0.25, low + (high - low) * 0.25),
            (0.5, low + (high - low) * 0.5),
            (0.75, low + (high - low) * 0.75),
            (1.0, high),
        ):
            _, abilities = _parse({"all_out": True, "w_charge": charge})
            assert abilities["W"]["parts"][1].amount == pytest.approx(want)

    def test_part_shapes_and_total_rule(self):
        # parts (physical) + (true, time_offset=charge) in All Out; one
        # physical part otherwise; total = physical + interpolated true in
        # All Out, physical only otherwise.
        stats, _ = _parse({})
        physical = _typed_w("Physical Damage", 5, stats)
        low = _typed_w("Minimum Bonus True Damage", 5, stats)
        high = _typed_w("Maximum Bonus True Damage", 5, stats)
        _, abilities = _parse({"all_out": True, "w_charge": 0.5})
        parts = abilities["W"]["parts"]
        assert (parts[0].damage_type, parts[1].damage_type) == ("physical", "true")
        assert parts[0].amount == pytest.approx(physical)
        assert parts[1].amount == pytest.approx(low + (high - low) * 0.5)
        assert abilities["W"]["total_raw"] == pytest.approx(
            physical + low + (high - low) * 0.5
        )
        _, abilities = _parse({"all_out": False, "w_charge": 0.5})
        parts = abilities["W"]["parts"]
        assert len(parts) == 1
        assert parts[0].damage_type == "physical"
        assert parts[0].amount == pytest.approx(physical)
        assert abilities["W"]["total_raw"] == pytest.approx(physical)


# ---------------------------------------------------------------------------
# S3 — Charge timing
# ---------------------------------------------------------------------------


class TestChargeTiming:
    def test_w_charge_metadata(self):
        # w_charge is a float, default 1.0, 0..1, step 0.25.
        meta = get_champion_options_meta("K'Sante")
        option = next(o for o in meta["options"] if o["key"] == "w_charge")
        assert option["type"] == "float"
        assert option["default"] == pytest.approx(_CHARGE_DEFAULT)
        assert option["min"] == pytest.approx(_CHARGE_MIN)
        assert option["max"] == pytest.approx(_CHARGE_MAX)
        assert option["step"] == pytest.approx(_CHARGE_STEP)
        assert "charge" in option["label"].lower()

    def test_parts_time_offset_equals_charge(self):
        # One cast lands one blow: BOTH W parts carry time_offset ==
        # charge, in All Out and out of it.  The asymmetry this test was
        # written to pin (an untimed physical part beside a timed true
        # one) is the defect the completion removed — the physical and
        # true halves are the same hit at the same instant.
        for charge in (0.0, 0.25, 0.5, 0.75, 1.0):
            _, abilities = _parse({"w_charge": charge})
            assert abilities["W"]["parts"][0].time_offset == pytest.approx(charge)
            _, abilities = _parse({"all_out": True, "w_charge": charge})
            parts = abilities["W"]["parts"]
            assert [part.damage_type for part in parts] == ["physical", "true"]
            assert [part.time_offset for part in parts] == pytest.approx(
                [charge, charge]
            )

    def test_damage_event_times_one_rotation(self):
        # One-rotation casts land at 0.0: the W hit lands at exactly the
        # charge (0/0.25/0.5/0.75/1).  In All Out the same instant carries
        # two rows — the physical hit and the charge-interpolated true
        # half — and together they are the row's whole total.
        for charge in (0.0, 0.25, 0.5, 0.75, 1.0):
            result = _fight({"w_charge": charge}, one_rotation=True)
            events = result["breakdown"]["W"]["damage_events"]
            assert [e["time"] for e in events] == pytest.approx([charge])
            assert events[0]["raw_damage"] == pytest.approx(
                result["breakdown"]["W"]["total_raw"]
            )
            row = _fight({"all_out": True, "w_charge": charge}, one_rotation=True)[
                "breakdown"
            ]["W"]
            events = row["damage_events"]
            assert [e["damage_type"] for e in events] == ["physical", "true"]
            assert [e["time"] for e in events] == pytest.approx([charge, charge])
            assert sum(e["raw_damage"] for e in events) == pytest.approx(
                row["total_raw"]
            )

    def test_damage_event_times_timed_fight(self):
        # Timed fight: the W cast starts at 0.45 (Q's 0.45 cast time), so
        # the hit lands at cast + charge (0.45/0.7/0.95/...) — All Out
        # puts both of its rows on that same instant.
        for charge, want in ((0.0, 0.45), (0.25, 0.7), (0.5, 0.95), (1.0, 1.45)):
            result = _fight({"w_charge": charge}, duration=10.0)
            events = result["breakdown"]["W"]["damage_events"]
            assert [e["time"] for e in events] == pytest.approx([want])
            events = _fight({"all_out": True, "w_charge": charge}, duration=10.0)[
                "breakdown"
            ]["W"]["damage_events"]
            assert [e["time"] for e in events] == pytest.approx([want, want])


# ---------------------------------------------------------------------------
# S4 — All Out branching
# ---------------------------------------------------------------------------


class TestAllOutBranching:
    def test_all_out_false_physical_only(self):
        # all_out False (default): the W prices the physical packet only —
        # one part, one damage event, no true damage anywhere.
        _, abilities = _parse({})
        assert len(abilities["W"]["parts"]) == 1
        assert abilities["W"]["parts"][0].damage_type == "physical"
        result = _fight({}, one_rotation=True)
        row = result["breakdown"]["W"]
        assert len(row["damage_events"]) == 1
        assert row["damage_events"][0]["damage_type"] == "physical"
        # Without All Out the row carries no damage split at all.
        assert "damage_by_type" not in row or "true" not in row["damage_by_type"]

    def test_all_out_true_adds_true_part(self):
        # all_out True: the W prices physical + interpolated true; the
        # fight row splits damage_by_type and the true part is unmitigated.
        stats, _ = _parse({})
        physical = _typed_w("Physical Damage", 5, stats)
        low = _typed_w("Minimum Bonus True Damage", 5, stats)
        high = _typed_w("Maximum Bonus True Damage", 5, stats)
        _, abilities = _parse({"all_out": True, "w_charge": 0.5})
        assert abilities["W"]["total_raw"] == pytest.approx(
            physical + low + (high - low) * 0.5
        )
        result = _fight({"all_out": True, "w_charge": 0.5}, one_rotation=True)
        row = result["breakdown"]["W"]
        assert row["total_raw"] == pytest.approx(physical + low + (high - low) * 0.5)
        assert row["damage_by_type"]["true"] == pytest.approx(
            (low + (high - low) * 0.5) * 100.0 / 100.0
        )
        # The rotation casts Q,W,E,R at time 0; R's buff resolves after W,
        # so W's physical packet is mitigated at the un-penned 50 armor.
        assert row["total_damage"] == pytest.approx(
            physical * 100.0 / 150.0 + (low + (high - low) * 0.5)
        )

    def test_r_terrain_unchanged_two_strikes(self):
        # r_terrain is independent of All Out: False -> the single
        # physical strike at 0.3; True -> both strikes (0.3 and 0.432),
        # total = Physical Damage + Strike Physical Damage (the 5% bonus
        # health term has no resolver and contributes 0 — pinned actual).
        stats, _ = _parse({})
        base = _extract("R", "Physical Damage", 3, stats)
        strike = _extract("R", "Strike Physical Damage", 3, stats)
        for option, want_parts in (
            ({}, 1),
            ({"r_terrain": True}, 2),
            ({"all_out": True, "r_terrain": True}, 2),
        ):
            _, abilities = _parse(option)
            parts = abilities["R"]["parts"]
            assert len(parts) == want_parts
            assert parts[0].amount == pytest.approx(base)
            assert parts[0].time_offset == pytest.approx(_R_STRIKE_FIRST_TIME_OFFSET)
            if want_parts == 2:
                assert parts[1].amount == pytest.approx(strike)
                assert parts[1].time_offset == pytest.approx(
                    _R_STRIKE_SECOND_TIME_OFFSET
                )
                assert abilities["R"]["total_raw"] == pytest.approx(base + strike)
            else:
                assert abilities["R"]["total_raw"] == pytest.approx(base)
        result = _fight({"r_terrain": True}, one_rotation=True)
        events = result["breakdown"]["R"]["damage_events"]
        assert [e["time"] for e in events] == pytest.approx([0.3, 0.432])
        assert [e["raw_damage"] for e in events] == pytest.approx([base, strike])
        assert result["breakdown"]["R"]["total_raw"] == pytest.approx(base + strike)

    def test_r_stat_buff_present_when_all_out(self):
        # The R entry carries the stat_buff ONLY when the all_out option
        # is set (not for r_terrain alone): attack speed from the cached
        # "Bonus Attack Speed" row (40/60/80 by R rank), 50% armor
        # penetration and 20% omnivamp (module constants under test).
        for rank, want_as in ((1, 40.0), (2, 60.0), (3, 80.0)):
            _, abilities = _parse({"all_out": True}, ranks={**_RANKS, "R": rank})
            assert abilities["R"]["stat_buff"] == {
                "bonus_attack_speed": want_as,
                "armor_penetration_bonus_percent": _ALLOUT_ARMOR_PEN_PERCENT,
                "omnivamp_percent": _ALLOUT_OMNIVAMP_PERCENT,
            }
        r_ability = _ability("R")
        assert extract_value(r_ability, "Bonus Attack Speed", 3) == pytest.approx(80.0)
        _, abilities = _parse({})
        assert abilities["R"].get("stat_buff") is None
        _, abilities = _parse({"r_terrain": True})
        assert abilities["R"].get("stat_buff") is None

    def test_65_percent_threshold_named_state_never_priced(self):
        # The 65% health threshold and the resist conversion are NAMED
        # state: the R detail carries the phrase, the R total_raw prices
        # only the sourced strikes, and no threshold/resist arithmetic
        # appears in any part.  The ASSUMPTIONS say the same.
        _, abilities = _parse({})
        r = abilities["R"]
        assert "65% health threshold" in r["detail"]
        assert "state" in r["detail"]
        assert r["total_raw"] == pytest.approx(
            _extract("R", "Physical Damage", 3, _stats())
        )
        assert all(part.damage_type == "physical" for part in r["parts"])
        assumptions = get_champion_options_meta("K'Sante")["assumptions"]
        assert any(
            "health threshold" in text and "visible state" in text
            for text in assumptions
        )


# ---------------------------------------------------------------------------
# S5 — Options
# ---------------------------------------------------------------------------


class TestOptions:
    def test_existing_options_byte_identical(self):
        # p_marks/r_terrain/all_out metadata is byte-identical (the P1-4A
        # completion may add a state receipt to w_charge only); w_charge's
        # declared fields are pinned in S3.
        meta = get_champion_options_meta("K'Sante")
        by_key = {option["key"]: option for option in meta["options"]}
        assert by_key["p_marks"] == {
            "key": "p_marks",
            "type": "int",
            "default": 1,
            "min": 0,
            "max": 8,
            "label": "Dauntless Instinct marked attacks",
        }
        assert by_key["r_terrain"] == {
            "key": "r_terrain",
            "type": "bool",
            "default": False,
            "label": "All Out terrain strike",
        }
        assert by_key["all_out"] == {
            "key": "all_out",
            "type": "bool",
            "default": False,
            "label": "All Out state",
        }

    def test_options_served_by_config_endpoint(self):
        response = app_module.app.test_client().get("/api/config")
        assert response.status_code == 200
        options = response.get_json()["champion_options"]["K'Sante"]["options"]
        by_key = {option["key"]: option for option in options}
        assert by_key["w_charge"]["type"] == "float"
        assert by_key["w_charge"]["default"] == pytest.approx(1.0)
        assert by_key["w_charge"]["min"] == pytest.approx(0.0)
        assert by_key["w_charge"]["max"] == pytest.approx(1.0)
        assert by_key["w_charge"]["step"] == pytest.approx(0.25)

    def test_api_rejects_named_400s(self):
        # The brief's named 400s: w_charge 1.5/-0.2/2.5 out of range, "abc"
        # not a number; all_out "yes"/1 not a JSON boolean.
        for bad, message in (
            (
                {"w_charge": 1.5},
                "champion_options.w_charge must be between 0.0 and 1.0",
            ),
            (
                {"w_charge": -0.2},
                "champion_options.w_charge must be between 0.0 and 1.0",
            ),
            (
                {"w_charge": 2.5},
                "champion_options.w_charge must be between 0.0 and 1.0",
            ),
            ({"w_charge": "abc"}, "champion_options.w_charge must be a number"),
            ({"all_out": "yes"}, "champion_options.all_out must be true or false"),
            ({"all_out": 1}, "champion_options.all_out must be true or false"),
        ):
            response = _api(bad)
            assert response.status_code == 400
            assert response.get_json()["error"] == message
        # Boundaries and the step grid pass.
        for good in (
            {"w_charge": 0.0},
            {"w_charge": 0.25},
            {"w_charge": 0.5},
            {"w_charge": 0.75},
            {"w_charge": 1.0},
            {"all_out": True},
            {"all_out": False},
        ):
            response = _api(good)
            assert response.status_code == 200

    def test_api_rejects_unknown_and_other_bounds(self):
        # Unknown keys and the other options' bounds get named 400s too.
        for bad, message in (
            ({"bogus": 1}, "champion_options contains unknown option bogus"),
            ({"p_marks": 9}, "champion_options.p_marks must be between 0 and 8"),
            ({"p_marks": -1}, "champion_options.p_marks must be between 0 and 8"),
            ({"p_marks": "abc"}, "champion_options.p_marks must be a number"),
            ({"r_terrain": "yes"}, "champion_options.r_terrain must be true or false"),
        ):
            response = _api(bad)
            assert response.status_code == 400
            assert response.get_json()["error"] == message

    def test_parse_path_clamps_and_coerces_pinned_actual(self):
        # Pinned actual: the parse path clamps w_charge to [0,1] (1.5 -> 1,
        # -0.2 -> 0, 2.5 -> 1) and float()s numeric seeds; all_out is a
        # bool() coercion (any truthy value flips All Out on — the strict
        # JSON-boolean boundary lives at the API only); p_marks int()s and
        # clamps (2.5 -> 2, 9 -> 8, 0/-1 -> no passive).
        _, one = _parse({"w_charge": 1.5})
        _, maxed = _parse({"w_charge": 1.0})
        assert one["W"]["parts"][0].time_offset == maxed["W"]["parts"][0].time_offset
        _, zero = _parse({"w_charge": -0.2})
        assert zero["W"]["parts"][0].time_offset == pytest.approx(0.0)
        _, two_five = _parse({"w_charge": 2.5})
        assert two_five["W"]["parts"][0].time_offset == pytest.approx(1.0)
        _, string_charge = _parse({"w_charge": "0.5"})
        assert string_charge["W"]["parts"][0].time_offset == pytest.approx(0.5)
        for truthy in ("yes", "no", 1, 0.5):
            _, abilities = _parse({"all_out": truthy})
            assert len(abilities["W"]["parts"]) == 2
        _, abilities = _parse({"all_out": 0})
        assert len(abilities["W"]["parts"]) == 1
        _, abilities = _parse({"p_marks": 2.5})
        assert abilities["passive"]["proc_count"] == 2
        _, abilities = _parse({"p_marks": 9})
        assert abilities["passive"]["proc_count"] == 8
        _, abilities = _parse({"p_marks": 0})
        assert "passive" not in abilities

    def test_parse_path_non_numeric_fails_closed(self):
        # Non-numeric options raise at the parse path (no invented charge).
        for option in ({"w_charge": "abc"}, {"p_marks": "abc"}):
            with pytest.raises(ValueError):
                _parse(option)

    def test_unlearned_and_overranked_slots(self):
        # Rank 0 slots are not emitted (fail closed); an over-rank (6)
        # clamps the extraction to the rank-5 values (pinned actual).
        _, abilities = _parse({}, ranks={**_RANKS, "W": 0})
        assert "W" not in abilities
        _, abilities = _parse({}, ranks={**_RANKS, "E": 0})
        assert "E" not in abilities
        _, abilities = _parse({}, ranks={**_RANKS, "W": 6})
        _, rank5 = _parse({}, ranks={**_RANKS, "W": 5})
        assert abilities["W"]["total_raw"] == rank5["W"]["total_raw"]

    def test_w_charge_option_state_receipt_declares_charge_rule(self):
        # Mirrors the P3-3Z option state receipts: w_charge carries a typed
        # public receipt declaring the charge rule — the row attributes the
        # interpolation reads, the bounds/step/default, and provenance.
        # Absent today (the P1-4A typed W declaration).
        meta = get_champion_options_meta("K'Sante")
        option = next(o for o in meta["options"] if o["key"] == "w_charge")
        state = option["state"]
        assert state["physical_row_attribute"] == "Physical Damage"
        assert state["min_true_row_attribute"] == "Minimum Bonus True Damage"
        assert state["max_true_row_attribute"] == "Maximum Bonus True Damage"
        assert state["default"] == pytest.approx(1.0)
        assert state["min"] == pytest.approx(0.0)
        assert state["max"] == pytest.approx(1.0)
        assert state["step"] == pytest.approx(0.25)
        assert state["source"]  # provenance on the declaration


# ---------------------------------------------------------------------------
# S6 — Resistance state
# ---------------------------------------------------------------------------


class TestResistanceState:
    def test_w_resist_rows_are_present_with_non_empty_units(self):
        # THE verdict for the coordinator: the "bonus armor"/"bonus magic
        # resistance" W rows ARE in the cache with values AND non-empty
        # descriptive units (the AGENTS.md "units come back empty" note is
        # stale for this cache state).  The generic resolver half-parses
        # them — see the next test.
        for attribute in (
            "Physical Damage",
            "Minimum Bonus True Damage",
            "Maximum Bonus True Damage",
            "Total Maximum Mixed Damage",
        ):
            row = _leveling("W", attribute)
            assert len(row["modifiers"]) == 2
            assert row["modifiers"][0]["units"] == [""] * 5
            units = row["modifiers"][1]["units"]
            assert all("per 100 bonus armor" in u for u in units)
            assert all("per 100 bonus magic resistance" in u for u in units)
            assert all("target's maximum health" in u for u in units)

    def test_resist_terms_resolve_against_bonus_armor_fixed_attribution(self):
        # P1-4A FIX: the W resist ratios are a real authored effect
        # (game MaxHealthDamageResistRatio 0.0002 = 2% per 100 bonus
        # armor/MR) and now resolve against the CASTER's BONUS armor/MR —
        # never the totals or the target's.  At the matrix stats (bonus
        # 20/10, totals 50/40) the rank-5 physical term is the correct
        # 8.6% of max health (172), NOT the old total-attributed 9.8%
        # (196) — the pre-fix W price overstated by 24 raw.
        stats, abilities = _parse({})
        physical = abilities["W"]["parts"][0].amount
        flat = float(_leveling("W", "Physical Damage")["modifiers"][0]["values"][4])
        assert physical == pytest.approx(_typed_w("Physical Damage", 5, stats))
        assert flat + (
            8.0 + 2.0 * 20.0 / 100.0 + 2.0 * 10.0 / 100.0
        ) / 100.0 * _TARGET_MAX_HP == pytest.approx(physical)
        assert (
            8.0 + 2.0 * 20.0 / 100.0 + 2.0 * 10.0 / 100.0
        ) / 100.0 * _TARGET_MAX_HP == pytest.approx(172.0)
        # The old total-attribution term (196) is GONE — asserting the
        # fixed price never equals it.
        assert physical != pytest.approx(flat + 196.0)
        # The true range uses the same bonus attribution.
        assert abilities["W"]["parts"][0].amount == pytest.approx(
            _typed_w("Physical Damage", 5, stats)
        )
        _, abilities_ao = _parse({"all_out": True})
        assert abilities_ao["W"]["parts"][1].amount == pytest.approx(
            _typed_w("Maximum Bonus True Damage", 5, stats)
        )

    def test_resist_conversion_named_fail_closed_denial(self):
        # The R armor/MR-to-AD resist conversion receipts a named
        # fail-closed denial (reason contains "resist") in the documentary
        # walk — and the denial invents no damage (the W total_raw stays
        # the engine-priced stream).  The R heal_omnivamp row carries no
        # total_damage key, so the sum tolerates it.
        result = _fight({"all_out": True}, one_rotation=True)
        reasons = " ".join(_denial_reasons(result)).lower()
        assert "resist" in reasons
        assert result["total_damage"] == pytest.approx(
            sum(row.get("total_damage", 0.0) for row in result["breakdown"].values())
        )

    def test_w_total_raw_prices_sourced_term_no_invented_stats(self):
        # P1-4A fail-closed contract: no invented stats — the W physical
        # packet prices the FULL sourced term (the cached flat row + the
        # %maxHP base + the game-verified bonus-armor/MR ratios attributed
        # to the CASTER's bonus stats).  The old TOTAL-armor misattribution
        # is gone: with zero bonus stats the term reduces to flat + 8%
        # maxHP, and it NEVER uses the totals or the target's resists.
        stats, _ = _parse({})
        flat = float(_leveling("W", "Physical Damage")["modifiers"][0]["values"][4])
        _, abilities = _parse({})
        assert abilities["W"]["parts"][0].amount == pytest.approx(
            _typed_w("Physical Damage", 5, stats)
        )
        assert abilities["W"]["total_raw"] == pytest.approx(
            _typed_w("Physical Damage", 5, stats)
        )
        # With the fixture's bonus 20/10 the term includes the ratios; a
        # zero-bonus caster prices flat + the 8% base only (never the
        # target's or the totals).
        zero = dict(_stats(), bonus_armor=0.0, bonus_magic_resistance=0.0)
        assert _typed_w("Physical Damage", 5, zero) == pytest.approx(
            flat + 8.0 / 100.0 * _TARGET_MAX_HP
        )


# ---------------------------------------------------------------------------
# S7 — Malformed inputs + missing rows
# ---------------------------------------------------------------------------


class TestMalformedInputs:
    def test_missing_w_rows_fail_closed_not_silent_zero(self):
        # Pinned contract: a missing/degraded W row must never price a
        # silent zero-damage W — the typed declaration either raises or
        # emits a named fail-closed receipt (the P3-3Z _require_row
        # precedent).  TODAY the module emits zero-total_raw entries in
        # both branches (pinned actual, flagged); this flips when the
        # P1-4A completion lands.
        try:
            abilities = _strip_rows("W")
        except (ValueError, KeyError, AssertionError):
            return  # fail-closed raise is contract-compliant
        w = abilities.get("W")
        assert w is None or w["total_raw"] != 0.0
        try:
            abilities = _strip_rows("W", {"all_out": True})
        except (ValueError, KeyError, AssertionError):
            return
        w = abilities.get("W")
        assert w is None or w["total_raw"] != 0.0

    def test_documentary_walk_receipts_engine_priced_stream_with_identity(self):
        # The coordinator's documentary walk receipts the accepted
        # engine-priced stream (physical + interpolated true at the fight's
        # charge) with ownership + event identity, amounts matching the
        # engine's raw values — never re-pricing mid-fight.  Absent today.
        result = _fight({"all_out": True, "w_charge": 0.5}, one_rotation=True)
        walk = _w_walk(result)
        assert walk is not None
        accepted = [r for r in walk.get("receipts", []) if r.get("accepted")]
        assert accepted
        assert all(r.get("owner") == "main" for r in accepted)
        assert all(
            r.get("source") or (r.get("detail") or {}).get("event_id") for r in accepted
        )
        physical = _typed_w("Physical Damage", 5, _stats())
        low = _typed_w("Minimum Bonus True Damage", 5, _stats())
        high = _typed_w("Maximum Bonus True Damage", 5, _stats())
        amounts = sorted(float(r["amount"]) for r in accepted)
        assert amounts == sorted([physical, low + (high - low) * 0.5])


# ---------------------------------------------------------------------------
# S8 — Unchanged boundaries
# ---------------------------------------------------------------------------


class TestUnchangedBoundaries:
    def test_p_unchanged(self):
        # Dauntless Instinct: the module's marked-attack formula — flat
        # "Bonus Damage" + "Max Health Damage" %maxHP, plus the authored
        # All Out extra (1% + 1% per 100 bonus armor/MR) when all_out —
        # all sourced from the cached P rows / module constants.
        stats, abilities = _parse({"p_marks": 1})
        p = abilities["passive"]
        assert p["name"] == "Dauntless Instinct"
        base = extract_value(_ability("P"), "Bonus Damage", _LEVEL)
        ratio = extract_value(_ability("P"), "Max Health Damage", _LEVEL) / 100.0
        want = base + ratio * _TARGET_MAX_HP
        assert p["parts"][0].amount == pytest.approx(want)
        assert p["total_raw"] == pytest.approx(want)
        assert p["proc_count"] == 1
        assert p["parts"][0].basic_damage is True
        _, abilities = _parse({"all_out": True})
        want_allout = (
            base
            + (ratio + 0.01 + 0.01 * 20.0 / 100.0 + 0.01 * 10.0 / 100.0)
            * _TARGET_MAX_HP
        )
        assert abilities["passive"]["total_raw"] == pytest.approx(want_allout)
        _, abilities = _parse({"p_marks": 3})
        assert abilities["passive"]["total_raw"] == pytest.approx(want * 3)
        assert abilities["passive"]["proc_count"] == 3
        # The All Out extra reads BONUS armor/MR (correct keys).
        assert 0.01 + 0.01 * 20.0 / 100.0 + 0.01 * 10.0 / 100.0 == pytest.approx(0.013)

    def test_q_unchanged(self):
        # Ntofo Strikes prices the cached "Physical Damage" row (which
        # resolves its "% bonus armor"/"% bonus magic resistance" modifiers
        # correctly — the simple-unit path) at every rank.
        for rank in range(1, 6):
            stats, abilities = _parse({}, ranks={**_RANKS, "Q": rank})
            assert abilities["Q"]["total_raw"] == pytest.approx(
                _extract("Q", "Physical Damage", rank, stats)
            )
            assert abilities["Q"]["parts"][0].damage_type == "physical"
        _, abilities = _parse({})
        assert abilities["Q"]["name"] == "Ntofo Strikes"
        assert abilities["Q"]["resource_cost"] == pytest.approx(20.0)
        assert abilities["Q"]["cast_time"] == pytest.approx(0.45)

    def test_e_unchanged(self):
        # Footwork stays a no-damage state row with its sourced cooldown
        # and cost.
        _, abilities = _parse({})
        e = abilities["E"]
        assert e["name"] == "Footwork"
        assert e["total_raw"] == 0.0
        assert e["parts"] == ()
        assert "utility" in e["detail"]
        assert e["cooldown"] == pytest.approx(8.0)
        assert e["resource_cost"] == pytest.approx(65.0)
        result = _fight({}, one_rotation=True)
        assert result["breakdown"]["E"]["total_damage"] == 0.0

    def test_cooldowns_and_mana_unchanged(self):
        # W cooldown 14..10 and cost 40..60 by rank; R cooldown 120/100/80
        # and cost 100; the one-rotation mana ledger books Q20/W60/E65/R100
        # against the 300 opening.
        for rank, cd, cost in ((1, 14.0, 40.0), (5, 10.0, 60.0)):
            _, abilities = _parse({}, ranks={**_RANKS, "W": rank})
            assert abilities["W"]["cooldown"] == pytest.approx(cd)
            assert abilities["W"]["resource_cost"] == pytest.approx(cost)
        for rank, cd in ((1, 120.0), (2, 100.0), (3, 80.0)):
            _, abilities = _parse({}, ranks={**_RANKS, "R": rank})
            assert abilities["R"]["cooldown"] == pytest.approx(cd)
            assert abilities["R"]["resource_cost"] == pytest.approx(100.0)
        result = _fight({}, one_rotation=True)
        ledger = result["resource_ledger"]
        assert ledger["kind"] == "mana"
        spends = {
            row["source"]: row
            for row in ledger["receipts"]
            if row["operation"] == "spend"
        }
        assert spends["ability Q cast"]["amount"] == pytest.approx(20.0)
        assert spends["ability W cast"]["amount"] == pytest.approx(60.0)
        assert spends["ability E cast"]["amount"] == pytest.approx(65.0)
        assert spends["ability R cast"]["amount"] == pytest.approx(100.0)
        assert result["resource_spent"] == pytest.approx(245.0)
        assert result["resource_remaining"] == pytest.approx(55.0)

    def test_assumptions_pin_charge_and_state(self):
        # The module ASSUMPTIONS name the charge rule and the state policy
        # (the health threshold / resistance conversion stay visible state,
        # not hidden arithmetic).
        assumptions = get_champion_options_meta("K'Sante")["assumptions"]
        assert any(
            "Path Maker uses its physical packet" in text
            and "true-damage range" in text
            for text in assumptions
        )
        assert any(
            "health threshold" in text
            and "resistance conversion" in text
            and "visible state" in text
            for text in assumptions
        )


# ---------------------------------------------------------------------------
# S9 — Score/receipt parity + no re-pricing
# ---------------------------------------------------------------------------


class TestScoreReceiptParity:
    def test_w_surface_byte_identical_under_score_only(self):
        # The W surface (breakdown row, raw, casts, mana ledger, spent /
        # remaining) is identical between the full walk and the compiled
        # score path, for every charge and both All Out states, in
        # one-rotation and timed fights.
        for option in (
            {},
            {"w_charge": 0.0},
            {"w_charge": 0.25},
            {"w_charge": 0.5},
            {"w_charge": 1.0},
            {"all_out": True},
            {"all_out": True, "w_charge": 0.5},
            {"all_out": True, "r_terrain": True},
        ):
            for one_rotation in (True, False):
                full = _fight(option, one_rotation=one_rotation)
                scored = _fight(option, one_rotation=one_rotation, score_only=True)
                assert full["breakdown"]["W"] == scored["breakdown"]["W"]
                assert full["breakdown"]["R"] == scored["breakdown"]["R"]
                assert full["resource_spent"] == scored["resource_spent"]
                assert full["resource_remaining"] == scored["resource_remaining"]
                assert full["resource_ledger"] == scored["resource_ledger"]
                shared = ("time", "slot", "name", "ordinal", "resource_cost")
                for full_row, scored_row in zip(
                    full["cast_timeline"], scored["cast_timeline"]
                ):
                    assert {k: full_row[k] for k in shared} == {
                        k: scored_row[k] for k in shared
                    }

    def test_charge_branch_never_re_priced_mid_fight(self):
        # The charge branch is priced at parse time only: the fight's W
        # raw equals the seeded parse raw at every charge and in both All
        # Out states, in one-rotation and timed fights.
        for option in (
            {},
            {"w_charge": 0.0},
            {"w_charge": 0.25},
            {"w_charge": 0.5},
            {"w_charge": 0.75},
            {"w_charge": 1.0},
            {"all_out": True, "w_charge": 0.0},
            {"all_out": True, "w_charge": 0.5},
            {"all_out": True, "w_charge": 1.0},
        ):
            _, abilities = _parse(option)
            for one_rotation in (True, False):
                result = _fight(option, one_rotation=one_rotation)
                assert result["breakdown"]["W"]["total_raw"] == pytest.approx(
                    abilities["W"]["total_raw"]
                )

    def test_all_out_full_vs_score_totals_equal_with_fresh_stats(self):
        # With the matrix fixture (fresh stats per fight — _parse builds a
        # new dict every call) the full and score paths agree under all_out
        # INCLUDING total_damage and the auto/omnivamp rows: the R
        # stat_buff's attack-speed/omnivamp channel prices the same stream
        # in both paths.
        #
        # FLAG (pre-existing engine quirk, outside this package): the fight
        # engine MUTATES the caller's stats dict in place when the R
        # stat_buff applies (attack_speed +0.5, bonus_attack_speed 80,
        # omnivamp 20, armor_pen 50) — reusing one stats dict across a
        # full + scored pair makes the scored run see the buffed stats and
        # diverge (13 vs 18 autos).  The score-parity contract holds only
        # when each fight is seeded from fresh stats, which the matrix and
        # the API path both do.
        full = _fight({"all_out": True}, one_rotation=True)
        scored = _fight({"all_out": True}, one_rotation=True, score_only=True)
        assert full["breakdown"]["W"] == scored["breakdown"]["W"]
        assert full["breakdown"]["R"] == scored["breakdown"]["R"]
        assert full["breakdown"]["auto_attacks"] == scored["breakdown"]["auto_attacks"]
        assert full["total_damage"] == scored["total_damage"]


# ---------------------------------------------------------------------------
# S10 — Regression surface (kept green; run list)
# ---------------------------------------------------------------------------
# Run ONLY this file plus the mandated sanity list (contract 10):
#   .venv/bin/python -m pytest tests/test_ksante_w_resistance.py \
#     tests/test_aurelion_sol_stardust_ledger.py tests/test_senna_souls_ledger.py \
#     tests/test_bard_chimes_ledger.py tests/test_heimerdinger_multihit.py \
#     tests/test_rengar_ferocity_ledger.py tests/test_state_lifecycle.py \
#     tests/test_state_lifecycle_consumers.py tests/test_resource_ledger.py \
#     tests/test_resource_ledger_consumers.py \
#     tests/test_resource_ledger_champion_consumers.py \
#     tests/test_catalyst_resource_ledger.py tests/test_item_sustain.py \
#     tests/test_mana_restore_refund.py tests/test_app.py
# K'Sante grep surface (contract 10), run separately:
#   tests/test_ksante_r_atomizer.py tests/test_p1_review_1.py \
#     tests/test_e1_healing_b6.py tests/test_cp10_batch_02.py
