"""Mel — CP10.4 full-entry-reviewed packet module.

E5-2 fixes:

- W (Rebuttal): the reviewed spec read "Replicated Projectile Magic
  Damage Modifier" (40-60% + 5% per 100 AP) as FLAT magic damage.  That
  attribute is a percentage of the ORIGINAL enemy projectile's damage;
  the calculator models no enemy projectile source, so the slot prices
  no damage (shield + conditional reflection are state, documented).

- R (Golden Eclipse): the reviewed spec read only the flat "Magic
  Damage" row (125/200/275 + 30% AP) and dropped the per-Overwhelm-
  stack term.  The wiki row's third modifier is "(4/7/10 + 4% AP) per
  Overwhelm stack on the target" (data/champions.json R "Magic
  Damage"), and P's Overwhelm prose says Mel applies a stack for each
  damage instance.  R now prices the flat row PLUS the per-stack term
  times an explicit ``r_overwhelm_stacks`` option (default 3 — the
  Overwhelm stacks accumulated before the blast in a one-rotation
  combo).  The P stored-damage execute (first stack stores
  50/60/70/80 + 10% AP, +2/3/4/5 + 0.75% AP per additional stack,
  consumed when the stored total exceeds the target's current health)
  is a kill-boundary execute and is documented, not priced as damage.
"""

from .reviewed_batch_04 import build_batch_module
from .engine import SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
)

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Mel")

# Default Overwhelm stacks the blast detonates in a one-rotation combo.
# P prose: "Mel's basic attacks and abilities apply a stack of Overwhelm
# for each instance of damage they deal"; Q alone fires 10 bolts, so a
# modest 3-stack default is conservative and user-tunable.
_R_DEFAULT_OVERWHELM_STACKS = 3
# The per-stack term's fixed AP ratio: " (+ 4% AP) per Overwhelm stack".
_R_PER_STACK_AP_RATIO = 0.04


def _rebuttal(ctx: SlotCtx):
    """W: shield + conditional projectile reflection — no modeled damage.

    Rebuttal reflects enemy projectiles at 40-60% (+ 5% per 100 AP) of
    their ORIGINAL damage; with no enemy projectile source in the
    calculator, pricing the modifier as flat damage would invent damage.
    """
    ability = ctx.ability("W", 0)
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    return {
        "name": ability.get("name", "Rebuttal"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "detail": (
            "Rebuttal shields Mel and reflects enemy projectiles at "
            "40-60% (+ 5% per 100 AP) of their original damage; no enemy "
            "projectile source is modeled, so the slot prices no damage."
        ),
    }


def _golden_eclipse(ctx: SlotCtx):
    """R: flat Magic Damage row + (4/7/10 + 4% AP) per Overwhelm stack."""
    ability = ctx.ability("R", 0)
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    # The wiki's "Magic Damage" row: flat + 30% AP + per-stack term.  The
    # per-stack unit (" (+ 4% AP) per Overwhelm stack on the target") is
    # not a generic scaling unit, so the flat+AP share comes from the row
    # and the per-stack share is priced explicitly below.
    flat_share = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    per_stack = extract_value(ability, "Magic Damage", rank, modifier_index=2)
    per_stack += _R_PER_STACK_AP_RATIO * float(
        ctx.stats.get("ability_power", 0.0) or 0.0
    )
    stacks = int(ctx.options.get("r_overwhelm_stacks", _R_DEFAULT_OVERWHELM_STACKS))
    stacks = max(0, min(stacks, 50))
    total = flat_share + per_stack * stacks
    entry = damage_entry(
        ability.get("name", "Golden Eclipse"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["detail"] = (
        f"{flat_share:g} flat + {per_stack:g} per Overwhelm stack x "
        f"{stacks} stack(s)"
    )
    return entry


SLOTS = dict(SLOTS)
SLOTS["W"] = _rebuttal
SLOTS["R"] = _golden_eclipse
parse_abilities = build_parser(SLOTS, "Mel")

OPTIONS = list(OPTIONS) + [
    {
        "key": "r_overwhelm_stacks",
        "type": "int",
        "default": _R_DEFAULT_OVERWHELM_STACKS,
        "label": "Overwhelm stacks on the target when Golden Eclipse detonates",
        "min": 0,
        "max": 50,
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Rebuttal) prices no damage: the 'Replicated Projectile Magic "
    "Damage Modifier' (40-60% + 5% per 100 AP) is a percentage of the "
    "original enemy projectile's damage, and the calculator models no "
    "enemy projectile source (data/champions.json W).",
    "R (Golden Eclipse) prices the wiki's 'Magic Damage' row "
    "(125/200/275 + 30% AP) plus (4/7/10 + 4% AP) per Overwhelm stack "
    "on the target (data/champions.json R), with the stack count from "
    "the r_overwhelm_stacks option (default 3).",
    "The Overwhelm stored-damage execute (P: first stack stores "
    "50/60/70/80 + 10% AP, +2/3/4/5 + 0.75% AP per additional stack, "
    "consumed when stored damage exceeds the target's current health "
    "and shields) is a kill boundary and is documented, not priced as "
    "damage.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
