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
from .engine import SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import (
    damage_entry,
    extract_cooldown,
    find_named_leveling,
    sum_modifiers,
)

PACKET_SHA256 = "ea21bda8a36a602ed96aad725ac6f585d0e3db982035f7c61a78ebc50db90152"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Sejuani", PACKET_SHA256
)
PACKET_SPEC = SLOTS.packet_spec


def _winters_wrath(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: both flail swings (first + second "Physical Damage" rows).

    Each swing carries a "% of her maximum health" modifier that the
    generic scaling core does not recognize (it is Sejuani's OWN max
    health, not a target stat), so both rows are summed with an explicit
    override that prices the percentage against the fight's live health —
    matching the cached Total Physical Damage row at every rank.
    """
    ability = ctx.ability("W")
    if ability is None:
        return None
    rank = ctx.rank_for("W")
    if rank < 1:
        return None

    def sejuani_max_health(unit: str, value: float) -> float | None:
        if unit == "% of her maximum health":
            return value / 100.0 * float(ctx.stats.get("health", 0.0) or 0.0)
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
        ability.get("name", "Winter's Wrath"),
        rank,
        extract_cooldown(ability, rank),
        swing_one + swing_two,
        "physical",
    )
    entry["parts"] = (
        DamagePart("physical", swing_one, time_offset=0.0),
        DamagePart("physical", swing_two, time_offset=0.0),
    )
    entry["detail"] = (
        "both flail swings priced (first 5-45 + 30% AP + 4% max HP; second "
        "5-85 + 60% AP + 8% max HP == Total Physical Damage 10-130 + 90% "
        "AP + 12% max HP); the %max-HP terms use Sejuani's own live health"
    )
    return entry


SLOTS = dict(SLOTS)
SLOTS["W"] = _winters_wrath
parse_abilities = build_parser(SLOTS, "Sejuani")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Winter's Wrath) prices both flail swings: the first and second "
    "'Physical Damage' rows sum to the cached 'Total Physical Damage' "
    "row (10-130 + 90% AP + 12% of Sejuani's maximum health) at every "
    "rank; the '% of her maximum health' terms are priced against "
    "Sejuani's live max health (her own stat, not the target's).",
    "The second swing's exact in-cast delay is not cached; both swings "
    "are priced at the cast boundary.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
