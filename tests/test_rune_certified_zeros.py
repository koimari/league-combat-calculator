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

from src.calculator import rune_effects
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

#: Probe 2's settled buckets. A certified zero is a no-damage compiler with
#: a measured exact zero pinned below and no axis that could price it (Jev
#: unanimous exact-zero, zero priceable votes). What remains refused is a
#: real number awaiting an axis or sourcing: Demolish (structure targets),
#: Triple Tonic (elixir numbers live nowhere in-tree), Nimbus Cloak
#: (summoner gate plus an unsourced decay shape). Priced is everything
#: else: 50 real effects, 9 certified zeros, 3 refused, 62 total.
CERTIFIED_ZEROS = frozenset(name for _, name in ZERO_RUNES)
REFUSED_REMAINDER = frozenset({"Demolish", "Triple Tonic", "Nimbus Cloak"})


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


class TestProbeTwoBucketsAreExhaustive:
    def test_every_no_damage_compiler_is_certified_or_in_the_remainder(self):
        """The settled definition, mechanised: a rune that books no damage
        is either measured exactly zero above or one of the three real
        numbers awaiting an axis. A new refusal — or a certified zero that
        starts moving numbers — fails here until it is triaged."""
        damageless = frozenset(
            entry["name"]
            for entry in rune_effects.rune_catalog()
            if isinstance(
                rune_effects.resolve_rune(entry["name"]),
                rune_effects.RuneNoDamageEffect,
            )
        )
        assert damageless == CERTIFIED_ZEROS | REFUSED_REMAINDER
        assert CERTIFIED_ZEROS & REFUSED_REMAINDER == frozenset()
        assert len(damageless) + 50 == 62
