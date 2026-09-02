"""Tests for the Aurelion Sol champion module.

Hand-derived values (wiki):
- Q Breath of Light: beam 45/60/75/90/105 (+55% AP) per second; one burst
  of 60/70/80/90/100 (+30% AP) plus (3.1% per 100 Stardust) of target max
  HP per full second of channel. Per-cast model: one full 3.25s channel
  (full beam + 3 bursts). Timed-fight model: continuous channel for the
  whole fight (beam x duration, one burst per full second).
- W Astral Flight: no damage row; while active, Q's NON-BURST flat damage
  is multiplied by 108/109/110/111/112% (wiki: "its non-burst flat damage
  is increased" — beam base only, never the burst base or AP portions).
- E Singularity: 50/75/100/125/150 (+60% AP) over the full 5s zone, plus
  an execute-threshold display line: 5% (+2.6% per 100 Stardust) max HP.
- R Falling Star 150/250/350 (+75% AP); empowered The Skies Descend
  187.5/312.5/437.5 (+93.75% AP), shockwave excluded (star-struck targets
  are immune to it).
"""

import copy

import pytest

from src.calculator.champions import (
    aurelion_sol,
    get_champion_module_contract,
    get_champion_options_meta,
)
from src.calculator.champions.aurelion_sol import _Q_CHANNEL_SECONDS
from src.calculator.champions.engine import CC_PER_PART
from src.calculator.champions.slotlib import extract_value
from src.calculator.pipeline import FightParams, run_fight
from tests import cc_review, coverage_truth, row_review
from tests.ability_math import parts_raw_total

MAX_RANKS = {"Q": 5, "W": 5, "E": 5, "R": 3}
TARGET_1000 = {"target_max_health": 1000.0}


# ---------------------------------------------------------------------------
# Q — Breath of Light (per-cast: one full 3.25s channel)
# ---------------------------------------------------------------------------


