"""Sett — Pit Grit right-punch combo system.

Stack mechanics modeled (E3):
- P (Pit Grit): Sett's basic attacks alternate between a Left Punch and
  a Right Punch on-attack.  The Right Punch is the combo's empowered
  hit: it gains 50 bonus range, attacks at 8x the Left Punch's attack
  speed, and deals bonus physical damage equal to 5 : 100 (based on
  level) (+ 55% bonus AD).  ``p_right_punches`` is the explicit count
  of Right Punches in the fight window (each auto stream alternates, so
  roughly half of the autos are Right Punches); 0 prices the state row.

Q (Knuckle Down), W (Haymaker), E (Facebreaker) and R (The Show
Stopper) keep the reviewed CP10.7 packet pricing. All numeric values
are read from the champion JSON data; the 55% bonus AD ratio is wiki
prose (the leveling array holds only the per-level flat value).
"""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .reviewed_batch_01 import no_damage
from .reviewed_batch_07 import _full_entry_sources, build_batch_module
from .slotlib import extract_named

_BATCH_PARSE, _BATCH_SLOTS, _BATCH_ASSUMPTIONS, _BATCH_SOURCES, _BATCH_OPTIONS = (
    build_batch_module("Sett")
)

# HARDCODED: verify on patch updates — wiki prose, not in the JSON.
# Pit Grit's Right Punch: "deal 5 : 100 (based on level) (+ 55% bonus
# AD) bonus physical damage"; the leveling array holds the flat part.
_RIGHT_PUNCH_BONUS_AD_RATIO = 0.55


def _pit_grit(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: alternating-punch combo — Right Punch bonus physical damage."""
    ability = ctx.ability()
    if ability is None:
        return None
    punches = min(max(int(ctx.options.get("p_right_punches", 0)), 0), 30)
    if punches <= 0:
        return no_damage(
            ctx,
            name=ability.get("name", "Pit Grit"),
            reason=(
                "Heavy Hands alternates Left and Right punches; the Right "
                "Punch deals the sourced bonus physical damage — set "
                "p_right_punches to price it (0 = no Right Punches)."
            ),
        )
    flat = extract_named(ability, "Per-Level Scaling", ctx.level)
    bonus_ad = float(ctx.stats.get("bonus_attack_damage", 0.0))
    per_punch = flat + _RIGHT_PUNCH_BONUS_AD_RATIO * bonus_ad
    total = per_punch * punches
    return {
        "name": ability.get("name", "Pit Grit"),
        "damage_type": "physical",
        "total_raw": total,
        "parts": (DamagePart("physical", per_punch, basic_damage=True),),
        "proc_count": punches,
        "detail": (
            f"{punches} Right Punch(es) x {per_punch:.2f} bonus physical "
            f"damage (5 : 100 by level + 55% bonus AD); the 8x Right "
            "Punch attack speed is state."
        ),
    }


SLOTS = {
    "P": _pit_grit,
    "Q": _BATCH_SLOTS["Q"],
    "W": _BATCH_SLOTS["W"],
    "E": _BATCH_SLOTS["E"],
    "R": _BATCH_SLOTS["R"],
}
parse_abilities = build_parser(SLOTS, "Sett")

OPTIONS = [
    {
        "key": "p_right_punches",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 30,
        "label": "Right Punch count (Pit Grit combo)",
    },
]

ASSUMPTIONS = [
    "Pit Grit's combo alternates Left and Right punches on-attack; the "
    "Right Punch deals the sourced bonus physical damage (5 : 100 by "
    "level + 55% bonus AD) and is priced per p_right_punches",
    "The fight model does not auto-derive Right Punch count from the "
    "auto stream (each attack alternates); p_right_punches is the "
    "explicit pre-stack state",
    "The Right Punch's 8x attack speed and 50 bonus range are state",
    "Q/W/E/R damage keep the reviewed CP10.7 packet pricing",
]

SOURCES = _full_entry_sources("Sett")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
