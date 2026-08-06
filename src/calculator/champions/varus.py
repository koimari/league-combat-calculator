"""Varus — slot map for the archetype engine (E3 stack systems).

Why each slot is non-generic:
- W (Blighted Quiver) is an ON-HIT passive, not a castable: every basic
  attack deals the "Bonus Magic Damage" leveling row and applies a Blight
  stack (max 3, 6s, refreshing). The reviewed packet priced this row as a
  40s-cooldown cast, which contributed ~0 damage in any real fight; the
  on-hit shell (Vayne W precedent) prices it per auto instead.
- Q (Piercing Arrow) is the primary Blight DETONATOR: abilities consume
  all Blight stacks on the target, dealing "Bonus Magic Damage per Stack"
  (% of the target's max health + % per 100 AP) per stack. The fight
  engine has no auto-application->ability-detonation cycle, so the
  detonation rides Q as a ``post_hit_proc`` priced from the
  ``blight_stacks`` option (default 3 = the sourced max) — one sourced
  detonation per Q cast. E and R also detonate in-game; re-stacking a
  target between casts is not double-priced here (conservative single
  detonator model). Q reads the MAXIMUM (fully-charged) damage rows; the
  0-50% charge scaling is not modeled.
- E (Hail of Arrows) is physical damage ("Physical Damage" — the packet's
  magic label was wrong; in-game and the JSON both say physical).
- P (Living Vengeance) is an on-takedown attack-speed buff: no enemy
  damage, emitted as a zero-damage row.
- R (Chain of Corruption) is a plain "Magic Damage" read; the root/chain
  is CC only.
"""

import json
from pathlib import Path
from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import (
    ability_on_hit_entry,
    damage_entry,
    extract_cooldown,
    extract_named,
    simple_damage,
    sum_modifiers,
    find_named_leveling,
)

# HARDCODED: verify on patch updates — wiki prose, not in the JSON.
# Blight stacks to 3 on basic attacks; abilities detonate all stacks.
_BLIGHT_MAX_STACKS = 3
_BLIGHT_DETONATION_ATTR = "Bonus Magic Damage per Stack"


def _blight_detonation(ctx: SlotCtx, rank: int) -> float:
    """One full detonation: ``blight_stacks`` x per-stack %maxHP damage.

    The per-stack row is "% of the target's maximum health" plus
    "% per 100 AP" — both units resolve through the shared scaling core.
    """
    ability = ctx.ability("W", 0)
    if ability is None:
        return 0.0
    leveling = find_named_leveling(ability, _BLIGHT_DETONATION_ATTR)
    if leveling is None:
        raise ValueError(
            "Varus W: 'Bonus Magic Damage per Stack' is missing from the "
            "ability JSON — cannot compute the Blight detonation"
        )
    stacks = min(
        _BLIGHT_MAX_STACKS,
        max(0, int(ctx.options.get("blight_stacks", _BLIGHT_MAX_STACKS))),
    )
    if stacks <= 0:
        return 0.0
    per_stack = sum_modifiers(leveling, rank, ctx.stats, ctx.target)
    return per_stack * stacks


