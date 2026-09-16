"""What the holder-side durability axis is, measured rather than asserted.

Two Resolve runes wait on it, and their receipts name a blocker each. A
receipt is only worth the measurement behind it, so this pins the facts both
reasons rest on. Every one is a thing that would CHANGE if the axis were
built, so the day it is, these fail and name what to re-read.

The two blockers are different and neither is the one the older receipts
gave, which was that the engine prices only the damage the holder deals:

* Bone Plating waits on the DIRECTION of a channel that already exists.
  ``champion_damage_flat_reduction`` is read off the target, where it lowers
  the damage this attacker deals. Nothing reads the holder's own.
* Second Wind waits on a TRIGGER. The fight carries the holder's health and
  the damage it takes and publishes both; what it has no vocabulary for is a
  rune that answers an incoming hit.
"""

import pytest

from src.calculator.calculate import calculate_payload
from src.calculator.rune_effects import RuneHealTrigger, RuneTrigger, resolve_rune
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
        "deterministic": True,
        "include_auto_attacks": True,
        "auto_attack_uptime": 1.0,
        "enemies_attack": True,
    }
    request.update(overrides)
    return calculate_payload(request)


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


class TestBonePlatingWaitsOnTheChannelsDirection:
    def test_the_flat_reduction_field_exists_on_the_defence_record(self):
        assert hasattr(StartingDefenses, "__dataclass_fields__")
        fields = StartingDefenses.__dataclass_fields__
        assert "champion_damage_flat_reduction" in fields

    def test_it_works_when_the_ENEMY_holds_it(self):
        """The direction that is wired, with the number the receipt quotes."""
        bare = _fight()["total_damage"]
        mitigated = _fight(enemies=[{**_ENEMY, "items": ["Guardian's Horn"]}])[
            "total_damage"
        ]
        assert bare == pytest.approx(2276.8, abs=0.1)
        assert mitigated == pytest.approx(1826.8, abs=0.1)
        assert mitigated < bare

    def test_it_does_nothing_when_the_HOLDER_holds_it(self):
        """The direction that is not, which is the whole blocker.

        Guardian's Horn also grants health, so the holder's damage taken goes
        UP rather than staying level. That is the point: none of the change
        is the flat reduction.
        """
        bare = _fight()["combat"]["breakdown"][0]
        held = _fight(items=["Guardian's Horn"])["combat"]["breakdown"][0]
        assert held["health_damage"] >= bare["health_damage"]

    def test_the_receipt_names_the_direction_and_not_the_old_reason(self):
        reason = resolve_rune("Bone Plating").zero_policy.reason
        assert "runs the other way" in reason
        assert "read off the TARGET" in reason
        disclosures = " ".join(resolve_rune("Bone Plating").disclosures)
        assert "2276.8 to 1826.8" in disclosures
        assert "next 3 hits within 1.5 seconds" in disclosures


class TestSecondWindWaitsOnATrigger:
    def test_no_trigger_in_either_vocabulary_fires_on_damage_taken(self):
        """Every member names something the holder DOES."""
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

    def test_the_receipt_names_the_trigger_and_says_the_health_is_there(self):
        effect = resolve_rune("Second Wind")
        assert "no rune trigger fires on damage TAKEN" in effect.zero_policy.reason
        disclosures = " ".join(effect.disclosures)
        assert "blocker is the trigger and not the health" in disclosures
