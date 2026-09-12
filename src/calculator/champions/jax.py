"""Jax's stackable attack speed, empowered attack, Counter Strike and R state."""

from __future__ import annotations

import re
from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .inputs import bool_option, float_option, int_option
from .module_helpers import no_damage, ranked_slot
from .shared_mechanics import empowered_auto_entry
from .slot_control import with_control
from .slot_entries import damage_entry
from .slot_extract import (
    ability_name,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    sum_modifiers,
)
from .slotlib import simple_damage
from .source_receipts import load_champion_sources

_ASSAULT_STACK_RE = re.compile(
    r"generate a stack of Relentless Assault on-attack for "
    r"(?P<seconds>\d+(?:\.\d+)?) seconds[^.]*?stacking up to (?P<stacks>\d+) times"
)


def _assault_stack_terms(ability: dict[str, Any]) -> tuple[float, int]:
    """Relentless Assault's cached stack life and cap."""
    effects = ability.get("effects")
    for effect in effects if effects else ():
        description = effect.get("description")
        if description is None:
            continue
        match = _ASSAULT_STACK_RE.search(str(description))
        if match is not None:
            return float(match.group("seconds")), int(match.group("stacks"))
    raise ValueError(
        "Jax P: the cached innate no longer states Relentless Assault's "
        "stack life and cap ('on-attack for N seconds ... stacking up to N "
        "times')"
    )


def _assault(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    requested = ctx.options.get("p_stacks")
    seconds, max_stacks = _assault_stack_terms(ability)
    stacks = min(max(int(requested), 0), max_stacks) if requested is not None else 0
    row = find_named_leveling(ability, "Per-Level Scaling")
    per_stack = sum_modifiers(row, ctx.level, ctx.stats, ctx.target) if row else 0.0
    entry = no_damage(
        ctx,
        name=ability_name(ability),
        reason=(
            (
                f"{per_stack:g}% attack speed per stack, up to {max_stacks} held "
                f"for {seconds:g}s each; the fight walks the swings that stack "
                "them.  Fish/river economy is explicit utility."
            )
            if requested is None
            else (
                f"{stacks} attack-speed stacks; fish/river economy is explicit "
                "utility."
            )
        ),
    )
    if entry is None:
        return None
    if requested is None:
        # One stack per completed attack, each living its cached seconds:
        # the record an item ramp already is, walked by the same walker
        # (interpreters/rearmed_swings).
        entry["swing_ramp"] = {
            "per_stack": per_stack / 100.0,
            "max_stacks": max_stacks,
            "stack_duration": seconds,
        }
    else:
        entry["stat_buff"] = {"bonus_attack_speed": per_stack * stacks}
    return entry


_assault.phase = BUFF


@ranked_slot
def _empower(ctx: SlotCtx, ability: dict[str, Any], rank: int) -> dict[str, Any] | None:
    value = extract_named(
        ability, "Additional Magic Damage", rank, ctx.stats, ctx.target
    )
    return empowered_auto_entry(
        ability,
        rank,
        "magic",
        {"name": "Empower", "damage_per_hit": value, "damage_type": "magic"},
        cooldown=extract_cooldown(ability, rank),
        detail="Empowers one basic attack or Leap Strike and resets the attack timer.",
    )


@ranked_slot
def _counter_strike(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    dodged = min(max(int(ctx.option("e_dodged_attacks")), 0), 5)
    low = extract_named(ability, "Minimum Magic Damage", rank, ctx.stats, ctx.target)
    high = extract_named(ability, "Maximum Magic Damage", rank, ctx.stats, ctx.target)
    value = low + (high - low) * dodged / 5.0
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=2.0),)
    entry["detail"] = (
        f"{dodged} dodged attacks; evasion and area-damage reduction are defensive state."
    )
    return entry


@ranked_slot
def _grandmaster(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=0.4),)
    armor = (
        extract_value(ability, "Bonus Armor", rank)
        + extract_value(ability, "Bonus Armor", rank, 1)
        * ctx.stat("bonus_attack_damage")
        / 100.0
    )
    mr = (
        extract_value(ability, "Bonus Magic Resistance", rank)
        + extract_value(ability, "Bonus Magic Resistance", rank, 1)
        * ctx.stat("bonus_attack_damage")
        / 100.0
    )
    entry["stat_buff"] = {"bonus_armor": armor, "bonus_magic_resistance": mr}
    if bool(ctx.option("r_passive_ready")):
        proc = extract_named(
            ability, "Additional Magic Damage", rank, ctx.stats, ctx.target
        )
        entry["on_hit"] = {
            "name": "Grandmaster-at-Arms passive",
            "damage_per_hit": proc,
            "damage_type": "magic",
        }
    entry["detail"] = (
        f"Active lantern swing; +{armor:g} armor/+{mr:g} magic resistance for the "
        f"authored 8-second window."
    )
    return entry


SLOTS = {
    "P": _assault,
    "Q": simple_damage(
        attr="Physical Damage",
        dmg_type="physical",
        event_order_certified="single_hit",
    ),
    "W": _empower,
    "E": with_control(
        _counter_strike,
        duration_attr="Stun Duration",
        effect_index=1,
    ),
    "R": _grandmaster,
}

# Q's leap only damages the target it lands on and R's lantern swing only
# damages.  E's recast "deals magic damage to nearby enemies ... and stuns
# them for 1 second".  P is the attack-speed stack row and authors no
# damage part.
#
# W (Empower) empowers "his next basic attack or Leap Strike ... to deal
# additional magic damage" and nothing else — a reviewed absence of
# control, riding the swing the cast forces.
MODULE_CC = {"Q": "none", "W": "none", "R": "none", "E": "stun", "P": "none"}

parse_abilities = build_parser(SLOTS, "Jax", cc_kinds=MODULE_CC)
OPTIONS = [
    int_option(
        "p_stacks",
        8,
        minimum=0,
        maximum=8,
        label=(
            "Relentless Assault stacks; unset walks the ramp, one stack per "
            "attack, so the swings speed up as they land"
        ),
    ),
    int_option(
        "e_dodged_attacks",
        0,
        minimum=0,
        maximum=5,
        label="Counter Strike attacks dodged",
    ),
    bool_option("e_active", False, label="E (Counter Strike) evasion active"),
    float_option(
        "e_active_from",
        0.0,
        minimum=0.0,
        maximum=120.0,
        label="E evasion start time in seconds",
    ),
    float_option(
        "e_active_seconds",
        0.0,
        minimum=0.0,
        maximum=2.0,
        label="E evasion seconds; zero uses the sourced duration",
    ),
    bool_option("r_passive_ready", False, label="Grandmaster passive hit ready"),
]
ASSUMPTIONS = [
    "Relentless Assault is an explicit stack-derived attack-speed buff; it is applied "
    "before later casts and autos.",
    "Empower is one next-attack magic rider; Counter Strike uses the sourced 0–100% "
    "dodge-damage range.",
    "Counter Strike's sourced 2-second evasion window blocks incoming basic attacks "
    "and reduces marked area-ability damage by 25% when e_active is selected.",
    "Grandmaster-at-Arms includes the active swing and defensive resistances; its "
    "passive hit is opt-in to avoid inventing prior stacks.",
]
SOURCES = load_champion_sources("Jax")
