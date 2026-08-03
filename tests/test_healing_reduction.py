"""Directional guarantees for text-derived Grievous Wounds profiles.

``healing_reduction_profiles`` reads cached Wiki passive text, so it must
distinguish outgoing anti-heal ("dealing damage inflicts...") from
reactive anti-heal ("when struck ... inflict the attacker") — a reactive
passive read as outgoing would wrongly anti-heal everyone the holder
damages.
"""

from src.calculator.healing_reduction import (
    GRIEVOUS_WOUNDS_DURATION,
    GRIEVOUS_WOUNDS_FACTOR,
    healing_reduction_profiles,
)


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
