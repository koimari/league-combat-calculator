"""Akali — slot map for the archetype engine.

Why each slot is non-generic:
- P (Assassin's Mark) is a per-level empowered-auto proc with a
  user-configurable proc count (``passive_procs``) — the proc_damage
  archetype.
- E (Shuriken Flip) is two hits (throw + dash); "Total Magic Damage"
  captures both.
- R (Perfect Execution) is a custom two-cast slot: R1 dash plus an R2
  execute that scales 0-200% with target missing HP. The entry carries
  ``r2_min``/``r2_max``/``missing_hp_scaling`` so damage.py can compute
  R2 from the HP remaining after earlier casts in the rotation.
- W (Twilight Shroud) deals no damage and is absent from the slot map.

All numeric values are read from the champion JSON data.
"""

from typing import Any

from .engine import SlotCtx, build_parser
from .slotlib import (
    build_stats_context,
    extract_cooldown,
    extract_named,
    proc_damage,
    simple_damage,
)


def _parse_passive_damage(
    passive: dict[str, Any],
    level: int,
    champion_stats: dict[str, float] | None = None,
    total_ability_power: float = 0.0,
) -> float:
    """Per-proc passive damage at a champion level.

    Thin seam over the same extraction the P slot's proc_damage
    archetype performs ("Bonus Magic Damage" holds per-level base values
    plus bonus-AD/AP scaling modifiers); kept because tests exercise the
    passive numbers directly against the wiki.
    """
    stats = build_stats_context(champion_stats, total_ability_power)
    return extract_named(passive, "Bonus Magic Damage", level, stats)


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

    # magic_damage is R1 only; total_raw shows the R1 + R2-max upper
    # bound. damage.py resolves actual R2 from missing HP at cast time.
    return {
        "name": ability.get("name", "Perfect Execution"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "magic_damage": r1_damage,
        "total_raw": r1_damage + r2_max,
        "r2_min": r2_min,
        "r2_max": r2_max,
        "missing_hp_scaling": True,
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
    "E": simple_damage(attr="Total Magic Damage", dmg_type="magic"),
    "R": _perfect_execution,
    "P": proc_damage(
        attr="Bonus Magic Damage", dmg_type="magic", count_option="passive_procs"
    ),
}

parse_abilities = build_parser(SLOTS, "Akali")
