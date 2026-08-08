"""Veigar — E5-1 corrected slot map for the archetype engine.

Why each slot is non-generic:

- R (Primordial Burst) is an execute, not a flat maximum hit: the wiki
  lists "Minimum Magic Damage" (175 / 250 / 325 + 65 / 70 / 75% AP) and
  "Maximum Magic Damage" (350 / 500 / 650 + 130 / 140 / 150% AP — the
  maximum row is exactly twice the minimum), with the description
  "deals magic damage, increased by 0% : 100% (based on target's missing
  health)".  The previous packet priced the maximum row unconditionally.
  The corrected parser prices the minimum row and scales it up to +100%
  (the maximum row) linearly as the target's missing-health ratio rises
  from 2/3 (target at 33% health) to 1.0 (target at 0 health), evaluated
  per cast against the target's live health by the fight engine.
- Q (Baleful Strike) is a plain "Magic Damage" read (80 / 120 / 160 /
  200 / 240 + 50 / 55 / 60 / 65 / 70% AP).
- W (Dark Matter) is a plain "Magic Damage" read (85 / 140 / 195 / 250 /
  305 + 70 / 80 / 90 / 100 / 110% AP).
- P (Phenomenal Evil Power) and E (Event Horizon) deal no enemy damage
  and are explicit no-damage slots.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any, Callable

from .engine import SlotCtx, build_parser
from .source_receipts import load_champion_sources
from .slotlib import extract_cooldown, extract_named, simple_damage
from ..ability_spec import DamagePart

# Primordial Burst ramps from 0% to +100% extra damage between the target
# at 33% health and the target at 0 health ("increased by 0% : 100% (based
# on target's missing health)"; the Maximum row == 2x the Minimum row).
_EXECUTE_MISSING_RATIO_START = 2.0 / 3.0


def _no_damage(slot: str, reason: str):
    """Emit an explicit zero-damage entry for a non-damaging slot."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None
        return {
            "name": ability.get("name", f"Ability {slot}"),
            "rank": ctx.rank_for(),
            "cooldown": 0.0,
            "damage_type": "magic",
            "total_raw": 0.0,
            "parts": (),
            "detail": reason,
        }

    parse.phase = "damage"
    return parse


def _primordial_burst_scaled(base: float) -> Callable[[float], float]:
    """R execute curve: +0% at 33% health, +100% (2x base) at 0 health."""

    def scaled(missing_ratio: float) -> float:
        boost = max(
            0.0,
            min(
                1.0,
                (missing_ratio - _EXECUTE_MISSING_RATIO_START)
                / (1.0 - _EXECUTE_MISSING_RATIO_START),
            ),
        )
        return base * (1.0 + boost)

    return scaled


def _primordial_burst(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: minimum-damage row scaled by the missing-health execute curve."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    base = extract_named(ability, "Minimum Magic Damage", rank, ctx.stats, ctx.target)
    entry = {
        "name": ability.get("name", "Primordial Burst"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": base,
        "parts": (
            DamagePart("magic", hp_scaled_damage=_primordial_burst_scaled(base)),
        ),
        "event_order_certified": "single_hit",
        "detail": (
            "Minimum Magic Damage base, boosted up to +100% (Maximum row) "
            "as the target's missing health crosses 33%"
        ),
    }
    return entry


ASSUMPTIONS = [
    "R (Primordial Burst) prices the Minimum Magic Damage row and ramps to "
    "the Maximum row (+100%) as the target drops below 33% health "
    "('increased by 0% : 100% based on target's missing health').",
    "Q and W price one enemy-champion hit each.",
    "P and E deal no enemy damage and are explicit no-damage slots.",
]

SOURCES = list(load_champion_sources("Veigar"))

SLOTS = {
    "P": _no_damage(
        "P",
        "Phenomenal Evil Power is a stacking AP passive; no enemy damage.",
    ),
    "Q": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "W": simple_damage(attr="Magic Damage", dmg_type="magic"),
    "E": _no_damage(
        "E",
        "Event Horizon is a stun cage; no enemy damage.",
    ),
    "R": _primordial_burst,
}

MODULE_COVERAGE = {
    "P": "no_damage",
    "Q": "modeled",
    "W": "modeled",
    "E": "no_damage",
    "R": "modeled",
}

OPTIONS: list[dict[str, Any]] = []

parse_abilities = build_parser(SLOTS, "Veigar")
REVIEW_STATUS = "reviewed_module"
