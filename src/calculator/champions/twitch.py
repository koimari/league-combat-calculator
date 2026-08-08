"""Twitch — slot map for the archetype engine (E3 stack systems).

Why each slot is non-generic:
- P (Deadly Venom) is the stack system: basic attacks apply stacks (max
  6, 6s, refreshing); each stack deals level-scaled TRUE damage over the
  duration. The wiki carries the per-stack totals only in prose
  ("6 / 12 / 18 / 24 / 30 (based on level) (+ 18% AP) total true damage
  over the duration"), so the breakpoints live here as module constants
  (the Akshan/Braum prose-value precedent). The DoT is priced once per
  fight from the ``poison_stacks`` option (default 6 = sourced max).
- E (Contaminate) is the DETONATION: base physical damage plus, for
  each Deadly Venom stack, "Physical Damage Per Stack" physical (+35%
  bonus AD) and 35%-AP magic damage (prose ratio). The reviewed packet
  priced only the base row, losing the entire per-stack scaling.
- R (Spray and Pray) is a BUFF, not a damage packet: it grants 30/45/60
  bonus attack damage for 6 seconds. The reviewed packet priced that AD
  as if it were direct damage; the stat_buff (Vayne R precedent) makes
  autos and E's %bonus-AD stack term parse against the buffed stat.
- Q (Ambush) and W (Venom Cask) deal no direct damage: Q is stealth +
  attack speed, W is a slow zone that applies poison stacks (covered by
  the pre-stack option). Both emit zero-damage rows.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    stat_buff,
)
from .source_receipts import load_champion_sources

# HARDCODED: verify on patch updates — wiki prose, not in the JSON.
# Deadly Venom per-stack total true damage over 6 seconds by level
# breakpoint (1/6/11/16) and its AP ratio; Contaminate's per-stack 35%
# AP magic damage; the sourced stack cap.
_POISON_MAX_STACKS = 6
_POISON_TOTAL_BREAKPOINTS = (6.0, 12.0, 18.0, 24.0, 30.0)
_POISON_BREAKPOINT_LEVELS = (1, 6, 11, 16, 18)
_POISON_AP_RATIO = 0.18  # (+ 18% AP) total per stack
_E_MAGIC_AP_RATIO = 0.35  # "and 35% AP magic damage for each stack"


def _poison_stacks(options: dict[str, Any]) -> int:
    return min(
        _POISON_MAX_STACKS,
        max(0, int(options.get("poison_stacks", _POISON_MAX_STACKS))),
    )


def _poison_total_per_stack(level: int, ap: float) -> float:
    """One stack's full 6s true damage at a champion level."""
    base = _POISON_TOTAL_BREAKPOINTS[-1]
    for min_level, value in zip(_POISON_BREAKPOINT_LEVELS, _POISON_TOTAL_BREAKPOINTS):
        if level >= min_level:
            base = value
    return base + _POISON_AP_RATIO * ap


