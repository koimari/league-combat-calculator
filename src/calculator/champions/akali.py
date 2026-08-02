"""Akali — slot map for the archetype engine.

Why each slot is non-generic:
- P (Assassin's Mark) is a per-level empowered-auto proc with a
  user-configurable proc count (``passive_procs``) — the proc_damage
  archetype.
- E (Shuriken Flip) is two hits (throw + dash); "Total Magic Damage"
  captures both.
- R (Perfect Execution) is a custom two-part slot: a flat R1 dash part
  plus an R2 execute part whose ``hp_scaled_damage`` closure interpolates
  min→max with the target's missing HP — the engine evaluates it against
  the HP remaining after R1 and earlier casts in the rotation.
- W (Twilight Shroud) is a zero-damage resource event: it restores energy
  and temporarily raises Akali's maximum energy.

All numeric values are read from the champion JSON data.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import (
    extract_cooldown,
    extract_named,
    extract_value,
    proc_damage,
    simple_damage,
)


def _twilight_shroud(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: emit the sourced energy restore and temporary maximum increase."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    duration = extract_value(ability, "Shroud Duration", rank)
    return {
        "name": ability.get("name", "Twilight Shroud"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "parts": (),
        "total_raw": 0.0,
        # Wiki revision 4007406: restores 100 energy and raises maximum
        # energy by 100 while the rank-scaled shroud remains active.
        "resource_restore": 100.0,
        "resource_maximum_bonus": 100.0,
        "resource_maximum_bonus_duration": duration,
        "detail": "Restores 100 energy and raises maximum energy by 100",
    }


def _assassins_mark_damage(ctx: SlotCtx, ability: dict[str, Any]) -> float:
    """Resolve one Assassin's Mark proc from per-level JSON scaling."""
    return extract_named(
        ability,
        "Bonus Magic Damage",
        ctx.level,
        ctx.stats,
        ctx.target,
    )


def _perfect_execution(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: R1 dash damage plus R2 execute bounds for missing-HP scaling."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    r1_damage = extract_named(ability, "Magic Damage", rank, ctx.stats)
    r2_min = extract_named(ability, "Minimum Magic Damage", rank, ctx.stats)
    r2_max = extract_named(ability, "Maximum Magic Damage", rank, ctx.stats)

    # R1 is flat; R2 interpolates min→max with the target's missing HP
    # at cast time — the part's closure sees HP after R1 lands because
    # the engine threads running damage through parts in order.
    span = r2_max - r2_min
    return {
        "name": ability.get("name", "Perfect Execution"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": r1_damage + r2_max,
        "parts": (
            DamagePart("magic", r1_damage, time_offset=0.25),
            DamagePart(
                "magic",
                hp_scaled_damage=lambda missing: r2_min + span * missing,
                # The Wiki documents a 2.5-second static recast lockout;
                # include the 0.25-second cast start so R2 is ordered after
                # R1 in the shared event ledger rather than collapsing both
                # hits into one cast-boundary row.
                time_offset=2.75,
            ),
        ),
    }


OPTIONS = [
    {
        "key": "passive_procs",
        "type": "int",
        "default": 4,
        "label": "Passive procs",
        "min": 0,
        "max": 20,
    },
]

ASSUMPTIONS = [
    "E always hits both shuriken and recast dash",
    "R always hits both R1 dash and R2 execute",
    "R2 damage scales with target missing HP from prior abilities",
]

SLOTS = {
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "W": _twilight_shroud,
    "E": simple_damage(attr="Total Magic Damage", dmg_type="magic"),
    "R": _perfect_execution,
    "P": proc_damage(
        per_proc=_assassins_mark_damage,
        dmg_type="magic",
        count_option="passive_procs",
        phase_order_events=True,
    ),
}

parse_abilities = build_parser(SLOTS, "Akali")
