"""Kayle — full-entry reviewed CP10.3 module.

Option keys consumed by the shared parser: "p_exalted", "e_empowered".

E8d ally-support: W (Celestial Blessing) heals the selected teammate.  The
event is authored by the engine's ally-support scanner from the cached W
leveling (Heal 55-155 + 25% AP; scope one_teammate) at the W cast time; the
module declares W in SLOTS so the fight rotation casts it.
"""

from .reviewed_batch_03 import build_batch_module
from .slotlib import with_item_on_hits

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Kayle")
_ON_HIT_SPECS: dict[str, dict] = {
    "E": {"effectiveness": 1.0, "hits": 1, "triggers": ("on_hit",)},
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


MODULE_COVERAGE = {slot: "modeled" for slot in "PQWER"}
REVIEW_STATUS = "reviewed_module"
