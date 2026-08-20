"""Warwick — CP10.9 packet module with the E9-1 R gap fix and the FC riders.

E9-1 closes the remaining audit gap: R (Infinite Duress) was declared
no_damage although the wiki cache carries "Total Magic Damage"
175/350/525 + 167% bonus AD over the 1.5-second suppress channel (the
wiki notes the channel deals magic damage every 0.25 seconds and that
on-hit/on-attack effects apply 3 times over its duration).  This
module prices the total as the R cast, which also lets healing.py's
existing 100%-of-R-damage self-heal rule fire (it previously could
never trigger because the module emitted no R damage events).

The coverage-frontier riders close P and W:

- P (Eternal Hunger) is the kit's on-hit rider — "Warwick deals
  6 : 60.76 (based on level) (+ 15% bonus AD) (+ 10% AP) bonus magic
  damage on-hit" — read from the cached per-level row and layered onto
  every basic attack.  It IS an on-hit, so item on-hit effects do not
  proc from it; it rides the swing they already proc from.  Its
  low-health self-heal is paid by the Warwick healing rule off the
  share this module publishes (``self_heal_share_of_damage``).
- W (Blood Hunt) is the attack-speed steroid the cache carries, applied
  through the engine's ``stat_buff`` channel.  The active marks the
  target "regardless of their current health", so a cast W always
  grants the base bonus; the doubled tier reads the shared
  ``target_missing_hp_pct`` option.  Blood Hunt's movement speed has no
  engine channel and stays unpriced.

E (Primal Howl) stays ``out_of_scope``: its 35-55% Damage Reduction is
damage *taken*, an axis the fight engine does not model at all (and the
recast's fear plus 90% slow are crowd control the model does not price).
"""

from functools import partial
from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, ONHIT, SlotCtx
from .healing_contract import declare_healing_rule
from .module_helpers import missing_hp_fraction
from .packet_module import build_packet_module
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    on_hit_entry,
    stat_buff,
    with_item_on_hits,
)

# Sourced channel (wiki R): "deal magic damage every 0.25 seconds" over
# the up-to-1.5s suppress; "applies on-hit effects and triggers
# on-attack effects 3 times over its duration".
_R_CHANNEL_SECONDS = 1.5

# HARDCODED: verify on patch updates — Eternal Hunger's heal is cached
# PROSE, not a leveling row: "While below 50% maximum health, Warwick
# also heals for 100% of the post-mitigation damage dealt by Eternal
# Hunger, increased to 250% while below 25% maximum health."
_HUNGER_HEAL_HEALTH_PERCENT = 50.0
_HUNGER_HEAL_SHARE = 1.0
_HUNGER_RAGE_HEALTH_PERCENT = 25.0
_HUNGER_RAGE_SHARE = 2.5

# Blood Hunt's two tiers are the TARGET's health: the passive triggers
# below 50% maximum health and both bonuses are "doubled against enemies
# who are below 25% of their maximum health".  Below 25% maximum health
# is more than 75% missing.
_BLOOD_HUNT_DOUBLED_MISSING = 0.75


def _infinite_duress(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: Total Magic Damage over the 1.5s suppress channel."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    total = extract_named(ability, "Total Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Infinite Duress"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", total, time_offset=0.0),)
    entry["dot_duration"] = _R_CHANNEL_SECONDS
    entry["detail"] = (
        "Total Magic Damage 175/350/525 + 167% bonus AD over the "
        f"{_R_CHANNEL_SECONDS:g}s suppress channel (magic damage every "
        "0.25s; the wiki's 3 on-hit applications are item on-hit/on-"
        "attack riders, not extra ability damage, and are not "
        "multiplied — the cache publishes no per-tick row)"
    )
    return entry


def _hunger_heal_share(health_percent: float) -> float:
    """The share of Eternal Hunger's damage Warwick heals at a health %."""
    if health_percent < _HUNGER_RAGE_HEALTH_PERCENT:
        return _HUNGER_RAGE_SHARE
    if health_percent < _HUNGER_HEAL_HEALTH_PERCENT:
        return _HUNGER_HEAL_SHARE
    return 0.0


