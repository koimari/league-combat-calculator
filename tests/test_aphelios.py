"""Tests for the Aphelios champion module."""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import aphelios, parse_champion_abilities
from src.calculator.stats import calculate_total_stats
from tests import cc_review

WEAPONS = ("calibrum", "severum", "gravitum", "infernum", "crescendum")
REVIEWED_WEAPONS = ("calibrum", "gravitum", "infernum", "crescendum")


def _parse(weapon, level=18):
    data = cc_review.kit("Aphelios")
    return parse_champion_abilities(
        data,
        level,
        0.0,
        champion_stats=calculate_total_stats(data, level, []),
        champion_options={"aphelios_main_weapon": weapon},
    )


class TestReviewedCrowdControl:
    """Aphelios's crowd-control review is per weapon, not per slot.

    Q is whichever Moonstone weapon is equipped — Gravitum's Binding
    Eclipse roots where the others apply nothing — so the answer follows
    the weapon option, and rides the parts each weapon form builds.
    """

    def test_the_kit_declares_nothing_at_slot_level(self):
        assert not hasattr(aphelios, "MODULE_CC")

    def test_only_gravitums_q_controls_what_it_damages(self):
        text = cc_review.slot_text(cc_review.kit("Aphelios"), "Q")
        assert (
            "aphelios expunges all enemies with gravitum's slow debuff, "
            "dealing 50 : 140 (based on level) (+ 32% : 50% (based on level) "
            "bonus ad) (+ 70% ap) magic damage and rooting them for 1 second" in text
        )
        assert aphelios._Q_CC_BY_WEAPON["gravitum"] == "root"
        for weapon in REVIEWED_WEAPONS:
            (part,) = _parse(weapon)["Q"]["parts"]
            assert part.cc_kind == aphelios._Q_CC_BY_WEAPON[weapon]

    def test_onslaughts_cadence_is_cached_but_the_heal_rule_owns_it(self):
        """Severum's schedule is whole in the cache and stays unauthored.

        Spreading the six attacks over the cached 1.75 seconds splits
        Severum's self-heal from one payment into one per attack, and the
        rule pays a full share for attacks that dealt nothing - healing the
        fight has not earned.  That is a heal change, not a review.
        """
        text = cc_review.slot_text(cc_review.kit("Aphelios"), "Q")
        assert (
            "aphelios enters an onslaught for 1.75 seconds, gaining 25% "
            "(+ 10% per 100 ap) bonus movement speed and automatically "
            "performing up to 6 (+ 2 per 100% bonus attack speed) attacks "
            "over the duration" in text
        )
        assert "severum" not in aphelios._Q_CC_BY_WEAPON
        (part,) = _parse("severum")["Q"]["parts"]
        assert part.count == 6
        assert part.hit_interval is None
        assert part.cc_kind is None

    def test_moonlight_vigils_blast_slows_only_under_gravitum(self):
        text = cc_review.slot_text(cc_review.kit("Aphelios"), "R")
        assert "gravitum: increases the initial slow to 99%" in text
        for weapon in WEAPONS:
            entry = _parse(weapon)["R"]
            assert entry["event_order_certified"] == "single_hit"
            (part,) = entry["parts"]
            assert part.cc_kind == ("slow" if weapon == "gravitum" else "none")

    def test_every_weapon_but_severum_clears_the_control_armed_scan(self):
        assert cc_review.unreviewed_ability_slots("Aphelios") == []
        for weapon in REVIEWED_WEAPONS:
            payload = calculate_payload(
                {
                    "champion": "Aphelios",
                    "level": 18,
                    "items": ["Fimbulwinter"],
                    "fight_mode": "timed",
                    "include_auto_attacks": True,
                    "champion_options": {"aphelios_main_weapon": weapon},
                }
            )
            coverage = payload["timeline_coverage"]
            assert coverage["complete"] is True, weapon
            assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]

    def test_severum_is_the_weapon_that_stays_coarse(self):
        payload = calculate_payload(
            {
                "champion": "Aphelios",
                "level": 18,
                "items": ["Fimbulwinter"],
                "fight_mode": "timed",
                "include_auto_attacks": True,
                "champion_options": {"aphelios_main_weapon": "severum"},
            }
        )
        coverage = payload["timeline_coverage"]
        assert coverage["complete"] is False
        assert "fimbulwinter_everlasting" in coverage["coarse_sources"]
