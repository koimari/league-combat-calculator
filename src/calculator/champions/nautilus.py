"""Nautilus — CP10.5 full-entry-reviewed packet module.

E5-2 fix — Staggering Blow (P): the reviewed packet read the passive's
root-duration row ("Bonus Damage" 0.75-1.5 seconds) as a flat physical
damage amount and dropped the actual damage term.  The wiki text is:
"Nautilus' basic attacks are empowered to deal 14 : 128 (based on level)
bonus physical damage" (data/champions.json P "Per-Level Scaling" row),
so the passive is an on-hit entry priced at the per-level value.  The
0.75-1.5 "Bonus Damage" row is the root duration (a CC state, not
damage) and is deliberately not priced.
"""

from .reviewed_batch_05 import build_batch_module
from .engine import ONHIT, SlotCtx, build_parser
from .slotlib import extract_named, on_hit_entry

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Nautilus")


def _staggering_blow(ctx: SlotCtx):
    """P: empowered basic attacks deal 14 : 128 (based on level) bonus
    physical damage — the "Per-Level Scaling" leveling row."""
    ability = ctx.ability("P", 0)
    if ability is None:
        return None
    per_hit = extract_named(
        ability, "Per-Level Scaling", ctx.level, ctx.stats, ctx.target
    )
    return on_hit_entry(ability.get("name", "Staggering Blow"), per_hit, "physical")


_staggering_blow.phase = ONHIT

SLOTS = dict(SLOTS)
SLOTS["P"] = _staggering_blow
parse_abilities = build_parser(SLOTS, "Nautilus")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Staggering Blow) deals 14 : 128 (based on level) bonus physical "
    "damage on empowered basic attacks — the wiki's 'Per-Level Scaling' "
    "row (data/champions.json). The packet's old 0.75-1.5 'Bonus Damage' "
    "values are the root duration, a crowd-control state, not damage.",
]
MODULE_COVERAGE = {slot: "modeled" for slot in "PQWER"}
REVIEW_STATUS = "reviewed_module"
