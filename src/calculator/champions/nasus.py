"""Nasus — slot map for the archetype engine (E3 stack systems).

Why each slot is non-generic:
- Q (Siphoning Strike) is the permanent-scaling stack: every kill grants
  Nasus 3 permanent stacks (12 for champions/large minions/monsters),
  and each stack adds 1 bonus damage to Q ("Bonus Physical Damage" =
  flat 40-120 by rank + 100% of Siphoning Strike stacks). The current
  stack total comes from the ``q_stacks`` option (default 0 = a fresh
  Nasus); the kill-gain itself is not modeled (the target never dies in
  this calculator). Q empowers the next basic attack, so it carries
  ``empowers_next_auto`` (Vayne Q precedent).
- E (Spirit Fire) prices the initial hit plus 10 sourced 0.5s zone
  ticks (E2 fix: "Magic Damage" + 10 x "Magic Damage Per Tick" ==
  "Total Magic Damage"), with the burn tail keeping item burns
  refreshed.
- R (Fury of the Sands) prices all 30 sourced 0.5s ticks ("Magic
  Damage Per Tick" x30 == "Total Magic Damage"); the bonus health /
  resistances are self-stats and the Siphoning Strike cooldown halving
  is not modeled.
- P (Soul Eater) and W (Wither) deal no enemy damage: zero-damage rows.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
)
from .source_receipts import load_champion_sources

# E2-sourced tick cadences (data/worklists/e2-dot-ticks.json and the
# ability descriptions): Spirit Fire's zone ticks every 0.5s over 5s
# (first tick 0.5s after the initial hit's 0.264s delay); Fury of the
# Sands ticks every 0.5s over 15s.
_E_INITIAL_DELAY = 0.264
_E_TICKS = 10
_E_TICK_INTERVAL = 0.5
_E_DOT_DURATION = 5.0
_R_TICKS = 30
_R_TICK_INTERVAL = 0.5
_R_DOT_DURATION = 15.0


def _siphoning_strike(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: bonus damage (flat + permanent stacks) riding the next auto."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    stacks = max(0, int(ctx.options.get("q_stacks", 0)))
    bonus = (
        extract_named(ability, "Bonus Physical Damage", rank, ctx.stats, ctx.target)
        + stacks
    )
    entry = damage_entry(
        ability.get("name", "Siphoning Strike"),
        rank,
        extract_cooldown(ability, rank),
        bonus,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", bonus),)
    entry["empowers_next_auto"] = True
    entry["detail"] = (
        f"flat {bonus - stacks:.2f} + {stacks} permanent Siphoning Strike " "stack(s)"
    )
    return entry


def _spirit_fire(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: initial hit + 10 sourced 0.5s zone ticks (E2 fix)."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    initial = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    per_tick = extract_named(
        ability, "Magic Damage Per Tick", rank, ctx.stats, ctx.target
    )
    total = initial + per_tick * _E_TICKS
    entry = damage_entry(
        ability.get("name", "Spirit Fire"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart("magic", initial, time_offset=_E_INITIAL_DELAY),
        DamagePart(
            "magic",
            per_tick,
            count=_E_TICKS,
            time_offset=_E_INITIAL_DELAY + _E_TICK_INTERVAL,
            hit_interval=_E_TICK_INTERVAL,
        ),
    )
    entry["dot_duration"] = _E_DOT_DURATION
    entry["detail"] = (
        f"initial hit + {_E_TICKS} sourced {_E_TICK_INTERVAL:g}s-interval "
        f"ticks (Magic Damage Per Tick x{_E_TICKS} = Spirit Fire total)"
    )
    return entry


def _fury_of_the_sands(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: all 30 sourced 0.5s ticks (E2 fix)."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    per_tick = extract_named(
        ability, "Magic Damage Per Tick", rank, ctx.stats, ctx.target
    )
    total = per_tick * _R_TICKS
    entry = damage_entry(
        ability.get("name", "Fury of the Sands"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            per_tick,
            count=_R_TICKS,
            time_offset=_R_TICK_INTERVAL,
            hit_interval=_R_TICK_INTERVAL,
        ),
    )
    entry["dot_duration"] = _R_DOT_DURATION
    entry["detail"] = (
        f"{_R_TICKS} sourced {_R_TICK_INTERVAL:g}s-interval ticks "
        f"(Magic Damage Per Tick x{_R_TICKS} = Fury of the Sands total)"
    )
    return entry


def _soul_eater(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: innate lifesteal — no enemy damage, self-heal via healing.py."""
    ability = ctx.ability()
    if ability is None:
        return None
    return {
        "name": ability.get("name", "Soul Eater"),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "physical",
        "total_raw": 0.0,
        "parts": (),
        "detail": (
            "Innate lifesteal: heals for 12% / 18% / 24% (based on level; "
            "game-file breakpoints 7/13) of the post-mitigation physical "
            "basic-attack/on-hit damage dealt — authored by the Soul Eater "
            "heal rule (HEALING_RULE_CHAMPIONS), no enemy damage."
        ),
    }


def _wither(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: slow/cripple — no enemy damage."""
    ability = ctx.ability()
    if ability is None:
        return None
    return {
        "name": ability.get("name", "Wither"),
        "rank": ctx.rank_for(),
        "cooldown": extract_cooldown(ability, ctx.rank_for()),
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "detail": "Slow and attack-speed cripple: CC only, no damage.",
    }


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "q_stacks",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 5000,
        "label": (
            "Permanent Siphoning Strike stacks (each adds 1 bonus damage "
            "to Q; 3 per minion kill, 12 per champion kill)"
        ),
    },
]

ASSUMPTIONS = [
    "Q (Siphoning Strike) bonus damage = the rank flat (40-120) + the "
    "q_stacks option total (100% of Siphoning Strike stacks); the "
    "permanent gain (+3 per kill, +12 for champions) is not modeled — "
    "the target never dies here, so the option IS the current stack "
    "state",
    "Q empowers the next basic attack (empowers_next_auto), so its "
    "casts are capped by the fight's auto count; with no auto stream it "
    "forces its own swing",
    "E (Spirit Fire) prices the initial hit + 10 sourced 0.5s zone "
    "ticks (E2 fix, unchanged from the reviewed packet)",
    "R (Fury of the Sands) prices all 30 sourced 0.5s ticks (E2 fix, "
    "unchanged); its bonus health/resistances are self-stats and the "
    "Q-cooldown halving is not modeled",
    "P (Soul Eater) lifesteal is a self-heal rule (HEALING_RULE_CHAMPIONS): "
    "12% / 18% / 24% (based on level; game-file breakpoints at 7/13) of the "
    "post-mitigation physical basic-attack/on-hit damage dealt; W (Wither) "
    "slow/cripple is a zero-damage row",
]

SLOTS = {
    "Q": _siphoning_strike,
    "W": _wither,
    "E": _spirit_fire,
    "R": _fury_of_the_sands,
    "P": _soul_eater,
}

parse_abilities = build_parser(SLOTS, "Nasus")

MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

SOURCES = load_champion_sources("Nasus")
