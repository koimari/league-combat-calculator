"""Singed — ability parsing, the R steroid, and the reviewed crowd control.

Reference arithmetic (sourced ``data/champions.json`` Singed R "Bonus
Stats" leveling, corroborated by the game binary's ``StatAmount``
DataValue ``[-5, 25, 55, 85, 115, 145, 175]``, ranks 1-3 = 25/55/85):

- R (Insanity Potion) rank 1/2/3 grants +25 / +55 / +85 to ability power,
  armour, magic resistance and movement speed at once — one sourced
  number feeding every ``stat_buff`` key.  Zero direct damage, 25s
  duration, 100s flat cooldown at all three ranks.
- R is BUFF phase (Syndra P / Vayne R precedent): it mutates
  ``ctx.stats["ability_power"]`` in-parse, so Poison Trail (Q, flat
  0.10625 AP ratio) and Fling (E, flat 0.55 AP ratio) read the buffed AP
  in the same call.  At 0 base AP, R rank 2 (+55 AP) adds 0.10625 * 55 to
  Q's ``total_raw`` and 0.55 * 55 to E's.
- P (Noxious Slipstream) and W (Mega Adhesive) carry no enemy-damage
  formula in the pinned Wiki packet spec or the game binary's DataValues
  (MSPercent/MSDuration/PerTargetCD/TriggerArea for P;
  SlowPercent/WDuration/WRadius/DelayExecute/Radius for W) — both are
  sourced zero-damage rows, not silently absent slots.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that
never says makes the whole timed fight fall back to coarse ordering, so
``MODULE_CC`` is asserted here too.
"""

import json
from pathlib import Path

import pytest

from src.calculator.champions import parse_champion_abilities as parse_abilities
from src.calculator.champions import singed
from src.calculator.champions.singed import ASSUMPTIONS, MODULE_COVERAGE
from src.calculator.damage import FightConfig, calculate_fight_damage
from src.calculator.data_fetcher import get_champion
from src.calculator.pipeline import FightParams, run_fight
from src.calculator.stats import calculate_total_stats, resolve_move_speed
from tests import cc_review

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STATS_0AP = {
    "ability_power": 0.0,
    "armor": 0.0,
    "magic_resistance": 0.0,
    "move_speed": 350.0,
}

# ``move_speed_flat`` is the fold's INPUT, not the displayed ``move_speed``
# it produces — see TestRMovementRidesTheSharedFold.
_R_STAT_KEYS = {"ability_power", "armor", "magic_resistance", "move_speed_flat"}


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
    """One sourced Bonus Stats row feeds every stat the cast grants that has
    a consumer here: ability power, the two self-resist keys every other
    steroid module publishes, and move speed (through the shared fold,
    whose output is ``item_state_receipts``' ``total_move_speed`` input).
    The row's health/mana regeneration has none, so it carries no key."""

    def test_r_deals_no_damage(self, singed_data) -> None:
        abilities = _parse(singed_data, ranks={"Q": 5, "W": 5, "E": 5, "R": 1})
        assert abilities["R"]["total_raw"] == 0.0

    def test_r_stat_buff_covers_every_consumed_stat(self, singed_data) -> None:
        abilities = _parse(singed_data, ranks={"Q": 5, "W": 5, "E": 5, "R": 1})
        assert set(abilities["R"]["stat_buff"]) == _R_STAT_KEYS

    @pytest.mark.parametrize("rank, value", [(1, 25.0), (2, 55.0), (3, 85.0)])
    def test_r_rank_values_are_the_sourced_row(self, singed_data, rank, value) -> None:
        abilities = _parse(singed_data, ranks={"Q": 5, "W": 5, "E": 5, "R": rank})
        stat_buff = abilities["R"]["stat_buff"]
        for stat_key in _R_STAT_KEYS:
            assert stat_buff[stat_key] == pytest.approx(value)

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
# R's movement grant on the shared fold
# ---------------------------------------------------------------------------


