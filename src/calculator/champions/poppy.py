"""Poppy — CP10.6 full-entry-reviewed packet module.

E5-2 fix — Iron Ambassador (P): the reviewed packet priced only the
%max-HP "Max Health Damage" row (0.11-0.2106, which is actually the
SHIELD the buckler grants when Poppy retrieves it, not damage) with a
zero base and dropped the flat damage term.  The wiki text is:
"Poppy's next basic attack ... deal[ing] 20 : 198.82 (based on level)
bonus magic damage" (data/champions.json P "Bonus Magic Damage" row),
so the passive is an on-hit entry priced at the per-level flat value.
"""

from .reviewed_batch_06 import build_batch_module
from .engine import ONHIT, SlotCtx, build_parser
from .slotlib import extract_named, on_hit_entry

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Poppy")


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

SLOTS = dict(SLOTS)
SLOTS["P"] = _iron_ambassador
parse_abilities = build_parser(SLOTS, "Poppy")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Iron Ambassador) deals 20 : 198.82 (based on level) bonus magic "
    "damage on the empowered buckler attack — the wiki's 'Bonus Magic "
    "Damage' row (data/champions.json). The old packet's %max-HP "
    "0.11-0.2106 'Max Health Damage' row is the shield Poppy gains when "
    "she retrieves the buckler, not damage, and is not priced.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
