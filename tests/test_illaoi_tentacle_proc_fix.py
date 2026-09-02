"""Regression pin: Illaoi P (Prophet of an Elder God) proc-count fix.

**The bug.** ``_tentacle`` carried the tentacle count in BOTH
``DamagePart.count`` and ``proc_count``. ``damage.py``'s
``_add_precomputed_proc_damage`` (~L6161-6175) prices
``sum(part.amount * part.count) * proc_count``, so a count of N tentacle
strikes was priced as N^2 hits.  At level 18 with zero target resistances
the sourced per-strike value is 448.50 (180 base + 110% of 150 total AD +
40% of 0 AP, all x1.30 for Tentacle Smash's max-rank +30% Q increase —
see ``TestSourcedPerStrikeValue``).  The bug scaled the fight-row total as
1x / 9x / 25x that base instead of 1x / 3x / 5x:

  p_tentacles=1 -> 448.50   (correct; N=1 hides N^2==N)
  p_tentacles=3 -> 4036.50  (bug) vs. 1345.50 (correct, 3 x 448.50)
  p_tentacles=5 -> 11212.50 (bug) vs. 2242.50 (correct, 5 x 448.50)

This was invisible to the golden snapshot (whose defaults use
p_tentacles=1, where N == N^2) and invisible to the pre-existing
``TestIllaoiTentacles.test_tentacle_count_option`` in
``test_e4_summon_1.py`` (that test's own assertion,
``total_damage == count * damage_per_hit``, is a tautology under the bug
too: the packet's ``damage_per_hit`` column was itself already inflated
by the same factor, so the identity held on both sides of the fix).

The exact same defect and fix pattern shipped for Naafiri's P (We Are
More) in the same session — see ``tests/test_naafiri_pack.py``'s
``TestProcCountSemantics`` and the module docstring of
``src/calculator/champions/naafiri.py``.

**The fix.** ``DamagePart.count`` is now 1 (one hit per part); the
tentacle count is carried only in ``proc_count``. ``total_raw`` (computed
directly in the module) was never affected — only the fight-engine
pricing path in ``damage.py`` was — so ``TestLinearScaling`` pins that the
fight breakdown's ``total_damage`` now equals the ability parse's
``total_raw`` at zero resistances, for every scale factor.
"""

import copy
import json
from pathlib import Path

import pytest

from src.calculator.champions import parse_champion_abilities
from src.calculator.data_fetcher import fetch_champion_data
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.stats import calculate_total_stats

_CHAMPIONS = fetch_champion_data()
_BY_NAME = {data.get("name"): data for data in _CHAMPIONS.values()}
_ILLAOI = _BY_NAME["Illaoi"]
_WIKI = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))["Illaoi"]

_LEVEL = 18
_TARGET = {
    "target_max_health": 2000.0,
    "target_current_health": 2000.0,
    "target_missing_health": 0.0,
}
# 448.50 / 1345.50 / 2242.50 at p_tentacles 1 / 3 / 5, L18, zero resists.
_PER_STRIKE = 448.5
_EXPECTED_BY_COUNT = {1: _PER_STRIKE, 3: 3 * _PER_STRIKE, 5: 5 * _PER_STRIKE}


def _parse(*, p_tentacles: int, level: int = _LEVEL):
    """Parse Illaoi at *level* with no items, mirroring the pipeline."""
    data = copy.deepcopy(_ILLAOI)
    stats = calculate_total_stats(data, level, [])
    abilities = parse_champion_abilities(
        data,
        level,
        stats["ability_power"],
        ability_ranks=None,
        champion_stats=stats,
        target_stats=dict(_TARGET),
        champion_options={"p_tentacles": p_tentacles},
    )
    return stats, abilities


def _fight(*, p_tentacles: int, level: int = _LEVEL):
    """One deterministic burst fight at zero target resistances."""
    params = FightParams(
        target_health=2000.0,
        target_bonus_health=0.0,
        target_armor=0.0,
        target_magic_resistance=0.0,
        fight_duration_seconds=5.0,
        auto_attack_uptime=0.0,
        one_rotation=True,
        include_actives=True,
        cast_order=None,
        auto_attacks_only=False,
        ability_ranks=None,
        champion_options={"p_tentacles": p_tentacles},
        deterministic=True,
    )
    return run_fight(copy.deepcopy(_ILLAOI), level, [], params)


# ---------------------------------------------------------------------------
# The sourced per-strike value the whole file is anchored to.
# ---------------------------------------------------------------------------


