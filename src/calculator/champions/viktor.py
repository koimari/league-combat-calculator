"""Viktor — CP10.9 full-entry-reviewed packet module.

E2 fix (packet_module): R (Arcane Storm) prices the impact plus the full
6.5-second storm (Magic Damage + 6 x Magic Damage Per Tick == Total
Magic Damage).

P1-2 fixes:
- Q (Siphon Power) now carries the sourced self-shield: the per-level
  "Bonus Damage" row is the shield base (40 : 140 by level + 25% AP)
  for 2.5 seconds (wiki Q effect prose; the row is mislabelled "Bonus
  Damage" in the cache, and its 18 values are level-indexed), authored
  via the E8c ``self_shield_events`` payload on the Q damage entry.
- Q's Discharge empowered-auto on-hit is priced from the "Modified
  Magic Damage" row (20 : 120 by rank + 100% AD + 50% AP) as an
  on-hit payload capped at one application (the next basic attack
  within the 4-second Discharge window), gated by the ``q_discharge``
  option (default True).  The "Total Magic Damage" row is the
  projectile + discharge sum and is not read separately.
"""

from typing import Any

from .engine import SlotCtx, build_parser
from .reviewed_batch_09 import build_batch_module
from .slotlib import (
    attach_self_shield,
    extract_named,
    find_named_leveling,
    is_flat_unit,
    resolve_scaling,
)

# HARDCODED: verify on patch updates — the shield window (2.5s) and the
# Discharge window (4s) are wiki Q prose; the shield base row and the
# discharge damage are cached leveling rows read live below.
_Q_SHIELD_DURATION_SECONDS = 2.5
_Q_DISCHARGE_WINDOW_SECONDS = 4.0

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Viktor")


def _siphon_shield(ctx: SlotCtx) -> float:
    """Q's shield: per-LEVEL base (40 : 140, 18 cached values) + 25% AP.

    ``extract_named`` indexes the 18-value row by RANK (values[4] at
    rank 5), but the wiki prose is "40 : 140 (based on level)"; long
    arrays (>= 18 values) are level-indexed here, the Ambessa W
    convention.
    """
    ability = ctx.ability()
    if ability is None:
        return 0.0
    leveling = find_named_leveling(ability, "Bonus Damage")
    if leveling is None:
        raise ValueError("Viktor Q shield leveling row is unavailable")
    total = 0.0
    rank = ctx.rank_for()
    for modifier in leveling.get("modifiers", []):
        values = modifier.get("values", [])
        units = modifier.get("units", [])
        if not values:
            continue
        if len(values) >= 18:
            index = min(max(ctx.level - 1, 0), len(values) - 1)
        else:
            index = min(max(rank - 1, 0), len(values) - 1)
        value = float(values[index])
        unit = units[index] if index < len(units) else ""
        total += (
            value
            if is_flat_unit(unit)
            else resolve_scaling(unit, value, ctx.stats, ctx.target)
        )
    return total


def _siphon_power(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: the projectile packet plus the shield and the Discharge on-hit."""
    entry = _packet_q(ctx)
    rank = int(entry.get("rank", 0) or 0) if entry is not None else 0
    if entry is None or rank < 1:
        return entry
    shield = _siphon_shield(ctx)
    entry = attach_self_shield(
        entry,
        amount=shield,
        duration=_Q_SHIELD_DURATION_SECONDS,
        source=entry.get("name", "Siphon Power"),
        detail=(
            f"Q also shields Viktor for {shield:g} for "
            f"{_Q_SHIELD_DURATION_SECONDS:g}s (self); the Discharge "
            "empowered next basic attack is priced as a one-application "
            "on-hit"
        ),
    )
    # One projectile hit at the cast boundary: certifying the packet lets
    # the damage engine declare its event ledger, which is what carries
    # the module-authored self-shield payload onto the event row (the
    # Ambessa W convention).
    entry["event_order_certified"] = "single_hit"
    if bool(ctx.options.get("q_discharge", True)):
        ability = ctx.ability()
        discharge = extract_named(
            ability, "Modified Magic Damage", rank, ctx.stats, ctx.target
        )
        entry["on_hit"] = {
            "name": "Siphon Power (Discharge)",
            "damage_per_hit": discharge,
            "damage_type": "magic",
            "max_procs": 1,
            "detail": (
                "Discharge empowered next basic attack within the 4-second "
                "window (Modified Magic Damage 20 : 120 by rank + 100% AD "
                "+ 50% AP)"
            ),
        }
    return entry


SLOTS = dict(SLOTS)
_packet_q = SLOTS["Q"]
SLOTS["Q"] = _siphon_power
parse_abilities = build_parser(SLOTS, "Viktor")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "Q (Siphon Power) shields Viktor for the per-level 40 : 140 (+ 25% AP) "
    "for 2.5 seconds (the cache's 'Bonus Damage' row is the shield base, "
    "level-indexed); the shield is granted at the cast (E8c "
    "self_shield_events payload).",
    "Q's Discharge empowers the next basic attack for 4 seconds: the "
    "Modified Magic Damage row (20 : 120 by rank + 100% AD + 50% AP) is "
    "priced as a one-application on-hit (q_discharge, default True). "
    "The Total Magic Damage row is the projectile + discharge sum.",
    "W (Gravity Field) crowd control and P (Glorious Evolution) augments "
    "remain documented out of scope.",
]
OPTIONS.append(
    {
        "key": "q_discharge",
        "type": "bool",
        "default": True,
        "label": "Q Discharge empowered next basic attack",
    }
)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
