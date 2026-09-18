"""The nine exact zeros: measured, not merely receipted.

Six structural zeros (no combat number in any source) and three withheld
runes whose number never reaches the fight (trinket haste with no trinket,
potion restoration with no potion drunk, gold that never joins a total).
Each already compiles to a receipted refusal; what this pins is the
stronger claim — selecting one moves no published number anywhere: not the
stat card, not the total, not the resource pool, not the self-healing
ledger. A rune that moves a number belongs in a path module with a channel;
a rune in this list that ever does fails here, which is the tripwire that
promotes it.
"""

import pytest

from src.calculator.calculate import calculate_payload

#: (slot, name): keystones ride the keystone field, minors the minor list.
ZERO_RUNES = (
    ("minor", "Sixth Sense"),
    ("minor", "Deep Ward"),
    ("minor", "Relentless Hunter"),
    ("minor", "Hextech Flashtraption"),
    ("minor", "Cash Back"),
    ("keystone", "Unsealed Spellbook"),
    ("minor", "Treasure Hunter"),
    ("minor", "Grisly Mementos"),
    ("minor", "Time Warp Tonic"),
)


def _fight(*, keystone="Arcane Comet", minor_runes=()):
    return calculate_payload(
        {
            "champion": "Ahri",
            "level": 18,
            "items": [],
            "fight_mode": "time_based",
            "fight_duration": 20.0,
            "include_auto_attacks": True,
            "auto_attack_uptime": 1.0,
            "target_health": 10000.0,
            "target_armor": 100.0,
            "target_mr": 100.0,
            "keystone": keystone,
            "minor_runes": list(minor_runes),
            "stat_shards": [],
        },
        deterministic=True,
    )


class TestExactZerosMoveNothing:
    @pytest.mark.parametrize(("slot", "name"), ZERO_RUNES)
    def test_selecting_it_moves_no_published_number(self, slot, name):
        # The keystone case compares against no keystone at all: swapping
        # Comet for Unsealed removes Comet's own damage, which is Comet
        # moving a number and not Unsealed doing anything.
        if slot == "keystone":
            bare = _fight(keystone="")
            held = _fight(keystone=name)
        else:
            bare = _fight()
            held = _fight(minor_runes=(name,))
        assert held["champion_stats"] == bare["champion_stats"]
        assert held["total_damage"] == pytest.approx(bare["total_damage"])
        assert held["resource_remaining"] == pytest.approx(bare["resource_remaining"])
        assert held["self_healing"] == pytest.approx(bare["self_healing"])
        assert any(
            name in note
            and ("deals no damage in any fight" in note or "is not priced" in note)
            for note in held["notes"]
        )
