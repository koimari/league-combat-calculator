"""Nocturne — CP10.5 full-entry-reviewed packet module.

E2 DoT fix: E (Unspeakable Horror) prices 4 sourced 0.5s tether ticks
(this module's packet timing declaration).
"""

from .packet_module import build_packet_module

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


def parse_abilities(*args, **kwargs):
    """Parse abilities, then declare wiki-sourced item on-hit application."""
    result = _parse_abilities(*args, **kwargs)
    for slot, spec in _ON_HIT_SPECS.items():
        entry = result.get(slot) or (result.get("passive") if slot == "P" else None)
        if entry is not None:
            entry["applies_item_on_hits"] = dict(spec)
    return result


MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
