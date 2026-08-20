"""Tests for the Aphelios champion module."""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.champions import aphelios, parse_champion_abilities
from src.calculator.stats import calculate_total_stats
from tests import cc_review

WEAPONS = ("calibrum", "severum", "gravitum", "infernum", "crescendum")
# The four weapon forms whose Q prices exactly one hit; Severum's Q is
# Onslaught, six attacks on a cached beat.
SINGLE_HIT_WEAPONS = ("calibrum", "gravitum", "infernum", "crescendum")
REVIEWED_WEAPONS = SINGLE_HIT_WEAPONS


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
        for weapon in SINGLE_HIT_WEAPONS:
            (part,) = _parse(weapon)["Q"]["parts"]
            assert part.cc_kind == aphelios._Q_CC_BY_WEAPON[weapon]

    def test_onslaught_spreads_its_attacks_over_the_cached_duration(self):
        """Six attacks over 1.75 seconds, at the rate that implies.

        The count is what scales with attack speed, not the window, so the
        beat is ``duration / count`` and every attack lands inside the
        cached duration.
        """
        text = cc_review.slot_text(cc_review.kit("Aphelios"), "Q")
        assert (
            "aphelios enters an onslaught for 1.75 seconds, gaining 25% "
            "(+ 10% per 100 ap) bonus movement speed and automatically "
            "performing up to 6 (+ 2 per 100% bonus attack speed) attacks "
            "over the duration" in text
        )
        assert aphelios._Q_CC_BY_WEAPON["severum"] == "none"
        (part,) = _parse("severum")["Q"]["parts"]
        assert part.count == 6
        assert part.time_offset == 0.0
        assert part.hit_interval == pytest.approx(aphelios._Q_ONSLAUGHT_SECONDS / 6)
        assert part.cc_kind == "none"
        assert (part.count - 1) * part.hit_interval < aphelios._Q_ONSLAUGHT_SECONDS

    def test_severum_pays_one_heal_per_attack_that_dealt_damage(self):
        """ "Severum's attacks heal Aphelios for ... the post-mitigation
        damage dealt" — six attacks, six shares, same total as the one
        payment the unspread row used to make.
        """
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
        onslaught = [
            event for event in payload["damage_events"] if event.get("source") == "Q"
        ]
        assert len(onslaught) == 6
        heals = [
            event
            for event in payload["self_healing_events"]
            if event["source"] == "Severum"
        ]
        by_time = {round(float(event["time"]), 3) for event in heals}
        assert {round(float(event["time"]), 3) for event in onslaught} <= by_time
        assert all(event["amount"] > 0.0 for event in heals)

    def test_moonlight_vigils_blast_slows_only_under_gravitum(self):
        text = cc_review.slot_text(cc_review.kit("Aphelios"), "R")
        assert "gravitum: increases the initial slow to 99%" in text
        for weapon in WEAPONS:
            entry = _parse(weapon)["R"]
            assert entry["event_order_certified"] == "single_hit"
            (part,) = entry["parts"]
            assert part.cc_kind == ("slow" if weapon == "gravitum" else "none")

    def test_every_weapon_clears_the_control_armed_scan(self):
        assert cc_review.unreviewed_ability_slots("Aphelios") == []
        for weapon in WEAPONS:
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

    def test_severum_clears_the_control_armed_scan_too(self):
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
        assert coverage["complete"] is True
        assert "fimbulwinter_everlasting" not in coverage["coarse_sources"]
