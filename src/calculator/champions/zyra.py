"""Zyra — Garden of Thorns plants (E4 summon damage).

Why each slot is non-generic:
- W (Rampant Growth) is the seed that Q/E sprout into attacking plants.
  The plant attack damage is NOT in the champion JSON (the Q/E ability
  text only says the plant "lasts for 8 seconds"; the numbers live on the
  wiki's pet section / the Community Dragon game files — see the
  HARDCODED block below), so W emits a fixed-count proc over the fight
  window: ``plant_count`` plants x ``plant_attacks`` attacks of
  ``15 : 75`` (based on level) (+ 20% AP) magic damage.
- Q/E/R keep the reviewed CP10.11 packet pricing.  P (Garden of Thorns)
  stays out of scope: its own seeds spawn on a timer and sprout into
  plants, a summon timeline the engine does not have.  The seed-spawn
  state row it emits prices nothing; the plants a player seeds through
  W are what the fight prices.

Plant boundaries: plants are static turrets with 0 move speed — the
model prices their attacks only while the target is in range for the
whole window (8s duration, well beyond the 5-second one-rotation
window).  The player controls the plant count (seeds via W, sprouting
via Q/E).  Stranglethorns enrage (flurry, 2 shots per attack at 150%)
and the 50% multi-plant falloff are not modeled.

Roadmap session 5 slot 14 (2026-08-21): P (Garden of Thorns) has no
enemy-damage formula: it periodically spawns Seeds (vision wards that
enemies can walk over to destroy), with no enemy-damage leveling row
(confirmed by the pinned reviewed packet's kind="no_damage" declaration
for P, and live: parse_champion_abilities emits P with total_raw=0.0,
and the fight breakdown carries no P/passive row at all). This module
keeps P at build_packet_module's default no-damage branch (``SLOTS["P"]
= _BATCH_SLOTS["P"]``, never reassigned). MODULE_COVERAGE was simply
stale, still reading "out_of_scope" for a slot this module already
treats as non-damaging (the Rek'Sai/Renekton precedent). Reclassified
to "no_damage"; zero fight-computation change.
"""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx
from .module_helpers import no_damage
from .packet_module import build_packet_module
from .slotlib import with_control

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
_PLANT_DAMAGE_START = 15.0  # level 1
_PLANT_DAMAGE_END = 75.0  # level 18
_PLANT_AP_RATIO = 0.20
_PLANT_AS = 0.8
_PLANT_DURATION = 8.0


def _plant_attack_damage(ctx: SlotCtx) -> float:
    """One plant basic attack at the champion's level (locked at spawn)."""
    span = _PLANT_DAMAGE_END - _PLANT_DAMAGE_START
    base = _PLANT_DAMAGE_START + span * (ctx.level - 1) / 17.0
    return base + _PLANT_AP_RATIO * ctx.stat("ability_power")


def _plants(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: plants — castable row pricing plant attacks over the window.

    The plant count is the player-controlled ``plant_count`` (a seed
    sprouts through Q/E; up to 8 plants) and ``plant_attacks`` is the
    per-plant attack count in the 5-second one-rotation window (0.8
    attack speed -> 4 attacks).  Zero cooldown keeps the row a single
    cast in both fight modes — the count is per window, never per recast.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    plants = min(max(int(ctx.option("plant_count")), 0), 8)
    attacks = min(max(int(ctx.option("plant_attacks")), 0), 20)
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
# W stays UNREVIEWED, so this kit keeps the coarse control-armed scan.
# The W row is not a cast at all but ``plant_count`` plants' basic
# attacks, and the two plant kinds do not answer alike: a Thorn Spitter
# (sprouted by Q) controls nothing while a Vine Lasher (sprouted by E)
# slows — a pets-page fact this module already records as unmodelled
# state and one the cached champion entry does not carry at all.  The
# option cannot tell them apart, so no one kind is true of the row.
MODULE_CC = {"Q": "none", "E": "root", "R": "knockup"}

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
        "declares the slot kind='no_damage'), so the slot is no_damage rather than an unmodeled gap",
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
            kind="root",
            duration_attr="Root Duration",
        ),
    },
    slot_order=("P", "Q", "W", "E", "R"),
    cc_kinds=MODULE_CC,
)

OPTIONS = [
    {
        "key": "plant_count",
        "type": "int",
        "default": 1,
        "label": "Plants attacking the target",
        "min": 0,
        "max": 8,
    },
    {
        "key": "plant_attacks",
        "type": "int",
        "default": 4,
        "label": "Plant attacks per plant (5s window)",
        "min": 0,
        "max": 20,
    },
]


MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "no_damage")
    for slot in "PQWER"
}
