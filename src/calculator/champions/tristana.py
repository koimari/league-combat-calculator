"""Tristana — slot map for the archetype engine (E3 stack systems).

Why each slot is non-generic:
- E (Explosive Charge) is the stack system: the charge attaches to the
  target and each of Tristana's basic attacks / abilities against it
  increases the detonation damage by 25%, stacking up to 4 times (100%)
  and detonating instantly at max stacks. The detonation is priced from
  the ``e_stacks`` option (default 4 = the sourced max): "Minimum
  Physical Damage" (the 0-stack base) plus ``e_stacks`` x "Bonus Damage
  Per Stack" — at 4 stacks this equals the wiki's "Full Stack Physical
  Damage" row at every rank. The charge detonates once per cast.
- Q (Rapid Fire) is an attack-speed buff and P (Draw a Bead) is a
  ranged-AA bonus: zero-damage rows.
- W (Rocket Jump) and R (Buster Shot) are plain attribute reads; W's
  takedown/max-stack-detonation reset is CC/state only, and R's
  knockback/stun is CC only.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    simple_damage,
)
from .source_receipts import load_champion_sources

# HARDCODED: verify on patch updates — the 4-stack cap is wiki prose
# ("stacking up to 4 times for a maximum 100% increase"); the damage
# rows themselves are read from the JSON.
_E_MAX_STACKS = 4


def _explosive_charge(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: the detonation — base + e_stacks x per-stack bonus."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    stacks = min(_E_MAX_STACKS, max(0, int(ctx.options.get("e_stacks", _E_MAX_STACKS))))
    base = extract_named(
        ability, "Minimum Physical Damage", rank, ctx.stats, ctx.target
    )
    per_stack = extract_named(
        ability, "Bonus Damage Per Stack", rank, ctx.stats, ctx.target
    )
    total = base + per_stack * stacks
    entry = damage_entry(
        ability.get("name", "Explosive Charge"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", total),)
    entry["detail"] = (
        f"{stacks}/4 stack(s); "
        f"base {base:.2f} + {stacks} x {per_stack:.2f} per-stack bonus"
    )
    return entry


def _rapid_fire(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: attack-speed steroid — no enemy damage."""
    ability = ctx.ability()
    if ability is None:
        return None
    return {
        "name": ability.get("name", "Rapid Fire"),
        "rank": ctx.rank_for(),
        "cooldown": extract_cooldown(ability, ctx.rank_for()),
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "detail": ("Bonus attack speed for 7s: self buff only, no enemy damage."),
    }


def _draw_a_bead(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: longer-range basic attacks — no enemy damage beyond the auto."""
    ability = ctx.ability()
    if ability is None:
        return None
    return {
        "name": ability.get("name", "Draw a Bead"),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "physical",
        "total_raw": 0.0,
        "parts": (),
        "detail": (
            "Ranged auto-attack bonus: range/on-hit state only, no " "separate damage."
        ),
    }


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "e_stacks",
        "type": "int",
        "default": _E_MAX_STACKS,
        "min": 0,
        "max": _E_MAX_STACKS,
        "label": (
            "Explosive Charge stacks when it detonates "
            "(4 = max 100% increase, instant detonation)"
        ),
    },
]

ASSUMPTIONS = [
    "E (Explosive Charge) detonates once per cast with e_stacks stacks "
    "(default 4 = the sourced max): Minimum Physical Damage + stacks x "
    "Bonus Damage Per Stack, equal to the wiki's Full Stack Physical "
    "Damage row at 4 stacks",
    "The auto-attack rate that adds stacks in a real fight is not "
    "modeled — the stack count is the option; the fight's own autos "
    "still deal their base AD damage",
    "The charge's 0-40% (+0-12%) crit-chance bonus to its total damage "
    "is not modeled (no crit in the no-items reference)",
    "Q (Rapid Fire) attack speed and P (Draw a Bead) range are "
    "zero-damage rows; the AS buff is not applied to the auto count",
    "W's takedown/max-stack reset and R's knockback/stun are " "CC/state only",
]

SLOTS = {
    "Q": _rapid_fire,
    "W": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "E": _explosive_charge,
    "R": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "P": _draw_a_bead,
}

parse_abilities = build_parser(SLOTS, "Tristana")

MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"W", "E", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

SOURCES = load_champion_sources("Tristana")
