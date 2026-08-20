"""Gragas' charge-scaled barrel and empowered brew attack."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .healing_contract import declare_healing_rule
from .module_helpers import no_damage
from .slotlib import damage_entry, extract_cooldown, extract_named
from .source_receipts import load_champion_sources


def _happy_hour(ctx: SlotCtx) -> dict[str, Any] | None:
    return no_damage(
        ctx,
        name="Happy Hour",
        reason="5.5% maximum-health heal after casting; no outgoing damage.",
        slot="P",
    )


def _barrel_roll(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    charged = bool(ctx.options.get("q_fully_fermented", True))
    attr = "Maximum Magic Damage" if charged else "Minimum Magic Damage"
    value = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Barrel Roll"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=2.0),)
    entry["detail"] = (
        f"{('Fully' if charged else 'minimum')} fermented barrel; source slow scales with the same charge state."
    )
    return entry


def _drunken_rage(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(ability, "Bonus Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Drunken Rage"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value),)
    entry["empowers_next_auto"] = True
    entry["event_order_certified"] = "single_hit"
    entry["detail"] = (
        "One brew-empowered basic attack; max-health term is evaluated against the live target."
    )
    entry["target_max_health_sensitive"] = True
    return entry


def _body_slam(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Body Slam"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value),)
    entry["event_order_certified"] = "single_hit"
    entry["detail"] = (
        "Collision damage plus sourced knockback/stun; cooldown refund is not assumed without a hit state."
    )
    return entry


def _explosive_cask(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Explosive Cask"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=0.5),)
    return entry


SLOTS = {
    "P": _happy_hour,
    "Q": _barrel_roll,
    "W": _drunken_rage,
    "E": _body_slam,
    "R": _explosive_cask,
}
# Q's cask detonation "slow[s] them for 2 seconds"; W only empowers an
# attack; E and R each lead with a displacement ("knocking them back") on
# the enemies they damage, so each declares its first-listed immobilize.
# P is the self-heal and authors no damage part.
MODULE_CC = {"Q": "slow", "W": "none", "E": "knockback", "R": "knockback"}

parse_abilities = build_parser(SLOTS, "Gragas", cc_kinds=MODULE_CC)

OPTIONS = [
    {
        "key": "q_fully_fermented",
        "type": "bool",
        "default": True,
        "label": "Barrel Roll fully fermented",
    },
]

ASSUMPTIONS = [
    "Barrel Roll exposes the minimum and fully fermented maximum damage branches; the source charge timing is not averaged.",
    "Drunken Rage is a single empowered attack with a target-max-health rider; the channel damage reduction is defensive state.",
    "Body Slam's cooldown refund requires a collision state and is not applied to every cast by default.",
]

SOURCES = load_champion_sources("Gragas")

SELF_HEALING_RULE = declare_healing_rule("Gragas")