def _eternal_hunger(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: bonus magic damage on every basic attack, plus its heal share."""
    ability = ctx.ability()
    if ability is None:
        return None
    per_hit = extract_named(
        ability, "Per-Level Scaling", ctx.level, ctx.stats, ctx.target, level=ctx.level
    )
    if per_hit <= 0:
        return None

    entry = on_hit_entry(ability.get("name", "Eternal Hunger"), per_hit, "magic")
    health_percent = min(max(float(ctx.option("p_self_health_percent")), 0.0), 100.0)
    share = _hunger_heal_share(health_percent)
    # The healing rule (healing_legacy, "Warwick") pays this share of every
    # post-mitigation Eternal Hunger hit.  The module owns the health state,
    # so the share is published here rather than re-derived there.
    entry["self_heal_share_of_damage"] = share
    entry["detail"] = (
        f"{per_hit:.2f} bonus magic damage on-hit (6 : 60.76 based on level "
        "+ 15% bonus AD + 10% AP); Warwick at "
        f"{health_percent:g}% health heals for {share:.0%} of the "
        "post-mitigation damage it deals"
    )
    return entry


_eternal_hunger.phase = ONHIT


_BLOOD_HUNT_TIERS = {
    False: (
        "Bonus Attack Speed",
        stat_buff("Bonus Attack Speed", "bonus_attack_speed"),
    ),
    True: (
        "Increased Attack Speed",
        stat_buff("Increased Attack Speed", "bonus_attack_speed"),
    ),
}


def _blood_hunt(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: the Blood Hunt attack-speed steroid, base or doubled."""
    doubled = missing_hp_fraction(ctx) > _BLOOD_HUNT_DOUBLED_MISSING
    attribute, parser = _BLOOD_HUNT_TIERS[doubled]
    entry = parser(ctx)
    if entry is None:
        return None
    bonus = entry["stat_buff"]["bonus_attack_speed"]
    entry["detail"] = (
        f"{bonus:g}% bonus attack speed (the sourced {attribute} row"
        + (
            " — the target is below 25% maximum health)"
            if doubled
            else "; the active marks the target regardless of its health)"
        )
        + "; Blood Hunt's movement speed has no engine channel"
    )
    return entry


_blood_hunt.phase = BUFF


PACKET_SHA256 = "2c91dcf27a641c6a177969744e204b672765d8fc7291214c069ecacc64511a19"

# Jaws of the Beast only bites ("dealing magic damage, healing himself...");
# the displacement immunity is Warwick's own.  Infinite Duress "knocks them
# down and channels for up to 1.5 seconds to suppress, reveal, and deal
# magic damage every 0.25 seconds" — the suppression is the control the
# damaged target is under for the whole priced channel.  E (Primal Howl,
# where the fear and 90% slow live) is out_of_scope with no damage row; W
# is a pure stat buff and P an on-hit rider on basic attacks, so neither
# authors a part a review could reach.
MODULE_CC = {"Q": "none", "R": "suppression"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Warwick",
    PACKET_SHA256,
    assumption_overrides=(
        "Warwick Q's sourced 0.264-second bite delay is applied to the hit "
        "event without inventing a channel lockout.",
    ),
    single_hit_slots=frozenset({"Q"}),
    packet_part_timings={"Q": {"time_offset": 0.264}},
    slot_parsers={
        "P": _eternal_hunger,
        "W": _blood_hunt,
        "R": _infinite_duress,
    },
    slot_wrappers={
        "Q": partial(
            with_item_on_hits,
            effectiveness=1.0,
            hits=1,
            triggers=("on_hit", "on_attack"),
        ),
    },
    cc_kinds=MODULE_CC,
)

OPTIONS.append(
    {
        "key": "p_self_health_percent",
        "type": "int",
        "default": 100,
        "min": 0,
        "max": 100,
        "label": (
            "Warwick's own health % (Eternal Hunger heals for 100% of its "
            "damage below 50%, 250% below 25%)"
        ),
    }
)
OPTIONS.append(
    {
        "key": "target_missing_hp_pct",
        "type": "int",
        "default": 50,
        "min": 0,
        "max": 100,
        "label": "Target missing health % (Blood Hunt doubles above 75%)",
    }
)

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "R (Infinite Duress) prices the wiki Total Magic Damage "
    "(175/350/525 + 167% bonus AD by rank) as one cast over the "
    "1.5-second suppress channel; healing.py's existing 100%-of-R-"
    "damage self-heal rule fires on the R damage event.  The channel's "
    "0.25s magic-damage ticks and its 3 on-hit/on-attack applications "
    "are documented cadence: item on-hits are not multiplied (the "
    "cache publishes no per-tick row).",
    "P (Eternal Hunger) is an on-hit rider on every basic attack: the "
    "cached per-level row (6 : 60.76 + 15% bonus AD + 10% AP magic).  "
    "It is an on-hit itself, so item on-hit effects do not proc from "
    "it — they proc from the swing it rides.  Its self-heal (100% of "
    "the post-mitigation damage below 50% maximum health, 250% below "
    "25%) is cached prose, gated on the p_self_health_percent option "
    "(default 100% — a healthy Warwick heals nothing) and paid by the "
    "Warwick healing rule.",
    "W (Blood Hunt) grants the sourced Bonus Attack Speed row "
    "(70-110% by rank) for the whole fight: the active marks the target "
    "'regardless of their current health', so the base tier needs no "
    "condition.  The doubled row (140-220%) applies when "
    "target_missing_hp_pct exceeds 75 (the target below 25% maximum "
    "health).  Blood Hunt's bonus movement speed and its 8-second mark "
    "duration are not modeled — stat_buff has no movement-speed key.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "R"} else "out_of_scope")
    for slot in "PQWER"
}

SELF_HEALING_RULE = declare_healing_rule("Warwick")
