"""Kindred — Mark of the Kindred and Mounting Dread (3-stack) systems.

Stack mechanics modeled (E3):
- P (Mark of the Kindred): takedowns on hunted targets collect Marks.
  Marks grant 75 : 250 (based on marks) bonus basic-attack range,
  +5% attack speed per mark on Q, and scale E's missing-health term
  (+0.5% per mark).  ``marks`` is the explicit pre-stack state.
- E (Mounting Dread): the active shot marks the target; basic attacks
  against the marked target apply stacks (cap 3).  The third stack
  directs Wolf to pounce, consuming all stacks to deal the sourced
  "Additional Physical Damage" (80 : 200 by rank + 100% bonus AD + 5%
  (+ 0.5% per Mark) of the target's missing health), increased by up to
  50% based on critical strike chance (wiki prose).  ``e_stacks`` is
  the explicit pre-stack state; the pounce is priced at 3 stacks.

Q (Dance of Arrows) and R (Lamb's Respite) keep the reviewed CP10.3
packet pricing.  W (Wolf's Frenzy) is the E4 summon row: Wolf's frenzy
attacks price the sourced "Magic Damage" leveling with the full
per-Mark current-health term (+1% per Mark, resolved via the same
modifier override Mounting Dread uses), over ``w_attacks`` attacks
(Wolf attacks at 25% of Kindred's bonus attack speed; the count is the
player-controlled option, default 3 attacks in the window).
"""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .reviewed_batch_01 import no_damage
from .reviewed_batch_03 import build_batch_module
from .slotlib import (
    damage_entry,
    extract_cooldown,
    find_named_leveling,
    sum_modifiers,
)

_BATCH_PARSE, _BATCH_SLOTS, _BATCH_ASSUMPTIONS, _BATCH_SOURCES, _BATCH_OPTIONS = (
    build_batch_module("Kindred")
)
_MARK_MAX = 25
_E_STACK_MAX = 3

# HARDCODED: verify on patch updates — wiki prose, not in the JSON.
# Mounting Dread's third-stack pounce "increased by 0% : 50% (+ 0% :
# 15%) (based on critical strike chance)" (the Akshan-R / Caitlyn-R
# crit_effectiveness precedent).
_E_POUNCE_CRIT_EFFECTIVENESS = 0.5


def _marks(ctx: SlotCtx) -> int:
    return min(max(int(ctx.options.get("marks", 0)), 0), _MARK_MAX)


