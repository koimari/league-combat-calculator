"""What the holder-side durability axis is, measured rather than asserted.

Two Resolve runes waited on it and neither does now. What this file is for
is the same as it was: the facts their receipts rested on, measured rather
than asserted, so that a later reader can see which of them changed and
which did not.

* Bone Plating's receipt named the DIRECTION of an item channel.
  ``champion_damage_flat_reduction`` is still read off the target alone, and
  that is still true and no longer a blocker: the rune is priced on the
  survival walk instead, where the packets the holder receives are held in
  order with their times, which is the only place its activation, its hit
  count and its cooldown all fit.
* Second Wind's receipt named a TRIGGER. Neither rune trigger vocabulary
  fires on damage taken, which is also still true and also not a blocker:
  the walk arms its regeneration window off the incoming hit itself, the
  lane Doran's Shield's Enduring Focus is already paid on.
"""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.rune_effects import (
    RuneHealEffect,
    RunePlatingEffect,
    RuneHealTrigger,
    RuneTrigger,
    resolve_rune,
)
from src.calculator.starting_defenses import StartingDefenses

_ENEMY = {"kind": "champion", "champion": "Darius", "level": 18, "role": "top"}


def _fight(**overrides) -> dict:
    request = {
        "champion": "Garen",
        "level": 18,
        "role": "top",
        "items": [],
        "boots": "",
        "enemies": [_ENEMY],
        "fight_duration": 10,
        "fight_mode": "time_based",
        "include_auto_attacks": True,
        "auto_attack_uptime": 1.0,
        "enemies_attack": True,
    }
    request.update(overrides)
    return calculate_payload(request, deterministic=True)


class TestTheFightDoesCarryTheHolderSide:
    """The half the older receipts got wrong, so it is pinned first."""

    def test_the_participant_row_publishes_damage_taken_and_survival(self):
        row = _fight()["combat"]["breakdown"][0]
        assert row["health_damage"] > 0.0
        assert row["effective_health"] > 0.0
        assert "survived_window" in row
        assert "death_time" in row

    def test_effective_health_carries_no_resistance_term(self):
        """Health, shields and healing. A pure-armor item moves none of it."""
        bare = _fight()["combat"]["breakdown"][0]
        armored = _fight(items=["Chain Vest"])["combat"]["breakdown"][0]
        assert armored["health_damage"] == pytest.approx(bare["health_damage"])
        assert armored["effective_health"] == pytest.approx(bare["effective_health"])


class TestBonePlatingIsPaidOnTheWalkRatherThanTheItemChannel:
    def test_the_item_channel_still_runs_one_way(self):
        """Unchanged, and no longer the rune's blocker.

        Guardian's Horn also grants health, so the holder's damage taken
        goes UP rather than staying level when the holder wears it. That is
        the point: none of the change is the flat reduction.
        """
        fields = StartingDefenses.__dataclass_fields__
        assert "champion_damage_flat_reduction" in fields
        bare = _fight()["total_damage"]
        mitigated = _fight(enemies=[{**_ENEMY, "items": ["Guardian's Horn"]}])[
            "total_damage"
        ]
        assert bare == pytest.approx(2239.9, abs=0.1)
        assert mitigated == pytest.approx(1796.1, abs=0.1)
        held = _fight(items=["Guardian's Horn"])["combat"]["breakdown"][0]
        assert (
            held["health_damage"] >= _fight()["combat"]["breakdown"][0]["health_damage"]
        )

    def test_the_rune_reduces_the_hits_after_the_one_that_armed_it(self):
        bare = _fight()["combat"]["breakdown"][0]
        plated = _fight(minor_runes=["Bone Plating"])["combat"]["breakdown"][0]
        assert plated["death_time"] > bare["death_time"]

    def test_the_receipt_names_the_lane_it_is_priced_on(self):
        effect = resolve_rune("Bone Plating")
        assert isinstance(effect, RunePlatingEffect)
        assert effect.hits == 3
        assert effect.window_seconds == pytest.approx(1.5)


class TestSecondWindIsPaidOnTheWalkSRecoveryLane:
    """The trigger the vocabularies still lack, and the lane that has one.

    Every member of both rune trigger enums still names something the
    holder DOES, and that is the fact the old receipt rested on. What it
    got wrong was the conclusion: the survival walk holds the packets the
    holder RECEIVED, and a rune kind armed there needs no member of either
    vocabulary. These pin both halves, so a trigger added to an enum does
    not quietly become the explanation for a rune that is not paid by one.
    """

    def test_neither_trigger_vocabulary_fires_on_damage_taken(self):
        """Unchanged, and no longer a blocker: the rune is not paid by one."""
        assert {member.name for member in RuneHealTrigger} == {
            "DAMAGE_DEALT",
            "IMPAIRING_INSTANCES",
            "TAKEDOWNS",
        }
        assert {member.name for member in RuneTrigger} == {
            "DAMAGE_INSTANCES",
            "BASIC_ATTACKS",
            "DAMAGING_CASTS",
            "IMPAIRED_INSTANCES",
            "SELF_SHIELD_EVENTS",
        }
        assert not isinstance(resolve_rune("Second Wind"), RuneHealEffect)

    def test_the_window_is_armed_by_an_incoming_hit_and_pays_the_holder(self):
        bare = _fight()["combat"]["breakdown"][0]
        held = _fight(minor_runes=["Second Wind"])["combat"]["breakdown"][0]
        assert bare["healing_received"] == pytest.approx(0.0)
        # Darius's first auto, at his 0.297s windup, arms it: three 1s ticks
        # (1.30 to 3.30s) land before he kills the holder at 3.75s.
        assert held["healing_received"] == pytest.approx(19.8, abs=0.1)
        assert held["effective_health"] > bare["effective_health"]

    def test_it_rides_the_same_lane_doran_s_shield_does(self):
        """One lane, two owners, and a holder may declare both."""
        item_only = _fight(items=["Doran's Shield"])["combat"]["breakdown"][0]
        both = _fight(items=["Doran's Shield"], minor_runes=["Second Wind"])["combat"][
            "breakdown"
        ][0]
        assert both["healing_received"] > item_only["healing_received"]
