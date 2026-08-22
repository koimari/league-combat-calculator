"""Directional guarantees for text-derived Grievous Wounds profiles.

``healing_reduction_profiles`` reads cached Wiki passive text, so it must
distinguish outgoing anti-heal ("dealing damage inflicts...") from
reactive anti-heal ("when struck ... inflict the attacker") — a reactive
passive read as outgoing would wrongly anti-heal everyone the holder
damages.
"""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.healing_reduction import (
    GRIEVOUS_WOUNDS_DURATION,
    GRIEVOUS_WOUNDS_FACTOR,
    amplifies_recovery,
    heal_and_shield_power_factor,
    healing_reduction_profiles,
)


class TestHealAndShieldPower:
    """The caster's amplifier, and the two recoveries it may not reach."""

    @pytest.mark.parametrize(
        ("stats", "expected"),
        [
            (None, 1.0),
            ({}, 1.0),
            ({"heal_and_shield_power_percent": 0.0}, 1.0),
            ({"heal_and_shield_power_percent": 10.0}, 1.1),
            ({"heal_and_shield_power_percent": 8.0}, 1.08),
        ],
    )
    def test_the_factor_is_one_plus_the_published_percent(self, stats, expected):
        assert heal_and_shield_power_factor(stats) == pytest.approx(expected)

    @pytest.mark.parametrize(
        ("kind", "category", "expected"),
        [
            ("heal", "", True),
            ("heal", "champion", True),
            ("shield", "", True),
            ("regen", "", False),
            ("heal", "vamp", False),
        ],
    )
    def test_regeneration_and_vamp_are_not_amplified(self, kind, category, expected):
        assert amplifies_recovery(kind, category) is expected

    @pytest.mark.parametrize("champion", ["Aatrox", "Warwick", "Vladimir"])
    def test_a_self_heal_is_amplified_by_the_published_stat(self, champion):
        """The published total is the authored packets times the factor."""
        request = {
            "champion": champion,
            "level": 18,
            "fight_mode": "timed",
            "fight_duration": 12,
            "include_auto_attacks": True,
        }
        healed = calculate_payload(
            {**request, "items": ["Redemption"]}, deterministic=True
        )
        assert healed["champion_stats"]["heal_and_shield_power_percent"] == 10.0
        authored = sum(
            float(event["amount"]) for event in healed["self_healing_events"]
        )
        assert authored > 0.0
        # The published packet amounts are rounded for display, so the
        # sum of them lands within a rounding step of the total.
        assert healed["self_healing"] == pytest.approx(authored * 1.1, rel=1e-3)

    def test_a_champion_without_the_stat_is_unamplified(self):
        bare = calculate_payload(
            {
                "champion": "Aatrox",
                "level": 18,
                "items": [],
                "fight_mode": "timed",
                "fight_duration": 12,
                "include_auto_attacks": True,
            },
            deterministic=True,
        )
        assert bare["champion_stats"]["heal_and_shield_power_percent"] == 0.0
        authored = sum(float(event["amount"]) for event in bare["self_healing_events"])
        assert bare["self_healing"] == pytest.approx(authored, rel=1e-3)


def _item(name: str, effects: str) -> dict:
    return {"name": name, "passives": [{"name": "Test Passive", "branches": [effects]}]}


def test_outgoing_anti_heal_text_produces_a_profile() -> None:
    profiles = healing_reduction_profiles(
        [
            _item(
                "Chempunk Chainsword",
                "Dealing physical damage inflicts enemies with Grievous Wounds "
                "for 3 seconds.",
            )
        ]
    )
    assert len(profiles) == 1
    assert profiles[0]["damage_types"] == frozenset({"physical"})
    assert profiles[0]["factor"] == GRIEVOUS_WOUNDS_FACTOR
    assert profiles[0]["duration"] == GRIEVOUS_WOUNDS_DURATION


def test_reactive_when_struck_text_is_not_an_outgoing_profile() -> None:
    """Bramble Vest's Thorns anti-heals whoever strikes the wearer, not the
    wearer's own targets — its text must fail closed here."""
    profiles = healing_reduction_profiles(
        [
            _item(
                "Bramble Vest",
                "When struck by a basic attack [[on-hit]], deal "
                "{{as|10 magic damage}} to the attacker and, if they are a "
                "champion, inflict them with {{tip|Grievous Wounds}} for "
                "3 seconds.",
            )
        ]
    )
    assert profiles == ()
