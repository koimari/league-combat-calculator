"""Nocturne — CP10.5 full-entry-reviewed packet module.

E2 DoT fix: E (Unspeakable Horror) prices 4 sourced 0.5s tether ticks
(this module's packet timing declaration).

Roadmap session 4 batch E (2026-08-21): W (Shroud of Darkness, the spell
shield) is a pure state ability with no enemy-damage formula. The pinned
reviewed packet already declares W ``kind: "no_damage"`` with a sourced
reason, and this module never overrides W, so it already emits the
packet's zero-damage row (``build_packet_module``'s ``no_damage``
branch) — MODULE_COVERAGE was simply stale, still reading "out_of_scope"
for an already-covered slot. Reclassified to "no_damage" (the
Malzahar/Nasus precedent, roadmap session 4 batch D); zero
fight-computation change.
"""

from ..ability_spec import ControlEvent
from .packet_module import build_packet_module
from .slotlib import extract_value, with_item_on_hits

PACKET_SHA256 = "0ce5c515d925ee81726b3430bfa9068b01a64a9901b67361a7f8da766fd561b8"

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Nocturne",
    PACKET_SHA256,
    packet_tick_fixes={
        "Unspeakable Horror": {
            "count": 4,
            "first_tick": 0.5,
            "tick_interval": 0.5,
            "dot_duration": 2.0,
        }
    },
)
PACKET_SPEC = SLOTS.packet_spec
_ON_HIT_SPECS: dict[str, dict] = {
    "P": {"effectiveness": 1.0, "hits": 1, "triggers": ("on_hit",)},
}

_parse_abilities = parse_abilities


def parse_abilities(
    champion_data,
    level,
    total_ability_power,
    ability_ranks=None,
    champion_options=None,
    champion_stats=None,
    target_stats=None,
):
    """Parse abilities and add the held-tether fear at its sourced time."""
    result = _parse_abilities(
        champion_data,
        level,
        total_ability_power,
        ability_ranks=ability_ranks,
        champion_options=champion_options,
        champion_stats=champion_stats,
        target_stats=target_stats,
    )
    entry = result.get("E")
    options = champion_options or {}
    if entry is not None and bool(options.get("e_tether_holds", True)):
        ability = champion_data["abilities"]["E"][0]
        duration = extract_value(ability, "Disable Duration", entry["rank"])
        entry["control_events"] = (ControlEvent("fear", duration, time_offset=2.0),)
    for slot, spec in _ON_HIT_SPECS.items():
        entry = result.get(slot) or (result.get("passive") if slot == "P" else None)
        if entry is not None:
            entry["applies_item_on_hits"] = dict(spec)
    return result


OPTIONS.append(
    {
        "key": "e_tether_holds",
        "type": "bool",
        "default": True,
        "label": "Unspeakable Horror tether holds",
    }
)


ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Shroud of Darkness) is the spell-shield state ability with no "
    "enemy-damage formula in the pinned packet; it emits the sourced "
    "zero-damage row (MODULE_COVERAGE: no_damage, not out_of_scope). W "
    "is already a cast slot in this module (never overridden from "
    "build_packet_module's no_damage branch).",
]

MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "E", "R"} else "no_damage")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
