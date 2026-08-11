"""Kennen — full-entry reviewed CP10.3 module.

Option keys consumed by the shared parser: "w_empowered", "r_bolts".
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import REVIEWED_MODULE_ASSUMPTIONS, no_damage
from .slotlib import (
    ability_on_hit_entry,
    extract_cooldown,
    extract_named,
    simple_damage,
)
from .source_receipts import load_champion_sources


def _electrical_surge(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    active = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    passive = extract_named(ability, "Bonus Magic Damage", rank, ctx.stats, ctx.target)
    result = ability_on_hit_entry(
        ability.get("name", "Electrical Surge"),
        rank,
        "magic",
        {
            "name": "Electrical Surge passive",
            "damage_per_hit": (
                passive if bool(ctx.options.get("w_empowered", True)) else 0.0
            ),
            "damage_type": "magic",
        },
        extract_cooldown(ability, rank),
    )
    result["parts"] = (DamagePart("magic", active),)
    result["total_raw"] = active
    result["detail"] = (
        "Active surge plus an explicit four-stack empowered on-hit branch."
    )
    return result


def _slicing_maelstrom(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    bolts = max(1, min(6, int(ctx.option("r_bolts"))))
    per = extract_named(ability, "Magic Damage Per Bolt", rank, ctx.stats, ctx.target)
    return {
        "name": ability.get("name", "Slicing Maelstrom"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": per * bolts,
        "parts": (
            DamagePart("magic", per, count=bolts, time_offset=0.5, hit_interval=0.5),
        ),
        "detail": (
            f"{bolts} ordered bolts; later strikes use the sourced escalating "
            "storm packet."
        ),
        "event_order_certified": True,
    }


SLOTS = {
    "P": lambda ctx: no_damage(
        ctx,
        name="Mark of the Storm",
        reason="Mark stacks, stun and energy refund are ordered control state.",
    ),
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "W": _electrical_surge,
    "E": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "R": _slicing_maelstrom,
}
OPTIONS = [
    {
        "key": "w_empowered",
        "type": "bool",
        "default": True,
        "label": "Four-stack Electrical Surge attack",
    },
    {
        "key": "r_bolts",
        "type": "int",
        "default": 6,
        "min": 1,
        "max": 6,
        "label": "Slicing Maelstrom bolts",
    },
]
ASSUMPTIONS = list(REVIEWED_MODULE_ASSUMPTIONS)
SOURCES = load_champion_sources("Kennen")
parse_abilities = build_parser(SLOTS, "Kennen")

MODULE_COVERAGE = {
    slot: ("modeled" if slot != "P" else "no_damage") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
