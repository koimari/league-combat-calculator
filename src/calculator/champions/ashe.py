"""Ashe — slot map for the archetype engine.

Why each slot is non-generic:
- P (Frost Shot) changes what an auto attack IS: crits deal no bonus
  damage, and instead crit chance converts to bonus physical damage on
  every auto (``auto_attack_override.crit_as_bonus``). Which entry
  carries the override depends on Q:
- Q (Ranger's Focus) is a BUFF-phase custom fn — no direct damage, but
  a bonus-attack-speed stat buff plus flurry autos at a modified AD
  ratio ("Total Damage Per Flurry", a per-flurry percentage). When Q is
  active (``q_active`` option, default True) and ranked, the Q entry
  carries the auto_attack_override (flurry ratio + crit-as-bonus) and
  the passive entry is display-only; otherwise the passive entry
  carries the override at the normal 1.0 AD ratio. P therefore reads
  ``ctx.results`` and must list after Q in the slot map.
- W/R are plain attribute reads.
- E (Hawkshot) is vision utility only and is absent from the slot map.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from .engine import BUFF, SlotCtx, build_parser
from .slotlib import extract_cooldown, extract_value, simple_damage


def _rangers_focus(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: attack-speed stat buff + flurry auto_attack_override."""
    if not bool(ctx.options.get("q_active", True)):
        return None
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    bonus_as_pct = extract_value(ability, "Bonus Attack Speed", rank)
    # Flurry AD ratio, e.g. 110 (% AD) -> 1.10.
    flurry_ratio = extract_value(ability, "Total Damage Per Flurry", rank) / 100.0

    # Apply the bonus AS to the shared stats context (BUFF phase).
    as_ratio = ctx.stats.get("attack_speed_ratio", 0.625)
    ctx.stats["attack_speed"] = ctx.stats.get("attack_speed", 0.0) + as_ratio * (
        bonus_as_pct / 100.0
    )

    return {
        "name": ability.get("name", "Ranger's Focus"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "physical",
        "total_raw": 0.0,
        "physical_damage": 0.0,
        "stat_buff": {
            "bonus_attack_speed": bonus_as_pct,
        },
        "auto_attack_override": {
            "ad_ratio": flurry_ratio,
            "crit_as_bonus": True,
        },
    }


_rangers_focus.phase = BUFF


def _frost_shot(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: crit-as-bonus auto override — carried here only when Q isn't."""
    ability = ctx.ability()
    if ability is None:
        return None

    entry: dict[str, Any] = {
        "name": ability.get("name", "Frost Shot"),
        "total_raw": 0.0,
        "damage_type": "physical",
    }
    if "Q" not in ctx.results:
        # Q inactive/unranked: normal autos, crit chance as bonus damage.
        entry["auto_attack_override"] = {
            "ad_ratio": 1.0,
            "crit_as_bonus": True,
        }
    return entry


OPTIONS = [
    {
        "key": "q_active",
        "type": "bool",
        "default": True,
        "label": "Ranger's Focus active",
    },
]

ASSUMPTIONS = [
    "Q (Ranger's Focus) assumed active by default",
    "Passive bonus damage from crit chance applied to all auto attacks",
    "W hits a single target (one arrow per enemy)",
    "E (Hawkshot) is utility only and deals no damage",
]

SLOTS = {
    "Q": _rangers_focus,
    "P": _frost_shot,
    "W": simple_damage(attr="Physical Damage", dmg_type="physical"),
    "R": simple_damage(attr="Magic Damage", dmg_type="magic"),
}

parse_abilities = build_parser(SLOTS, "Ashe")
