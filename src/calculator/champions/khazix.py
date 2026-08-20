"""Kha'Zix — full-entry reviewed CP10.3 module.

Option keys consumed by the shared parser: "p_ready", "q_isolated".
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import REVIEWED_MODULE_ASSUMPTIONS, no_damage
from .slotlib import extract_cooldown, extract_named, on_hit_entry, simple_damage
from .source_receipts import load_champion_sources


def _unseen_threat(ctx: SlotCtx) -> dict[str, Any] | None:
    if not bool(ctx.options.get("p_ready", True)):
        return no_damage(
            ctx,
            name="Unseen Threat",
            reason="The isolated-stealth empowered attack is not armed in this scenario.",
        )
    ability = ctx.ability()
    if ability is None:
        return None
    value = extract_named(
        ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target
    )
    result = on_hit_entry("Unseen Threat", value, "magic")
    result["detail"] = (
        "One empowered next basic attack after Kha'Zix leaves enemy vision; "
        "isolation is a target-state option."
    )
    return result


def _taste_their_fear(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    isolated = bool(ctx.options.get("q_isolated", True))
    attribute = "Isolated Target Physical Damage" if isolated else "Physical Damage"
    value = extract_named(ability, attribute, rank, ctx.stats, ctx.target)
    return {
        "name": ability.get("name", "Taste Their Fear"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "physical",
        "total_raw": value,
        "parts": (DamagePart("physical", value),),
        "detail": (
            "Isolated target branch is explicit; nearby-allies state disables "
            "the 210% branch."
        ),
        "event_order_certified": "single_hit",
    }


SLOTS = {
    "P": _unseen_threat,
    "Q": _taste_their_fear,
    # Each of Q/W/E deals its packet once, at the cast: the boundary claim
    # that carries MODULE_CC's reviewed answers into the event ledger.
    "W": simple_damage(
        attr="Physical Damage", dmg_type="physical", event_order_certified="single_hit"
    ),
    "E": simple_damage(
        attr="Physical Damage", dmg_type="physical", event_order_certified="single_hit"
    ),
    "R": lambda ctx: no_damage(
        ctx,
        name="Void Assault",
        reason=(
            "Invisibility, evolution and movement speed are state; the recast "
            "does not deal enemy damage."
        ),
    ),
}
OPTIONS = [
    {
        "key": "p_ready",
        "type": "bool",
        "default": True,
        "label": "Unseen Threat armed",
    },
    {
        "key": "q_isolated",
        "type": "bool",
        "default": True,
        "label": "Isolated target",
    },
]
ASSUMPTIONS = list(REVIEWED_MODULE_ASSUMPTIONS)
SOURCES = load_champion_sources("Kha'Zix")

# Cached kit review: the damaging slots this module prices are the
# UNevolved abilities — Taste Their Fear slashes, Void Spike explodes and
# Leap lands, none of them applying control.  The kit's two slows are the
# evolution bonus (Evolved Spike Racks) and the Unseen Threat empowered
# attack, neither of which is a slot packet this module emits.
MODULE_CC = {"Q": "none", "W": "none", "E": "none"}

parse_abilities = build_parser(SLOTS, "Kha'Zix", cc_kinds=MODULE_CC)

MODULE_COVERAGE = {
    slot: ("modeled" if slot != "R" else "no_damage") for slot in "PQWER"
}

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Kha'Zix")
