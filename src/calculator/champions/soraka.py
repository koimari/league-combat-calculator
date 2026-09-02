"""Soraka — revision-backed offensive slot map.

Starcall deals one magic hit. Equinox deals one hit on cast and the same hit
again after 1.5 seconds when the target remains in the zone. Its second hit is
an explicit option because crowd control does not guarantee that condition.
Soraka's passive and R do not damage enemies.

R (Wish) is a zero-damage cast so the ally-support scanner prices the
sourced team heal (350.0 to Soraka and every selected teammate at rank 3,
0 AP); its "+50% on targets below 40% of their maximum health" is a
live-health condition the scan cannot establish and is not priced.

P (Salvation) is ``no_damage``: movement only, with no enemy-damage clause
anywhere in the slot.  Its 90% bonus toward wounded allies is withheld on
its CONDITION, not for want of a channel — ``move_speed_percent`` is a live
``stat_buff`` key, folded through ``stats.resolve_move_speed`` by
``damage._apply_stat_buff_ultimates``.  The condition is "while facing
nearby allied champions below 40% of their maximum health", which needs
both an allied champion (a 1v1 surface has none) and live ally health;
this module withholds R's "+50% below 40% maximum health" on exactly that
ground.  See ASSUMPTIONS.

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
from .inputs import bool_option
from .module_contract import coverage
from .module_helpers import ranked_slot
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


@ranked_slot
def _equinox(ctx: SlotCtx, ability: dict[str, Any], rank: int) -> dict[str, Any] | None:
    """E: initial hit plus the optional equal-damage eruption."""

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
    "P (Salvation) is no_damage, NOT out_of_scope. Its single cached effect "
    "grants Soraka '90% bonus movement speed while facing nearby allied "
    "champions that are below 40% of their maximum health' (damageType null, "
    "affects Self, leveling []) — there is no enemy-damage clause anywhere in "
    "the slot, so there is no damage to miss. The grant is NOT published as a "
    "move_speed_percent stat_buff, and the blocker is the CONDITION, not the "
    "channel: the channel exists and Sivir R rides it. Two cached conditions "
    "gate it and this surface can establish neither — it needs nearby ALLIED "
    "CHAMPIONS (a 1v1 fight has none), each below 40% of maximum health (a "
    "live-health state the scan cannot establish; this module already "
    "withholds R's '+50% on targets below 40% of their maximum health' on "
    "exactly that ground). Publishing 90% unconditionally would assert a "
    "buff that is off for the whole fight — the Akshan-W rider convention, "
    "which documents a conditional movement grant instead of emitting it. "
    "The label is no_damage rather than an Olaf-R open because an ability "
    "movement stat_buff does not become damage here: Swiftmarch's "
    "adaptive_force_per_total_move_speed is resolved inside "
    "calculate_total_stats from the BUILD's move speed (stats.py, "
    "final_move_speed -> resolve_stat_effects) before any cast, while an "
    "ability stat_buff rewrites stats['move_speed'] afterwards, so the grant "
    "could only move champion_stats and the descriptive item_state_receipts, "
    "never a damage row (verified live: Teemo with Swiftmarch reads "
    "move_speed 395.0 at W0 and 452.088 at W5 with attack_damage, "
    "ability_power and total_damage identical). This is the Sivir-P verdict "
    "on the same axis.",
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
MODULE_CC = {"Q": "slow", "E": "root", "W": "none", "R": "none"}

parse_abilities = build_parser(SLOTS, "Soraka", cc_kinds=MODULE_CC)

# P is unemitted AND no_damage — the Azir-P direction, which
# ``module_contract`` blesses explicitly: no rule ties either label to
# whether the slot map emits the slot.  Salvation carries no enemy-damage
# clause at all, and its one grant is movement gated on a condition this
# surface cannot establish (see ASSUMPTIONS).
MODULE_COVERAGE = coverage(no_damage="P")


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Resolve Soraka self-healing events from its authored packet."""
    healing = []
    ability = _healing.ability_json(champion_data, "Q")
    rank = _healing.parsed_rank(ability_damages, "Q")
    per_tick = extract_named(ability, "Heal per Tick", rank, champion_stats, {})
    total = extract_named(ability, "Total Heal", rank, champion_stats, {})
    tick_count = (
        max(1, min(100, round(total / per_tick)))
        if per_tick > 0.0 and total > 0.0
        else 0
    )
    for event in damage_events:
        if _healing.event_source(event) != "Q" or tick_count <= 0:
            continue
        trigger = _healing.trigger_fields(event)
        healing.extend(
            {
                "time": float(event.get("time", 0.0)) + index * 0.2,
                "amount": float(per_tick),
                "source": "Starcall · Rejuvenation",
                "kind": "champion_ability",
                **trigger,
            }
            for index in range(1, tick_count + 1)
        )
    return healing


SELF_HEALING_RULE = self_healing_rule("Soraka")(derive_self_healing)
