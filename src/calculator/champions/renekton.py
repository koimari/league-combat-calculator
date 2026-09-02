"""Renekton — CP10.6 full-entry-reviewed packet module.

E2 DoT fix: W (Ruthless Predator) prices 2 strikes; R (Dominus) prices
30 sourced 0.5s ticks (this module's packet timing declaration).

Coverage: P (Reign of Anger) is the Fury meter that empowers the next
ability. Its empowered rows are priced on the abilities themselves; all
three cached P effects (generation/decay, the 50-Fury empower gate, the
sub-50%-health rule) carry zero leveling rows, and the pinned reviewed
packet declares P ``kind: "no_damage"`` on that basis. P is a cast slot
here, so it emits that sourced zero-damage row: MODULE_COVERAGE reads
"no_damage", not "out_of_scope".
"""

from functools import partial
from typing import Any

from ..healing_helpers import ability_json, event_source, heal_from_damage, parsed_rank
from .healing_contract import self_healing_rule
from .module_contract import coverage
from .packet_module import build_packet_module
from .slotlib import extract_named, with_item_on_hits

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
    # Cull the Meek cleaves once around Renekton and Slice's dash damages
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
    "P (Reign of Anger) has no enemy-damage formula: all three cached "
    "effects (Fury generation/decay, the 50-Fury empower gate, the "
    "sub-50%-health bonus-Fury-generation rule) carry zero leveling "
    "rows (confirmed by the pinned reviewed packet's kind='no_damage' "
    "declaration for P). P is a cast slot in this module (never "
    "reassigned away from build_packet_module's no_damage branch), so "
    "MODULE_COVERAGE reflects a sourced no-damage classification "
    "rather than an unmodeled gap (no_damage, not out_of_scope).",
]
MODULE_COVERAGE = coverage(no_damage="P")


# pylint: disable=too-many-arguments,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Cull the Meek pays its heal on every Q hit that lands."""
    healing: list[dict] = []
    ability = ability_json(champion_data, "Q")
    rank = parsed_rank(ability_damages, "Q")
    amount = extract_named(ability, "Champion Healing", rank, champion_stats, {})
    for event in damage_events:
        if event_source(event) == "Q":
            heal_from_damage(healing, event, amount, "Cull the Meek")
    return healing


SELF_HEALING_RULE = self_healing_rule("Renekton")(derive_self_healing)
