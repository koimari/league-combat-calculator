"""Skarner — CP10.7 full-entry-reviewed packet module.

P1-3 closures:

- W (Seismic Bastion) shield: the reviewed packet priced only the
  shockwave's magic damage.  The cached W description sources the
  shield: "shielding himself equal to 8% of his maximum health for 2.5
  seconds" — the W damage event now carries a ``self_shield_events``
  payload (the E8c interface) for 8% of Skarner's maximum health over
  2.5s.

- E (Ixtal's Impact): the packet manifest lists E as a formula slot
  (wiki_attribute "Physical Damage") while MODULE_COVERAGE declared it
  out_of_scope — an inconsistency.  The damage lands when the charged
  target collides with terrain; the deterministic single-target model
  assumes the collision and prices the sourced "Physical Damage" row
  (30-150 + 120% bonus AD + 6% of his maximum health by rank).  The
  "of his maximum health" term is not a generic scaling unit, so the
  parser adds it explicitly from the same leveling row.
"""

from .engine import SlotCtx, build_parser
from .reviewed_batch_07 import build_batch_module
from .slotlib import (
    attach_self_shield,
    damage_entry,
    extract_cooldown,
    extract_named,
    find_named_leveling,
    sum_modifiers,
)

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Skarner")
VARIANT_OPTION_KEYS = ("q_variant",)

# HARDCODED: verify on patch updates — wiki prose, not in the JSON
# leveling rows.  Seismic Bastion's shield: "shielding himself equal to
# 8% of his maximum health for 2.5 seconds" (cached W description).
_W_SHIELD_MAX_HEALTH_RATIO = 0.08
_W_SHIELD_DURATION = 2.5


def _seismic_bastion(ctx: SlotCtx):
    """W: shockwave magic damage + the 8%-max-health self-shield."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    damage = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Seismic Bastion"),
        rank,
        extract_cooldown(ability, rank),
        damage,
        "magic",
    )
    entry["event_order_certified"] = "single_hit"
    shield = _W_SHIELD_MAX_HEALTH_RATIO * float(ctx.stats.get("health", 0.0) or 0.0)
    attach_self_shield(
        entry,
        amount=shield,
        duration=_W_SHIELD_DURATION,
        source="Seismic Bastion",
        detail=(
            f"W also shields Skarner for {shield:g} "
            f"({_W_SHIELD_MAX_HEALTH_RATIO * 100:g}% of his maximum "
            f"health) for {_W_SHIELD_DURATION:g}s (self)"
        ),
    )
    return entry


def _ixtals_impact(ctx: SlotCtx):
    """E: terrain-collision physical damage (flat + bAD + % max health)."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    leveling = find_named_leveling(ability, "Physical Damage")
    if leveling is None:
        return None

    def max_health_override(unit: str, value: float) -> float | None:
        """E's '6% of his maximum health' term (Skarner's own health)."""
        if "of his maximum health" not in unit:
            return None
        return value / 100.0 * float(ctx.stats.get("health", 0.0) or 0.0)

    damage = sum_modifiers(
        leveling, rank, ctx.stats, ctx.target, modifier_override=max_health_override
    )
    entry = damage_entry(
        ability.get("name", "Ixtal's Impact"),
        rank,
        extract_cooldown(ability, rank),
        damage,
        "physical",
    )
    entry["detail"] = (
        "Terrain-collision damage (the charged target is assumed to "
        "collide): 30-150 + 120% bonus AD + 6% of Skarner's maximum "
        "health by rank"
    )
    return entry


SLOTS = dict(SLOTS)
SLOTS["W"] = _seismic_bastion
SLOTS["E"] = _ixtals_impact
parse_abilities = build_parser(SLOTS, "Skarner")

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "W (Seismic Bastion) shields Skarner for 8% of his maximum health "
    "for 2.5 seconds (cached W prose) via the shared self_shield_events "
    "interface; the shockwave damage is unchanged.",
    "E (Ixtal's Impact) prices the sourced 'Physical Damage' row "
    "(30-150 + 120% bonus AD + 6% of his maximum health by rank, "
    "data/champions.json E) assuming the charged target collides with "
    "terrain; the charge, grab, and stun are state.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "E", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
