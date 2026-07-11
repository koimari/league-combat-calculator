"""Alistar — slot map for the archetype engine.

Why each slot is non-generic:
- E (Trample) is a custom fn: the cast total is the "Total Magic
  Damage" attribute (all 10 ticks over 5 s — the classifier would pick
  the per-tick "Magic Damage" first), plus the empowered-auto bonus
  that Trample grants once per cast, which scales with champion LEVEL
  (not rank) and is baked into the cast total rather than emitted as an
  on-hit. Phase 3b confirmed this shape does not fit toggle_dot (it is
  a total-attribute read plus an add-once on-hit addend).
- Q (Pulverize) / W (Headbutt) are fully generic single-hit magic
  damage — auto-mode ``simple_damage``, exactly the generic path the
  legacy module reached by calling the generic parser and patching its
  output.
- R (Unbreakable Will) is damage reduction only and P (Triumphant
  Roar) is healing only — neither is modeled, both absent from the
  slot map.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from .engine import SlotCtx, build_parser
from .slotlib import damage_entry, extract_cooldown, extract_named, simple_damage


def _extract_e_on_hit_damage(
    ability: dict[str, Any],
    level: int,
) -> float:
    """Extract E's empowered-auto bonus magic damage at a champion level.

    The empowered auto scales with champion level (not ability rank);
    the JSON stores it under "Bonus Magic Damage" as per-level values.
    Per-level arrays may have fewer entries than 18, in which case the
    level is linearly interpolated across the available values.
    (Test seam: tests/test_alistar.py validates the JSON values here.)
    """
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute", "") != "Bonus Magic Damage":
                continue

            modifiers = leveling.get("modifiers", [])
            if not modifiers:
                continue

            values = modifiers[0].get("values", [])
            if not values:
                continue

            if len(values) >= level:
                return float(values[level - 1])

            # Interpolate: map level (1-18) into the values array.
            num_values = len(values)
            if num_values == 1:
                return float(values[0])

            fraction = (level - 1) / 17.0  # 0.0 at level 1, 1.0 at 18
            index_float = fraction * (num_values - 1)
            low_idx = int(index_float)
            high_idx = min(low_idx + 1, num_values - 1)
            weight = index_float - low_idx
            return (
                float(values[low_idx]) * (1 - weight) + float(values[high_idx]) * weight
            )

    return 0.0


def _trample(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: full-duration tick total + level-scaled empowered auto."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    total = extract_named(ability, "Total Magic Damage", rank, ctx.stats, ctx.target)
    # The empowered auto procs once per E cast, so it joins the cast
    # total instead of becoming a per-auto on_hit entry.
    total += _extract_e_on_hit_damage(ability, ctx.level)

    name = ability.get("name", "Trample")
    return damage_entry(name, rank, extract_cooldown(ability, rank), total, "magic")


SLOTS = {
    "Q": simple_damage(),
    "W": simple_damage(),
    "E": _trample,
}

parse_abilities = build_parser(SLOTS, "Alistar")
