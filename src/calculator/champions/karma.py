"""Karma's Mantra variants, tether recast and ally-shield state."""

from __future__ import annotations

from typing import Any

from ..ability_atoms import ability_field, ability_payload
from ..ability_spec import DamagePart
from .engine import CC_PER_PART, SlotCtx, build_parser
from .healing_contract import self_healing_rule
from .inputs import bool_option, champion_stat
from .module_helpers import no_damage
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
)
from .source_receipts import load_champion_sources


def _inner_flame(ctx: SlotCtx) -> dict[str, Any] | None:
    mantra = bool(ctx.option("q_mantra"))
    ability = ctx.ability("Q", 1 if mantra else 0)
    if ability is None:
        return None
    rank = ctx.rank_for("R") if mantra else ctx.rank_for("Q")
    rank = max(1, min(rank, 4 if mantra else 5))
    attr = "Total Damage" if mantra else "Magic Damage"
    value = extract_named(ability, attr, rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
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
    renewal = bool(ctx.option("w_renewal"))
    ability = ctx.ability("W", 1 if renewal else 0)
    if ability is None:
        return None
    rank = ctx.rank_for("R") if renewal else ctx.rank_for("W")
    rank = max(1, min(rank, 4 if renewal else 5))
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    holds = bool(ctx.option("w_tether_holds"))
    # The opening hit only tethers and reveals; the root arrives with the
    # second hit, "if the tether is not broken by the end of its duration".
    parts = [DamagePart("magic", value, time_offset=0.1, cc_kind="none")]
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
        ability_name(ability),
        rank,
        extract_cooldown(ctx.ability("W", 0), rank),
        value * (2 if holds else 1),
        "magic",
    )
    entry["parts"] = tuple(parts)
    entry["cc_reviewed"] = True
    entry["detail"] = (
        f"{'Renewal' if renewal else 'Focused Resolve'}; tether holds={holds}. "
        f"Healing/root duration are utility/state."
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
MODULE_CC = {"Q": "slow", "W": CC_PER_PART}

parse_abilities = build_parser(SLOTS, "Karma", cc_kinds=MODULE_CC)
OPTIONS = [
    bool_option("q_mantra", False, label="Mantra Soulflare"),
    bool_option("w_renewal", False, label="Mantra Renewal"),
    bool_option("w_tether_holds", True, label="Focused Resolve tether completes"),
]
ASSUMPTIONS = [
    "Mantra is an explicit next-ability state; Soulflare and Renewal use the Mantra "
    "rank rather than silently changing base ranks.",
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
SOURCES = load_champion_sources("Karma")


# Renewal (Mantra-empowered W): "Karma heals for 17% (+ 1% per 100 AP) of
# her missing health once on-cast, and again once the tether lasts its
# full duration or the target dies while tethered."  The tether lasts 2
# seconds (the module prices the completion hit at +2.0s).  The heal is a
# missing-health formula priced by the coupled timeline at each heal's
# timestamp (Darius pattern); the Mantra variant only exists when the
# parse picked it (its parsed name is "Renewal").  The heal lands on cast,
# even if the paired W packet was fully blocked.
# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Resolve Karma self-healing events from its authored packet."""
    healing = []
    w_payload = ability_payload(ability_damages, "W")
    if w_payload and str(ability_field(w_payload, "name")) == "Renewal":
        ap = champion_stat(champion_stats, "ability_power")
        ratio = 0.17 + ap / 10000.0

        def _renewal_heal(current_health: float, maximum_health: float) -> float:
            return max(0.0, maximum_health - current_health) * ratio

        for cast in cast_timeline or []:
            if cast.get("slot") != "W":
                continue
            cast_time = float(cast.get("time", 0.0))
            healing.extend(
                {
                    "time": cast_time + offset,
                    "amount": 0.0,
                    "amount_formula": _renewal_heal,
                    "source": "Renewal",
                    "kind": "champion_ability",
                    "actor_wide": True,
                }
                for offset in (0.0, 2.0)
            )
    return healing


SELF_HEALING_RULE = self_healing_rule("Karma")(derive_self_healing)
