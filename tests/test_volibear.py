"""Reviewed crowd control for Volibear (MODULE_CC).

Thundering Smash stuns, Sky Splitter slows, and Stormbringer's slow rides
the impact a second after the cast that the packet authors.  Frenzied
Maul's bite is a two-part row that lands on its cached cast time and
controls nothing, and its heal follows bites rather than parts.
"""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import parse_champion_abilities, volibear
from tests import cc_review


class TestReviewedCrowdControl:
    """Volibear's reviewed crowd control, kit-wide.

    A control-armed holder shield (Fimbulwinter's Everlasting) has to know
    whether an ability event was a control event; an ability packet that
    never says makes the whole timed fight fall back to coarse ordering.
    ``MODULE_CC`` is where this kit answers, read from the cached text.
    """

    def test_declared_kinds_are_the_ones_the_cached_kit_gives(self):
        data = cc_review.kit("Volibear")
        assert volibear.MODULE_CC == {
            "Q": "stun",
            "W": "none",
            "E": "slow",
            "R": "slow",
        }
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

    def test_frenzied_maul_strikes_on_its_cached_cast_time(self):
        """Both halves of the bite land where the cache puts the bite.

        "Frenzied Maul deals bonus damage and heals if the target is still
        Wounded after the cast time" (cached W note), and that cast time is
        the cached 0.25 seconds.
        """
        data = cc_review.kit("Volibear")
        assert volibear.MODULE_CC["W"] == "none"
        assert cc_review.control_words(cc_review.slot_text(data, "W")) == []
        assert "after the cast time" in data["abilities"]["W"][0]["notes"]
        assert data["abilities"]["W"][0]["castTime"] == "0.25"
        parsed = parse_champion_abilities(
            data, 18, 100.0, {"Q": 5, "W": 5, "E": 5, "R": 3}
        )
        base, bonus = parsed["W"]["parts"]
        assert base.time_offset == bonus.time_offset == volibear._W_BITE_SECONDS
        assert base.cc_kind == bonus.cc_kind == "none"

    def test_one_bite_pays_one_heal_however_many_parts_price_it(self):
        """The defect this cadence was held back for.

        Two parts per bite used to be two heal events (and, across two
        casts, three): the rule counted W damage events and skipped the
        first.  It counts bites now (``HealAnchor.CAST``), so a ten-second
        fight with three W casts heals exactly twice — the first cast only
        applies the Wound.
        """
        payload = calculate_payload(
            {
                "champion": "Volibear",
                "level": 18,
                "items": ["Fimbulwinter"],
                "fight_mode": "timed",
                "fight_duration": 10,
                "include_auto_attacks": True,
            }
        )
        casts = [row for row in payload["cast_timeline"] if row["slot"] == "W"]
        events = [row for row in payload["damage_events"] if row["source"] == "W"]
        heals = [
            row
            for row in payload["self_healing_events"]
            if row["source"] == "Frenzied Maul"
        ]
        assert len(casts) == 3
        assert len(events) == 6  # two parts per bite
        assert len(heals) == len(casts) - 1
        assert [round(float(row["time"]), 3) for row in heals] == [
            pytest.approx(float(cast["time"]) + volibear._W_BITE_SECONDS, abs=5e-4)
            for cast in casts[1:]
        ]

    def test_the_kit_clears_the_control_armed_scan(self):
        assert cc_review.unreviewed_ability_slots("Volibear") == []
        coverage = cc_review.fimbulwinter_coverage("Volibear")
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
