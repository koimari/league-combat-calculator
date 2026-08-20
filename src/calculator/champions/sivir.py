"""Sivir — CP10.7 full-entry-reviewed packet module, plus the E9-3 Q fix.

E9-3: Boomerang Blade (Q) is a two-way blade: "Upon reaching maximum
range, the crossblade returns to her ... dealing the same damage to
enemies on its way back" — the cached "Total Maximum Champion Damage"
row (120-320 + 140% bonus AD + 120% AP) is exactly double the
single-pass "Physical Damage" row the reviewed packet priced.  The
module now prices the Total row so a full out-and-back pass deals the
in-game 2x damage (320 at rank 5 vs the old 160).
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx
from .packet_module import build_packet_module
from .slotlib import damage_entry, extract_cooldown, extract_named

PACKET_SHA256 = "ac50a4316c8ffc3f6f326c6be14ec20867f6301066621ff49ec26c1fad1b97a7"


def _boomerang_blade(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: the two-way pass priced from the Total Maximum Champion Damage row."""
    ability = ctx.ability("Q")
    if ability is None:
        return None
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None
    total = extract_named(
        ability, "Total Maximum Champion Damage", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability.get("name", "Boomerang Blade"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", total / 2.0, count=2),)
    entry["detail"] = (
        "two-way Boomerang Blade: the crossblade hits out AND back for 2x "
        "(Total Maximum Champion Damage 120-320 + 140% bonus AD + 120% AP "
        "== 2 x the single-pass row)"
    )
    return entry


parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Sivir",
    PACKET_SHA256,
    slot_parsers={
        "Q": _boomerang_blade,
    },
)

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "Q (Boomerang Blade) prices the full two-way pass from the cached "
    "'Total Maximum Champion Damage' row (120-320 + 140% bonus AD + "
    "120% AP == 2 x the single-pass 'Physical Damage' row): the blade "
    "deals the same damage on the way out and back.",
    "The exact return cadence is not cached; both passes are priced at "
    "the cast boundary.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E"} else "out_of_scope") for slot in "PQWER"
}