class TestSourcedPerStrikeValue:
    def test_bonus_physical_damage_row_at_level_18(self):
        """P's own leveling row: index 17 (level 18) is 180."""
        p_effects = _WIKI["abilities"]["P"][0]["effects"][1]["leveling"]
        row = next(r for r in p_effects if r["attribute"] == "Bonus Physical Damage")
        assert row["modifiers"][0]["values"][17] == pytest.approx(180.0)
        assert row["modifiers"][1]["values"] == [110.0]
        assert row["modifiers"][1]["units"] == ["% AD"]
        assert row["modifiers"][2]["values"] == [40.0]
        assert row["modifiers"][2]["units"] == ["% AP"]

    def test_q_damage_increase_max_rank(self):
        """Q's own leveling row: rank 5 (index 4) is 30%."""
        q_effects = _WIKI["abilities"]["Q"][0]["effects"]
        row = next(
            r
            for effect in q_effects
            for r in effect.get("leveling", [])
            if r["attribute"] == "Damage Increase"
        )
        assert row["modifiers"][0]["values"][4] == pytest.approx(30.0)

    def test_per_strike_composition_at_level_18_no_items(self):
        """180 + 110% x 150 total AD + 40% x 0 AP, x1.30 == 448.50."""
        stats, _ = _parse(p_tentacles=1)
        assert stats["attack_damage"] == pytest.approx(150.0)
        assert stats["ability_power"] == pytest.approx(0.0)
        base = 180.0 + 1.10 * stats["attack_damage"] + 0.40 * stats["ability_power"]
        assert base * 1.30 == pytest.approx(_PER_STRIKE)

    def test_ability_parse_total_raw_at_count_one(self):
        _, abilities = _parse(p_tentacles=1)
        assert abilities["passive"]["total_raw"] == pytest.approx(_PER_STRIKE)


# ---------------------------------------------------------------------------
# The regression pin: linear scaling, not N^2.
# ---------------------------------------------------------------------------


class TestLinearScaling:
    """Pins the exact before/after values from the audit at 1/3/5."""

    @pytest.mark.parametrize("count", [1, 3, 5])
    def test_ability_parse_total_raw_scales_linearly(self, count):
        """total_raw was already correct pre-fix (computed in-module)."""
        _, abilities = _parse(p_tentacles=count)
        assert abilities["passive"]["total_raw"] == pytest.approx(
            _EXPECTED_BY_COUNT[count]
        )

    @pytest.mark.parametrize("count", [1, 3, 5])
    def test_fight_breakdown_total_scales_linearly_not_quadratically(self, count):
        """The literal bug: L18 zero-resist totals were N^2 x 448.50."""
        result = _fight(p_tentacles=count)
        total = result["breakdown"]["passive"]["total_damage"]
        assert total == pytest.approx(_EXPECTED_BY_COUNT[count])
        if count > 1:
            # The old (buggy) value the audit measured, for the record.
            buggy_value = count * count * _PER_STRIKE
            assert total != pytest.approx(buggy_value)

    @pytest.mark.parametrize("count", [1, 3, 5])
    def test_fight_breakdown_total_equals_ability_parse_total_raw(self, count):
        """At zero resistances the fight row must equal total_raw exactly."""
        _, abilities = _parse(p_tentacles=count)
        result = _fight(p_tentacles=count)
        assert result["breakdown"]["passive"]["total_damage"] == pytest.approx(
            abilities["passive"]["total_raw"]
        )

    def test_the_three_measured_bug_values_exactly(self):
        """The audit's exact bug numbers, 4036.50 and 11212.50, do not appear."""
        assert _fight(p_tentacles=1)["breakdown"]["passive"]["total_damage"] == (
            pytest.approx(448.5)
        )
        three = _fight(p_tentacles=3)["breakdown"]["passive"]["total_damage"]
        five = _fight(p_tentacles=5)["breakdown"]["passive"]["total_damage"]
        assert three == pytest.approx(1345.5)
        assert three != pytest.approx(4036.5)
        assert five == pytest.approx(2242.5)
        assert five != pytest.approx(11212.5)


# ---------------------------------------------------------------------------
# Proc-count contract: one hit per part, N as the proc count.
# ---------------------------------------------------------------------------


class TestProcCountSemantics:
    @pytest.mark.parametrize("count", [1, 3, 5])
    def test_one_hit_per_part_and_tentacle_count_as_proc_count(self, count):
        _, abilities = _parse(p_tentacles=count)
        passive = abilities["passive"]
        assert len(passive["parts"]) == 1
        assert passive["parts"][0].count == 1
        assert passive["proc_count"] == count
        assert passive["total_raw"] == pytest.approx(passive["parts"][0].amount * count)

    def test_damage_events_are_one_per_tentacle_at_half_second_cadence(self):
        _, abilities = _parse(p_tentacles=5)
        events = abilities["passive"]["damage_events"]
        assert len(events) == 5
        assert [event["time"] for event in events] == pytest.approx(
            [0.0, 0.5, 1.0, 1.5, 2.0]
        )
        assert all(event["damage_type"] == "physical" for event in events)


# ---------------------------------------------------------------------------
# The amp path: Tentacle strikes are not basic-damage instances, so
# ``_apply_basic_amp`` was always a no-op for this row regardless of the
# proc-count bug (unlike a genuine basic-attack proc row).
# ---------------------------------------------------------------------------


class TestAmpPathUnaffected:
    def test_tentacle_part_is_not_basic_damage(self):
        """basic_damage=False means _apply_basic_amp short-circuits."""
        _, abilities = _parse(p_tentacles=5)
        part = abilities["passive"]["parts"][0]
        assert part.basic_damage is False

    def test_fight_total_matches_raw_mitigation_with_no_amp_sources(self):
        """No item/rune amp is active in this fixture; totals stay exact."""
        result = _fight(p_tentacles=5)
        assert result["breakdown"]["passive"]["total_damage"] == pytest.approx(2242.5)
