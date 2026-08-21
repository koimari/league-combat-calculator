"""Tests for Singed champion ability parsing and damage calculation.

Closes the P/W/R slots (Q and E were already modeled before this session).

Reference arithmetic (sourced ``data/champions.json`` Singed R "Bonus Stats"
leveling, corroborated by the game binary's ``StatAmount`` DataValue
``[-5, 25, 55, 85, 115, 145, 175]`` at indices 0-6, ranks 1-3 = 25/55/85):

- R (Insanity Potion) rank 1/2/3: +25 / +55 / +85 to ability power and move
  speed (one sourced number feeds both ``stat_buff`` keys). Zero direct
  damage, 25s duration, 100s flat cooldown (all 3 ranks). The same sourced
  number also grants bonus armor and bonus magic resistance (the wiki text:
  "ability power, bonus armor, bonus magic resistance, bonus movement
  speed"), but those two stay OUT of ``stat_buff`` — see the closing-task
  consumer trace below.
- R is BUFF phase (Syndra P / Vayne R / Ambessa R precedent): it mutates
  ``ctx.stats["ability_power"]`` in-parse, so Poison Trail (Q, AP ratio
  0.10625 flat) and Fling (E, AP ratio 0.55 flat) read the buffed AP when
  both are parsed in the same call. At 0 base AP, R rank 2 (+55 AP) adds
  0.10625 * 55 = 5.84375 to Q's total_raw and 0.55 * 55 = 30.25 to E's
  total_raw.
- P (Noxious Slipstream) and W (Mega Adhesive) carry no enemy-damage
  formula in the pinned Wiki packet spec or the game binary's DataValues
  (MSPercent/MSDuration/PerTargetCD/TriggerArea for P; SlowPercent/
  WDuration/WRadius/DelayExecute/Radius for W) - both are sourced
  zero-damage rows, not silently absent slots.

Roadmap session (2026-08-21, closing task) — R's bonus_armor/
bonus_magic_resistance consumer question: traced ``_apply_stat_buff_
ultimates`` (``damage.py``) and the survival subsystem
(``participant_timeline.py`` / ``survival/receipt_state.py`` /
``survival/transitions.py``), then live-probed ``/api/calculate`` with
Singed vs. Ashe at level 18, R rank 0 vs. rank 3 (see
``src/calculator/champions/singed.py``'s module docstring for the full
trace and probe numbers). Verdict: NOT consumed anywhere — Singed's own
reported ``stats.bonus_armor``/``stats.bonus_magic_resistance`` and an
opponent's ``survival.damage_taken`` against him are bit-identical at
every R rank, in both attacker and defender roles. ``_INSANITY_POTION_
STATS`` was trimmed to ``("ability_power", "move_speed")`` accordingly;
bonus armor/MR moved to ``ASSUMPTIONS`` alongside the regen/Grievous
Wounds riders.
"""

import pytest

from src.calculator.champions import parse_champion_abilities as parse_abilities
from src.calculator.champions.singed import ASSUMPTIONS, MODULE_COVERAGE
from src.calculator.damage import FightConfig, calculate_fight_damage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STATS_0AP = {
    "ability_power": 0.0,
    "bonus_armor": 0.0,
    "bonus_magic_resistance": 0.0,
    "move_speed": 350.0,
}


def _parse(singed_data, *, ap=0.0, ranks, stats=None):
    """Parse Singed at level 18 with explicit ability ranks."""
    return parse_abilities(
        singed_data,
        18,
        ap,
        ability_ranks=ranks,
        champion_stats=dict(stats or STATS_0AP),
    )


# ---------------------------------------------------------------------------
# P: Noxious Slipstream / W: Mega Adhesive — sourced no-damage rows
# ---------------------------------------------------------------------------


