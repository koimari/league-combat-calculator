"""Jax's stackable attack speed, empowered attack, Counter Strike and R state."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .module_helpers import no_damage
from .slotlib import (
    ability_on_hit_entry,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    sum_modifiers,
    simple_damage,
    with_control,
)
from .source_receipts import load_champion_sources
from .inputs import bool_option, float_option, int_option


def _assault(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    stacks = min(max(int(ctx.option("p_stacks")), 0), 8)
    row = find_named_leveling(ability, "Per-Level Scaling")
    per_stack = sum_modifiers(row, ctx.level, ctx.stats, ctx.target) if row else 0.0
    bonus_as = per_stack * stacks
    entry = no_damage(
        ctx,
        name=ability.get("name", "Relentless Assault"),
        reason=f"{stacks} attack-speed stacks; fish/river economy is explicit utility.",
    )
    if entry is not None:
        entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    return entry


_assault.phase = BUFF


def _empower(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    value = extract_named(
        ability, "Additional Magic Damage", rank, ctx.stats, ctx.target
    )
    entry = ability_on_hit_entry(
        ability.get("name", "Empower"),
        rank,
        "magic",
        {"name": "Empower", "damage_per_hit": value, "damage_type": "magic"},
        extract_cooldown(ability, rank),
    )
    entry["empowers_next_auto"] = True
    entry["detail"] = (
        "Empowers one basic attack or Leap Strike and resets the attack timer."
    )
    return entry


def _counter_strike(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    dodged = min(max(int(ctx.option("e_dodged_attacks")), 0), 5)
    low = extract_named(ability, "Minimum Magic Damage", rank, ctx.stats, ctx.target)
    high = extract_named(ability, "Maximum Magic Damage", rank, ctx.stats, ctx.target)
    value = low + (high - low) * dodged / 5.0
    entry = damage_entry(
        ability.get("name", "Counter Strike"),
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


def _grandmaster(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Grandmaster-at-Arms"),
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
    if bool(ctx.options.get("r_passive_ready", False)):
        proc = extract_named(
            ability, "Additional Magic Damage", rank, ctx.stats, ctx.target
        )
        entry["on_hit"] = {
            "name": "Grandmaster-at-Arms passive",
            "damage_per_hit": proc,
            "damage_type": "magic",
        }
    entry["detail"] = (
        f"Active lantern swing; +{armor:g} armor/+{mr:g} magic resistance for the authored 8-second window."
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
MODULE_CC = {"Q": "none", "W": "none", "R": "none", "E": "stun"}

parse_abilities = build_parser(SLOTS, "Jax", cc_kinds=MODULE_CC)
OPTIONS = [
    int_option("p_stacks", 8, minimum=0, maximum=8, label="Relentless Assault stacks"),
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
    "Relentless Assault is an explicit stack-derived attack-speed buff; it is applied before later casts and autos.",
    "Empower is one next-attack magic rider; Counter Strike uses the sourced 0–100% dodge-damage range.",
    "Counter Strike's sourced 2-second evasion window blocks incoming basic attacks and reduces marked area-ability damage by 25% when e_active is selected.",
    "Grandmaster-at-Arms includes the active swing and defensive resistances; its passive hit is opt-in to avoid inventing prior stacks.",
]
SOURCES = load_champion_sources("Jax")
