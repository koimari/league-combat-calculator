"""Renekton — CP10.6 full-entry-reviewed packet module.

E2 DoT fix: W (Ruthless Predator) prices 2 strikes; R (Dominus) prices
30 sourced 0.5s ticks (this module's packet timing declaration).
"""

from .packet_module import build_packet_module

PACKET_SHA256 = "d331bfbe1255392c5667aa32b6403badc5674e16c7196822d0a8bee5a94a4f3f"

# Cached kit review.  Q "deal[s] physical damage to nearby enemies and
# heal[s] himself"; E's dash "deal[s] physical damage to enemies he passes
# through" and its empowered recast "inflicts armor reduction", a
# resistance shred rather than a control class; R "deals magic damage every
# 0.5 seconds to nearby enemies" while buffing Renekton's own stats.  W is
# the kit's one control: the empowered attack "strike[s] the target twice,
# dealing modified physical damage and stunning them for 0.75 seconds".  P
# is Fury bookkeeping with no damage row.
MODULE_CC = {"Q": "none", "W": "stun", "E": "none", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Renekton",
    PACKET_SHA256,
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
PACKET_SPEC = SLOTS.packet_spec
_ON_HIT_SPECS: dict[str, dict] = {
    "W": {"effectiveness": 1.0, "hits": 2, "triggers": ("on_hit",)},
}

_parse_abilities = parse_abilities


def parse_abilities(*args, **kwargs):
    """Parse abilities, then declare wiki-sourced item on-hit application."""
    result = _parse_abilities(*args, **kwargs)
    for slot, spec in _ON_HIT_SPECS.items():
        entry = result.get(slot) or (result.get("passive") if slot == "P" else None)
        if entry is not None:
            entry["applies_item_on_hits"] = dict(spec)
    return result


# The on-hit declaration above wraps the compiled parser, so the reviewed
# crowd control it carries has to travel with the wrapper: the contract
# proves the module's declaration and its parser's wiring are one dict.
parse_abilities.cc_kinds = _parse_abilities.cc_kinds


MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Renekton")
