"""Ahri — slot map for the archetype engine.

Why each slot is non-generic:
- Q (Orb of Deception) deals its "Damage Per Pass" twice — magic
  outgoing, true returning: ``casts=2`` with the mixed split (half
  magic / half true) reproduces exactly one pass of each type.
- W (Fox-Fire) is three flames at two damage tiers; the entry carries
  the ``initial_damage`` / ``subsequent_damage`` keys damage.py uses to
  mitigate each flame separately — custom fn.
- R (Spirit Rush) is three dashes per activation — the multi_cast
  archetype (``damage_per_cast`` / ``total_casts``, no cooldown key;
  damage.py spaces the dashes itself).
- E (Charm) is generic besides pinning the damage type.

All numeric values are read from the champion JSON data; nothing is
hardcoded.
"""

from typing import Any

from .engine import SlotCtx, build_parser
from .slotlib import extract_cooldown, extract_named, multi_cast, simple_damage


def _fox_fire(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: initial flame + 2 subsequent flames at reduced damage."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    initial = extract_named(ability, "Primary Magic Damage", rank, ctx.stats)
    subsequent = extract_named(ability, "Subsequent Magic Damage", rank, ctx.stats)

    return {
        "name": ability.get("name", "Fox-Fire"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "initial_damage": initial,
        "subsequent_damage": subsequent,
        "total_raw": initial + (subsequent * 2),
        "damage_type": "magic",
    }


OPTIONS: list[dict[str, Any]] = []

ASSUMPTIONS: list[str] = []

SLOTS = {
    "Q": simple_damage(attr="Damage Per Pass", dmg_type="mixed", casts=2),
    "W": _fox_fire,
    "E": simple_damage(dmg_type="magic"),
    "R": multi_cast(casts=3, dmg_type="magic"),
}

parse_abilities = build_parser(SLOTS, "Ahri")
