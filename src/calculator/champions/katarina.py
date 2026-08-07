"""Katarina — reviewed packet slots plus the E3 dagger-spin passive.

Option keys consumed by this module's parsers: "p_daggers" (spin
count, read by the P proc resolver below) and "r_daggers" (Death
Lotus dagger count, consumed by the shared batch R parser from
reviewed_batch_03).

E3 fix over the CP10.3 packet module:
- P (Voracity / Sinister Steel) already procs per dagger retrieval, but
  the shared ``extract_named("Bonus Magic Damage")`` walk resolves the
  AP modifier's garbled unit ("% / 80% / 90% / 100% (based on level")
  to ZERO — the spin silently lost its AP ratio. This module prices the
  dagger spin exactly: level-scaled flat (68 : 240) + 60% bonus AD +
  the level-band AP ratio (70% / 80% / 90% / 100% at levels 1-5 /
  6-10 / 11-15 / 16+). The retrieval count stays the ``p_daggers``
  option (default 1 — one dagger pickup, e.g. W's or Q's landing
  dagger; the model cannot simulate dagger pickups mid-fight).
"""

from typing import Any, Callable

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .reviewed_batch_03 import build_batch_module
from .slotlib import with_item_on_hits, extract_value, proc_damage

_packet_parse, _packet_slots, _packet_assumptions, _packet_sources, _packet_options = (
    build_batch_module("Katarina")
)

# HARDCODED: verify on patch updates — Sinister Steel's AP ratio is
# level-banded (70%/80%/90%/100% at 1-5/6-10/11-15/16+); the JSON only
# carries the first band (70) under a garbled unit string.
_AP_RATIO_BANDS: tuple[tuple[int, float], ...] = (
    (16, 1.00),
    (11, 0.90),
    (6, 0.80),
    (1, 0.70),
)


def _sinister_steel_ratio(level: int) -> float:
    """The AP ratio of a dagger-retrieval spin at a champion level."""
    for min_level, ratio in _AP_RATIO_BANDS:
        if level >= min_level:
            return ratio
    return _AP_RATIO_BANDS[-1][1]


def _spin_damage(ctx: SlotCtx, ability: dict[str, Any]) -> float:
    """One dagger spin: flat(level) + 60% bonus AD + level-banded AP."""
    flat = extract_value(ability, "Bonus Magic Damage", ctx.level, 0)
    bonus_ad_ratio = extract_value(ability, "Bonus Magic Damage", ctx.level, 1) / 100.0
    ad = ctx.stats.get("bonus_attack_damage", 0.0)
    ap = ctx.stats.get("ability_power", 0.0)
    return flat + bonus_ad_ratio * ad + _sinister_steel_ratio(ctx.level) * ap


_sinister_steel = proc_damage(
    _spin_damage,
    "magic",
    count_option="p_daggers",
    default_count=1,
    name="Voracity (Sinister Steel)",
    phase_order_events=True,
)

# HARDCODED: verify on patch updates — wiki prose in the cached R JSON
# ("inflicts Grievous Wounds on the target for 3 seconds").  Every Death
# Lotus dagger hit refreshes the patch-wide 40% Grievous Wounds window
# (strength/duration are the engine constants, not module numbers).
GRIEVOUS_WOUNDS_SOURCES = frozenset({"R"})

SLOTS = {**_packet_slots, "P": _sinister_steel}
SLOTS["P"] = with_item_on_hits(SLOTS["P"], effectiveness=1.0, hits=1, triggers=('on_hit',))
SLOTS["E"] = with_item_on_hits(SLOTS["E"], effectiveness=1.0, hits=1, triggers=('on_hit',))
parse_abilities = build_parser(SLOTS, "Katarina")

OPTIONS = list(_packet_options)
ASSUMPTIONS = list(_packet_assumptions) + [
    "Sinister Steel's dagger spin prices the flat level term plus 60% "
    "bonus AD plus the level-banded AP ratio (70%/80%/90%/100% at "
    "levels 1-5/6-10/11-15/16+) — the band values are wiki prose "
    "(module constants) because the JSON's AP-modifier unit is garbled",
    "The dagger-retrieval count is user-set (``p_daggers``, default 1); "
    "the 4-second dagger lifetime and pickup positioning are not "
    "simulated",
    "Q's dagger landing, W's toss, and E-onto-dagger pickups are all "
    "counted as the same spin proc",
    "Death Lotus applies Grievous Wounds for 3 seconds on every dagger "
    "hit (wiki prose); the coupled timeline refreshes the patch-wide "
    "40% window per hit",
]
SOURCES = list(_packet_sources)
MODULE_COVERAGE = {
    slot: ("modeled" if slot != "W" else "no_damage") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