class TestQBreathOfLight:
    """Q per-cast model: full 3.25s beam plus 3 bursts on the primary target."""

    def test_q_damage_type(self, aurelion_sol_data, parse_at) -> None:
        _, abilities = parse_at(aurelion_sol_data, 9)
        assert abilities["Q"]["damage_type"] == "magic"

    def test_q_per_cast_cooldown(self, aurelion_sol_data, parse_at) -> None:
        """Per-cast entries carry the real Q cooldown (3s at every rank)."""
        _, abilities = parse_at(aurelion_sol_data, 9)
        assert abilities["Q"]["cooldown"] == pytest.approx(3.0)

    def test_q_rank5_no_ap(self, aurelion_sol_data, parse_at) -> None:
        """Rank 5, 0 AP: beam 105 x 3.25 + 3 x 100 = 341.25 + 300 = 641.25."""
        _, abilities = parse_at(aurelion_sol_data, 18, ap=0.0, ability_ranks=MAX_RANKS)
        assert abilities["Q"]["total_raw"] == pytest.approx(641.25)

    def test_q_rank5_100ap(self, aurelion_sol_data, parse_at) -> None:
        """100 AP adds 55% x 3.25 = 178.75 (beam) + 3 x 30 = 90 (bursts)."""
        _, abilities = parse_at(
            aurelion_sol_data, 18, ap=100.0, ability_ranks=MAX_RANKS
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(910.0)

    def test_q_w_active_beam_only_modifier(self, aurelion_sol_data, parse_at) -> None:
        """W rank 5 multiplies the beam base by 112%; bursts unchanged.

        341.25 x 1.12 + 300 = 682.20 (wiki: 'non-burst flat damage').
        """
        _, abilities = parse_at(
            aurelion_sol_data,
            18,
            ap=0.0,
            ability_ranks=MAX_RANKS,
            champion_options={"w_active": True},
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(682.20)

    def test_q_w_active_ap_portion_unmodified(
        self, aurelion_sol_data, parse_at
    ) -> None:
        """AP portions are never W-modified: 682.20 + 178.75 + 90 = 950.95."""
        _, abilities = parse_at(
            aurelion_sol_data,
            18,
            ap=100.0,
            ability_ranks=MAX_RANKS,
            champion_options={"w_active": True},
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(950.95)

    def test_q_w_active_without_w_learned(self, aurelion_sol_data, parse_at) -> None:
        """w_active with W at rank 0 applies no modifier."""
        _, abilities = parse_at(
            aurelion_sol_data,
            18,
            ap=0.0,
            ability_ranks={"Q": 5, "W": 0, "E": 5, "R": 3},
            champion_options={"w_active": True},
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(641.25)

    def test_q_stardust_bursts(self, aurelion_sol_data, parse_at) -> None:
        """100 Stardust vs 1000 max HP: +3.1% x 1000 = +31 per burst.

        641.25 + 3 x 31 = 734.25.
        """
        _, abilities = parse_at(
            aurelion_sol_data,
            18,
            ap=0.0,
            ability_ranks=MAX_RANKS,
            champion_options={"stardust_stacks": 100},
            target_stats=TARGET_1000,
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(734.25)

    def test_q_stardust_needs_target(self, aurelion_sol_data, parse_at) -> None:
        """Without target stats the %maxHP component contributes nothing."""
        _, abilities = parse_at(
            aurelion_sol_data,
            18,
            ap=0.0,
            ability_ranks=MAX_RANKS,
            champion_options={"stardust_stacks": 100},
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(641.25)

    def test_q_w_modifier_rename_raises(self, aurelion_sol_data, parse_at) -> None:
        """A renamed W modifier attribute must raise, never zero the beam."""
        data = copy.deepcopy(aurelion_sol_data)
        leveling = data["abilities"]["W"][0]["effects"][0]["leveling"][0]
        leveling["attribute"] = "Renamed By Patch"
        with pytest.raises(ValueError, match="Breath of Light Flat Damage"):
            parse_at(
                data,
                18,
                ability_ranks=MAX_RANKS,
                champion_options={"w_active": True},
            )

    def test_q_channel_seconds_matches_json(self, aurelion_sol_data) -> None:
        """The 3.25s channel is derivable from the JSON at ranks 1-4:
        Total Maximum Magic Damage / Magic Damage per Second (rank 5 has
        no maximum — its value is absent, which is why the module pins
        the constant instead of reading the truncated attribute)."""
        q_ability = aurelion_sol_data["abilities"]["Q"][0]
        for rank in range(1, 5):
            channel_total = extract_value(
                q_ability, "Total Maximum Magic Damage", rank, 0
            )
            per_second = extract_value(q_ability, "Magic Damage per Second", rank, 0)
            assert channel_total / per_second == pytest.approx(_Q_CHANNEL_SECONDS)

    def test_q_parts_match_total_raw(self, aurelion_sol_data, parse_at) -> None:
        _, abilities = parse_at(aurelion_sol_data, 9)
        assert (
            parts_raw_total(abilities["Q"]["parts"], "magic")
            == abilities["Q"]["total_raw"]
        )


class TestQContinuousFightMode:
    """Timed fights channel Q continuously for the whole fight duration."""

    def test_q_10s_fight(self, aurelion_sol_data, parse_at) -> None:
        """10s: beam 105 x 10 = 1050 + 10 bursts x 100 = 2050."""
        _, abilities = parse_at(
            aurelion_sol_data,
            18,
            ap=0.0,
            ability_ranks=MAX_RANKS,
            champion_options={"fight_duration_seconds": 10.0},
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(2050.0)

    def test_q_continuous_never_recasts(self, aurelion_sol_data, parse_at) -> None:
        """The whole fight is one channel — cooldown pinned so it casts once."""
        _, abilities = parse_at(
            aurelion_sol_data,
            18,
            ability_ranks=MAX_RANKS,
            champion_options={"fight_duration_seconds": 10.0},
        )
        assert abilities["Q"]["cooldown"] >= 999.0

    def test_q_fractional_duration(self, aurelion_sol_data, parse_at) -> None:
        """8.5s: beam 105 x 8.5 = 892.5; bursts only per FULL second (8)."""
        _, abilities = parse_at(
            aurelion_sol_data,
            18,
            ap=0.0,
            ability_ranks=MAX_RANKS,
            champion_options={"fight_duration_seconds": 8.5},
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(892.5 + 800.0)

    def test_q_10s_fight_100ap(self, aurelion_sol_data, parse_at) -> None:
        """(105 + 55) x 10 + (100 + 30) x 10 = 2900."""
        _, abilities = parse_at(
            aurelion_sol_data,
            18,
            ap=100.0,
            ability_ranks=MAX_RANKS,
            champion_options={"fight_duration_seconds": 10.0},
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(2900.0)

    def test_q_10s_fight_w_active(self, aurelion_sol_data, parse_at) -> None:
        """Beam base x 1.12 for 10s: 117.6 x 10 + 1000 = 2176."""
        _, abilities = parse_at(
            aurelion_sol_data,
            18,
            ap=0.0,
            ability_ranks=MAX_RANKS,
            champion_options={"fight_duration_seconds": 10.0, "w_active": True},
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(2176.0)

    def test_q_10s_fight_stardust(self, aurelion_sol_data, parse_at) -> None:
        """10 bursts each gain 3.1% x 1000 = 31: 2050 + 310 = 2360."""
        _, abilities = parse_at(
            aurelion_sol_data,
            18,
            ap=0.0,
            ability_ranks=MAX_RANKS,
            champion_options={
                "fight_duration_seconds": 10.0,
                "stardust_stacks": 100,
            },
            target_stats=TARGET_1000,
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(2360.0)


# ---------------------------------------------------------------------------
# W — Astral Flight (no damage row)
# ---------------------------------------------------------------------------


class TestWAstralFlight:
    """W is a dash/utility; its only calc effect is Q's beam modifier."""

    def test_w_is_explicit_zero_damage_row(self, aurelion_sol_data, parse_at) -> None:
        """W carries no damage attribute of its own — documented zero-damage
        row (module_helpers.no_damage), not a silent absence."""
        _, abilities = parse_at(aurelion_sol_data, 18)
        entry = abilities["W"]
        assert entry["name"] == "Astral Flight"
        assert entry["total_raw"] == 0.0
        assert entry["parts"] == ()
        assert "damage-less dash" in entry["detail"].lower()

    def test_w_absent_when_unlearned(self, aurelion_sol_data, parse_at) -> None:
        """The state row is rank-gated like every other slot."""
        _, abilities = parse_at(
            aurelion_sol_data,
            18,
            ability_ranks={"Q": 5, "W": 0, "E": 5, "R": 3},
        )
        assert "W" not in abilities


# ---------------------------------------------------------------------------
# E — Singularity
# ---------------------------------------------------------------------------


class TestESingularity:
    """E uses the full-5s-zone total and carries the execute display line."""

    def test_e_damage_type(self, aurelion_sol_data, parse_at) -> None:
        _, abilities = parse_at(aurelion_sol_data, 9)
        assert abilities["E"]["damage_type"] == "magic"

    def test_e_cooldown(self, aurelion_sol_data, parse_at) -> None:
        _, abilities = parse_at(aurelion_sol_data, 9)
        assert abilities["E"]["cooldown"] == pytest.approx(12.0)

    def test_e_rank5_no_ap(self, aurelion_sol_data, parse_at) -> None:
        """Rank 5, 0 AP: 150 total over the full zone."""
        _, abilities = parse_at(aurelion_sol_data, 18, ap=0.0, ability_ranks=MAX_RANKS)
        assert abilities["E"]["total_raw"] == pytest.approx(150.0)

    def test_e_rank5_100ap(self, aurelion_sol_data, parse_at) -> None:
        """Rank 5, 100 AP: 150 + 60 = 210."""
        _, abilities = parse_at(
            aurelion_sol_data, 18, ap=100.0, ability_ranks=MAX_RANKS
        )
        assert abilities["E"]["total_raw"] == pytest.approx(210.0)

    def test_e_execute_display_no_stardust(self, aurelion_sol_data, parse_at) -> None:
        """0 Stardust vs 1000 max HP: executes below 5% (50 HP)."""
        _, abilities = parse_at(
            aurelion_sol_data,
            18,
            ability_ranks=MAX_RANKS,
            target_stats=TARGET_1000,
        )
        assert abilities["E"]["detail"] == "Executes below 5.0% max HP (50 HP)"

    def test_e_execute_display_100_stardust(self, aurelion_sol_data, parse_at) -> None:
        """100 Stardust: 5 + 2.6 = 7.6% (76 HP of 1000)."""
        _, abilities = parse_at(
            aurelion_sol_data,
            18,
            ability_ranks=MAX_RANKS,
            champion_options={"stardust_stacks": 100},
            target_stats=TARGET_1000,
        )
        assert abilities["E"]["detail"] == "Executes below 7.6% max HP (76 HP)"

    def test_e_execute_display_without_target(
        self, aurelion_sol_data, parse_at
    ) -> None:
        """No target max HP in context: percent-only threshold."""
        _, abilities = parse_at(aurelion_sol_data, 18, ability_ranks=MAX_RANKS)
        assert abilities["E"]["detail"] == "Executes below 5.0% max HP"

    def test_e_parts_match_total_raw(self, aurelion_sol_data, parse_at) -> None:
        _, abilities = parse_at(aurelion_sol_data, 9)
        assert (
            parts_raw_total(abilities["E"]["parts"], "magic")
            == abilities["E"]["total_raw"]
        )


# ---------------------------------------------------------------------------
# R — Falling Star / The Skies Descend
# ---------------------------------------------------------------------------


class TestRFallingStar:
    """R form is controlled by the r_empowered option."""

    def test_r_damage_type(self, aurelion_sol_data, parse_at) -> None:
        _, abilities = parse_at(aurelion_sol_data, 18)
        assert abilities["R"]["damage_type"] == "magic"

    def test_r_base_rank3_no_ap(self, aurelion_sol_data, parse_at) -> None:
        """Falling Star rank 3, 0 AP: 350."""
        _, abilities = parse_at(aurelion_sol_data, 18, ap=0.0, ability_ranks=MAX_RANKS)
        assert abilities["R"]["total_raw"] == pytest.approx(350.0)
        assert abilities["R"]["name"] == "Falling Star"

    def test_r_base_rank3_100ap(self, aurelion_sol_data, parse_at) -> None:
        """Falling Star rank 3, 100 AP: 350 + 75 = 425."""
        _, abilities = parse_at(
            aurelion_sol_data, 18, ap=100.0, ability_ranks=MAX_RANKS
        )
        assert abilities["R"]["total_raw"] == pytest.approx(425.0)

    def test_r_empowered_rank3_no_ap(self, aurelion_sol_data, parse_at) -> None:
        """The Skies Descend rank 3, 0 AP: 437.5 — star only, NO shockwave.

        (Star + shockwave would be 752.5; a star-struck target is immune
        to the shockwave, so only 437.5 is correct.)
        """
        _, abilities = parse_at(
            aurelion_sol_data,
            18,
            ap=0.0,
            ability_ranks=MAX_RANKS,
            champion_options={"r_empowered": True},
        )
        assert abilities["R"]["total_raw"] == pytest.approx(437.5)
        assert abilities["R"]["name"] == "The Skies Descend"

    def test_r_empowered_rank3_100ap(self, aurelion_sol_data, parse_at) -> None:
        """The Skies Descend rank 3, 100 AP: 437.5 + 93.75 = 531.25."""
        _, abilities = parse_at(
            aurelion_sol_data,
            18,
            ap=100.0,
            ability_ranks=MAX_RANKS,
            champion_options={"r_empowered": True},
        )
        assert abilities["R"]["total_raw"] == pytest.approx(531.25)

    def test_r_empowered_is_125_percent_of_base(
        self, aurelion_sol_data, parse_at
    ) -> None:
        _, base = parse_at(aurelion_sol_data, 18, ap=0.0, ability_ranks=MAX_RANKS)
        _, emp = parse_at(
            aurelion_sol_data,
            18,
            ap=0.0,
            ability_ranks=MAX_RANKS,
            champion_options={"r_empowered": True},
        )
        assert emp["R"]["total_raw"] == pytest.approx(base["R"]["total_raw"] * 1.25)

    def test_r_empowered_uses_base_cooldown(self, aurelion_sol_data, parse_at) -> None:
        """R[1] has no cooldown data — the empowered form reads R[0]'s."""
        _, abilities = parse_at(
            aurelion_sol_data,
            18,
            ability_ranks=MAX_RANKS,
            champion_options={"r_empowered": True},
        )
        assert abilities["R"]["cooldown"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Passive — Cosmic Creator (no damage row)
# ---------------------------------------------------------------------------


class TestPassiveCosmicCreator:
    """The passive is the Stardust stack mechanic — no damage of its own."""

    def test_passive_is_explicit_zero_damage_row(
        self, aurelion_sol_data, parse_at
    ) -> None:
        """P feeds Q/E's Stardust math but prices nothing itself —
        documented zero-damage row (module_helpers.no_damage), not a
        silent absence."""
        _, abilities = parse_at(aurelion_sol_data, 18)
        entry = abilities["passive"]
        assert entry["name"] == "Cosmic Creator"
        assert entry["total_raw"] == 0.0
        assert entry["parts"] == ()
        assert "stardust" in entry["detail"].lower()
        assert "P" not in abilities


# ---------------------------------------------------------------------------
# Options / assumptions metadata
# ---------------------------------------------------------------------------


class TestOptionsMeta:
    """The module declares its four options and its modeling assumptions."""

    def test_declared_options(self) -> None:
        meta = get_champion_options_meta("Aurelion Sol")
        keys = {opt["key"]: opt for opt in meta["options"]}
        # Breath of Light's secondary-beam target count is a declared row:
        # the formula reads it, so it belongs among the rows the frontend
        # renders rather than being a parse-only key with a call-site
        # default (D-24).
        assert set(keys) == {
            "stardust_stacks",
            "w_active",
            "r_empowered",
            "q_secondary_targets",
        }
        assert keys["stardust_stacks"]["default"] == 0
        assert keys["stardust_stacks"]["max"] == 999
        assert keys["w_active"]["default"] is False
        assert keys["r_empowered"]["default"] is False
        assert keys["q_secondary_targets"]["default"] == 0
        assert keys["q_secondary_targets"]["max"] == 5

    def test_assumptions_present(self) -> None:
        meta = get_champion_options_meta("Aurelion Sol")
        assert any("3.25" in text for text in meta["assumptions"])
        assert any("continuous" in text.lower() for text in meta["assumptions"])


# ---------------------------------------------------------------------------
# Fight-engine integration (pipeline injects the timed-fight duration)
# ---------------------------------------------------------------------------


def _fight_params(**overrides) -> FightParams:
    request = {
        "target_health": 1000.0,
        "target_armor": 0.0,
        "target_mr": 0.0,
    }
    request.update(overrides)
    return FightParams.from_request(request, deterministic=True)


class TestFightIntegration:
    """run_fight wires the fight duration into the Q channel model."""

    def test_timed_fight_channels_q_continuously(self, aurelion_sol_data) -> None:
        """10s timed fight, level 18, no items (0 AP), 0 MR target:
        Q = 105 x 10 + 100 x 10 = 2050 in ONE cast."""
        params = _fight_params(fight_mode="timed", fight_duration=10.0)
        result = run_fight(aurelion_sol_data, 18, [], params)
        q_row = result["breakdown"]["Q"]
        assert q_row["casts"] == 1
        assert q_row["total_damage"] == pytest.approx(2050.0)

    def test_one_rotation_fight_keeps_per_cast_q(self, aurelion_sol_data) -> None:
        """One-rotation mode keeps the single full-channel model (641.25)."""
        params = _fight_params(fight_mode="one_rotation")
        result = run_fight(aurelion_sol_data, 18, [], params)
        q_row = result["breakdown"]["Q"]
        assert q_row["casts"] == 1
        assert q_row["total_damage"] == pytest.approx(641.25)

    def test_e_execute_detail_reaches_breakdown(self, aurelion_sol_data) -> None:
        params = _fight_params(fight_mode="one_rotation")
        result = run_fight(aurelion_sol_data, 18, [], params)
        assert (
            result["breakdown"]["E"]["detail"] == "Executes below 5.0% max HP (50 HP)"
        )

    def test_one_rotation_strips_smuggled_duration_option(
        self, aurelion_sol_data
    ) -> None:
        """Reserved keys are pipeline-owned: a caller-supplied duration in
        one-rotation mode is stripped, keeping the per-cast Q model."""
        params = _fight_params(
            fight_mode="one_rotation",
            champion_options={"fight_duration_seconds": 60.0},
        )
        result = run_fight(aurelion_sol_data, 18, [], params)
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(641.25)

    def test_timed_fight_with_stardust_option(self, aurelion_sol_data) -> None:
        """Champion options ride along with the injected duration:
        Q = 2050 + 10 bursts x 31 = 2360."""
        params = _fight_params(
            fight_mode="timed",
            fight_duration=10.0,
            champion_options={"stardust_stacks": 100},
        )
        result = run_fight(aurelion_sol_data, 18, [], params)
        assert result["breakdown"]["Q"]["total_damage"] == pytest.approx(2360.0)


class TestReviewedCrowdControl:
    """Aurelion Sol's crowd-control review, per branch where it differs.

    R lands on a sourced delay in both branches and applies a different
    kind in each (Falling Star's 1.25 s stun, The Skies Descend's 2 s
    knock-up), so the answer is authored per part rather than per slot.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Aurelion Sol")
        assert aurelion_sol.MODULE_CC == {
            "Q": "none",
            "E": "none",
            "R": CC_PER_PART,
            "P": "none",
            "W": "none",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []

    def test_each_r_branch_authors_its_own_delay_and_kind(
        self, aurelion_sol_data, parse_at
    ):
        """R is absent from MODULE_CC because its two branches disagree."""
        assert aurelion_sol.MODULE_CC["R"] == CC_PER_PART
        entries = aurelion_sol_data["abilities"]["R"]
        assert "strikes the target location after 1.25 seconds" in (
            entries[0]["effects"][0]["description"]
        )
        assert "stunning them for 1 second" in entries[0]["effects"][0]["description"]
        assert "strikes the target location after 2 seconds" in (
            entries[1]["effects"][0]["description"]
        )
        assert "knocking up enemies hit for 1 second" in (
            entries[1]["effects"][0]["description"]
        )
        for empowered, delay, kind in ((False, 1.25, "stun"), (True, 2.0, "knockup")):
            _, abilities = parse_at(
                aurelion_sol_data,
                18,
                ap=100.0,
                ability_ranks=MAX_RANKS,
                champion_options={"r_empowered": empowered},
            )
            (part,) = abilities["R"]["parts"]
            assert (part.time_offset, part.cc_kind) == (delay, kind)

    def test_the_reviewed_kit_clears_the_control_armed_scan(self):
        assert cc_review.unreviewed_ability_slots("Aurelion Sol") == []
        coverage = cc_review.fimbulwinter_coverage("Aurelion Sol")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestCoverageMap:
    """P and W read ``no_damage``, and neither is a damage gap.

    The frontier page flagged W because the cached entry carries a
    leveling row with "Damage" in its name.  That row is
    "Breath of Light Flat Damage Modifier" — a 108-112% multiplier on Q,
    priced through ``w_active`` — and Cosmic Creator is the same story:
    every Stardust effect the cache states augments another slot.  Both
    slots emit an explicit zero-damage row, so the map says ``no_damage``
    rather than hiding them as ``out_of_scope``.
    """

    def test_the_map_is_the_rows_the_module_prices(self):
        assert get_champion_module_contract("Aurelion Sol").coverage == {
            "P": "no_damage",
            "Q": "modeled",
            "W": "no_damage",
            "E": "modeled",
            "R": "modeled",
        }
        assert coverage_truth.emitted("Aurelion Sol") == {
            "P": coverage_truth.ZERO,
            "Q": coverage_truth.PRICED,
            "W": coverage_truth.ZERO,
            "E": coverage_truth.PRICED,
            "R": coverage_truth.PRICED,
        }

    def test_the_flagged_w_row_is_a_q_multiplier_not_w_damage(self):
        rows = {
            level["attribute"]
            for ability in cc_review.kit("Aurelion Sol")["abilities"]["W"]
            for effect in ability["effects"]
            for level in effect["leveling"] or []
        }
        assert rows == {"Breath of Light Flat Damage Modifier"}
        off = row_review.priced("Aurelion Sol", "Q", w_active=False)
        on = row_review.priced("Aurelion Sol", "Q", w_active=True)
        assert on > off