def _piercing_arrow(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: fully-charged arrow damage + the Blight detonation it triggers."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    arrow = extract_named(
        ability, "Maximum Physical Damage", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability.get("name", "Piercing Arrow"),
        rank,
        extract_cooldown(ability, rank),
        arrow,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", arrow),)
    entry["event_order_certified"] = "single_hit"

    detonation = _blight_detonation(ctx, rank)
    if detonation > 0:
        stacks = min(
            _BLIGHT_MAX_STACKS,
            max(0, int(ctx.options.get("blight_stacks", _BLIGHT_MAX_STACKS))),
        )
        entry["post_hit_proc"] = {
            "name": "Blight Detonation",
            "breakdown_key": "blight_detonation",
            "parts": (DamagePart("magic", detonation, time_offset=0.0),),
            "detail": (f"{stacks} Blight stack(s) consumed at {rank} points in W"),
        }
        entry["total_raw"] = arrow + detonation
    return entry


def _blighted_quiver(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: flat on-hit magic per basic attack (Blight stacks ride it)."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    leveling = find_named_leveling(ability, "Bonus Magic Damage")
    if leveling is None:
        raise ValueError(
            "Varus W: 'Bonus Magic Damage' leveling entry missing from the "
            "ability JSON — cannot compute the on-hit damage"
        )
    per_hit = sum_modifiers(leveling, rank, ctx.stats, ctx.target)
    name = ability.get("name", "Blighted Quiver")
    entry = ability_on_hit_entry(
        name,
        rank,
        "magic",
        {
            "name": name,
            "damage_per_hit": per_hit,
            "damage_type": "magic",
        },
    )
    entry["event_order_certified"] = "auto_stack_proc"
    return entry


def _living_vengeance(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: takedown attack-speed buff — no enemy damage."""
    ability = ctx.ability()
    if ability is None:
        return None
    return {
        "name": ability.get("name", "Living Vengeance"),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "detail": ("On-takedown attack speed: self buff only, no enemy damage."),
    }


# HARDCODED: verify on patch updates — wiki prose in the cached E JSON
# ("...inflicting them with Grievous Wounds").  Hail of Arrows' desecrated
# area applies the patch-wide 40% Grievous Wounds window; the strength and
# 3-second duration are the engine constants, not module numbers.
GRIEVOUS_WOUNDS_SOURCES = frozenset({"E"})

OPTIONS: list[dict[str, Any]] = [
    {
        "key": "blight_stacks",
        "type": "int",
        "default": _BLIGHT_MAX_STACKS,
        "min": 0,
        "max": _BLIGHT_MAX_STACKS,
        "label": (
            "Blight stacks on the target when Piercing Arrow lands "
            "(3 = fully stacked; the Q detonation consumes them)"
        ),
    },
]

ASSUMPTIONS = [
    "W (Blighted Quiver) is an on-hit passive: every basic attack deals "
    "its bonus magic damage (4-40 + 15% bonus AD + 25% AP by rank) and "
    "applies one Blight stack; stacks cap at 3 and refresh for 6s",
    "Blight detonation is priced on Piercing Arrow (the primary "
    "detonator) once per Q cast from the blight_stacks option — E and R "
    "also detonate in-game, but re-stacking between casts is not "
    "double-priced in this single-target rotation (conservative)",
    "Detonation per stack = the sourced 'Bonus Magic Damage per Stack' "
    "row (% of target max health + 1.3% per 100 AP by rank); Q's "
    "0-50% charge bonus (the 'Maximum' rows) is not modeled — the "
    "arrow itself is priced at its Maximum (fully-charged) row",
    "Q detonation requires the Q cast; with blight_stacks=0 the option "
    "models a fresh target and no detonation fires",
    "P (Living Vengeance) is a takedown attack-speed buff — no enemy "
    "damage, emitted as a zero-damage row",
    "E is physical damage (JSON and in-game); the reviewed packet's "
    "magic label was a parser error, corrected here",
    "E's desecrated ground applies Grievous Wounds for 3 seconds (wiki "
    "prose); the coupled timeline wounds enemies it damages with the "
    "patch-wide 40% window",
    "R root/chain and Q self-slow are CC/utility only and not valued as " "damage",
]

def _certified_single_hit(parser):
    """Wrap a simple one-instance parser with the event-order certification."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = parser(ctx)
        if entry is not None and int(entry.get("rank", 0) or 0) >= 1:
            entry["event_order_certified"] = "single_hit"
        return entry

    return parse


SLOTS = {
    "Q": _piercing_arrow,
    "W": _blighted_quiver,
    "E": _certified_single_hit(simple_damage(attr="Physical Damage", dmg_type="physical")),
    "R": _certified_single_hit(simple_damage(attr="Magic Damage", dmg_type="magic")),
    "P": _living_vengeance,
}

parse_abilities = build_parser(SLOTS, "Varus")

MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

_SOURCE_PATH = (
    Path(__file__).resolve().parents[3] / "static" / "cp10_batch_09_sources.json"
)


def _load_sources(name: str) -> list[dict[str, object]]:
    try:
        payload = json.loads(_SOURCE_PATH.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"CP10.9 source receipts are unavailable: {_SOURCE_PATH}"
        ) from exc
    rows = payload.get(name) if isinstance(payload, dict) else None
    if (
        not isinstance(rows, list)
        or len(rows) != 6
        or any(not isinstance(row, dict) or not all(row.values()) for row in rows)
    ):
        raise RuntimeError(f"CP10.9 source receipts for {name!r} are incomplete")
    return rows


SOURCES = _load_sources("Varus")
