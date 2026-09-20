"""Malphite's reviewed crowd control (``MODULE_CC``).

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

from functools import partial

import pytest

from src.calculator.champions import malphite
from src.calculator.champions.slot_extract import extract_named
from src.calculator.control_spec import IMMOBILIZING_CC_KINDS, NON_IMMOBILIZING_CC_KINDS
from tests import cc_review
from tests import champion_closure as closure


class TestReviewedCrowdControl:
    """Ground Slam's cripple is the kind the vocabulary added for it."""

    def test_module_cc_is_the_declaration_the_parser_wired(self):
        assert malphite.MODULE_CC == {
            "Q": "slow",
            "W": "none",
            "E": "cripple",
            "R": "knockup",
            "P": "none",
        }
        assert malphite.parse_abilities.cc_kinds == malphite.MODULE_CC

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Malphite")
        assert "slows them for 3 seconds upon impact" in cc_review.slot_text(data, "Q")
        assert "crippling them for 3 seconds" in cc_review.slot_text(data, "E")
        assert "knocks them up for 1.5 seconds" in cc_review.slot_text(data, "R")

    def test_a_cripple_is_neither_an_immobilize_nor_a_movement_slow(self):
        assert "cripple" in NON_IMMOBILIZING_CC_KINDS
        assert "cripple" not in IMMOBILIZING_CC_KINDS

    def test_thunderclaps_two_halves_are_one_landing_and_say_so(self):
        """W is one empowered swing priced as its on-hit bonus plus its
        cone, so the shared-instant certification carries its review."""
        data = cc_review.kit("Malphite")
        text = cc_review.slot_text(data, "W")
        assert (
            "empowers his next basic attack within 6 seconds to have an "
            "uncancellable windup, gain 50 bonus range, and deal additional "
            "physical damage on-hit" in text
        )
        assert (
            "basic attacks on-hit for the next 5 seconds are empowered to "
            "trigger a cone in the direction of the target that deals "
            "physical damage to enemies hit" in text
        )
        assert cc_review.control_words(text) == []

    def test_the_whole_kit_is_reviewed_and_the_fight_certifies(self):
        assert cc_review.unreviewed_ability_slots("Malphite") == []
        coverage = cc_review.fimbulwinter_coverage("Malphite")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


# Level 18, ranks Q5/W5/E5/R3, no items, six seconds of autos at full uptime
# into a 3000-HP Aatrox whose own resistances mitigate.
_closure_fight = partial(
    closure.combat,
    mode="time_based",
    duration=6.0,
    include_autos=True,
    auto_uptime=1.0,
    target_health=3000.0,
    enemy=closure.AATROX,
)
_closure_parse = partial(closure.parse, target=closure.TARGET_3000)


# ---------------------------------------------------------------------------
# Malphite — W empowered-attack parts + tripled bonus armor
# ---------------------------------------------------------------------------


def test_malphite_w_prices_empowered_attack_both_parts():
    data, stats, abilities = _closure_parse("Malphite")
    w = data["abilities"]["W"][0]
    armor_grant = extract_named(w, "Increased Bonus Armor", 5, stats, {})
    assert armor_grant == pytest.approx(0.9 * stats["armor"])  # tripled 30%
    buffed = dict(stats)
    buffed["armor"] = stats["armor"] + armor_grant
    on_hit = extract_named(w, "Additional Physical Damage", 5, buffed, {})
    cone = extract_named(w, "Physical Damage", 5, buffed, {})
    part_on_hit, part_cone = abilities["W"]["parts"]
    assert part_on_hit.amount == pytest.approx(on_hit)
    assert part_cone.amount == pytest.approx(cone)
    assert abilities["W"]["total_raw"] == pytest.approx(on_hit + cone)


def test_malphite_e_scales_off_tripled_armor():
    data, stats, abilities = _closure_parse("Malphite")
    w = data["abilities"]["W"][0]
    e = data["abilities"]["E"][0]
    armor_grant = extract_named(w, "Increased Bonus Armor", 5, stats, {})
    buffed = dict(stats)
    buffed["armor"] = stats["armor"] + armor_grant
    expected_e = extract_named(e, "Magic Damage", 5, buffed, {})
    assert abilities["E"]["total_raw"] == pytest.approx(expected_e)
    # The grant is damage-relevant: without it E would price the lower armor.
    assert abilities["E"]["total_raw"] > extract_named(e, "Magic Damage", 5, stats, {})


def test_malphite_api_w_and_e_match_sourced_mitigation():
    combat = _closure_fight("Malphite")
    enemy_stats = closure.enemy_stats(combat)
    _, _stats, abilities = _closure_parse("Malphite")
    w_raw = abilities["W"]["total_raw"]
    e_raw = abilities["E"]["total_raw"]
    w_events = closure.main_damage_events(combat, "W")
    e_events = closure.main_damage_events(combat, "E")
    assert w_events
    assert e_events
    # Thunderclap lands its empowered-attack bonus and its cone in one
    # instant but at two magnitudes, so the row's claim is that its events
    # ACCOUNT for the raw total, not that they are equal shares of it.
    assert sum(e["raw_damage"] for e in w_events) == pytest.approx(w_raw, rel=1e-3)
    assert e_events[0]["raw_damage"] == pytest.approx(e_raw / len(e_events), rel=1e-3)
    assert sum(e["damage"] for e in w_events) == pytest.approx(
        w_raw * 100.0 / (100.0 + enemy_stats["armor"]), rel=1e-3
    )
    assert sum(e["damage"] for e in e_events) == pytest.approx(
        e_raw * 100.0 / (100.0 + enemy_stats["magic_resistance"]), rel=1e-3
    )
