"""Poppy — CP10.6 full-entry-reviewed packet module.

E5-2 fix — Iron Ambassador (P): the reviewed packet priced only the
%max-HP "Max Health Damage" row (0.11-0.2106, which is actually the
SHIELD the buckler grants when Poppy retrieves it, not damage) with a
zero base and dropped the flat damage term.  The wiki text is:
"Poppy's next basic attack ... deal[ing] 20 : 198.82 (based on level)
bonus magic damage" (data/champions.json P "Bonus Magic Damage" row),
so the passive is an on-hit entry priced at the per-level flat value.
"""

from typing import Any

from ..ability_spec import DamagePart
from .packet_module import build_packet_module
from .engine import ONHIT, SlotCtx, build_parser
from .slotlib import damage_entry, extract_cooldown, extract_named, on_hit_entry

PACKET_SHA256 = "1a31e4f033cd7f636b093e6398b78eaa559462a22552cb2fe1cc48b46f618be5"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Poppy",
    PACKET_SHA256,
    assumption_overrides=(
        "Poppy Q's sourced Hammer Shock field ruptures 1 second after impact; "
        "the packet emits both physical hits.",
    ),
    packet_part_timings={
        "Q": {
            "count": 2,
            "time_offset": 0.0,
            "hit_interval": 1.0,
            "total_multiplier": 2.0,
        }
    },
)
PACKET_SPEC = SLOTS.packet_spec


def _iron_ambassador(ctx: SlotCtx):
    """P: the empowered buckler toss deals 20 : 198.82 (based on level)
    bonus magic damage on-hit — the "Bonus Magic Damage" leveling row."""
    ability = ctx.ability("P", 0)
    if ability is None:
        return None
    per_hit = extract_named(
        ability, "Bonus Magic Damage", ctx.level, ctx.stats, ctx.target
    )
    return on_hit_entry(ability.get("name", "Iron Ambassador"), per_hit, "magic")


_iron_ambassador.phase = ONHIT


def _keepers_verdict(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: Keeper's Verdict, priced at the charged or uncharged branch.

    The reviewed packet prices the UNCHARGED row ("Physical Damage"
    100-200 + 45% bonus AD).  Keeper's Verdict can be charged for up to
    1 second to deal double damage (the E3 worklist charge-state
    variant); the cached "Increased Damage" row (200-400 + 90% bonus AD)
    is that fully-charged branch, selected by the ``r_charged`` option.
    """
    if not bool(ctx.options.get("r_charged", False)):
        return _packet_r(ctx)
    ability = ctx.ability("R")
    if ability is None:
        return None
    rank = ctx.rank_for("R")
    if rank < 1:
        return None
    total = extract_named(ability, "Increased Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Keeper's Verdict"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", total),)
    entry["detail"] = (
        "fully-charged Keeper's Verdict ('Increased Damage' row 200-400 "
        "+ 90% bonus AD == 2x the uncharged row)"
    )
    return entry


SLOTS = dict(SLOTS)
SLOTS["P"] = _iron_ambassador
_packet_r = SLOTS["R"]
SLOTS["R"] = _keepers_verdict
parse_abilities = build_parser(SLOTS, "Poppy")

OPTIONS = list(OPTIONS) + [
    {
        "key": "r_charged",
        "type": "bool",
        "default": False,
        "label": "Fully-charged Keeper's Verdict (R)",
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Iron Ambassador) deals 20 : 198.82 (based on level) bonus magic "
    "damage on the empowered buckler attack — the wiki's 'Bonus Magic "
    "Damage' row (data/champions.json). The old packet's %max-HP "
    "0.11-0.2106 'Max Health Damage' row is the shield Poppy gains when "
    "she retrieves the buckler, not damage, and is not priced.",
    "R (Keeper's Verdict) defaults to the reviewed packet's uncharged "
    "row ('Physical Damage' 100-200 + 45% bonus AD); the fully-charged "
    "branch (the E3 worklist charge-state variant, 'Increased Damage' "
    "200-400 + 90% bonus AD == 2x) is option-gated via r_charged — the "
    "1-second charge time is state.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
