"""Renekton — CP10.6 full-entry-reviewed packet module.

E2 DoT fix: W (Ruthless Predator) prices 2 strikes; R (Dominus) prices
30 sourced 0.5s ticks (this module's packet timing declaration).

Roadmap session 4 batch F (2026-08-21): P (Reign of Anger) is the Fury
resource system only — all three cached P effects (data/champions.json)
are Fury generation/decay/empower-gating prose with zero leveling rows,
no enemy-damage formula anywhere. The pinned reviewed packet (static/
reviewed-packets.json) independently declares P ``kind: "no_damage"``
with a sourced reason, and P is not a slot this module reassigns away
from ``build_packet_module``'s cast slots, so it already emits the
packet's sourced zero-damage row today — MODULE_COVERAGE was simply
stale, still reading "out_of_scope" for an already-covered slot (the
Malzahar/Nasus precedent, roadmap session 4 batch D). Reclassified to
"no_damage"; zero fight-computation change.
"""

from .packet_module import build_packet_module

PACKET_SHA256 = "d331bfbe1255392c5667aa32b6403badc5674e16c7196822d0a8bee5a94a4f3f"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Renekton",
    PACKET_SHA256,
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


ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Reign of Anger) has no enemy-damage formula: all three cached "
    "effects (Fury generation/decay, the 50-Fury empower gate, the "
    "sub-50%-health bonus-Fury-generation rule) carry zero leveling "
    "rows (confirmed by the pinned reviewed packet's kind='no_damage' "
    "declaration for P). P is a cast slot in this module (never "
    "reassigned away from build_packet_module's no_damage branch), so "
    "MODULE_COVERAGE reflects a sourced no-damage classification "
    "rather than an unmodeled gap (no_damage, not out_of_scope).",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "E", "R"} else "no_damage")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

from .. import healing_helpers as _healing  # pylint: disable=wrong-import-position


# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument,wrong-import-position
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Renekton self-healing events from its authored packet."""
    healing = []
    ability = _healing._ability(champion_data, "Q")
    rank = _healing._rank(ability_damages, "Q")
    amount = _healing.extract_named(
        ability, "Champion Healing", rank, champion_stats, {}
    )
    for event in damage_events:
        if _healing._event_source(event) == "Q":
            _healing._heal_from_damage(healing, event, amount, "Cull the Meek")
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Renekton", derive_self_healing)
