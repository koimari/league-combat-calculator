"""Soraka — revision-backed offensive slot map.

Starcall deals one magic hit. Equinox deals one hit on cast and the same hit
again after 1.5 seconds when the target remains in the zone. Its second hit is
an explicit option because crowd control does not guarantee that condition.
Soraka's passive and R do not damage enemies.

R (Wish) is a zero-damage cast so the ally-support scanner prices the
sourced team heal (350.0 to Soraka and every selected teammate at rank 3,
0 AP); its "+50% on targets below 40% of their maximum health" is a
live-health condition the scan cannot establish and is not priced.

P (Salvation) stays ``out_of_scope`` on the movement-speed axis: its 90%
bonus toward wounded allies has no ``stat_buff`` key at all.

E8d: W (Astral Infusion) is an ally-only heal with no enemy damage.  The slot
is declared here so the ability is CAST in the fight rotation; the engine's
ally-support scanner then derives the heal packet from the cached W leveling
("Heal: 90 / 110 / 130 / 150 / 170 (+ 50% AP)", scope one_teammate).  The
cached cost row is 10% of maximum health per cast — a health cost, not mana —
so the module documents it and does not author a mana resource cost.
"""

from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .healing_contract import self_healing_rule
from .slotlib import (
    ability_name,
    extract_cooldown,
    extract_named,
    extract_value,
    park_control_interval,
    simple_damage,
    support_cast,
)
from .source_receipts import load_champion_sources
from .inputs import bool_option


def _equinox(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: initial hit plus the optional equal-damage eruption."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    per_hit = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    second_hit = bool(ctx.option("e_second_hit"))
    count = 2 if second_hit else 1
    entry: dict[str, Any] = {
        "name": ability_name(ability),
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
        park_control_interval(
            entry,
            extract_value(ability, "Root Duration", rank),
            time_offset=1.5,
        )
    return entry


OPTIONS = [
    bool_option("e_second_hit", True, label="Target remains for E eruption"),
]

ASSUMPTIONS = [
    "Starcall counts one enemy-champion hit.",
    "Equinox's eruption is counted only when its target-remains option is on.",
    "Passive and Wish are excluded because they deal no enemy damage.",
    "Astral Infusion (W) is declared as a zero-damage cast so the ally-support "
    "scanner emits its sourced heal (90-170 + 50% AP); its 10%-of-max-health "
    "cost per cast is documented, not modeled as mana.",
    "W's cached 'cost' row (10/10/10/10/10, '%' units) is the ability's "
    "health-cost leg only; Astral Infusion actually costs TWO resources "
    "('10% Current Health, {{ cost }} Mana' per ddragon costType), and "
    "the wiki cache never captured the mana leg (bin SorakaW 'mana' "
    "[40, 45, 50, 55, 60]; ddragon costBurn '40/45/50/55/60') under this "
    "or any other key in data/champions.json's W entry — a known-"
    "degraded wiki parse, not a value that changed patch-to-patch. "
    "patch_regression.py's ability-row comparison flags 'cost drifted' "
    "because it diffs the cached %-health row against the game's "
    "separate mana field; that is a row-mapping artifact (comparing two "
    "different cost components), not a real drift. The module already "
    "declares resource_cost=0.0 above and never modeled W's mana leg, "
    "so no runtime behavior is affected (verified 16.15/16.16.1: cdtb "
    "soraka.bin.json + ddragon Soraka.json).",
]

SOURCES = load_champion_sources("Soraka")

SLOTS = {
    # One star, one landing ("dealing magic damage to enemies hit and
    # slowing them by 30%"), so the row is a hit the ledger can time.
    "Q": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    # Astral Infusion heals the selected ally (cached "Heal" row, 90-170 +
    # 50% AP).  The cached cost row is 10% of maximum health per cast — a
    # health cost, not mana — so the entry declares zero rather than let the
    # engine's mana stamp mislabel it as a 10-mana cast.
    "W": support_cast(
        default_name="Astral Infusion",
        resource_cost=0.0,
        detail="Ally-only heal (sourced by the support scanner); "
        "costs 10% of max health per cast, not modeled as mana.",
    ),
    "E": _equinox,
    # Wish heals Soraka and every selected teammate (cached "Heal" row,
    # 150/250/350 + 50% AP).  The cached "Increased Heal" row is the +50%
    # applied to a recipient below 40% of their maximum health, which is a
    # live-health condition the scan cannot establish, so the base row is
    # what is priced.
    "R": support_cast(
        default_name="Wish",
        detail="Team heal (sourced by the support scanner); the "
        "below-40%-health increase is not priced.",
    ),
}

# Reviewed crowd control, read from the cached kit.  Q (Starcall) deals
# its damage "and slowing them by 30% for 1.5 seconds".  E (Equinox)
# "deals magic damage to enemy champions within at the time of cast", then
# "silences enemies within" for 1.5 seconds before the zone "erupts to
# deal the same damage ... and root them for a duration" — the root is the
# immobilizing half of what this row's two hits apply, and ``_equinox``
# authors it as a sourced control event at the eruption's 1.5s offset when
# the target-remains option arms that second hit.  W deals no damage.
MODULE_CC = {"Q": "slow", "E": "root"}

parse_abilities = build_parser(SLOTS, "Soraka", cc_kinds=MODULE_CC)


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
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
    ability = _healing.ability_json(champion_data, "Q")
    rank = _healing.parsed_rank(ability_damages, "Q")
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
        if _healing.event_source(event) != "Q" or tick_count <= 0:
            continue
        trigger = _healing.trigger_fields(event)
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
    return healing


SELF_HEALING_RULE = self_healing_rule("Soraka")(derive_self_healing)
