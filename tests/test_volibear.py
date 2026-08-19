"""Reviewed crowd control for Volibear (MODULE_CC) — and the slot that
still withholds.

Thundering Smash stuns, Sky Splitter slows, and Stormbringer's slow now
rides the impact a second after the cast that the packet authors.
Frenzied Maul's bite is a two-part row whose only route to the ledger
would re-split the self-heal, so this kit stays coarse.
"""

from src.calculator.champions import parse_champion_abilities, volibear
from tests import cc_review


class TestReviewedCrowdControl:
    """Volibear's reviewed crowd control, and the slots that still withhold.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Volibear")
        assert volibear.MODULE_CC == {"Q": "stun", "E": "slow", "R": "slow"}
        assert volibear.parse_abilities.cc_kinds == volibear.MODULE_CC
        assert "stunning them for 1 second" in cc_review.slot_text(data, "Q")
        assert "slows them by 40% for 2 seconds" in cc_review.slot_text(data, "E")

    def test_stormbringer_slows_on_the_impact_it_is_authored_at(self):
        """R's slow and its damage are the same landing, one second in."""
        data = cc_review.kit("Volibear")
        r_text = cc_review.slot_text(data, "R")
        assert "impacts after 1 second, slowing nearby enemies by 50%" in r_text
        assert "enemies within the epicenter are also dealt physical damage" in r_text
        parsed = parse_champion_abilities(
            data, 18, 100.0, {"Q": 5, "W": 5, "E": 5, "R": 3}
        )
        (part,) = parsed["R"]["parts"]
        assert part.time_offset == 1.0
        assert part.cc_kind == "slow"

    def test_frenzied_maul_withholds_on_its_two_part_bite(self):
        """W is control-free, but its row cannot certify a single hit.

        The bite's own cast instant is sourced ("Frenzied Maul deals bonus
        damage and heals if the target is still Wounded after the cast
        time"), but authoring it on both parts is not a timing change
        alone: the self-heal rule counts W *damage events* and skips the
        first, so two parts per bite turn one heal into three.  The
        module leaves the row untimed until that rule counts bites.
        """
        data = cc_review.kit("Volibear")
        assert "W" not in volibear.MODULE_CC
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        parsed = parse_champion_abilities(
            data, 18, 100.0, {"Q": 5, "W": 5, "E": 5, "R": 3}
        )
        base, bonus = parsed["W"]["parts"]
        assert base.time_offset is None and bonus.time_offset is None
        assert parsed["W"].get("event_order_certified") is None

    def test_the_unreviewable_slots_keep_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Volibear") == ["W"]
        coverage = cc_review.fimbulwinter_coverage("Volibear")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
