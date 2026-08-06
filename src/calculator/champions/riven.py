"""Riven — CP10.6 full-entry-reviewed packet module.

E5-2 fix — Runic Blade (P): the reviewed packet declared the passive
no_damage, but the wiki carries a sourced formula: "Riven's basic
attacks are empowered to each consume a stack to deal bonus physical
damage equal to 30% : 46.76% (based on level) AD" (data/champions.json
P "Per-Level Scaling" [0], 30-46.76% AD; the second row is the 50%
structure-reduced share).  The passive is an on-hit entry priced at
``AD x per-level% / 100`` per empowered auto.  The bonus damage is
crit-affected and life-steals at 100% in game; the on-hit framework
prices the flat per-hit amount (no crit rider), conservative for the
0%-crit test fights.
"""

from .reviewed_batch_06 import build_batch_module
from .engine import ONHIT, SlotCtx, build_parser
from .slotlib import extract_named, on_hit_entry

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Riven")


def _runic_blade(ctx: SlotCtx):
    """P: empowered basic attacks deal per-level % AD bonus physical damage."""
    ability = ctx.ability("P", 0)
    if ability is None:
        return None
    percent = extract_named(
        ability, "Per-Level Scaling", ctx.level, ctx.stats, ctx.target
    )
    per_hit = float(ctx.stats.get("attack_damage", 0.0) or 0.0) * percent / 100.0
    return on_hit_entry(ability.get("name", "Runic Blade"), per_hit, "physical")


_runic_blade.phase = ONHIT

SLOTS = dict(SLOTS)
SLOTS["P"] = _runic_blade
parse_abilities = build_parser(SLOTS, "Riven")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Runic Blade) prices the wiki's per-level AD ratio: empowered "
    "basic attacks deal bonus physical damage equal to 30% : 46.76% "
    "(based on level) AD, one stack per auto (data/champions.json P "
    "'Per-Level Scaling' [0]).",
    "Runic Blade's bonus damage is affected by critical strike "
    "modifiers in game; the on-hit framework prices the flat per-hit "
    "amount and does not roll crits on it (conservative, and exact at "
    "0% crit).",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
