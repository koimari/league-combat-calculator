"""Lux — CP10.4 full-entry-reviewed packet module.

P1-3 closures:

- P (Illumination): the reviewed packet declared the passive no_damage,
  but the wiki carries a sourced proc formula: "Lux's basic attacks
  on-hit and Final Spark consume the mark to deal 30 : 200 (based on
  level) (+ 35% AP) bonus magic damage" (data/champions.json P
  "Per-Level Scaling", 30-200 over levels 1-18).  Each marking ability
  (Q/E/R) lets the next auto (or Final Spark itself) consume the mark,
  so the P slot prices ``p_illumination_procs`` procs (default 3 — one
  per Q/E/R in the one-rotation combo), each at the sourced per-level
  amount.

- W (Prismatic Barrier): Lux "gains the shield upon throwing and upon
  retrieving the wand", so one cast stacks two shields of "Shield
  Strength" (40-100 + 40% AP by rank) into the sourced "Maximum Shield"
  row (80-200 + 80% AP).  The shield is a self-targeted support packet:
  support_effects.py prices "Maximum Shield" at the W cast with a
  self scope override (no teammate roster in the 1v1).
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .reviewed_batch_04 import build_batch_module
from .slotlib import (
    damage_entry,
    find_named_leveling,
    sum_modifiers,
)

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Lux")

# Default Illumination procs in a one-rotation combo: Q, E and R each
# mark the target, and the following auto/Final Spark consumes the mark.
_P_ILLUMINATION_DEFAULT_PROCS = 3


def _illumination(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: Illumination — post-ability autos deal 30 : 200 + 35% AP magic."""
    ability = ctx.ability()
    if ability is None:
        return None
    level = ctx.level
    leveling = find_named_leveling(ability, "Per-Level Scaling")
    if leveling is None:
        raise ValueError(
            "Lux P: 'Per-Level Scaling' leveling entry missing from the "
            "ability JSON — cannot compute the Illumination proc"
        )
    per_proc = sum_modifiers(leveling, level, ctx.stats, ctx.target)
    count = max(
        0, int(ctx.options.get("p_illumination_procs", _P_ILLUMINATION_DEFAULT_PROCS))
    )
    if count <= 0:
        return None
    entry = damage_entry(
        ability.get("name", "Illumination"),
        level,
        0.0,
        per_proc * count,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", per_proc),)
    entry["proc_count"] = count
    entry["detail"] = (
        f"{count} Illumination proc(s): 30 : 200 (based on level) "
        f"({per_proc:g} at level {level}) + 35% AP bonus magic damage "
        "per post-ability auto / Final Spark"
    )
    return entry


SLOTS = dict(SLOTS)
SLOTS["P"] = _illumination
parse_abilities = build_parser(SLOTS, "Lux")

OPTIONS = list(OPTIONS) + [
    {
        "key": "p_illumination_procs",
        "type": "int",
        "default": _P_ILLUMINATION_DEFAULT_PROCS,
        "min": 0,
        "max": 12,
        "label": (
            "Illumination procs in the fight (each post-ability auto / "
            "Final Spark consumes one mark)"
        ),
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Illumination) prices the sourced per-level proc (30 : 200 based "
    "on level, + 35% AP) from the p_illumination_procs option (default 3 "
    "— one per Q/E/R mark in the one-rotation combo); each proc is one "
    "post-ability auto or Final Spark consuming the mark.",
    "W (Prismatic Barrier) shields Lux twice per cast (on throw and on "
    "return), stacking into the sourced 'Maximum Shield' row (80-200 + "
    "80% AP at rank 5); support_effects.py emits it as a self-targeted "
    "shield at the cast (Lux gains the shield herself; the allied half "
    "needs a teammate roster).",
]

MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "E", "R", "W"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
