"""Tests for Anivia champion module."""

import pytest

from src.calculator.champions import anivia, get_champion_module_meta
from tests import cc_review
from tests.ability_math import parts_raw_total

# ---------------------------------------------------------------------------
# Q — Flash Frost
# ---------------------------------------------------------------------------


class TestQFlashFrost:
    """Q uses Total Magic Damage (pass-through + detonation combined)."""

    def test_q_damage_type(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(anivia_data, 9)
        assert abilities["Q"]["damage_type"] == "magic"

    def test_q_has_cooldown(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(anivia_data, 9)
        assert abilities["Q"]["cooldown"] > 0

    def test_q_rank5_no_ap(self, anivia_data, parse_at) -> None:
        """Rank 5 Q with 0 AP: 330 total magic damage."""
        _, abilities = parse_at(
            anivia_data,
            9,
            ability_ranks={"Q": 5, "E": 1, "R": 1},
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(330.0)

    def test_q_rank5_100ap(self, anivia_data, parse_at) -> None:
        """Rank 5 Q with 100 AP: 330 + 70 = 400."""
        _, abilities = parse_at(
            anivia_data,
            9,
            ap=100.0,
            ability_ranks={"Q": 5, "E": 1, "R": 1},
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(400.0)

    def test_q_parts_match_total_raw(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(anivia_data, 9)
        assert (
            parts_raw_total(abilities["Q"]["parts"], "magic")
            == abilities["Q"]["total_raw"]
        )


# ---------------------------------------------------------------------------
# W — Crystallize (skipped, no damage)
# ---------------------------------------------------------------------------


class TestWCrystallize:
    """W is a knockback wall with no sourced damage/heal/shield number —
    documented zero-damage row (module_helpers.no_damage), not a silent
    absence (roadmap session 3)."""

    def test_w_is_explicit_zero_damage_row(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(anivia_data, 9)
        entry = abilities["W"]
        assert entry["name"] == "Crystallize"
        assert entry["total_raw"] == 0.0
        assert entry["parts"] == ()
        assert "knockback wall" in entry["detail"].lower()

    def test_w_absent_when_unlearned(self, anivia_data, parse_at) -> None:
        """The state row is rank-gated like every other slot."""
        _, abilities = parse_at(
            anivia_data,
            9,
            ability_ranks={"Q": 5, "W": 0, "E": 1, "R": 1},
        )
        assert "W" not in abilities


# ---------------------------------------------------------------------------
# E — Frostbite
# ---------------------------------------------------------------------------


class TestEFrostbite:
    """E always uses Enhanced Damage (target assumed Chilled)."""

    def test_e_damage_type(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(anivia_data, 9)
        assert abilities["E"]["damage_type"] == "magic"

    def test_e_has_cooldown(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(anivia_data, 9)
        assert abilities["E"]["cooldown"] > 0

    def test_e_rank5_no_ap(self, anivia_data, parse_at) -> None:
        """Rank 5 E with 0 AP: 310 enhanced damage."""
        _, abilities = parse_at(
            anivia_data,
            9,
            ability_ranks={"Q": 1, "E": 5, "R": 1},
        )
        assert abilities["E"]["total_raw"] == pytest.approx(310.0)

    def test_e_rank5_100ap(self, anivia_data, parse_at) -> None:
        """Rank 5 E with 100 AP: 310 + 110 = 420."""
        _, abilities = parse_at(
            anivia_data,
            9,
            ap=100.0,
            ability_ranks={"Q": 1, "E": 5, "R": 1},
        )
        assert abilities["E"]["total_raw"] == pytest.approx(420.0)

    def test_e_parts_match_total_raw(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(anivia_data, 9)
        assert (
            parts_raw_total(abilities["E"]["parts"], "magic")
            == abilities["E"]["total_raw"]
        )


# ---------------------------------------------------------------------------
# R — Glacial Storm
# ---------------------------------------------------------------------------


class TestRGlacialStorm:
    """R is a two-phase DoT toggle with configurable duration."""

    def test_r_damage_type(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(anivia_data, 16)
        assert abilities["R"]["damage_type"] == "magic"

    def test_r_cooldown_is_very_high(self, anivia_data, parse_at) -> None:
        """R should only be cast once (cooldown set to 999)."""
        _, abilities = parse_at(anivia_data, 16)
        assert abilities["R"]["cooldown"] >= 999.0

    def test_r_rank3_100ap_5s(self, anivia_data, parse_at) -> None:
        """Rank 3 R, 100 AP, 5s duration:
        3 ticks × (30 + 6.25) + 7 ticks × (90 + 18.75) = 108.75 + 761.25 = 870.
        """
        _, abilities = parse_at(
            anivia_data,
            16,
            ap=100.0,
            ability_ranks={"Q": 5, "E": 5, "R": 3},
            champion_options={"r_duration": 5.0},
        )
        assert abilities["R"]["total_raw"] == pytest.approx(870.0)

    def test_r_rank3_no_ap_5s(self, anivia_data, parse_at) -> None:
        """Rank 3 R, 0 AP, 5s duration:
        3 × 30 + 7 × 90 = 90 + 630 = 720.
        """
        _, abilities = parse_at(
            anivia_data,
            16,
            ability_ranks={"Q": 5, "E": 5, "R": 3},
            champion_options={"r_duration": 5.0},
        )
        assert abilities["R"]["total_raw"] == pytest.approx(720.0)

    def test_r_minimum_duration_clamp(self, anivia_data, parse_at) -> None:
        """Duration below 1.5 should be clamped to 1.5 (3 initial ticks only)."""
        _, abilities = parse_at(
            anivia_data,
            16,
            ability_ranks={"Q": 5, "E": 5, "R": 3},
            champion_options={"r_duration": 0.5},
        )
        # 1.5s = 3 initial ticks only, 0 empowered
        # 3 × 30 = 90 (0 AP)
        assert abilities["R"]["total_raw"] == pytest.approx(90.0)

    def test_r_longer_duration(self, anivia_data, parse_at) -> None:
        """R at 10s duration: 3 initial + 17 empowered ticks, 0 AP, rank 3.
        3 × 30 + 17 × 90 = 90 + 1530 = 1620.
        """
        _, abilities = parse_at(
            anivia_data,
            16,
            ability_ranks={"Q": 5, "E": 5, "R": 3},
            champion_options={"r_duration": 10.0},
        )
        assert abilities["R"]["total_raw"] == pytest.approx(1620.0)

    def test_r_parts_match_total_raw(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(anivia_data, 16)
        assert (
            parts_raw_total(abilities["R"]["parts"], "magic")
            == abilities["R"]["total_raw"]
        )

    def test_r_default_duration_is_5s(self, anivia_data, parse_at) -> None:
        """Without champion_options, R uses the default 5s duration."""
        _, abilities_default = parse_at(
            anivia_data,
            16,
            ability_ranks={"Q": 5, "E": 5, "R": 3},
        )
        _, abilities_explicit = parse_at(
            anivia_data,
            16,
            ability_ranks={"Q": 5, "E": 5, "R": 3},
            champion_options={"r_duration": 5.0},
        )
        assert (
            abilities_default["R"]["total_raw"] == abilities_explicit["R"]["total_raw"]
        )


# ---------------------------------------------------------------------------
# Passive — Rebirth (skipped)
# ---------------------------------------------------------------------------


class TestPassiveRebirth:
    """Passive is the sourced revive state (StartingDefenses.revive_*) —
    it prices no cast damage of its own, so it stays absent from the
    parsed abilities dict even though MODULE_COVERAGE now reads
    "modeled" (roadmap session 3: tests/test_e8_support.py exercises the
    revive kernel end to end)."""

    def test_passive_not_in_results(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(anivia_data, 9)
        assert "P" not in abilities

    def test_passive_not_in_slot_map(self) -> None:
        """P has no cast-damage SLOTS entry; it is wired through
        starting_revive_defense instead."""
        assert "P" not in get_champion_module_meta("Anivia")["slots"]


# ---------------------------------------------------------------------------
# Full combo verification
# ---------------------------------------------------------------------------


class TestFullCombo:
    """Verify the expected damage from the spec at rank 5/5/3, 100 AP."""

    def test_full_combo_damage(self, anivia_data, parse_at) -> None:
        _, abilities = parse_at(
            anivia_data,
            18,
            ap=100.0,
            ability_ranks={"Q": 5, "E": 5, "R": 3},
            champion_options={"r_duration": 5.0},
        )
        assert abilities["Q"]["total_raw"] == pytest.approx(400.0)
        assert abilities["E"]["total_raw"] == pytest.approx(420.0)
        assert abilities["R"]["total_raw"] == pytest.approx(870.0)
        total = (
            abilities["Q"]["total_raw"]
            + abilities["E"]["total_raw"]
            + abilities["R"]["total_raw"]
        )
        assert total == pytest.approx(1690.0)


class TestReviewedCrowdControl:
    """Anivia's crowd-control review, and the two slots that withhold.

    R's blizzard ticks ride their cached 0.5-second beat and each slows,
    but stating the kind on them is the ``enhanced_consume`` ruling that
    has its own slice.  Q's row is the cached 'Total Magic Damage' of the
    slowing pass-through and the stunning shatter, with no cached time for
    the shatter.  Both name themselves per-part and neither answers.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Anivia")
        assert anivia.MODULE_CC == {
            "E": "none",
            "Q": "per_part",
            "W": "knockback",
            "R": "per_part",
        }
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []

    def test_glacial_storms_ticks_ride_their_cached_beat(
        self, anivia_data, parse_at
    ) -> None:
        text = cc_review.slot_text(cc_review.kit("Anivia"), "R")
        assert (
            "dealing magic damage every 0.5 seconds to enemies within and "
            "slowing them for 1 second" in text
        )
        assert "the blizzard increases in size over 1.5 seconds" in text
        _, abilities = parse_at(anivia_data, 18)
        growing, empowered = abilities["R"]["parts"]
        assert (growing.time_offset, growing.hit_interval) == (0.0, 0.5)
        assert growing.count == 3
        assert (empowered.time_offset, empowered.hit_interval) == (1.5, 0.5)

    def test_the_blizzards_slow_is_cached_and_still_unstated(
        self, anivia_data, parse_at
    ):
        """R's slow is cached and unambiguous, and no tick part carries it.

        Stating it makes Anivia the roster's first ``enhanced_consume``
        producer, R's chill feeding E's "Enhanced Damage", which is the
        cast-dependency ruling reserved to its own slice.
        """
        text = cc_review.slot_text(cc_review.kit("Anivia"), "R")
        assert "slowing them for 1 second" in text
        _, abilities = parse_at(anivia_data, 18)
        assert {part.cc_kind for part in abilities["R"]["parts"]} == {None}

    def test_flash_frosts_shatter_has_no_cached_time(self):
        """The other withholding slot, and the sentence that proves it.

        The shatter's stun IS sourced ("Stun Duration"), but Q's row is
        the pass-through and the shatter summed into one "Total Magic
        Damage" — two landings, so the row cannot certify a single hit,
        and a kind on it would never reach the event ledger.
        """
        text = cc_review.slot_text(cc_review.kit("Anivia"), "Q")
        assert (
            "flash frost can be recast while the ice is in flight after its "
            "cast time, and does so automatically at maximum range." in text
        )
        assert cc_review.unreviewed_ability_slots("Anivia") == ["Q", "R"]
        coverage = cc_review.fimbulwinter_coverage("Anivia")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]


def test_p_is_modeled_through_the_2114_rebirth_revive() -> None:
    """P emits no cast row; Rebirth's revive state is what prices the slot.

    At level 18 with no items Anivia's maximum health is 2114.0, and
    Rebirth "restores all of her health" — the receipt behind P's
    ``modeled`` label.
    """
    from src.calculator.champions import get_champion_module_contract
    from src.calculator.defensive_effects import resolve_starting_defenses
    from src.calculator.stats import calculate_total_stats

    contract = get_champion_module_contract("Anivia")
    assert "P" not in contract.slots
    assert contract.coverage["P"] == "modeled"
    assert contract.coverage_channels["P"] == ("starting_revive_defense",)

    data = cc_review.kit("Anivia")
    defenses = resolve_starting_defenses(
        "Anivia", 18, calculate_total_stats(data, 18, []), []
    )
    assert defenses.revive_source == "Rebirth"
    assert defenses.revive_health_amount == pytest.approx(2114.0)


# ---------------------------------------------------------------------------
# Module coverage metadata
# ---------------------------------------------------------------------------


class TestModuleCoverage:
    """Roadmap session 3: P and W close from out_of_scope (P -> modeled via
    the sourced revive kernel, W -> no_damage via the explicit zero-damage
    row)."""

    def test_module_coverage_reflects_p_w_dispositions(self) -> None:
        coverage = get_champion_module_meta("Anivia")["coverage"]
        assert coverage == {
            "P": "modeled",
            "Q": "modeled",
            "W": "no_damage",
            "E": "modeled",
            "R": "modeled",
        }
