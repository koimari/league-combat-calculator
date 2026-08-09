"""Soraka — revision-backed offensive slot map.

Starcall deals one magic hit. Equinox deals one hit on cast and the same hit
again after 1.5 seconds when the target remains in the zone. Its second hit is
an explicit option because crowd control does not guarantee that condition.
Soraka's passive and R do not damage enemies.

E8d: W (Astral Infusion) is an ally-only heal with no enemy damage.  The slot
is declared here so the ability is CAST in the fight rotation; the engine's
ally-support scanner then derives the heal packet from the cached W leveling
("Heal: 90 / 110 / 130 / 150 / 170 (+ 50% AP)", scope one_teammate).  The
cached cost row is 10% of maximum health per cast — a health cost, not mana —
so the module documents it and does not author a mana resource cost.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import extract_cooldown, extract_named, simple_damage


def _astral_infusion(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: zero-damage cast so the ally-support scanner emits the heal.

    Astral Infusion heals the selected ally (cached "Heal" row, 90-170 +
    50% AP); it costs 10% of Soraka's maximum health per cast, which the
    engine's mana/energy resource ledger does not model.  The entry carries
    the cached cooldown so the ability is scheduled like any other cast.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    return {
        "name": ability.get("name", "Astral Infusion"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        # The cached cost row is 10% of maximum health per cast — a health
        # cost, not mana.  Declare zero so the engine's mana stamp cannot
        # mislabel it as a 10-mana cast; the cost is documented, not modeled.
        "resource_cost": 0.0,
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "detail": "Ally-only heal (sourced by the support scanner); "
        "costs 10% of max health per cast, not modeled as mana.",
    }


def _equinox(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: initial hit plus the optional equal-damage eruption."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    per_hit = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    second_hit = bool(ctx.options.get("e_second_hit", True))
    count = 2 if second_hit else 1
    entry: dict[str, Any] = {
        "name": ability.get("name", "Equinox"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "parts": (
            DamagePart(
                "magic",
                per_hit,
                count=count,
                time_offset=0.0,
                hit_interval=1.5 if second_hit else None,
            ),
        ),
        "total_raw": per_hit * count,
        "damage_type": "magic",
        "detail": "Initial hit + eruption" if second_hit else "Initial hit only",
    }
    if second_hit:
        # The eruption refreshes ability-triggered item burns 1.5s later.
        entry["dot_duration"] = 1.5
    return entry


OPTIONS = [
    {
        "key": "e_second_hit",
        "type": "bool",
        "default": True,
        "label": "Target remains for E eruption",
    },
]

ASSUMPTIONS = [
    "Starcall counts one enemy-champion hit.",
    "Equinox's eruption is counted only when its target-remains option is on.",
    "Passive and Wish are excluded because they deal no enemy damage.",
    "Astral Infusion (W) is declared as a zero-damage cast so the ally-support "
    "scanner emits its sourced heal (90-170 + 50% AP); its 10%-of-max-health "
    "cost per cast is documented, not modeled as mana.",
]

SOURCES = [
    {
        "label": "Starcall",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Soraka/Starcall",
        "revision_id": 3953362,
        "revision_timestamp": "2025-09-11T19:22:43Z",
    },
    {
        "label": "Equinox",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Soraka/Equinox",
        "revision_id": 3907153,
        "revision_timestamp": "2025-06-06T18:23:34Z",
    },
]

SLOTS = {
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "W": _astral_infusion,
    "E": _equinox,
}

parse_abilities = build_parser(SLOTS, "Soraka")


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
    """Resolve Soraka self-healing events from its authored packet."""
    healing = []
    ability = _healing._ability(champion_data, "Q")
    rank = _healing._rank(ability_damages, "Q")
    per_tick = _healing.extract_named(
        ability, "Heal per Tick", rank, champion_stats, {}
    )
    total = _healing.extract_named(ability, "Total Heal", rank, champion_stats, {})
    tick_count = (
        max(1, min(100, int(round(total / per_tick))))
        if per_tick > 0.0 and total > 0.0
        else 0
    )
    for event in damage_events:
        if _healing._event_source(event) != "Q" or tick_count <= 0:
            continue
        trigger = _healing._trigger_fields(event)
        for index in range(1, tick_count + 1):
            healing.append(
                {
                    "time": float(event.get("time", 0.0)) + index * 0.2,
                    "amount": float(per_tick),
                    "source": "Starcall · Rejuvenation",
                    "kind": "champion_ability",
                    **trigger,
                }
            )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Soraka", derive_self_healing)