def _mark_of_the_kindred(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: Mark state row (bonus range, Q AS, E missing-health scaling)."""
    ability = ctx.ability()
    if ability is None:
        return None
    marks = _marks(ctx)
    return no_damage(
        ctx,
        name=ability.get("name", "Mark of the Kindred"),
        reason=(
            f"{marks} Mark(s) of the Kindred: 75 : 250 (based on marks) "
            "bonus basic-attack range, +5% attack speed per mark on Q, "
            "and +0.5% per mark on E's missing-health term are state/"
            "scaling; the hunt target selection is state."
        ),
    )


def _mounting_dread(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: Mounting Dread — third-stack Wolf pounce."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    stacks = min(max(int(ctx.options.get("e_stacks", 3)), 1), _E_STACK_MAX)
    if stacks < _E_STACK_MAX:
        return no_damage(
            ctx,
            name=ability.get("name", "Mounting Dread"),
            reason=(
                f"{stacks}/3 Mounting Dread stacks on the marked target; "
                "the third stack directs Wolf to pounce (consuming all "
                "stacks) — set e_stacks to 3 to price the pounce."
            ),
        )

    marks = _marks(ctx)
    leveling = find_named_leveling(ability, "Additional Physical Damage")
    if leveling is None:
        return None

    def per_mark_override(unit: str, value: float) -> float | None:
        """Kindred E's missing-health modifier: 5% (+ 0.5% per Mark)."""
        if "of target's missing health" not in unit:
            return None
        percent = value + 0.5 * marks
        missing = float(ctx.target.get("target_missing_health", 0.0) or 0.0)
        return percent / 100.0 * missing

    damage = sum_modifiers(
        leveling, rank, ctx.stats, ctx.target, modifier_override=per_mark_override
    )
    entry = damage_entry(
        ability.get("name", "Mounting Dread"),
        rank,
        extract_cooldown(ability, rank),
        damage,
        "physical",
    )
    entry["parts"] = (
        DamagePart(
            "physical",
            damage,
            crit_effectiveness=_E_POUNCE_CRIT_EFFECTIVENESS,
        ),
    )
    entry["target_max_health_sensitive"] = True
    entry["detail"] = (
        f"Third-stack Wolf pounce at {stacks}/3 stacks: {damage:.2f} "
        "physical (80 : 200 by rank + 100% bonus AD + 5% (+0.5% per "
        f"Mark) of missing health at {marks} mark(s)); the pounce "
        "consumes all stacks."
    )
    return entry


def _wolfs_frenzy(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: Wolf's Frenzy — Wolf basic attacks over the fight window.

    Wolf's attacks are magic and the rate scales with 25% of Kindred's
    bonus attack speed (wiki prose); the zone lasts 8.5 seconds.  The
    attack COUNT is the player-controlled ``w_attacks`` option (default
    3).  The per-Mark current-health term (1.5% + 1% per Mark) resolves
    through the same modifier override Mounting Dread uses, so the
    sourced formula prices exactly.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    attacks = min(max(int(ctx.options.get("w_attacks", 3)), 1), 8)
    marks = _marks(ctx)
    leveling = find_named_leveling(ability, "Magic Damage")
    if leveling is None:
        return None

    def per_mark_override(unit: str, value: float) -> float | None:
        """Wolf's current-health modifier: 1.5% (+ 1% per Mark)."""
        if "of target's current health" not in unit:
            return None
        percent = value + 1.0 * marks
        current = float(ctx.target.get("target_current_health", 0.0) or 0.0)
        return percent / 100.0 * current

    per = sum_modifiers(
        leveling, rank, ctx.stats, ctx.target, modifier_override=per_mark_override
    )
    entry = damage_entry(
        ability.get("name", "Wolf's Frenzy"),
        rank,
        0.0,
        per * attacks,
        "magic",
    )
    entry["parts"] = (
        DamagePart("magic", per, count=attacks, time_offset=0.5, hit_interval=1.0),
    )
    entry["target_max_health_sensitive"] = True
    entry["detail"] = (
        f"Wolf attacks {attacks} time(s) for {per:.2f} magic each (25 : 45 by "
        f"rank + 20% bonus AD + 20% AP + 1.5% (+1% per Mark) of current health "
        f"at {marks} mark(s)); Wolf attack speed scales with 25% of Kindred's "
        "bonus attack speed and the 8.5s zone duration are state"
    )
    return entry


SLOTS = {
    "P": _mark_of_the_kindred,
    "Q": _BATCH_SLOTS["Q"],
    "W": _wolfs_frenzy,
    "E": _mounting_dread,
    "R": _BATCH_SLOTS["R"],
}
parse_abilities = build_parser(SLOTS, "Kindred")

OPTIONS = [
    {
        "key": "marks",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 25,
        "label": "Mark of the Kindred stacks",
    },
    {
        "key": "w_attacks",
        "type": "int",
        "default": 3,
        "min": 1,
        "max": 8,
        "label": "Wolf attacks (W)",
    },
    {
        "key": "e_stacks",
        "type": "int",
        "default": 3,
        "min": 1,
        "max": 3,
        "label": "Mounting Dread stacks (3 = pounce)",
    },
]

ASSUMPTIONS = [
    "Mark of the Kindred stacks (0-25) grant bonus range (75 : 250), Q "
    "attack speed (+5% per mark) and E missing-health scaling (+0.5% per "
    "mark); takedown collection is state",
    "Mounting Dread marks for 4 seconds and stacks on basic attacks (cap "
    "3); the third stack fires the Wolf pounce, consuming all stacks — "
    "e_stacks is the explicit pre-stack state (3 prices the pounce)",
    "The pounce is the sourced Additional Physical Damage (+ 100% bonus "
    "AD + missing-health term), amplified up to 50% by critical strike "
    "chance (crit_effectiveness 0.5, wiki prose)",
    "W (Wolf's Frenzy) prices the sourced Magic Damage leveling over "
    "w_attacks Wolf attacks, including the per-Mark current-health term "
    "(1.5% + 1% per Mark); the zone duration and 25%-of-bonus-AS rate are "
    "state (attack count is the player-controlled option)",
    "R (Lamb's Respite) is the reviewed no-damage packet",
]

SOURCES = _BATCH_SOURCES
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "W", "E"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