class TestRMovementRidesTheSharedFold:
    """The grant is the fold's input, so the soft caps still apply.

    Keying the displayed ``move_speed`` wrote past
    ``stats.resolve_move_speed`` and published an uncapped 430.0 where
    the fold gives 427.0 — and ``item_state_receipts`` reads that number
    as its ``total_move_speed`` input, so the miss reached Swiftmarch's
    adaptive force.
    """

    RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}

    def test_the_grant_keys_the_folds_input_not_its_output(self, singed_data) -> None:
        stat_buff = _parse(singed_data, ranks=dict(self.RANKS))["R"]["stat_buff"]
        assert "move_speed" not in stat_buff
        assert stat_buff["move_speed_flat"] == pytest.approx(85.0)

    def test_the_fight_publishes_the_soft_capped_number(self) -> None:
        data = get_champion("Singed")
        build = calculate_total_stats(data, 18, [])
        result = run_fight(
            data,
            18,
            [],
            FightParams(
                target_health=2000.0,
                target_armor=100.0,
                target_magic_resistance=50.0,
                fight_duration_seconds=10.0,
                ability_ranks=dict(self.RANKS),
                deterministic=True,
            ),
        )
        raw = build["move_speed_flat"] + 85.0
        buffed = result["champion_stats"]["move_speed"]

        assert build["move_speed_flat"] == pytest.approx(345.0)
        assert raw == pytest.approx(430.0)
        # Above the 415 breakpoint: raw * 0.8 + 83.
        assert buffed == pytest.approx(427.0)
        assert buffed == pytest.approx(
            resolve_move_speed(raw, build["move_speed_percent"])
        )


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
# R's sourced-but-unmodeled riders are documented, not silently dropped
# ---------------------------------------------------------------------------


class TestRSourcedButUnmodeledRiders:
    def test_regen_and_grievous_wounds_riders_are_documented_unmodeled(self) -> None:
        assumptions_text = " ".join(ASSUMPTIONS)
        assert "health/mana regeneration" in assumptions_text
        assert "Grievous Wounds" in assumptions_text

    def test_conditional_e_root_is_documented_unmodeled(self) -> None:
        """Fling's root is gated on landing in W's field; the module says so
        rather than arming an unconditional root."""
        assumptions_text = " ".join(ASSUMPTIONS)
        assert "Mega Adhesive's area of effect" in assumptions_text


# ---------------------------------------------------------------------------
# P: the percent-movement grant the cache cannot source
# ---------------------------------------------------------------------------


class TestNoxiousSlipstreamHasNoSourcedMagnitude:
    """Why P alone stays off the shared ``resolve_move_speed`` fold.

    Every other percent-movement grant in this repo reads a leveling
    row. P has none, and the one number that exists is ambiguous by a
    factor of 25 — so the slot publishes nothing rather than a guess.
    """

    def test_every_cached_p_effect_has_an_empty_leveling_array(self) -> None:
        wiki = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
        for entry in wiki["Singed"]["abilities"]["P"]:
            for effect in entry["effects"]:
                assert effect["leveling"] == []

    def test_the_cached_prose_multiplies_the_stack_cap_into_the_magnitude(
        self,
    ) -> None:
        """625 == 25 x 25: the wiki-template substitution, pinned."""
        wiki = json.loads(Path("data/champions.json").read_text(encoding="utf-8"))
        prose = " ".join(
            effect["description"]
            for entry in wiki["Singed"]["abilities"]["P"]
            for effect in entry["effects"]
        )
        assert "stacking up to 25 times" in prose
        assert "25% bonus movement speed, up to a maximum of 625%" in prose

    def test_no_move_speed_stat_buff_is_published(self, singed_data) -> None:
        abilities = _parse(singed_data, ranks={"Q": 5, "W": 5, "E": 5, "R": 3})
        assert "stat_buff" not in abilities["passive"]

    def test_the_gap_is_named_in_the_assumptions(self) -> None:
        assumption = next(text for text in ASSUMPTIONS if "MSPercent" in text)
        assert "empty leveling array" in assumption
        assert "ambiguous between per-stack and total" in assumption


# ---------------------------------------------------------------------------
# Reviewed crowd control (``MODULE_CC``)
# ---------------------------------------------------------------------------


class TestReviewedCrowdControl:
    """Singed's reviewed crowd control, and what declaring it clears."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Singed")
        assert singed.MODULE_CC == {"Q": "none", "E": "airborne"}
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        # Fling throws the target; the cached text names the throw only as
        # a displacement, so the reviewed kind is the un-narrowed airborne
        # one.  Its root is conditional on landing in W's field.
        assert "flings the target enemy 550 units over himself" in (
            cc_review.slot_text(data, "E")
        )
        assert "after the displacement" in cc_review.slot_text(data, "E")

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Singed") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Singed")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
