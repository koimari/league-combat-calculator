"""Katarina — reviewed packet slots plus the E3 dagger-spin passive.

Option keys consumed by this module's parsers: "p_daggers" (spin
count, read by the P proc resolver below) and "r_daggers" (Death
Lotus dagger count, consumed by this module's R parser).

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

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import REVIEWED_MODULE_ASSUMPTIONS, no_damage
from .slotlib import (
    extract_cooldown,
    extract_named,
    extract_value,
    proc_damage,
    simple_damage,
    with_item_on_hits,
)
from .source_receipts import load_champion_sources
from .module_contract import coverage


def _death_lotus(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    daggers = max(1, min(15, int(ctx.option("r_daggers"))))
    physical = extract_named(
        ability, "Physical Damage Per Dagger", rank, ctx.stats, ctx.target
    )
    magic = extract_named(
        ability, "Magic Damage Per Dagger", rank, ctx.stats, ctx.target
    )
    interval = 2.5 / daggers
    return {
        "name": ability.get("name", "Death Lotus"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "mixed",
        "total_raw": (physical + magic) * daggers,
        "parts": (
            DamagePart(
                "physical",
                physical,
                count=daggers,
                time_offset=0.166,
                hit_interval=interval,
            ),
            DamagePart(
                "magic",
                magic,
                count=daggers,
                time_offset=0.166,
                hit_interval=interval,
            ),
        ),
        # No ``event_order_certified``: the certification vocabulary is a
        # string ("single_hit" / "auto_stack_proc"), and 15 daggers over a
        # 2.5-second channel is neither.  The parts author their own
        # cadence, which is what the ledger reads.
        "detail": (
            f"{daggers} sourced daggers at 0.166-second cadence; "
            "on-hit/Grievous Wounds are ordered state."
        ),
    }


_packet_slots = {
    # Q and E each deal their packet once, at the cast: the reviewed
    # cast-boundary claim that carries MODULE_CC into the event ledger.
    "Q": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "W": lambda ctx: no_damage(
        ctx,
        name="Preparation",
        reason="Dagger toss, movement speed and landing location are utility state.",
    ),
    "E": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "R": _death_lotus,
}
_packet_assumptions = list(REVIEWED_MODULE_ASSUMPTIONS)
_packet_options = [
    {
        "key": "p_daggers",
        "type": "int",
        "default": 1,
        "min": 0,
        "max": 6,
        "label": "Dagger retrieval procs",
    },
    {
        "key": "r_daggers",
        "type": "int",
        "default": 15,
        "min": 1,
        "max": 15,
        "label": "Death Lotus daggers",
    },
]

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
    ad = ctx.stat("bonus_attack_damage")
    ap = ctx.stat("ability_power")
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
SLOTS["P"] = with_item_on_hits(
    SLOTS["P"], effectiveness=1.0, hits=1, triggers=("on_hit",)
)
SLOTS["E"] = with_item_on_hits(
    SLOTS["E"], effectiveness=1.0, hits=1, triggers=("on_hit",)
)

# Cached kit review: nothing in Katarina's kit applies crowd control.  Q
# bounces, W tosses a dagger and grants movement speed, E blinks, and R's
# only debuff is Grievous Wounds (healing reduction, not control).
MODULE_CC = {"Q": "none", "E": "none", "R": "none"}

parse_abilities = build_parser(SLOTS, "Katarina", cc_kinds=MODULE_CC)

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
SOURCES = load_champion_sources("Katarina")
MODULE_COVERAGE = coverage(no_damage="W")
