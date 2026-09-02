"""Lissandra — revision-backed direct-damage slot map.

Q, W, E, and R each deal one sourced magic-damage instance. E's recast only
moves Lissandra, while R's ice field deals the same damage whether she targets
herself or an enemy.

P (Iceborn Subjugation) spawns a Frozen Thrall from a NEARBY ENEMY
CHAMPION'S corpse when it dies; the thrall chases for 4 seconds, then
shatters for the cached "Per-Level Scaling" magic damage (120 : 520 over
levels 1-18) + 50% AP (prose-only rider, not a structured modifier).
Roadmap session 4 batch C (2026-08-21): closes the single out_of_scope
slot with an explicit zero-damage boundary receipt (the Karthus P
"Death Defied" / Kog'Maw P "Icathian Surprise" pattern) rather than
leaving MODULE_COVERAGE reading "out_of_scope" for a kill-triggered
effect this calculator's deterministic 1v1 fight cannot enter (the
target never dies in the model). The sourced would-be magnitude is
computed and reported in the row's detail text for traceability, but
priced at zero damage since the trigger never fires here — the thrall
is also a summoned pet on its own timeline, an axis the engine does
not have, so nothing but the boundary receipt could be priced anyway.
"""

from typing import Any

from .. import healing_helpers as _healing
from .engine import CC_PER_PART, SlotCtx, build_parser
from .healing_contract import self_healing_rule
from .slotlib import (
    ability_name,
    damage_entry,
    extract_named,
    simple_damage,
    with_control,
)
from .source_receipts import load_champion_sources

OPTIONS: list[dict[str, Any]] = []


def _iceborn_subjugation(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: zero-damage receipt — a kill-only trigger outside the fight.

    Iceborn Subjugation spawns a Frozen Thrall whenever a nearby ENEMY
    CHAMPION dies; the thrall chases for 4 seconds then shatters for
    the cached "Per-Level Scaling" magic damage (120 : 520 over levels
    1-18) plus a prose-only "+50% AP" rider (not a structured
    modifier, so not read here). The deterministic single-target fight
    never kills its target, so the passive contributes zero damage
    here; this receipt documents the boundary — with the sourced
    would-be magnitude — so the alive-state package is complete.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    entry = damage_entry(
        ability_name(ability),
        ctx.level,
        0.0,
        0.0,
        "magic",
    )
    entry["parts"] = ()
    would_be = extract_named(
        ability, "Per-Level Scaling", ctx.level, ctx.stats, ctx.target
    )
    entry["detail"] = (
        "Kill-only trigger: whenever a nearby enemy champion dies, "
        "Lissandra spawns a Frozen Thrall that chases for 4 seconds "
        "then shatters for the sourced "
        f"{would_be:g} magic damage (cached 'Per-Level Scaling' at "
        f"champion level {ctx.level}) + 50% AP (prose-only, not "
        "modeled) to nearby enemies. The deterministic 1v1 fight's "
        "target never dies in the model; priced at zero damage as a "
        "documented boundary."
    )
    return entry


ASSUMPTIONS = [
    "Iceborn Subjugation (P) is a kill-only trigger: it fires when a "
    "nearby ENEMY CHAMPION dies, spawning a Frozen Thrall that shatters "
    "for the sourced 120 : 520 (by champion level) magic damage + 50% AP "
    "(prose-only rider, not modeled). The deterministic 1v1 fight's "
    "target never dies, so this boundary is priced at zero damage "
    "(MODULE_COVERAGE: modeled, not out_of_scope) — the would-be "
    "magnitude is reported in the row's detail text",
    "Glacial Path counts its outward hit; the recast is movement only.",
    "Frozen Tomb counts one ice-field hit, whether cast on Lissandra or an enemy.",
]

SOURCES = load_champion_sources("Lissandra")

# Each slot deals its one sourced instance at the cast (the module
# docstring's own claim), so each certifies that boundary — which is what
# carries MODULE_CC's reviewed kinds into the event ledger.
SLOTS = {
    "P": _iceborn_subjugation,
    "Q": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    # Ring of Frost carries its sourced root duration onto the hit.
    "W": with_control(
        simple_damage(
            attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
        ),
        duration_attr="Root Duration",
    ),
    "E": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "R": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
}

# Cached kit review: Q "slows enemies hit for 1.5 seconds", W deals damage
# "and root[s] them for a duration", E's claw only decelerates itself, and
# the R instance this module prices is the ice field, which deals damage
# "and slow[s] them for 0.5 seconds" on either cast — the enemy cast's
# 1.5-second stun is not the hit the module counts (ASSUMPTIONS above).
# P's kill-boundary row prices nothing and authors no part, so it
# declares no kind.
MODULE_CC = {"Q": "slow", "W": "root", "E": "none", "R": "slow", "P": CC_PER_PART}

parse_abilities = build_parser(SLOTS, "Lissandra", cc_kinds=MODULE_CC)


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Resolve Lissandra self-healing events from its authored packet."""
    healing = []
    r = _healing.ability_json(champion_data, "R")
    r_rank = _healing.parsed_rank(ability_damages, "R")
    min_tick = extract_named(r, "Minimum Heal per Tick", r_rank, champion_stats)
    max_tick = extract_named(r, "Maximum Heal per Tick", r_rank, champion_stats)
    for payment in _healing.payments(
        _healing.HealAnchor.CAST_SCHEDULE, "R", damage_events, cast_timeline
    ):
        trigger = _healing.trigger_fields(payment.event)
        healing.extend(
            {
                "time": payment.cast_time + index * 0.25,
                "amount": 0.0,
                "amount_formula": _healing.missing_health_scaled_heal(
                    min_tick, max_tick
                ),
                "source": "Frozen Tomb",
                "kind": "champion_ability",
                **trigger,
            }
            for index in range(1, 11)
        )
    return healing


SELF_HEALING_RULE = self_healing_rule("Lissandra")(derive_self_healing)
