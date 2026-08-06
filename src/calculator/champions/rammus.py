"""Rammus — CP10.6 full-entry-reviewed packet module, plus the E9-3 W fix.

E9-3: Defensive Ball Curl (W) is a defensive stance whose damage is the
THORNS proc against basic-attacking enemies: "enemies that use a basic
attack on-hit against Rammus are dealt 15 (+ 10% total armor) (+ 10%
total magic resistance) magic damage".  The reviewed packet misread the
stance's 'Bonus Armor' leveling row as magic damage (47 + 60% armor
against MR at rank 5); the thorns formula has NO leveling row in the
cache, so it is pinned here as wiki prose with the source cited.  The
module prices the thorns damage per enemy basic attack that lands
during the stance via the ``w_thorns_autos`` option (0 by default — the
fight engine has no incoming-auto hook, so the enemy's auto count is
explicit state); the stance's bonus armor/MR rows are the defensive
buff, not damage, and remain state.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .reviewed_batch_06 import build_batch_module
from .slotlib import damage_entry, extract_cooldown

# HARDCODED: verify on patch updates — the thorns formula exists only in
# the cached W description prose ("enemies that use a basic attack
# on-hit against Rammus are dealt 15 (+ 10% total armor) (+ 10% total
# magic resistance) magic damage"); there is no leveling row for it.
_THORNS_BASE = 15.0
_THORNS_ARMOR_RATIO = 0.10
_THORNS_MAGIC_RESISTANCE_RATIO = 0.10

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Rammus")


def _defensive_ball_curl(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the thorns damage per enemy basic attack during the stance."""
    ability = ctx.ability("W")
    if ability is None:
        return None
    rank = ctx.rank_for("W")
    if rank < 1:
        return None
    autos = min(max(int(ctx.options.get("w_thorns_autos", 0)), 0), 30)
    armor = float(ctx.stats.get("armor", 0.0) or 0.0)
    magic_resistance = float(ctx.stats.get("magic_resistance", 0.0) or 0.0)
    per_auto = (
        _THORNS_BASE
        + _THORNS_ARMOR_RATIO * armor
        + _THORNS_MAGIC_RESISTANCE_RATIO * magic_resistance
    )
    total = per_auto * autos
    entry = damage_entry(
        "Defensive Ball Curl (thorns)",
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", per_auto, count=max(autos, 1)),)
    entry["detail"] = (
        f"thorns: {per_auto:.2f} magic damage per enemy basic attack "
        f"(15 + 10% total armor ({armor:.1f}) + 10% total magic "
        f"resistance ({magic_resistance:.1f})) x {autos} auto(s) that hit "
        "Rammus during the stance; the stance's bonus armor/MR rows are "
        "the defensive buff, not damage"
    )
    return entry


SLOTS = dict(SLOTS)
SLOTS["W"] = _defensive_ball_curl
parse_abilities = build_parser(SLOTS, "Rammus")

OPTIONS = list(OPTIONS) + [
    {
        "key": "w_thorns_autos",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 30,
        "label": "Enemy basic attacks during Defensive Ball Curl",
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Defensive Ball Curl) prices the thorns damage — 15 + 10% total "
    "armor + 10% total magic resistance magic damage per enemy basic "
    "attack that hits Rammus during the stance (cached W description "
    "prose; there is no leveling row). The fight engine has no "
    "incoming-auto hook, so w_thorns_autos is the explicit count of "
    "enemy autos (0 = none). The reviewed packet's misread of the "
    "'Bonus Armor' row as magic damage is removed; the stance's bonus "
    "armor/MR rows are the defensive buff and remain state.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
