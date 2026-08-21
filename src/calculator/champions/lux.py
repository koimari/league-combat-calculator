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
from .engine import SlotCtx
from .packet_module import build_packet_module
from .slotlib import (
    damage_entry,
    find_named_leveling,
    sum_modifiers,
)

PACKET_SHA256 = "2f20b99c3cd6919e7b81d1fb0cf912d9e02ea8ac475c4c4fa6381bc332407130"


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
    # Illumination procs ride the post-ability autos / Final Spark: the
    # proc event lands at the consuming hit boundary, so the part carries an
    # authored time_offset 0.0 (hit precision, Viego R pattern) — without it
    # the row emits no hit event and the coverage classifier downgrades it
    # coarse, withholding the champion from optimizer certification.
    entry["parts"] = (DamagePart("magic", per_proc),)
    entry["proc_count"] = count
    # Each proc is consumed by the next post-ability auto / Final Spark.
    # Declare the fixed-count ledger (Diana passive precedent) so the row is
    # event-ordered instead of phase-order coarse: one exact event per proc,
    # spaced at the authored auto cadence when the engine supplies auto
    # timestamps, else stamped at the cast boundary.
    # The one-rotation ledger stamps each proc at the cast boundary; the
    # sequence field preserves their order relative to the marking casts.
    entry["damage_events"] = [
        {
            "time": 0.0,
            "damage_type": "magic",
            "damage": per_proc,
            "event_precision": "exact",
        }
        for _ in range(count)
    ]
    entry["event_phase"] = "effect"
    entry["detail"] = (
        f"{count} Illumination proc(s): 30 : 200 (based on level) "
        f"({per_proc:g} at level {level}) + 35% AP bonus magic damage "
        "per post-ability auto / Final Spark"
    )
    return entry


# Cached kit review: Q's sphere "root[s] them for 2 seconds", E's
# singularity slows the enemies inside it and its detonation slows the
# ones it hits, and R's beam only damages and reveals.  W shields allies
# and P's proc is a bonus-damage mark, neither applying control.
MODULE_CC = {"Q": "root", "E": "slow", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Lux",
    PACKET_SHA256,
    # Light Binding's sphere, Lucent Singularity's detonation and Final
    # Spark's beam each deal their packet once, at the cast — the boundary
    # claim that carries MODULE_CC's reviewed answers into the ledger.
    single_hit_slots=frozenset({"Q", "E", "R"}),
    slot_parsers={
        "P": _illumination,
    },
    cc_kinds=MODULE_CC,
)

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
