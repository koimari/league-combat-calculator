"""Seraphine — CP10.7 full-entry-reviewed packet module.

E8d ally-support: W (Surround Sound) shields the caster and every selected
teammate (Shield Strength 60-140 + 20% AP; scope self_and_all_teammates).
The event is authored by the engine's ally-support scanner from cached
leveling at the W cast time; the module declares W in SLOTS so the fight
rotation casts it.  W's conditional pulse heal ("% of target's missing
health") is dynamic and is NOT emitted as a flat packet — it requires the
target's live missing-health state, which the support scanner does not carry.

P1 addition over the reviewed packet:
- Q (High Note) prices the missing-health amplifier: "Against champions
  and monsters, the damage is increased by 0% : 75% (based on target's
  missing health)" (cached Q description, second effect).  The base row
  "Magic Damage" (60-160 + 40% AP) is the flat part; a second
  hp-scaled part adds 0.75 x base x missing-health-ratio, so at full
  missing health the total equals the cached "Maximum Enhanced Damage"
  row (105-280 + 70% AP = 1.75 x base).  The engine evaluates the
  hp-scaled part at the cast with the target's live missing health —
  deterministic given the fight's health walk (Akshan R precedent).
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .reviewed_batch_07 import build_batch_module
from .slotlib import damage_entry, extract_cooldown, extract_named

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Seraphine")

# HARDCODED: verify on patch updates — the 0%:75% missing-health amplifier
# is prose in the cached Q second effect ("Against champions and monsters,
# the damage is increased by 0% : 75% (based on target's missing health)");
# it is cross-checked by the cached "Maximum Enhanced Damage" row
# (105-280 + 70% AP == 1.75 x the base row at every rank).
_Q_MISSING_HEALTH_MAX_BONUS = 0.75


def _high_note(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: flat base + 0%:75% missing-health amplifier (hp-scaled part)."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    base = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    maximum = extract_named(
        ability, "Maximum Enhanced Damage", rank, ctx.stats, ctx.target
    )
    entry = damage_entry(
        ability.get("name", "High Note"),
        rank,
        extract_cooldown(ability, rank),
        base,
        "magic",
    )
    entry["parts"] = (
        # Both the flat base and the missing-health amplifier land at the
        # cast boundary: authored time_offset 0.0 upgrades their events from
        # cast_boundary to hit precision so the coverage classifier certifies
        # the row instead of downgrading it coarse (Viego R pattern).
        DamagePart("magic", base, time_offset=0.0),
        DamagePart(
            "magic",
            hp_scaled_damage=lambda missing, base=base: base
            * _Q_MISSING_HEALTH_MAX_BONUS
            * max(0.0, min(1.0, missing)),
            time_offset=0.0,
        ),
    )
    entry["detail"] = (
        f"flat {base:g} + up to {_Q_MISSING_HEALTH_MAX_BONUS * 100:g}% of "
        f"base ({maximum:g} at full missing health, the cached Maximum "
        "Enhanced Damage row) scaled by the target's live missing-health "
        "ratio"
    )
    entry["event_order_certified"] = "single_hit"
    return entry


SLOTS = dict(SLOTS)
SLOTS["Q"] = _high_note
parse_abilities = build_parser(SLOTS, "Seraphine")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "Q (High Note) prices the missing-health amplifier: base (60-160 + "
    "40% AP) plus 0.75 x base x the target's live missing-health ratio "
    "(0%:75% based on missing health; equals the cached Maximum Enhanced "
    "Damage row at full missing health)",
]

MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
