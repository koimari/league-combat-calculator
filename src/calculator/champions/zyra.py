"""Zyra: Garden of Thorns plants.

W (Rampant Growth) is the seed Q and E sprout into attacking plants.  The plant
attack damage is not in the champion cache at all, the ability text giving only
the 8-second lifetime, so it is a module constant from the game files and W
emits a fixed-count proc: ``plant_count`` plants times ``plant_attacks`` attacks
of 15 to 75 by level (+ 20% AP) magic.
Q, E and R keep their packet pricing.  P (Garden of Thorns) is ``no_damage``:
its own seeds spawn on a timer and sprout on their own, a summon timeline this
engine does not have, and the plants a player seeds through W are what the
fight prices.
Plant boundaries: plants are static turrets, so the model prices their attacks
only while the target stays in range for the whole window, which the 8-second
lifetime covers.  The Stranglethorns enrage and the 50% multi-plant falloff are
not modeled.
"""

from __future__ import annotations

import re
from typing import Any

from ..data_fetcher import get_champion
from ..ability_prose import CachedSentence
from ..ability_spec import DamagePart
from ..binary_roots import calculation_interpolation, data_value, spell_object
from .pet_window import derived_attack_count
from .charge_cadence import ChargeRule
from .contract_vocabulary import REQUIRED_CHAMPION_SLOTS, coverage
from .engine import SlotCtx
from .inputs import int_option
from .module_helpers import ability_slot, no_damage
from .packet_module import build_packet_module
from .slot_cc import CC_PER_PART
from .slot_control import with_control

PACKET_SHA256 = "e34a0a227a5432c3c99a6fc6850e3c3ea23f9b2148c3690c93907949b5874b5b"

# Deadly Spines lands on its own delay: "Zyra sprouts thorny spines at the
# target location that appear after a 0.625-seconds delay, dealing magic
# damage to enemies hit" (data/champions.json Zyra Q).  The cached entry
# attaches no cast-time qualifier to the number, so it is read from the
# cast start as written.
_Q_SPROUT_SECONDS = 0.625


# HARDCODED: verify on patch updates — plant attack damage is not scraped
# into data/champions.json (the Q/E text says only "lasts for 8 seconds";
# the ability descriptions point to "See Pets for more details").
# Sourced from the Community Dragon game files (current patch) and the
# wiki pet infobox:
#   https://raw.communitydragon.org/latest/game/data/characters/
#     zyra/zyra.bin.json  (ZyraP "PlantDamage" spell calc: 15 : 75 by
#       char level + 20% AP; PlantDuration 8s)
#   https://wiki.leagueoflegends.com/en-us/Zyra (Thorn Spitter / Vine
#     Lasher: attack speed 0.8, duration 8s)
# Plant attack: 15 : 75 (based on level) (+ 20% AP) magic — the same for
# Thorn Spitters (Q) and Vine Lashers (E); 0.8 attack speed -> 4 attacks
# in the 5-second one-rotation window.
_ZYRA_P_SPELL = spell_object("Zyra", "ZyraP")
_PLANT_DAMAGE_START, _PLANT_DAMAGE_END = calculation_interpolation(
    _ZYRA_P_SPELL, "PlantDamage"
)
_PLANT_AP_RATIO = data_value(_ZYRA_P_SPELL, "APRatio")
_PLANT_AS = 0.8

# "If Deadly Spine hits a Seed, it sprouts into a Thorn Spitter that lasts
# for 8 seconds" — the plant's own clock, which bounds the derived attack
# count however long the fight runs.  Q is where the cache states it, and a
# cache that stops saying so raises rather than leaving a stale constant to
# price a plant that outlives its sentence.
_PLANT_LIFETIME = CachedSentence(
    re.compile(
        r"sprouts into a Thorn Spitter that lasts for (?P<value>\d+(?:\.\d+)?) seconds"
    ),
    missing=(
        "Zyra Q: the cached entry no longer states the plant's lifetime "
        "('sprouts into a Thorn Spitter that lasts for N seconds')"
    ),
)
_PLANT_LIFETIME_SECONDS = _PLANT_LIFETIME.value(
    get_champion("Zyra")["abilities"]["Q"][0]
)
# A clockless parse reads the five-second one-rotation window the declared
# count was written against, so such a parse prices what it always did.
_PLANT_FALLBACK_WINDOW = 5.0
_PLANT_MAX_ATTACKS = 20


def _plant_attack_damage(ctx: SlotCtx) -> float:
    """One plant basic attack at the champion's level (locked at spawn)."""
    span = _PLANT_DAMAGE_END - _PLANT_DAMAGE_START
    base = _PLANT_DAMAGE_START + span * (ctx.level - 1) / 17.0
    return base + _PLANT_AP_RATIO * ctx.stat("ability_power")


