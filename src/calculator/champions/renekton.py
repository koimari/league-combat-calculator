"""Renekton: full-entry-reviewed packet module.

W (Ruthless Predator) prices two strikes and R (Dominus) prices thirty sourced
0.5-second ticks.
P (Reign of Anger) is the Fury meter that empowers the next ability, and its
empowered rows are priced on the abilities themselves.  All three cached P
effects, generation and decay, the 50-Fury empower gate and the sub-50%-health
rule, carry zero leveling rows, so P is a cast slot emitting a sourced
zero-damage row.
"""

from functools import partial
from typing import Any

from ..healing_helpers import (
    ability_json,
    heal_from_damage,
    ledger_source_key,
    parsed_rank,
)
from .contract_vocabulary import coverage
from .healing_contract import SelfHealCtx, self_healing_rule
from .packet_module import build_packet_module
from .slot_extract import extract_named
from .slotlib import with_item_on_hits

PACKET_SHA256 = "d331bfbe1255392c5667aa32b6403badc5674e16c7196822d0a8bee5a94a4f3f"

# Cached kit review.  Q "deal[s] physical damage to nearby enemies and
# heal[s] himself"; E's dash "deal[s] physical damage to enemies he passes
# through" and its empowered recast "inflicts armor reduction", a
# resistance shred rather than a control class; R "deals magic damage every
# 0.5 seconds to nearby enemies" while buffing Renekton's own stats.  W is
# the kit's one control: the empowered attack "strike[s] the target twice,
# dealing modified physical damage and stunning them for 0.75 seconds".  P
# is Fury bookkeeping with no damage row.
MODULE_CC = {"Q": "none", "W": "stun", "E": "none", "R": "none", "P": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Renekton",
    PACKET_SHA256,
    slot_wrappers={
        "W": partial(
            with_item_on_hits, effectiveness=1.0, hits=2, triggers=("on_hit",)
        ),
    },
    cc_kinds=MODULE_CC,
    # Cull the Meek cleaves once around Renekton and E's dash damages
    # what it passes through once — the boundary claim that carries
    # MODULE_CC's reviewed answers into the event ledger.  W and R already
    # author their own strike and tick timings below.
    single_hit_slots=frozenset({"Q", "E"}),
    packet_tick_fixes={
        "Ruthless Predator": {
            "count": 2,
            "first_tick": 0.0,
            "tick_interval": 0.2,
        },
        "Dominus": {
            "count": 30,
            "first_tick": 0.5,
            "tick_interval": 0.5,
            "dot_duration": 15.0,
        },
    },
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "P (Reign of Anger) has no enemy-damage formula: all three cached effects carry "
    "zero leveling rows.",
    "Those are Fury generation and decay, the 50-Fury empower gate and the "
    "sub-50%-health rule.",
    "P is a cast slot here, so MODULE_COVERAGE records a sourced no_damage rather "
    "than an unmodeled gap.",
]
MODULE_COVERAGE = coverage(no_damage="P")


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Cull the Meek pays its heal on every Q hit that lands."""
    healing: list[dict] = []
    ability = ability_json(ctx.champion_data, "Q")
    rank = parsed_rank(ctx.ability_damages, "Q")
    amount = extract_named(ability, "Champion Healing", rank, ctx.champion_stats, {})
    for event in ctx.damage_events:
        if ledger_source_key(event) == "Q":
            heal_from_damage(healing, event, amount, "Cull the Meek")
    return healing


SELF_HEALING_RULE = self_healing_rule("Renekton")(derive_self_healing)
