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

Roadmap session 5 slot 14 (2026-08-21): R (Portal Jump) has no
enemy-damage formula: the cached effects are a blink/reposition with a
static movement-speed lock and an attack-reset, with no enemy-damage
leveling row (confirmed by the pinned reviewed packet's kind="no_damage"
declaration for R, and live: parse_champion_abilities emits R with
total_raw=0.0, and the fight breakdown carries an R row that totals
zero damage). This module never reassigns R away from
build_packet_module's default no-damage branch (only W is overridden
above). MODULE_COVERAGE was simply stale, still reading "out_of_scope"
for a slot this module already treats as non-damaging (the
Rek'Sai/Renekton precedent). Reclassified to "no_damage"; zero
fight-computation change.
"""

from ..ability_spec import DamagePart
from .packet_module import build_packet_module
from .engine import SlotCtx, build_parser
from .slotlib import damage_entry, extract_cooldown, extract_named

PACKET_SHA256 = "254423a49d0d309eafb437ffdb27709166a149f7ea2bc6aa1f21cf01f1b747a8"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Zoe", PACKET_SHA256
)
PACKET_SPEC = SLOTS.packet_spec

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
    "The mimicked summoner Heal (w_summoner=1) has no sourced amount: "
    "summoner-spell values (90 : 345 based on level) are not part of "
    "data/champions.json, so no heal atom is authored — the option "
    "stays a no-damage receipt until a summoner-spell atom exists.",
    "R (Portal Jump) has no enemy-damage formula: it is a blink "
    "reposition with a static movement-speed lock and a basic-attack "
    "reset, no term dealt to an enemy (confirmed by the pinned reviewed "
    "packet's kind='no_damage' declaration for R). R is a cast slot in "
    "this module (never reassigned away from build_packet_module's "
    "no_damage branch), so MODULE_COVERAGE reflects a sourced "
    "no-damage classification rather than an unmodeled gap (no_damage, "
    "not out_of_scope).",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "E"} else "no_damage")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
