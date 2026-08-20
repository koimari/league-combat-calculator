"""Wukong's Stone Skin, empowered attack, and Cyclone timeline.

Why the Q slot is non-generic:
- Q (Crushing Blow) is a DEBUFF-phase custom fn: the empowered basic
  attack's bonus physical damage plus a percentage armor reduction
  emitted as a ``target_debuff`` (``q_armor_reduction`` option, default
  True). damage.py applies the shred AFTER the ability's own damage —
  Q's bonus packet is always priced at full target armor, while
  everything after it (R ticks, E follow-ups, later Q casts, autos)
  sees the reduced armor for the debuff's 3 seconds (the Kog'Maw Q
  rule). In the sustained auto path the empowered swing rides the auto
  stream, which the fight engine prices against its single time-weighted
  armor scalar like every other post-Q hit.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, DEBUFF, SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    simple_damage,
    sum_modifiers,
)

# Crushing Blow's debuff lasts 3s ("inflict armor reduction for 3
# seconds", wiki prose below) — it is not permanent.
Q_SHRED_DURATION = 3.0


def _stone_skin(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("P")
    if ability is None:
        return None
    base = find_named_leveling(ability, "Per-Level Scaling", 0)
    per_stack = find_named_leveling(ability, "Per-Level Scaling", 1)
    if base is None or per_stack is None:
        return None
    stacks = min(max(int(ctx.option("stone_skin_stacks")), 0), 5)
    armor = sum_modifiers(base, ctx.level) + stacks * sum_modifiers(
        per_stack, ctx.level
    )
    ctx.stats["armor"] = ctx.stat("armor") + armor
    entry = damage_entry("Stone Skin", ctx.level, 0.0, 0.0, "physical")
    entry["stat_buff"] = {"armor": armor}
    entry["detail"] = f"{stacks} Strength of Stone stack(s); +{armor:.2f} bonus armor"
    return entry


_stone_skin.phase = BUFF


def _crushing_blow(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("Q")
    if ability is None:
        return None
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None
    bonus = extract_named(ability, "Bonus Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Crushing Blow"),
        rank,
        extract_cooldown(ability, rank),
        bonus,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", bonus, time_offset=0.0),)
    entry["empowers_next_auto"] = True

    # Armor REDUCTION (not penetration): damage.py shreds target armor
    # after Q's own damage, so the empowered swing itself lands at full
    # armor while everything after it (R ticks, E follow-up, later Q
    # casts) sees the reduced armor — matching in-game.
    shred = extract_value(ability, "Armor Reduction", rank)
    if ctx.options.get("q_armor_reduction", True) and shred > 0:
        entry["target_debuff"] = {
            "armor_reduction_percent": shred,
            "duration": Q_SHRED_DURATION,
        }
    entry["detail"] = "bonus damage is attached to the empowered basic attack"
    return entry


_crushing_blow.phase = DEBUFF


def _cyclone(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability("R")
    if ability is None:
        return None
    rank = ctx.rank_for("R")
    if rank < 1:
        return None
    per_tick = extract_named(
        ability, "Physical Damage Per Tick", rank, ctx.stats, ctx.target
    )
    casts = min(max(int(ctx.option("r_casts")), 1), 2)
    ticks = 8 * casts
    total = per_tick * ticks
    entry = damage_entry(
        ability.get("name", "Cyclone"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (
        DamagePart(
            "physical", per_tick, count=ticks, time_offset=0.0, hit_interval=0.25
        ),
    )
    entry["detail"] = f"{casts} Cyclone cast(s), eight sourced 0.25-second ticks each"
    return entry


SLOTS = {
    "P": _stone_skin,
    "Q": _crushing_blow,
    # The W clone's attacks are a separate pet timeline; it is not a direct
    # cast packet and therefore is intentionally omitted here.
    # One strike on the dash target (the two clone strikes land on *other*
    # enemies), so the single-target row is one hit at the cast.
    "E": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "R": _cyclone,
}

# Cyclone's staff "deals physical damage every 0.25 seconds to enemies hit,
# and can knock them up once for 0.6 seconds".  Crushing Blow's empowered
# swing only deals damage and "inflict[s] armor reduction" — a resistance
# shred, not control — and Nimbus Strike only strikes.  W is the clone's
# pet timeline (no direct cast packet) and P is the armor buff; neither
# authors a damage part.
MODULE_CC = {"Q": "none", "E": "none", "R": "knockup"}

parse_abilities = build_parser(SLOTS, "Wukong", cc_kinds=MODULE_CC)

OPTIONS = [
    {
        "key": "stone_skin_stacks",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 5,
        "label": "Strength of Stone stacks",
    },
    {
        "key": "q_armor_reduction",
        "type": "bool",
        "default": True,
        "label": "Q armor reduction active",
    },
    {
        "key": "r_casts",
        "type": "int",
        "default": 1,
        "min": 1,
        "max": 2,
        "label": "Cyclone casts",
    },
]

ASSUMPTIONS = [
    "Stone Skin armor uses explicit Strength of Stone stacks; regeneration is a separate survival effect.",
    "Crushing Blow exposes its bonus packet and attaches the next basic attack through the shared empowered-auto path.",
    "Q's armor reduction (10-30% of target's armor by rank, 3s) applies "
    "to damage dealt after the empowered attack lands, not to the attack "
    "itself.",
    "Warrior Trickster clone attacks are a separate pet timeline and are not invented as direct W spell damage.",
    "Cyclone uses eight sourced 0.25-second ticks per cast; the second cast is explicit.",
]

SOURCES = [
    {
        "label": "Wukong — full champion entry",
        "url": "https://wiki.leagueoflegends.com/en-us/Wukong",
        "revision_id": 4021883,
        "revision_timestamp": "2026-05-21T19:27:04Z",
    }
]