class TestNonDamageSlots:
    """P and W carry no enemy-damage formula (packet spec + binary DataValues
    agree); each still emits an explicit zero-damage row, not a silent gap."""

    def test_passive_present_zero_damage(self, singed_data) -> None:
        abilities = _parse(singed_data, ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
        entry = abilities["passive"]
        assert entry["name"] == "Noxious Slipstream"
        assert entry["total_raw"] == 0.0
        assert entry["parts"] == ()
        assert entry["detail"]

    def test_w_present_zero_damage(self, singed_data) -> None:
        abilities = _parse(singed_data, ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
        entry = abilities["W"]
        assert entry["name"] == "Mega Adhesive"
        assert entry["total_raw"] == 0.0
        assert entry["parts"] == ()
        assert entry["detail"]


# ---------------------------------------------------------------------------
# R: Insanity Potion — BUFF-phase stat steroid
# ---------------------------------------------------------------------------


class TestRInsanityPotion:
    """R grants a flat AP/move-speed steroid; bonus armor/MR are sourced
    but have no consumer anywhere in this engine (see the module
    docstring's traced+probed consumer verdict), so they are documented
    in ASSUMPTIONS rather than carrying an inert stat_buff key."""

    def test_r_deals_no_damage(self, singed_data) -> None:
        abilities = _parse(singed_data, ranks={"Q": 5, "W": 5, "E": 5, "R": 1})
        assert abilities["R"]["total_raw"] == 0.0

    def test_r_has_stat_buff_for_two_consumed_stats_only(self, singed_data) -> None:
        abilities = _parse(singed_data, ranks={"Q": 5, "W": 5, "E": 5, "R": 1})
        stat_buff = abilities["R"]["stat_buff"]
        assert set(stat_buff) == {"ability_power", "move_speed"}

    def test_r_rank1_value_is_25(self, singed_data) -> None:
        abilities = _parse(singed_data, ranks={"Q": 5, "W": 5, "E": 5, "R": 1})
        stat_buff = abilities["R"]["stat_buff"]
        assert stat_buff["ability_power"] == pytest.approx(25.0)
        assert stat_buff["move_speed"] == pytest.approx(25.0)

    def test_r_rank2_value_is_55(self, singed_data) -> None:
        abilities = _parse(singed_data, ranks={"Q": 5, "W": 5, "E": 5, "R": 2})
        stat_buff = abilities["R"]["stat_buff"]
        assert stat_buff["ability_power"] == pytest.approx(55.0)
        assert stat_buff["move_speed"] == pytest.approx(55.0)

    def test_r_rank3_value_is_85(self, singed_data) -> None:
        abilities = _parse(singed_data, ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
        stat_buff = abilities["R"]["stat_buff"]
        assert stat_buff["ability_power"] == pytest.approx(85.0)
        assert stat_buff["move_speed"] == pytest.approx(85.0)

    def test_r_cooldown_is_100_at_every_rank(self, singed_data) -> None:
        for rank in (1, 2, 3):
            abilities = _parse(
                singed_data,
                ranks={"Q": 5, "W": 5, "E": 5, "R": rank},
            )
            assert abilities["R"]["cooldown"] == pytest.approx(100.0)

    def test_r_unranked_is_absent(self, singed_data) -> None:
        """rank < 1 (R not yet unlocked) fails closed: no entry at all."""
        abilities = _parse(singed_data, ranks={"Q": 5, "W": 5, "E": 5, "R": 0})
        assert "R" not in abilities


# ---------------------------------------------------------------------------
# R's BUFF-phase AP mutates Q/E, which parse in the DAMAGE phase after it
# ---------------------------------------------------------------------------


class TestRBuffPropagatesToDamageSlots:
    """R is listed with a BUFF phase, so Q/E scale off the buffed AP within
    the same parse call (Syndra P / Vayne R precedent)."""

    def test_r_buff_increases_q_total(self, singed_data) -> None:
        no_r = _parse(singed_data, ranks={"Q": 5, "W": 5, "E": 5, "R": 0})
        with_r = _parse(singed_data, ranks={"Q": 5, "W": 5, "E": 5, "R": 2})
        assert with_r["Q"]["total_raw"] > no_r["Q"]["total_raw"]

    def test_r_buff_increases_e_total(self, singed_data) -> None:
        no_r = _parse(singed_data, ranks={"Q": 5, "W": 5, "E": 5, "R": 0})
        with_r = _parse(singed_data, ranks={"Q": 5, "W": 5, "E": 5, "R": 2})
        assert with_r["E"]["total_raw"] > no_r["E"]["total_raw"]

    def test_q_rank2_buff_delta_matches_ap_ratio(self, singed_data) -> None:
        """Poison Trail's flat 0.10625 AP ratio times R rank 2's +55 AP."""
        no_r = _parse(singed_data, ranks={"Q": 5, "W": 5, "E": 5, "R": 0})
        with_r = _parse(singed_data, ranks={"Q": 5, "W": 5, "E": 5, "R": 2})
        delta = with_r["Q"]["total_raw"] - no_r["Q"]["total_raw"]
        assert delta == pytest.approx(0.10625 * 55.0)

    def test_e_rank2_buff_delta_matches_ap_ratio(self, singed_data) -> None:
        """Fling's flat 0.55 AP ratio times R rank 2's +55 AP."""
        no_r = _parse(singed_data, ranks={"Q": 5, "W": 5, "E": 5, "R": 0})
        with_r = _parse(singed_data, ranks={"Q": 5, "W": 5, "E": 5, "R": 2})
        delta = with_r["E"]["total_raw"] - no_r["E"]["total_raw"]
        assert delta == pytest.approx(0.55 * 55.0)


# ---------------------------------------------------------------------------
# R stat buff in the fight engine
# ---------------------------------------------------------------------------


class TestRStatBuffInFightEngine:
    def _fight(self, stats, abilities):
        return calculate_fight_damage(
            stats,
            abilities,
            [],
            FightConfig(
                target_health=2000,
                target_armor=100,
                target_magic_resistance=60,
                fight_duration_seconds=5.0,
                one_rotation=True,
            ),
        )

    def test_stat_buff_applied_to_champion_stats(self, singed_data, parse_at) -> None:
        """The fight engine applies R's stat buff to the real champion stats
        shape (level 18, R rank 3 by the default skill order)."""
        stats, abilities = parse_at(singed_data, 18)
        original_ap = stats["ability_power"]
        self._fight(stats, abilities)
        assert stats["ability_power"] > original_ap

    def test_r_zero_damage_in_breakdown(self, singed_data, parse_at) -> None:
        stats, abilities = parse_at(singed_data, 18)
        result = self._fight(stats, abilities)
        r_entry = result["breakdown"].get("R", {})
        assert r_entry.get("total_damage", 0.0) == 0.0


# ---------------------------------------------------------------------------
# Module coverage
# ---------------------------------------------------------------------------


class TestModuleCoverage:
    def test_all_five_slots_covered(self) -> None:
        assert MODULE_COVERAGE == {
            "P": "no_damage",
            "Q": "modeled",
            "W": "no_damage",
            "E": "modeled",
            "R": "modeled",
        }


# ---------------------------------------------------------------------------
# R's sourced-but-unmodeled riders (bonus armor/MR, HP/mana regen,
# Grievous Wounds) are documented, not silently dropped
# ---------------------------------------------------------------------------


class TestRSourcedButUnmodeledRiders:
    def test_bonus_armor_and_magic_resistance_are_documented_unmodeled(self) -> None:
        assumptions_text = " ".join(ASSUMPTIONS)
        assert "bonus armor" in assumptions_text
        assert "bonus magic resistance" in assumptions_text
        assert "no consumer" in assumptions_text

    def test_regen_and_grievous_wounds_riders_are_documented_unmodeled(self) -> None:
        assumptions_text = " ".join(ASSUMPTIONS)
        assert "HP/Mana Regenerated" in assumptions_text
        assert "Grievous Wounds" in assumptions_text
