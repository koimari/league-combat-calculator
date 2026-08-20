"""Locke — full-entry reviewed module, plus the P1 W grey-health heal.

Option keys consumed by this module: "q_casts", "soul_nails", "e_dash".

P1 addition over the reviewed packet:
- W (Soul Ignition) recast heal is now authored by the E8a grey-health
  primitive (GREY_HEALTH_RULE_CHAMPIONS + participant_timeline):
  "stores an amount of grey health ... equal to 100% of the
  post-mitigation damage he takes from enemy champions, up to a cap"
  (cached W prose; cap = the "Damage taken grey health cap" leveling row
  40/60/80/100/120 by W rank + 100% AP).  Each W cast opens a 6-second
  storage window and the automatic recast at 6 s heals the stored pool.
  The health-cost add and the missing-health bonus ("increased by up to
  40 : 200 (based on level) (+ 20% AP) based on his missing health")
  remain documented dynamic-self-state boundaries — the deterministic
  pool is the sourced 100%-of-damage-taken term.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import REVIEWED_MODULE_ASSUMPTIONS, no_damage, typed_damage
from .slotlib import extract_cooldown, extract_named, on_hit_entry
from .source_receipts import load_champion_sources


def _silver_stake(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: on-hit damage scaling linearly with target missing health."""
    ability = ctx.ability()
    if ability is None:
        return None
    base = extract_named(
        ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target
    )
    missing_ratio = float(ctx.target_stat("target_missing_health") or 0.0) / max(
        1.0, float(ctx.target_stat("target_max_health") or 1.0)
    )
    value = base * (1.0 + max(0.0, min(1.0, missing_ratio)))
    result = on_hit_entry("Silver Stake", value, "magic")
    result["target_max_health_sensitive"] = True
    result["detail"] = (
        "On-hit damage doubles linearly with target missing-health ratio, "
        "capped by the sourced bonus row."
    )
    return result


def _ritual_nails(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: one to three casts plus the selected Soul Nails detonation."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    casts = max(1, min(3, int(ctx.option("q_casts"))))
    per = extract_named(ability, "Magic Damage per Nail", rank, ctx.stats, ctx.target)
    stacks = max(0, min(3, int(ctx.option("soul_nails"))))
    bonus_attr = {
        1: "One Stack Bonus Damage",
        2: "Two Stacks Bonus Damage",
        3: "Three Stacks Bonus Damage",
    }.get(stacks)
    bonus = (
        extract_named(ability, bonus_attr, rank, ctx.stats, ctx.target)
        if bonus_attr
        else 0.0
    )
    parts = [DamagePart("magic", per, count=casts, time_offset=0.15, hit_interval=0.15)]
    if bonus:
        parts.append(DamagePart("magic", bonus, time_offset=0.5))
    return {
        "name": ability.get("name", "Ritual Nails"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": per * casts + bonus,
        "parts": tuple(parts),
        "detail": (
            f"{casts} Ritual Nails casts; {stacks} Soul Nails stacks are "
            "consumed by the next damaging attack."
        ),
    }


def _ashen_pursuit(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: blink packet plus the optional empowered dash attack."""
    attribute = (
        "Total Magic Damage"
        if bool(ctx.options.get("e_dash", True))
        else "Blink Magic Damage"
    )
    result = typed_damage(ctx, attribute, "magic", time_offset=0.1)
    if result:
        result["detail"] = "Ashen Pursuit blink plus optional empowered dash attack."
    return result


def _purgatory(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: totem damage; mark refresh and execute remain target state."""
    result = typed_damage(ctx, "Magic Damage", "magic", time_offset=0.75)
    if result:
        result["target_max_health_sensitive"] = True
        result["detail"] = (
            "Purgatory totem damage; mark refresh and execute threshold remain "
            "explicit target state."
        )
    return result


SLOTS = {
    "P": _silver_stake,
    "Q": _ritual_nails,
    "W": lambda ctx: no_damage(
        ctx,
        name="Soul Ignition",
        reason=(
            "Grey health storage, attack speed, movement speed and recast healing "
            "are self-state."
        ),
    ),
    "E": _ashen_pursuit,
    "R": _purgatory,
}

OPTIONS: list[dict[str, Any]] = [
    {
        "key": "q_casts",
        "type": "int",
        "default": 3,
        "min": 1,
        "max": 3,
        "label": "Ritual Nails casts",
    },
    {
        "key": "soul_nails",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 3,
        "label": "Soul Nails stacks",
    },
    {
        "key": "e_dash",
        "type": "bool",
        "default": True,
        "label": "Ashen Pursuit dash",
    },
]

ASSUMPTIONS = list(REVIEWED_MODULE_ASSUMPTIONS)
SOURCES = load_champion_sources("Locke")

# Cached kit review: Q's nails "slow[] them by 25% for 1 second" (60% at
# two Soul Nails stacks) and R's latching nails slow "by 99% decaying over
# 2 seconds"; E blinks and dashes without applying control.  W is a
# self-buff and P an on-hit rider, neither emitting an ability event.
MODULE_CC = {"Q": "slow", "E": "none", "R": "slow"}

parse_abilities = build_parser(SLOTS, "Locke", cc_kinds=MODULE_CC)

_ON_HIT_SPECS: dict[str, dict] = {
    "E": {"effectiveness": 1.0, "hits": 1, "triggers": ("on_hit",)},
}

_parse_abilities = parse_abilities


def parse_abilities(*args, **kwargs):
    """Parse abilities, then declare wiki-sourced item on-hit application."""
    result = _parse_abilities(*args, **kwargs)
    for slot, spec in _ON_HIT_SPECS.items():
        entry = result.get(slot) or (result.get("passive") if slot == "P" else None)
        if entry is not None:
            entry["applies_item_on_hits"] = dict(spec)
    return result


# The wrapper is the module's published parser, so it republishes the
# wiring the inner parser holds — the contract proves declaration and
# wiring are one dict off whichever function the module exports.
parse_abilities.cc_kinds = _parse_abilities.cc_kinds


MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "E", "R"} else "no_damage")
    for slot in "PQWER"
}

ASSUMPTIONS += [
    "W (Soul Ignition) recast heal is authored by the grey-health "
    "primitive: 100% of the post-mitigation champion damage taken during "
    "the 6s active is stored (capped by the 'Damage taken grey health "
    "cap' row) and healed at the automatic 6s recast.  The health-cost "
    "add and the missing-health bonus are dynamic self-state boundaries, "
    "per the E1-b6 scope note",
]
