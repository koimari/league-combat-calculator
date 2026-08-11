"""Karma's Mantra variants, tether recast and ally-shield state."""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import no_damage, source_row
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
)


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
    parts = [DamagePart("magic", value, time_offset=0.1)]
    if holds:
        parts.append(
            DamagePart(
                "magic",
                value,
                time_offset=2.0,
                cc_kind="root",
                cc_duration=extract_value(ability, "Root Duration", rank),
            )
        )
    entry = damage_entry(
        ability.get("name", "Focused Resolve"),
        rank,
        extract_cooldown(ctx.ability("W", 0), rank),
        value * (2 if holds else 1),
        "magic",
    )
    entry["parts"] = tuple(parts)
    entry["cc_reviewed"] = True
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
parse_abilities = build_parser(SLOTS, "Karma")
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
    "E (Inspire) shields Karma or the selected teammate the sourced "
    "Shield Strength (80-280 + 60% AP) for 2.5s (self-or-target scope "
    "one_teammate with self fallback in a solo fight; selection key "
    "shield:E:<cast>); the 40% movement speed for 2s is utility state.",
    "Mantra-empowered Inspire (Defiance) is documented-only: the cached "
    "R data carries no sourced Defiance shield numbers (the Mantra "
    "description only names the empowered effect), so the AoE ally "
    "spread of the enhanced shield fails closed instead of inventing a "
    "value.",
]
SOURCES = [
    source_row(
        "Karma parent entry",
        "https://wiki.leagueoflegends.com/en-us/Karma",
        4001401,
        "2026-03-20T15:07:52Z",
    ),
    source_row(
        "Karma Q template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Karma/Q",
        2863960,
        "2019-11-03T19:57:17Z",
    ),
    source_row(
        "Karma W template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Karma/W",
        2864255,
        "2019-11-03T20:10:04Z",
    ),
    source_row(
        "Karma E template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Karma/E",
        2864401,
        "2019-11-03T20:12:35Z",
    ),
    source_row(
        "Karma R template",
        "https://wiki.leagueoflegends.com/en-us/Template:Data_Karma/R",
        2864547,
        "2019-11-03T20:16:00Z",
    ),
]
MODULE_COVERAGE = {slot: "modeled" for slot in ("P", "Q", "W", "E", "R")}
REVIEW_STATUS = "reviewed_module"

from .. import healing_helpers as _healing  # pylint: disable=wrong-import-position


# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument,wrong-import-position
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Karma self-healing events from its authored packet."""
    healing = []
    if str(ability_damages.get("W", {}).get("name", "")) == "Renewal":
        ap = float(champion_stats.get("ability_power", 0.0) or 0.0)
        ratio = 0.17 + ap / 10000.0

        def _renewal_heal(current_health: float, maximum_health: float) -> float:
            return max(0.0, maximum_health - current_health) * ratio

        for cast in cast_timeline or []:
            if cast.get("slot") != "W":
                continue
            cast_time = float(cast.get("time", 0.0))
            for offset in (0.0, 2.0):
                healing.append(
                    {
                        "time": cast_time + offset,
                        "amount": 0.0,
                        "amount_formula": _renewal_heal,
                        "source": "Renewal",
                        "kind": "champion_ability",
                        "actor_wide": True,
                    }
                )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Karma", derive_self_healing)
