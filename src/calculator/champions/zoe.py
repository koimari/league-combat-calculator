"""Zoe — CP10.11 full-entry-reviewed packet module.

E5-2 fix — Spell Thief (W): the reviewed packet collapsed the passive
to ONE flat bolt (15-55 + 10% AP, the "Magic Damage Per Bolt" row).
Wheeeee summons THREE bolts ("she shoots one bolt at a time at the
nearest non-sleeping enemy"), so the damage is the wiki's "Total Magic
Damage" row (45-165 + 30% AP == 3 x per-bolt at every rank,
data/champions.json W).  The stolen Spell Shard actives (Heal, Barrier,
Smite) are modeled as an explicit ``w_summoner`` option: none of them
deals damage to enemy champions in this calculator's scope (Heal heals
the caster, Barrier shields, Smite damages monsters), so each variant
is a documented no-damage row instead of being collapsed into a bolt.
"""

from ..ability_spec import DamagePart
from .reviewed_batch_11 import build_batch_module
from .engine import SlotCtx, build_parser
from .slotlib import damage_entry, extract_cooldown, extract_named

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Zoe")

# Wheeeee fires three bolts; the "Total Magic Damage" row is exactly
# 3 x "Magic Damage Per Bolt" at every rank (45/3 == 15, ..., 165/3 == 55).
_W_BOLTS = 3
# Summoner Shard mimics (wiki prose on W; none deals champion damage):
#   0 = Spell Thief bolts (the modeled damage)
#   1 = Heal  — heals Zoe, no enemy damage
#   2 = Barrier — shields Zoe, no enemy damage
#   3 = Smite — true damage to monsters/minions, no champion damage
_W_SUMMONER_VARIANTS = {
    1: "Heal (mimicked Spell Shard): heals Zoe; no enemy damage modeled.",
    2: "Barrier (mimicked Spell Shard): shields Zoe; no enemy damage modeled.",
    3: "Smite (mimicked Spell Shard): true damage to monsters/minions; no "
    "champion damage modeled.",
}


def _spell_thief(ctx: SlotCtx):
    """W: three orbiting bolts, or a no-damage summoner Shard mimic."""
    ability = ctx.ability("W", 0)
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    summoner = int(ctx.options.get("w_summoner", 0))
    if summoner != 0:
        reason = _W_SUMMONER_VARIANTS.get(
            summoner, "Unknown summoner Spell Shard mimic."
        )
        return {
            "name": ability.get("name", "Spell Thief"),
            "rank": rank,
            "cooldown": extract_cooldown(ability, rank),
            "damage_type": "magic",
            "total_raw": 0.0,
            "parts": (),
            "detail": reason,
        }
    total = extract_named(ability, "Total Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Spell Thief"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart(
            "magic",
            amount=total / _W_BOLTS,
            count=_W_BOLTS,
        ),
    )
    entry["detail"] = (
        f"{_W_BOLTS} bolts of {total / _W_BOLTS:g} = the wiki Total Magic " "Damage row"
    )
    return entry


SLOTS = dict(SLOTS)
SLOTS["W"] = _spell_thief
parse_abilities = build_parser(SLOTS, "Zoe")

OPTIONS = list(OPTIONS) + [
    {
        "key": "w_summoner",
        "type": "int",
        "default": 0,
        "label": "W Spell Shard mimic (0 Spell Thief bolts / 1 Heal / 2 Barrier / 3 Smite)",
        "min": 0,
        "max": 3,
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Spell Thief) prices all three orbiting bolts — the wiki's 'Total "
    "Magic Damage' row (45-165 + 30% AP == 3 x 'Magic Damage Per Bolt', "
    "data/champions.json W).",
    "The stolen Spell Shard actives are option-gated no-damage rows: "
    "Heal heals Zoe, Barrier shields her, and Smite deals true damage "
    "to monsters/minions — none deals damage to enemy champions in this "
    "calculator's scope (wiki prose on W).",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "E"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
