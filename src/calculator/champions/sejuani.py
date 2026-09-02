"""Sejuani — CP10.7 full-entry-reviewed packet module, plus the E9-3 W fix.

E9-3: Winter's Wrath (W) is a double flail swing.  The reviewed packet
read only the first "Physical Damage" row (5-45 + 30% AP + 4% of her
maximum health); the cached JSON also carries the second swing
(5-85 + 60% AP + 8% max health) and the Total Physical Damage row
(10-130 + 90% AP + 12% max health).  The module now prices BOTH swing
rows — each with the "% of her maximum health" term resolved against
Sejuani's own live max health (the unit is not a generic scaling unit,
so the module folds it in with a modifier override, the Swain bonus-
health pattern) — so W matches the in-game 10-130 + 90% AP + 12% max
health total at every rank.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import CC_PER_PART, SlotCtx
from .packet_module import build_packet_module
from .slotlib import (
    ability_name,
    damage_entry,
    extract_cooldown,
    find_named_leveling,
    sum_modifiers,
)

PACKET_SHA256 = "ea21bda8a36a602ed96aad725ac6f585d0e3db982035f7c61a78ebc50db90152"


def _winters_wrath(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: both flail swings (first + second "Physical Damage" rows).

    Each swing carries a "% of her maximum health" modifier that the
    generic scaling core does not recognize (it is Sejuani's OWN max
    health, not a target stat), so both rows are summed with an explicit
    override that prices the percentage against the fight's live health —
    matching the cached Total Physical Damage row at every rank.
    """
    ranked = ctx.ranked("W")
    if ranked is None:
        return None
    ability, rank = ranked

    def sejuani_max_health(unit: str, value: float) -> float | None:
        if unit == "% of her maximum health":
            return value / 100.0 * float(ctx.stat("health") or 0.0)
        return None

    first = find_named_leveling(ability, "Physical Damage", 0)
    second = find_named_leveling(ability, "Physical Damage", 1)
    swing_one = (
        sum_modifiers(first, rank, ctx.stats, ctx.target, sejuani_max_health)
        if first is not None
        else 0.0
    )
    swing_two = (
        sum_modifiers(second, rank, ctx.stats, ctx.target, sejuani_max_health)
        if second is not None
        else 0.0
    )
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        swing_one + swing_two,
        "physical",
    )
    # The two swings apply different control, so each says so itself
    # instead of MODULE_CC answering for both: the cone "knocks back
    # minions and monsters hit" and therefore nothing to a champion, while
    # the lash that follows is "dealing physical damage to enemies hit and
    # slowing them by 75% for 0.25 seconds".
    entry["parts"] = (
        DamagePart("physical", swing_one, time_offset=0.0, cc_kind="none"),
        DamagePart("physical", swing_two, time_offset=0.0, cc_kind="slow"),
    )
    entry["detail"] = (
        "both flail swings priced (first 5-45 + 30% AP + 4% max HP; second "
        "5-85 + 60% AP + 8% max HP == Total Physical Damage 10-130 + 90% "
        "AP + 12% max HP); the %max-HP terms use Sejuani's own live health"
    )
    return entry


# Cached kit review.  Q's dash deals magic damage while "knocking them up
# for 0.5 seconds".  E's trap "deals magic damage, displaces slightly, and
# stuns them for 1 second" — two immobilize kinds from one cast, which is
# what the un-narrowed "immobilize" states.  R's bola deals magic damage
# "and stun[s] them for 1 second"; its frost storm slows the enemies around
# the detonation, and the cached text says outright that "the enemy hit by
# the bola is unaffected by the storm's effects", so the stun is the whole
# answer for the target this row prices.  W answers per swing
# (``_winters_wrath``).  P is absent: Icebreaker's bonus rides Sejuani's
# next attack or ability rather than emitting an ability event of its own.
MODULE_CC = {"Q": "knockup", "W": CC_PER_PART, "E": "immobilize", "R": "stun"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Sejuani",
    PACKET_SHA256,
    # Bristle's dash damages what it passes through once, Permafrost's
    # trap hits its one marked target and the ice bola stops on the first
    # champion — the boundary claim that carries MODULE_CC's reviewed
    # answers into the event ledger.
    single_hit_slots=frozenset({"Q", "E", "R"}),
    slot_parsers={
        "W": _winters_wrath,
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "W (Winter's Wrath) prices both flail swings: the first and second "
    "'Physical Damage' rows sum to the cached 'Total Physical Damage' "
    "row (10-130 + 90% AP + 12% of Sejuani's maximum health) at every "
    "rank; the '% of her maximum health' terms are priced against "
    "Sejuani's live max health (her own stat, not the target's).",
    "The second swing's exact in-cast delay is not cached; both swings "
    "are priced at the cast boundary.",
]
