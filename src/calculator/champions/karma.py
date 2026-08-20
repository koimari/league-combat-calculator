"""Karma's Mantra variants, tether recast and ally-shield state."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import no_damage
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
)
from .source_receipts import load_champion_sources


def _inner_flame(ctx: SlotCtx) -> dict[str, Any] | None:
    mantra = bool(ctx.options.get("q_mantra", False))
    ability = ctx.ability("Q", 1 if mantra else 0)
    if ability is None:
        return None
    rank = ctx.rank_for("R") if mantra else ctx.rank_for("Q")
    rank = max(1, min(rank, 4 if mantra else 5))
    attr = "Total Damage" if mantra else "Magic Damage"
    value = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Inner Flame"),
        rank,
        extract_cooldown(ctx.ability("Q", 0), rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=0.25),)
    entry["detail"] = (
        "Mantra Soulflare field/detonation is included only when the explicit Mantra toggle is on."
    )
    return entry


def _focused_resolve(ctx: SlotCtx) -> dict[str, Any] | None:
    renewal = bool(ctx.options.get("w_renewal", False))
    ability = ctx.ability("W", 1 if renewal else 0)
    if ability is None:
        return None
    rank = ctx.rank_for("R") if renewal else ctx.rank_for("W")
    rank = max(1, min(rank, 4 if renewal else 5))
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    holds = bool(ctx.options.get("w_tether_holds", True))
    # The opening hit only tethers and reveals; the root arrives with the
    # second hit, "if the tether is not broken by the end of its duration".
    parts = [DamagePart("magic", value, time_offset=0.1, cc_kind="none")]
    if holds:
        parts.append(DamagePart("magic", value, time_offset=2.0, cc_kind="root"))
    entry = damage_entry(
        ability.get("name", "Focused Resolve"),
        rank,
        extract_cooldown(ctx.ability("W", 0), rank),
        value * (2 if holds else 1),
        "magic",
    )
    entry["parts"] = tuple(parts)
    entry["detail"] = (
        f"{'Renewal' if renewal else 'Focused Resolve'}; tether holds={holds}. Healing/root duration are utility/state."
    )
    return entry


SLOTS = {
    "P": lambda ctx: no_damage(
        ctx,
        name="Gathering Fire",
        reason="Mantra cooldown refunds are a cast-state mechanic.",
    ),
    "Q": _inner_flame,
    "W": _focused_resolve,
    "E": lambda ctx: no_damage(
        ctx,
        name="Inspire/Defiance",
        reason="Shield, ally spread and movement speed are ally-facing utility.",
    ),
    "R": lambda ctx: no_damage(
        ctx,
        name="Mantra",
        reason="Mantra empowers the next Q/W/E variant; the toggle itself has no outgoing damage.",
    ),
}
# Inner Flame's explosion "slow[s] them by 40% for 1.5 seconds" and its
# Mantra field slows by 50%, so Q has one answer either way.  W's two hits
# do not (see _focused_resolve).  P, E and R author no damage part.
MODULE_CC = {"Q": "slow"}

parse_abilities = build_parser(SLOTS, "Karma", cc_kinds=MODULE_CC)
OPTIONS = [
    {"key": "q_mantra", "type": "bool", "default": False, "label": "Mantra Soulflare"},
    {"key": "w_renewal", "type": "bool", "default": False, "label": "Mantra Renewal"},
    {
        "key": "w_tether_holds",
        "type": "bool",
        "default": True,
        "label": "Focused Resolve tether completes",
    },
]
ASSUMPTIONS = [
    "Mantra is an explicit next-ability state; Soulflare and Renewal use the Mantra rank rather than silently changing base ranks.",
    "Focused Resolve emits one or two sourced magic hits depending on the tether-completion input.",
    "Inspire/Defiance shields and Gathering Fire cooldown refunds remain ally/state utility.",
]
SOURCES = load_champion_sources("Karma")

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Karma")
