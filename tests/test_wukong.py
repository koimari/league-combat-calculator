"""Reviewed crowd control for Wukong (MODULE_CC).

Cyclone knocks up; Crushing Blow's armor reduction is a shred, not
control.
"""

from src.calculator.champions import get_champion_module_contract, wukong
from tests import cc_review, coverage_truth, row_review


class TestReviewedCrowdControl:
    """Wukong's reviewed crowd control, and what declaring it clears.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text, and
    the probe below is the reason it exists.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Wukong")
        assert wukong.MODULE_CC == {"Q": "none", "E": "none", "R": "knockup"}
        assert wukong.parse_abilities.cc_kinds == wukong.MODULE_CC
        assert "knock them up once for 0.6 seconds" in cc_review.slot_text(data, "R")
        # Q's only debuff is "armor reduction for 3 seconds" — a resistance
        # shred, which is not a kind in the control vocabulary.
        q_text = cc_review.slot_text(data, "Q")
        assert cc_review.control_words(q_text) == []
        assert "inflict armor reduction for 3 seconds" in q_text
        assert cc_review.control_words(cc_review.slot_text(data, "E")) == []

    def test_the_unmodelled_slots_stay_absent(self):
        """W is the clone's pet timeline; P is the armor buff."""
        assert "W" not in wukong.MODULE_CC and "P" not in wukong.MODULE_CC
        assert get_champion_module_contract("Wukong").coverage["W"] == "out_of_scope"

    def test_every_ability_event_carries_the_review(self):
        assert cc_review.unreviewed_ability_slots("Wukong") == []

    def test_a_timed_fimbulwinter_fight_is_fully_certified(self):
        coverage = cc_review.fimbulwinter_coverage("Wukong")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]


class TestCoverageMap:
    """Stone Skin is a stat grant the survival side reads; the clone needs an axis.

    P emits a ``stat_buff`` of bonus armor with a zero damage part — a
    priced row under the campaign's vocabulary (a state row the engine
    consumes), so the derivation from ``SLOTS`` is the map and no map is
    declared.  W is the real gap and the missing axis is a pet timeline: the cached "Clone Outgoing
    Damage" row (40/45/50/55/60%) scales a *second attacker's* autos and
    copied casts, and the engine prices one attacker's timeline.
    """

    def test_the_map_is_the_rows_the_module_prices(self):
        assert get_champion_module_contract("Wukong").coverage == {
            "P": "modeled",
            "Q": "modeled",
            "W": "out_of_scope",
            "E": "modeled",
            "R": "modeled",
        }
        assert coverage_truth.emitted("Wukong") == {
            "P": coverage_truth.PRICED,
            "Q": coverage_truth.PRICED,
            "W": coverage_truth.ABSENT,
            "E": coverage_truth.PRICED,
            "R": coverage_truth.PRICED,
        }

    def test_the_passive_grants_armor_and_no_damage(self):
        entry = row_review.entry("Wukong", "passive", stone_skin_stacks=5)
        assert entry["total_raw"] == 0.0
        assert entry["stat_buff"]["armor"] > 0.0

    def test_the_clone_row_is_an_output_ratio_not_a_damage_row(self):
        rows = {
            level["attribute"]
            for ability in cc_review.kit("Wukong")["abilities"]["W"]
            for effect in ability["effects"]
            for level in effect["leveling"] or []
        }
        assert rows == {"Clone Outgoing Damage"}
        assert "can basic attack autonomously" in cc_review.slot_text(
            cc_review.kit("Wukong"), "W"
        )
