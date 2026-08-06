"""Zyra — Garden of Thorns plants (E4 summon damage).

Why each slot is non-generic:
- W (Rampant Growth) is the seed that Q/E sprout into attacking plants.
  The plant attack damage is NOT in the champion JSON (the Q/E ability
  text only says the plant "lasts for 8 seconds"; the numbers live on the
  wiki's pet section / the Community Dragon game files — see the
  HARDCODED block below), so W emits a fixed-count proc over the fight
  window: ``plant_count`` plants x ``plant_attacks`` attacks of
  ``15 : 75`` (based on level) (+ 20% AP) magic damage.
- Q/E/R keep the reviewed CP10.11 packet pricing; P keeps its explicit
  seed-spawn state row.

Plant boundaries: plants are static turrets with 0 move speed — the
model prices their attacks only while the target is in range for the
whole window (8s duration, well beyond the 5-second one-rotation
window).  The player controls the plant count (seeds via W, sprouting
via Q/E).  Stranglethorns enrage (flurry, 2 shots per attack at 150%)
and the 50% multi-plant falloff are not modeled.
"""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .reviewed_batch_01 import no_damage
from .reviewed_batch_11 import build_batch_module
from .slotlib import extract_named

_BATCH_PARSE, _BATCH_SLOTS, _BATCH_ASSUMPTIONS, _BATCH_SOURCES, _BATCH_OPTIONS = (
    build_batch_module("Zyra")
)

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
    return base + _PLANT_AP_RATIO * ctx.stats.get("ability_power", 0.0)


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
    plants = min(max(int(ctx.options.get("plant_count", 1)), 0), 8)
    attacks = min(max(int(ctx.options.get("plant_attacks", 4)), 0), 20)
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

ASSUMPTIONS = [
    "Every slot is an explicit packet or sourced no-damage entry from the "
    "pinned local Wiki cache; no runtime archetype inference is used.",
    "Numeric packets preserve rank/level arrays, typed scaling, target-health "
    "terms, and explicit variant selectors where the source lists them.",
    "The complete parent Wiki entry was read before certifying this module.",
    "Passive plus Q/W/E/R entries are represented by explicit packet or "
    "no-damage slot declarations.",
    "Rank arrays, cooldowns, typed target-health terms, and packet variants "
    "remain sourced from the local reviewed-packet asset.",
    "Non-damaging shields, buffs, movement, and utility branches remain "
    "explicit state/out-of-scope rows rather than invented damage.",
    "Plant attack damage (15 : 75 by level + 20% AP magic, 0.8 attack speed, ",
    "8s duration) is a game-file constant (ZyraP PlantDamage); verify on patch ",
    "updates against Community Dragon",
    "Thorn Spitters (Q) and Vine Lashers (E) share the same attack formula; ",
    "the Vine Lasher slow and the Stranglethorns enrage flurry (2 shots per ",
    "attack at 150%) are state, not modeled",
    "The 50% damage falloff for plants that are not the first to attack their ",
    "target and the Monster Hunter bonus vs non-epic monsters are not modeled",
]
SLOTS = {
    "P": _BATCH_SLOTS["P"],
    "Q": _BATCH_SLOTS["Q"],
    "W": _plants,
    "E": _BATCH_SLOTS["E"],
    "R": _BATCH_SLOTS["R"],
}

parse_abilities = build_parser(SLOTS, "Zyra")
SOURCES = _BATCH_SOURCES
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
