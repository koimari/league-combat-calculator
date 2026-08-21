"""Imperial Mandate's Control: the haste an immobilizing ability is cast at.

"Abilities with immobilizing effects have their cooldown reduced equivalent
to 20 ability haste" — sourced, cached in ``ALLY_ITEM_EFFECTS`` and, until
this file, read by nothing. It is not a stat of the build: it reaches only
the slots whose *reviewed* control marker says they immobilize, which is the
same declaration Command's amplifier gates on. So it is read at the
cooldown, beside the ultimate haste an ultimate alone reads.

It only ever moves a timed fight: one rotation casts each ability once
whatever its cooldown.
"""

import pytest

from src.calculator import item_effects
from src.calculator.ability_spec import DamagePart
from src.calculator.calculate import calculate_payload
from src.calculator.damage import FightConfig, calculate_fight_damage

_MANDATE = [{"name": "Imperial Mandate"}]


class TestTheSourcedValue:
    def test_the_build_carries_the_haste_the_cache_states(self):
        assert item_effects.immobilize_ability_haste(_MANDATE) == pytest.approx(20.0)
        assert (
            item_effects.ALLY_ITEM_EFFECTS["Imperial Mandate"][
                item_effects.CONTROL_ABILITY_HASTE_KEY
            ]
            == 20.0
        )

    def test_a_build_without_the_declared_key_carries_none(self):
        assert item_effects.immobilize_ability_haste([]) == 0
        assert (
            item_effects.immobilize_ability_haste([{"name": "Rabadon's Deathcap"}]) == 0
        )

    def test_the_filter_is_the_key_and_not_an_item_name(self):
        """A second item declaring it would join without touching the engine."""
        holders = [
            name
            for name, entry in item_effects.ALLY_ITEM_EFFECTS.items()
            if item_effects.CONTROL_ABILITY_HASTE_KEY in entry
        ]
        assert holders == ["Imperial Mandate"]


# ---------------------------------------------------------------------------
# What the fight does with it
# ---------------------------------------------------------------------------
#
# One 6s ability, no ability haste of its own, in a 20s fight: four casts at
# 0, 6, 12 and 18. Mandate's 20 haste makes the cooldown 6 x 100/120 = 5s,
# which fits a fifth cast at 20s. The synthetic build carries no stat block
# from its items, so the extra cast is this haste and nothing else.

_STATS = {
    "attack_damage": 100.0,
    "base_attack_damage": 60.0,
    "bonus_attack_damage": 40.0,
    "ability_power": 0.0,
    "attack_speed": 0.7,
    "attack_speed_ratio": 0.7,
    "critical_strike_chance": 0.0,
    "health": 2000.0,
    "armor": 50.0,
    "magic_resistance": 50.0,
    "level": 18,
    "ability_haste": 0.0,
}
_MITIGATED_CAST = 150.0


def _abilities(cc_kind):
    """One 6-second ability whose reviewed control marker is *cc_kind*."""
    return {
        "Q": {
            "name": "Test Q",
            "rank": 1,
            "cooldown": 6.0,
            "damage_type": "magic",
            "total_raw": 300.0,
            "parts": (DamagePart("magic", 300.0, cc_kind=cc_kind),),
        }
    }


def _fight(cc_kind, items):
    config = {
        "target_health": 100_000.0,
        "target_armor": 100.0,
        "target_magic_resistance": 100.0,
        "fight_duration_seconds": 20.0,
        "auto_attack_uptime": 0.0,
        "one_rotation": False,
        "deterministic": True,
    }
    return calculate_fight_damage(
        dict(_STATS), _abilities(cc_kind), list(items), FightConfig(**config)
    )


class TestTheCooldownPathReadsIt:
    @pytest.mark.parametrize("cc_kind", ["stun", "root", "charm", "immobilize"])
    def test_an_immobilizing_slot_is_recast_sooner(self, cc_kind):
        bare = _fight(cc_kind, [])
        held = _fight(cc_kind, _MANDATE)
        assert bare["breakdown"]["Q"]["casts"] == 4
        assert held["breakdown"]["Q"]["casts"] == 5
        assert held["total_damage"] == pytest.approx(5 * _MITIGATED_CAST)

    @pytest.mark.parametrize("cc_kind", ["none", "slow", "silence"])
    def test_a_slot_that_does_not_immobilize_is_not(self, cc_kind):
        """The gate is the immobilize predicate, not "declares some control"."""
        held = _fight(cc_kind, _MANDATE)
        assert held["breakdown"]["Q"]["casts"] == 4
        assert held["total_damage"] == pytest.approx(4 * _MITIGATED_CAST)

    def test_an_unreviewed_slot_pays_nothing(self):
        """An absent marker is unreviewed, and unreviewed is never assumed."""
        assert _fight(None, _MANDATE)["breakdown"]["Q"]["casts"] == 4

    def test_a_build_without_the_item_is_the_fight_unchanged(self):
        assert _fight("stun", [])["total_damage"] == pytest.approx(4 * _MITIGATED_CAST)


class TestThroughTheRealPipeline:
    """Ahri's Charm is a reviewed immobilize (``ahri.MODULE_CC["E"]``)."""

    _REQUEST = {
        "champion": "Ahri",
        "level": 18,
        "items": ["Imperial Mandate"],
        "fight_mode": "time_based",
        "fight_duration": 20.0,
        "target_health": 3000.0,
        "target_armor": 100.0,
        "target_mr": 100.0,
    }

    def test_ahris_charm_lands_a_third_time_inside_the_window(self):
        result = calculate_payload(dict(self._REQUEST))
        breakdown = result["breakdown"]
        assert breakdown["E"]["casts"] == 3
        assert result["total_damage"] == pytest.approx(2459.2, abs=0.05)

    def test_her_other_slots_keep_their_own_cadence(self):
        """Q is reviewed ``none``; W and R declare no marker at all."""
        breakdown = calculate_payload(dict(self._REQUEST))["breakdown"]
        assert [breakdown[slot]["casts"] for slot in ("Q", "W", "R")] == [4, 5, 1]

    def test_one_rotation_is_untouched_because_nothing_recasts(self):
        rotation = calculate_payload({**self._REQUEST, "fight_mode": "one_rotation"})
        assert all(
            rotation["breakdown"][slot]["casts"] == 1 for slot in ("Q", "W", "E", "R")
        )
