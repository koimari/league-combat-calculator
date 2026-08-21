"""Lissandra — revision-backed direct-damage slot map.

Q, W, E, and R each deal one sourced magic-damage instance. E's recast only
moves Lissandra, while R's ice field deals the same damage whether she targets
herself or an enemy.

P (Iceborn Subjugation) spawns a Frozen Thrall from a NEARBY ENEMY
CHAMPION'S corpse when it dies; the thrall chases for 4 seconds, then
shatters for the cached "Per-Level Scaling" magic damage (120-1180 by
champion level) + 50% AP (prose-only rider, not a structured modifier).
Roadmap session 4 batch C (2026-08-21): closes the single out_of_scope
slot with an explicit zero-damage boundary receipt (the Karthus P
"Death Defied" / Kog'Maw P "Icathian Surprise" pattern) rather than
leaving MODULE_COVERAGE reading "out_of_scope" for a kill-triggered
effect this calculator's deterministic 1v1 fight cannot enter (the
target never dies in the model). The sourced would-be magnitude is
computed and reported in the row's detail text for traceability, but
priced at zero damage since the trigger never fires here.
"""

from typing import Any

from .engine import SlotCtx, build_parser
from .slotlib import damage_entry, extract_named, simple_damage, with_control

OPTIONS: list[dict[str, Any]] = []


def _iceborn_subjugation(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: zero-damage receipt — a kill-only trigger outside the fight.

    Iceborn Subjugation spawns a Frozen Thrall whenever a nearby ENEMY
    CHAMPION dies; the thrall chases for 4 seconds then shatters for
    the cached "Per-Level Scaling" magic damage (120-1180 by champion
    level) plus a prose-only "+50% AP" rider (not a structured
    modifier, so not read here). The deterministic single-target fight
    never kills its target, so the passive contributes zero damage
    here; this receipt documents the boundary — with the sourced
    would-be magnitude — so the alive-state package is complete.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    entry = damage_entry(
        ability.get("name", "Iceborn Subjugation"),
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
    "for the sourced 120-1180 (by champion level) magic damage + 50% AP "
    "(prose-only rider, not modeled). The deterministic 1v1 fight's "
    "target never dies, so this boundary is priced at zero damage "
    "(MODULE_COVERAGE: modeled, not out_of_scope) — the would-be "
    "magnitude is reported in the row's detail text",
    "Glacial Path counts its outward hit; the recast is movement only.",
    "Frozen Tomb counts one ice-field hit, whether cast on Lissandra or an enemy.",
]

SOURCES = [
    {
        "label": "Ice Shard",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Lissandra/Ice_Shard",
        "revision_id": 4007664,
        "revision_timestamp": "2026-04-12T10:26:56Z",
    },
    {
        "label": "Ring of Frost",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Lissandra/Ring_of_Frost",
        "revision_id": 3936419,
        "revision_timestamp": "2025-07-24T17:33:52Z",
    },
    {
        "label": "Glacial Path",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Lissandra/Glacial_Path",
        "revision_id": 4007666,
        "revision_timestamp": "2026-04-12T10:34:41Z",
    },
    {
        "label": "Frozen Tomb",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Lissandra/Frozen_Tomb",
        "revision_id": 4017996,
        "revision_timestamp": "2026-05-14T13:55:57Z",
    },
]

SLOTS = {
    "P": _iceborn_subjugation,
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "W": with_control(
        simple_damage(attr="Magic Damage", dmg_type="magic"),
        kind="root",
        duration_attr="Root Duration",
    ),
    "E": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "R": simple_damage(attr="Magic Damage", dmg_type="magic"),
}

parse_abilities = build_parser(SLOTS, "Lissandra")


# Authoritative review metadata (issue #161).
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
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
    """Resolve Lissandra self-healing events from its authored packet."""
    healing = []
    r = _healing._ability(champion_data, "R")
    r_rank = _healing._rank(ability_damages, "R")
    min_tick = _healing.extract_named(
        r, "Minimum Heal per Tick", r_rank, champion_stats
    )
    max_tick = _healing.extract_named(
        r, "Maximum Heal per Tick", r_rank, champion_stats
    )
    for event in _healing._attributed_events(
        damage_events, lambda source, _event: source == "R"
    ):
        trigger = _healing._trigger_fields(event)
        for index in range(1, 11):
            healing.append(
                {
                    "time": float(event.get("time", 0.0)) + index * 0.25,
                    "amount": 0.0,
                    "amount_formula": _healing._missing_health_scaled_heal(
                        min_tick, max_tick
                    ),
                    "source": "Frozen Tomb",
                    "kind": "champion_ability",
                    **trigger,
                }
            )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Lissandra", derive_self_healing)
