"""Locke — full-entry reviewed CP10.3 module, plus the P1 W grey-health heal.

Option keys consumed by the shared parser: "q_casts", "soul_nails", "e_dash".

P1 addition over the reviewed packet:
- W (Soul Ignition) recast heal is now authored by the E8a grey-health
  primitive (GREY_HEALTH_RULE_CHAMPIONS + participant_timeline):
  "stores an amount of grey health ... equal to 100% of the
  post-mitigation damage he takes from enemy champions, up to a cap"
  (cached W prose; cap = the "Damage taken grey health cap" leveling row
  40/60/80/100/120 by W rank + 100% AP).  Each W cast opens a 6-second
  storage window and the automatic recast at 6 s heals the stored pool.
  The health-cost add and the missing-health bonus ("increased by up to
  40 : 200 (based on level) (+ 20% AP) based on his missing health")
  remain documented dynamic-self-state boundaries — the deterministic
  pool is the sourced 100%-of-damage-taken term.
"""

from .reviewed_batch_03 import build_batch_module
from .slotlib import with_item_on_hits

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Locke")
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


MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "E", "R"} else "no_damage")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Soul Ignition) recast heal is authored by the grey-health "
    "primitive: 100% of the post-mitigation champion damage taken during "
    "the 6s active is stored (capped by the 'Damage taken grey health "
    "cap' row) and healed at the automatic 6s recast.  The health-cost "
    "add and the missing-health bonus are dynamic self-state boundaries, "
    "per the E1-b6 scope note",
]