def _deadly_venom(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the poison DoT priced once per fight at the stack option."""
    ability = ctx.ability()
    if ability is None:
        return None
    stacks = _poison_stacks(ctx.options)
    if stacks <= 0:
        return None
    per_stack = _poison_total_per_stack(ctx.level, ctx.stats.get("ability_power", 0.0))
    total = per_stack * stacks
    return {
        "name": ability.get("name", "Deadly Venom"),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "true",
        "total_raw": total,
        "parts": (DamagePart("true", per_stack, count=stacks),),
        "proc_count": 1,
        # Every tick is ability damage for 6s past the last application,
        # so item burns stay refreshed through the poison tail.
        "dot_duration": 6.0,
        "dot_tick_interval": 1.0,
        # One sourced event per fight: the poison packet is priced once
        # from the poison_stacks option.  The declared event is placed at
        # the fight-window end — the engine's end-of-rotation fallback
        # this ledger replaces — so ordering-certifying the row does not
        # move its ledger position and cannot change window-order item
        # outcomes (e.g. Shadowflame's threshold).  damage.py re-prices
        # the declared event at the proc's mitigated total, keeping the
        # ledger sum exactly equal to the row's total.
        "event_phase": "effect",
        "damage_events": [
            {
                "time": float(ctx.options.get("fight_duration_seconds", 0.0) or 0.0),
                "damage_type": "true",
                "damage": total,
                "event_precision": "phase_order",
            }
        ],
        "detail": (
            f"{stacks} Deadly Venom stack(s) x {per_stack:.2f} total true "
            "damage per stack over 6s"
        ),
    }


def _contaminate(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: base + per-stack physical (+35% bonus AD) + per-stack 35% AP magic."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    base = extract_named(ability, "Base Physical Damage", rank, ctx.stats, ctx.target)
    per_stack = extract_named(
        ability, "Physical Damage Per Stack", rank, ctx.stats, ctx.target
    )
    stacks = _poison_stacks(ctx.options)
    physical = base + per_stack * stacks
    magic = _E_MAGIC_AP_RATIO * ctx.stats.get("ability_power", 0.0) * stacks

    entry = damage_entry(
        ability.get("name", "Contaminate"),
        rank,
        extract_cooldown(ability, rank),
        physical + magic,
        "mixed",
    )
    entry["parts"] = (
        # Both damage types land at the detonation boundary: the sourced
        # per-stack terms are consumed at the cast, so each part authors
        # its hit at time_offset 0.0 (the coverage classifier certifies
        # "hit"-precision events instead of downgrading the row coarse).
        DamagePart("physical", physical, time_offset=0.0),
        DamagePart("magic", magic, time_offset=0.0),
    )
    entry["event_order_certified"] = "single_hit"
    entry["detail"] = f"{stacks} Deadly Venom stack(s) consumed"
    return entry


def _ambush(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: stealth and attack speed — no enemy damage."""
    ability = ctx.ability()
    if ability is None:
        return None
    return {
        "name": ability.get("name", "Ambush"),
        "rank": ctx.rank_for(),
        "cooldown": extract_cooldown(ability, ctx.rank_for()),
        "damage_type": "physical",
        "total_raw": 0.0,
        "parts": (),
        "detail": (
            "Camouflage and post-stealth attack speed: self buffs only, "
            "no enemy damage."
        ),
    }


def _venom_cask(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: slow zone that applies poison stacks — no direct damage."""
    ability = ctx.ability()
    if ability is None:
        return None
    return {
        "name": ability.get("name", "Venom Cask"),
        "rank": ctx.rank_for(),
        "cooldown": extract_cooldown(ability, ctx.rank_for()),
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "detail": (
            "Contaminated zone applies Deadly Venom stacks and slows; "
            "stack applications are covered by the poison_stacks option."
        ),
    }


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "poison_stacks",
        "type": "int",
        "default": _POISON_MAX_STACKS,
        "min": 0,
        "max": _POISON_MAX_STACKS,
        "label": (
            "Deadly Venom stacks on the target when the fight opens "
            "(6 = fully stacked)"
        ),
    },
]

ASSUMPTIONS = [
    "Deadly Venom stacks come from the poison_stacks option (default 6 "
    "= the sourced max); each stack deals its full 6-second total of "
    "level-scaled true damage (6/12/18/24/30 by level + 18% AP — wiki "
    "prose, module constants) once per fight",
    "E (Contaminate) detonates all stacks: base physical + stacks x "
    "per-stack physical (+35% bonus AD) + stacks x 35% AP magic",
    "R (Spray and Pray) is a 6s bonus-AD buff (+30/45/60 by rank) that "
    "raises autos and E's %bonus-AD stack term — modeled as a BUFF-phase "
    "stat_buff, not direct damage",
    "The auto-attack rate that applies poison in a real fight is not "
    "modeled (stack rate is the option); the fight's own autos still "
    "deal their base AD damage",
    "Q (Ambush) stealth/attack speed and W (Venom Cask) slow are "
    "utility-only zero-damage rows; W's in-zone stack applications are "
    "covered by the poison_stacks option",
    "The 40% bonus attack speed from Q's post-stealth buff is not "
    "applied to the auto count",
]

SLOTS = {
    "R": stat_buff(
        "Bonus Attack Damage",
        "bonus_attack_damage",
        apply_to=("attack_damage", "bonus_attack_damage"),
    ),
    "Q": _ambush,
    "W": _venom_cask,
    "E": _contaminate,
    "P": _deadly_venom,
}

parse_abilities = build_parser(SLOTS, "Twitch")

MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "E", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

SOURCES = load_champion_sources("Twitch")
