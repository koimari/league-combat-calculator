"""Mel's reviewed crowd control (``MODULE_CC`` plus Solar Snare's two parts).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

import pytest

from src.calculator.champions import (
    get_champion_module_contract,
    mel,
    parse_champion_abilities,
)
from src.calculator.champions.slotlib import find_named_leveling, sum_modifiers
from src.calculator.calculate import calculate_payload
from src.calculator.stats import calculate_total_stats
from tests import cc_review, coverage_truth, row_review


class TestReviewedCrowdControl:
    """Solar Snare's orb roots and its field slows, so E answers per part."""

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        assert mel.MODULE_CC == {"P": "none", "Q": "none", "R": "none"}
        assert mel.parse_abilities.cc_kinds == mel.MODULE_CC

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Mel")
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        assert cc_review.control_words(cc_review.slot_text(data, "R")) == []

    def test_solar_snares_orb_and_field_carry_their_own_kinds(self):
        text = cc_review.slot_text(cc_review.kit("Mel"), "E")
        assert "rooted for 1.5 seconds" in text
        assert "slowed by 30% every 0.125 seconds" in text
        data = cc_review.kit("Mel")
        parsed = parse_champion_abilities(
            data, 18, 100.0, champion_stats=calculate_total_stats(data, 18, [])
        )
        assert [part.cc_kind for part in parsed["E"]["parts"]] == ["root", "slow"]

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Mel") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Mel")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestSearingBrilliance:
    """P's volley: priced, and the half of the passive that is not.

    The cache carries the projectile row twice — per projectile and at
    nine stacks — and drops both AP ratios the prose states, so the
    module pins 4% AP and cross-checks the two rows against each other.
    """

    def test_the_default_request_prices_no_volley(self):
        entry = row_review.entry("Mel", "passive")
        assert entry["total_raw"] == 0.0
        assert entry["parts"] == ()

    def test_each_stack_is_one_cached_projectile_plus_the_prose_ap_ratio(self):
        # Level 18: cached 30 per projectile, + 4% of row_review's 200 AP.
        for stacks, expected in ((1, 38.0), (9, 342.0)):
            entry = row_review.entry("Mel", "passive", p_searing_brilliance=stacks)
            assert entry["total_raw"] == pytest.approx(expected)
            (part,) = entry["parts"]
            assert (part.damage_type, part.count) == ("magic", stacks)
            assert entry["proc_count"] == 1
            assert entry["requires_auto_timeline_coupling"] is True

    def test_the_two_cached_rows_cross_check_the_nine_stack_cap(self):
        ability = cc_review.kit("Mel")["abilities"]["P"][0]
        per_projectile = sum_modifiers(
            find_named_leveling(ability, "Per-Level Scaling", 0), 18
        )
        at_max = sum_modifiers(find_named_leveling(ability, "Per-Level Scaling", 1), 18)
        assert (per_projectile, at_max) == (30.0, 270.0)
        assert at_max == pytest.approx(9 * per_projectile)

    def test_the_volley_reaches_the_fight(self):
        probe = {
            "champion": "Mel",
            "level": 18,
            "items": ["Rabadon's Deathcap"],
            "fight_mode": "timed",
            "include_auto_attacks": True,
        }
        off = calculate_payload({**probe, "champion_options": {}})
        on = calculate_payload(
            {**probe, "champion_options": {"p_searing_brilliance": 9}}
        )
        assert "passive" not in off["breakdown"]
        volley = on["breakdown"]["passive"]
        assert volley["name"] == "Searing Brilliance"
        assert volley["total_damage"] > 0.0
        assert on["ability_damage"] - off["ability_damage"] == pytest.approx(
            volley["total_damage"], rel=1e-2
        )
        assert on["auto_attack_damage"] == off["auto_attack_damage"]

        # The volley is fired BY a basic attack: with no auto stream there
        # is no swing to carry it, and the row prices nothing.
        no_autos = calculate_payload(
            {
                **probe,
                "include_auto_attacks": False,
                "champion_options": {"p_searing_brilliance": 9},
            }
        )
        assert "passive" not in no_autos["breakdown"]

    def test_overwhelm_stays_a_documented_kill_boundary(self):
        text = cc_review.slot_text(cc_review.kit("Mel"), "P")
        assert (
            "exceeds the target's current health and shields, the next stack "
            "applied against them will consume them all" in text
        )
        detail = row_review.entry("Mel", "passive", p_searing_brilliance=9)["detail"]
        assert "Overwhelm's stored damage is a kill boundary" in detail


class TestCoverageMap:
    """P prices its volley; W's reflection has no enemy projectile to read.

    W is the only slot left out: its damage is a percentage of an incoming
    enemy projectile's damage, and the calculator's target never attacks.
    """

    def test_the_map_is_the_rows_the_module_prices(self):
        assert get_champion_module_contract("Mel").coverage == {
            "P": "modeled",
            "Q": "modeled",
            "W": "out_of_scope",
            "E": "modeled",
            "R": "modeled",
        }
        assert coverage_truth.emitted("Mel", p_searing_brilliance=9) == {
            "P": coverage_truth.PRICED,
            "Q": coverage_truth.PRICED,
            "W": coverage_truth.ZERO,
            "E": coverage_truth.PRICED,
            "R": coverage_truth.PRICED,
        }

    def test_the_reflection_row_is_a_share_of_someone_elses_damage(self):
        rows = {
            level["attribute"]
            for ability in cc_review.kit("Mel")["abilities"]["W"]
            for effect in ability["effects"]
            for level in effect["leveling"] or []
        }
        assert "Replicated Projectile Magic Damage Modifier" in rows
        assert "retain a ratio of the damage that the original ones would deal" in (
            cc_review.slot_text(cc_review.kit("Mel"), "W")
        )
        assert row_review.entry("Mel", "W")["total_raw"] == 0.0
