"""Shaco's reviewed crowd control (``MODULE_CC``), and the slot that withholds.

A control-armed holder shield (Fimbulwinter's Everlasting) has to know
whether an ability event was a control event; an ability packet that never
says makes the whole timed fight fall back to coarse ordering.
"""

import pytest

from src.calculator.champions import get_champion_module_contract, shaco
from tests import cc_review, rider_probe, row_review


class TestReviewedCrowdControl:
    """Q/W/E reviewed; R's optional clone attacks keep Shaco coarse."""

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Shaco")
        assert shaco.MODULE_CC == {"Q": "none", "W": "immobilize", "E": "slow"}
        assert cc_review.control_words(cc_review.slot_text(data, "Q")) == []
        # Two immobilize kinds land together, so the reviewed kind is the
        # un-narrowed one rather than a choice between them.
        assert "fearing nearby enemies" in cc_review.slot_text(data, "W")
        assert "rooting them" in cc_review.slot_text(data, "W")
        assert "slows them for 3 seconds" in cc_review.slot_text(data, "E")

    def test_r_is_undeclared_because_its_entry_can_carry_a_second_part(self):
        """Hallucinate's boxes do control what the explosion damages, but with
        ``r_clone_attacks`` set the entry carries a second, separately timed
        part, so the explosion is not a hit the ledger can time in every
        configuration."""
        r_text = cc_review.slot_text(cc_review.kit("Shaco"), "R")
        assert "deploy three mini-boxes that activate instantly" in r_text
        # The explosion has no instant either: the cache times it to the
        # clone's death, and gives only the 18-second cap on its life.
        assert (
            "remaining within control range of him as a controllable clone "
            "for up to 18 seconds" in r_text
        )
        assert (
            "the clone will explode upon dying or expiring to deal magic "
            "damage to nearby enemies" in r_text
        )
        assert "R" not in shaco.MODULE_CC

    def test_the_unreviewable_slot_keeps_the_fight_coarse(self):
        assert cc_review.unreviewed_ability_slots("Shaco") == ["R"]
        coverage = cc_review.fimbulwinter_coverage("Shaco")
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]


class TestBackstab:
    """P: the from-behind auto modifier, on the attacks that land there."""

    def test_the_per_hit_damage_is_the_cached_row_plus_the_prose_ratio(self):
        """30 at level 18, + 20% of the 100 bonus AD row_review fixes."""
        values = [
            leveling["modifiers"][0]["values"]
            for effect in cc_review.kit("Shaco")["abilities"]["P"][0]["effects"]
            for leveling in effect.get("leveling") or []
        ]
        # One cached row, and it carries only the flat per-level term: the
        # wiki's "+ 20% bonus AD" has no modifier here, which is why the
        # ratio is a module constant.
        assert len(values) == 1 and values[0][17] == 30
        on_hit = row_review.entry("Shaco", "passive")["on_hit"]
        assert on_hit["damage_type"] == "physical"
        assert on_hit["damage_per_hit"] == pytest.approx(30 + 20)
        assert on_hit["max_procs"] == 1

    def test_one_backstab_reaches_the_fight_total_by_default(self):
        result = rider_probe.fight("Shaco")
        row = result["breakdown"][rider_probe.RIDER_ROW]
        assert row["name"] == "Backstab (on-hit)"
        assert row["count"] == 1
        assert row["total_damage"] == pytest.approx(15.0, abs=0.05)
        assert row["total_damage"] < result["total_damage"]

    def test_a_frontal_duel_prices_nothing(self):
        result = rider_probe.fight("Shaco", champion_options={"p_procs": 0})
        assert rider_probe.RIDER_ROW not in result["breakdown"]

    def test_every_slot_now_prices_something(self):
        assert get_champion_module_contract("Shaco").coverage == {
            slot: "modeled" for slot in "PQWER"
        }