@ability_slot()
def _plants(ctx: SlotCtx, _ability: dict[str, Any]) -> dict[str, Any] | None:
    """W: plants — castable row pricing plant attacks over the window.

    The plant count is the player-controlled ``plant_count`` (a seed
    sprouts through Q/E; up to 8 plants) and ``plant_attacks`` is the
    per-plant attack count in the 5-second one-rotation window (0.8
    attack speed -> 4 attacks).  Zero cooldown keeps the row a single
    cast in both fight modes — the count is per window, never per recast.
    """
    plants = min(max(int(ctx.option("plant_count")), 0), 8)
    attacks = derived_attack_count(
        ctx,
        "plant_attacks",
        attack_speed=_PLANT_AS,
        fallback_window=_PLANT_FALLBACK_WINDOW,
        lifetime=_PLANT_LIFETIME_SECONDS,
        maximum=_PLANT_MAX_ATTACKS,
    )
    count = plants * attacks
    if count <= 0:
        return no_damage(
            ctx,
            name="Garden of Thorns (Plants)",
            reason=(
                f"{plants} plant(s) x {attacks} attacks per plant in the window — "
                "set plant_count / plant_attacks to price them."
            ),
        )
    per = _plant_attack_damage(ctx)
    entry: dict[str, Any] = {
        "name": "Garden of Thorns (Plants)",
        "damage_type": "magic",
        # Plants are summons, not Zyra: a charm, stun or root on her stops
        # her casting and does not stop a plant that is already on the
        # field from attacking.
        "cast_while_disabled": True,
        "cooldown": 0.0,
        "total_raw": per * count,
        "parts": (
            DamagePart(
                "magic",
                per,
                count=count,
                time_offset=0.0,
                hit_interval=1.0 / _PLANT_AS,
            ),
        ),
        "detail": (
            f"{plants} plant(s) x {attacks} attacks = {count} attacks of {per:.2f} "
            "magic (15 : 75 based on level + 20% AP) spread over the 5s window; "
            "Thorn Spitter (Q) and Vine Lasher (E) share the formula, 0.8 attack "
            "speed (1.25s interval), 8s duration"
        ),
    }
    return entry


# Grasping Roots' vines "deal[] magic damage to enemies hit and root[] them
# for a duration"; Stranglethorns damages "as it expands" and then "snaps
# upward to knock up enemies within for 1 second".  P is the seed-spawn
# state row and authors no damage part.
#
# Deadly Spines only damages ("dealing magic damage to enemies hit"); its
# sprout delay is authored above, so the row carries that answer.
#
# W names itself per-part and no part states a kind.  The W row is not a
# cast at all but ``plant_count`` plants' basic attacks, and the two plant
# kinds do not answer alike: a Thorn Spitter (sprouted by Q) controls
# nothing while a Vine Lasher (sprouted by E) slows — a pets-page fact
# this module already records as unmodelled state and one the cached
# champion entry does not carry at all.  The option cannot tell them
# apart, so no one kind is true of the row.
MODULE_CC = {"Q": "none", "E": "root", "R": "knockup", "P": "none", "W": CC_PER_PART}

# What this module says about its charge slot (charge_cadence.py).
CHARGE_RULES = {
    "W": ChargeRule(
        why=(
            "W (Rampant Growth) banks seeds on its cached rechargeRate "
            "(10s at rank 5); the cached cooldown is zero because "
            "placing two seeds has no gap at all. The cached stock of 2 "
            "is not spent here: a later cast grows the seed, so placing "
            "one is not damage of its own."
        ),
        charges=1,
    )
}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Zyra",
    PACKET_SHA256,
    assumption_overrides=(
        "Plant attack damage (15 : 75 by level + 20% AP magic, 0.8 attack speed, 8s duration) is a "
        "game-file constant (ZyraP PlantDamage); verify on patch updates against Community Dragon",
        "Thorn Spitters (Q) and Vine Lashers (E) share the same attack formula; the Vine Lasher "
        "slow and the Stranglethorns enrage flurry (2 shots per attack at 150%) are state, not "
        "modeled",
        "The 50% damage falloff for plants that are not the first to attack their target and the "
        "Monster Hunter bonus vs non-epic monsters are not modeled",
        "P (Garden of Thorns) has no enemy-damage formula: it periodically spawns Seeds (vision "
        "wards enemies can walk over to destroy), no term dealt to an enemy (the pinned packet "
        "declares the slot kind='no_damage'), so the slot is no_damage rather than an "
        "unmodeled gap",
    ),
    # E's vines burst on the enemies they reach and R damages "as it
    # expands"; neither packet carries a travel or tick phase to place.
    single_hit_slots=frozenset({"E", "R"}),
    # Q's spines are not a cast-boundary hit: Zyra "sprouts thorny
    # spines at the target location that appear after a 0.625-seconds
    # delay, dealing magic damage to enemies hit".
    packet_part_timings={"Q": {"time_offset": _Q_SPROUT_SECONDS}},
    slot_parsers={
        "W": _plants,
    },
    # E's root duration is sourced off the packet's own "Root Duration"
    # attribute rather than restated here.
    slot_wrappers={
        "E": lambda compiled: with_control(
            compiled,
            duration_attr="Root Duration",
        ),
    },
    slot_order=REQUIRED_CHAMPION_SLOTS,
    cc_kinds=MODULE_CC,
    charge_rules=CHARGE_RULES,
)

OPTIONS = [
    int_option(
        "plant_count",
        1,
        minimum=0,
        maximum=8,
        label="Plants attacking the target",
        rotation={"role": "self_state", "slot": "R"},
    ),
    int_option(
        "plant_attacks",
        4,
        minimum=0,
        maximum=_PLANT_MAX_ATTACKS,
        label=(
            "Plant attacks per plant; unset derives them from the plant's "
            "0.8 attack speed over its sourced 8-second life"
        ),
        rotation={"role": "self_state", "slot": "R"},
    ),
]


MODULE_COVERAGE = coverage(no_damage="P")
