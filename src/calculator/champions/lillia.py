"""Lillia — full-entry reviewed CP10.3 module.

Option keys consumed by the shared parser: "p_ticks", "q_outer_edge", "w_epicenter", "r_wake".
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import (
    REVIEWED_MODULE_ASSUMPTIONS,
    mixed_damage,
    no_damage,
    typed_damage,
)
from .slotlib import extract_cooldown, extract_named, simple_damage
from .source_receipts import load_champion_sources


def _dream_laden_bough(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    ticks = max(1, min(6, int(ctx.option("p_ticks"))))
    max_hp = float(ctx.target_stat("target_max_health") or 0.0)
    ap = float(ctx.stat("ability_power"))
    total = max_hp * (0.05 + 0.0125 * ap / 100.0)
    per_tick = total / 6.0
    return {
        "name": ability.get("name", "Dream-Laden Bough"),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "magic",
        "total_raw": per_tick * ticks,
        "parts": (
            DamagePart(
                "magic", per_tick, count=ticks, time_offset=0.5, hit_interval=0.5
            ),
        ),
        "target_max_health_sensitive": True,
        "detail": f"Dream Dust over 3 seconds; {ticks} half-second ticks selected.",
    }


def _blooming_blows(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    magic = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    true_damage = magic if bool(ctx.options.get("q_outer_edge", True)) else 0.0
    return mixed_damage(
        ctx,
        ability.get("name", "Blooming Blows"),
        rank,
        extract_cooldown(ability, rank),
        magic,
        true_damage,
        detail="Outer-edge option adds the sourced true-damage ring.",
    )


def _watch_out_eep(ctx: SlotCtx) -> dict[str, Any] | None:
    attribute = (
        "Increased Damage"
        if bool(ctx.options.get("w_epicenter", True))
        else "Magic Damage"
    )
    result = typed_damage(ctx, attribute, "magic", time_offset=0.759)
    if result:
        result["detail"] = (
            "Watch Out! Eep! epicenter branch is explicit; dash distance and "
            "slow are utility state."
        )
    return result


def _lilting_lullaby(ctx: SlotCtx) -> dict[str, Any] | None:
    if not bool(ctx.options.get("r_wake", True)):
        return no_damage(
            ctx,
            name="Lilting Lullaby",
            reason="The sleep is applied but no post-sleep waking damage is selected.",
        )
    result = typed_damage(ctx, "Magic Damage", "magic", time_offset=2.3)
    if result:
        result["detail"] = (
            "Lilting Lullaby wake damage after drowsy and sleep; the "
            "crowd-control window is state."
        )
    return result


SLOTS = {
    "P": _dream_laden_bough,
    "Q": _blooming_blows,
    "W": _watch_out_eep,
    "E": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "R": _lilting_lullaby,
}
OPTIONS = [
    {
        "key": "p_ticks",
        "type": "int",
        "default": 6,
        "min": 1,
        "max": 6,
        "label": "Dream Dust ticks",
    },
    {
        "key": "q_outer_edge",
        "type": "bool",
        "default": True,
        "label": "Blooming Blows outer edge",
    },
    {
        "key": "w_epicenter",
        "type": "bool",
        "default": True,
        "label": "Watch Out! Eep! epicenter",
    },
    {
        "key": "r_wake",
        "type": "bool",
        "default": True,
        "label": "Lilting Lullaby wake damage",
    },
]
ASSUMPTIONS = list(REVIEWED_MODULE_ASSUMPTIONS)
SOURCES = load_champion_sources("Lillia")
parse_abilities = build_parser(SLOTS, "Lillia")

MODULE_COVERAGE = {slot: "modeled" for slot in "PQWER"}
REVIEW_STATUS = "reviewed_module"
