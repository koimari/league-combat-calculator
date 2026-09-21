"""Soraka: revision-backed offensive slot map.

Q (Starcall) deals one magic hit.  E (Equinox) deals one hit on cast and the
same hit again after 1.5 seconds if the target stays in the zone, which crowd
control does not guarantee, so the second hit is an explicit option.
W (Astral Infusion) is an ally-only heal.  The slot is declared here so the
rotation CASTS the ability, and the support scanner derives the heal packet from
the cached W leveling.  Its cached cost row is 10% of maximum health per cast, a
health cost rather than mana, so the module documents it and authors no resource
cost.
R (Wish) is a zero-damage cast whose sourced team heal the scanner prices.  Its
"+50% on targets below 40% of their maximum health" is a live-health condition
no scan establishes and is not priced.
P (Salvation) is ``no_damage``, movement only.  Its 90% bonus toward wounded
allies is withheld on its CONDITION rather than for want of a channel:
``move_speed_percent`` is a live ``stat_buff`` key, but the condition needs both
an allied champion, which a duel has none of, and live ally health.
"""

from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from ..damage_event_row import event_time as _row_time
from .contract_vocabulary import coverage
from .engine import SlotCtx, build_parser
from .healing_contract import SelfHealCtx, self_healing_rule
from .inputs import bool_option
from .module_helpers import ranked_slot
from .slot_control import park_control_interval
from .slot_entries import damage_entry, support_cast
from .slot_extract import ability_name, extract_cooldown, extract_named, extract_value
from .slotlib import simple_damage
from .source_receipts import load_champion_sources


@ranked_slot
def _equinox(ctx: SlotCtx, ability: dict[str, Any], rank: int) -> dict[str, Any] | None:
    """E: initial hit plus the optional equal-damage eruption."""

    per_hit = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    second_hit = bool(ctx.option("e_second_hit"))
    count = 2 if second_hit else 1
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        per_hit * count,
        "magic",
        parts=(
            DamagePart(
                "magic",
                per_hit,
                count=count,
                time_offset=0.0,
                hit_interval=1.5 if second_hit else None,
            ),
        ),
        detail="Initial hit + eruption" if second_hit else "Initial hit only",
    )
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
    bool_option(
        "e_second_hit",
        True,
        label="Target remains for E eruption",
        rotation={"role": "irrelevant", "slot": "E"},
    ),
]

ASSUMPTIONS = [
    "Starcall counts one enemy-champion hit.",
    "Equinox's eruption is counted only when its target-remains option is on.",
    "Passive and Wish are excluded because they deal no enemy damage.",
    "P (Salvation) is no_damage, NOT out_of_scope: no enemy-damage clause exists in "
    "the slot.",
    "Its single cached effect grants 90% bonus movement speed near allies below 40% "
    "maximum health.",
    "damageType is null, it affects Self, and leveling is empty.",
    "The grant is NOT published as a move_speed_percent stat_buff, and the blocker is "
    "the CONDITION.",
    "The channel exists and Sivir R rides it.",
    "It needs nearby ALLIED CHAMPIONS, which a 1v1 fight has none of.",
    "Each must be below 40% of maximum health, a live-health state the scan cannot "
    "establish.",
    "This module already withholds R's '+50% on targets below 40% of their maximum "
    "health' on that ground.",
    "Publishing 90% unconditionally would assert a buff off for the whole fight, the "
    "Akshan-W convention.",
    "The label is no_damage because an ability movement stat_buff does not become "
    "damage here.",
    "Swiftmarch's adaptive_force_per_total_move_speed resolves in "
    "calculate_total_stats before any cast.",
    "An ability stat_buff rewrites stats['move_speed'] afterwards, so it moves "
    "champion_stats only.",
    "Teemo with Swiftmarch reads move_speed 395.0 at W0 and 452.088 at W5, damage "
    "identical.",
    "This is the Sivir-P verdict on the same axis.",
    "Astral Infusion (W) is a zero-damage cast so the scanner emits its sourced heal, "
    "90 to 170 + 50% AP.",
    "W's 10%-of-maximum-health cost per cast is documented, not modeled as mana.",
    "W's cached cost row, 10 at every rank in '%' units, is the health-cost leg only.",
    "Astral Infusion costs two resources: '10% Current Health, {{ cost }} Mana' per "
    "ddragon costType.",
    "The wiki cache never captured the mana leg (bin SorakaW 'mana' [40, 45, 50, 55, "
    "60]).",
    "No key in data/champions.json's W entry carries it, verified 16.15/16.16.1 "
    "against cdtb soraka.bin.json.",
    "ddragon costBurn reads '40/45/50/55/60'; this is a known-degraded parse, not a "
    "patch change.",
    "patch_regression diffs the %-health row against the game's mana field, a "
    "row-mapping artifact.",
    "The module declares resource_cost 0.0 and never modeled W's mana leg, so no "
    "behavior is affected.",
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


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Resolve Soraka self-healing events from its authored packet."""
    healing = []
    per_tick, total = ctx.ranked_rows("Q", "Heal per Tick", "Total Heal")
    tick_count = (
        max(1, min(100, round(total / per_tick)))
        if per_tick > 0.0 and total > 0.0
        else 0
    )
    for event in ctx.damage_events:
        if _healing.ledger_source_key(event) != "Q" or tick_count <= 0:
            continue
        trigger = _healing.trigger_fields(event)
        healing.extend(
            {
                "time": _row_time(event) + index * 0.2,
                "amount": float(per_tick),
                "source": "Starcall · Rejuvenation",
                "kind": "champion_ability",
                **trigger,
            }
            for index in range(1, tick_count + 1)
        )
    return healing


SELF_HEALING_RULE = self_healing_rule("Soraka")(derive_self_healing)
