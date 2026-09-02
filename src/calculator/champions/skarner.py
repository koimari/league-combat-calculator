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

from ..binary_roots import data_value, spell_object
from .engine import SlotCtx
from .packet_module import build_packet_module, repeat_damage_parser
from .slotlib import (
    ability_name,
    attach_self_shield,
    damage_entry,
    extract_cooldown,
    extract_named,
    find_named_leveling,
    simple_damage,
    sum_modifiers,
)

PACKET_SHA256 = "1f62c9ad3216116b491935d3b92ff91949b3bea5a6a7381af05e7b6cfcbf5577"


# Rooted in SkarnerW.InitialShieldRatio / ShieldDuration; the cached W
# description corroborates the 8%-maximum-health shield over 2.5 seconds.
_SKARNER_W_SPELL = spell_object("Skarner", "SkarnerW")
_W_SHIELD_MAX_HEALTH_RATIO = data_value(_SKARNER_W_SPELL, "InitialShieldRatio")
_W_SHIELD_DURATION = data_value(_SKARNER_W_SPELL, "ShieldDuration")


def _seismic_bastion(ctx: SlotCtx):
    """W: shockwave magic damage + the 8%-max-health self-shield."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    damage = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        damage,
        "magic",
    )
    entry["event_order_certified"] = "single_hit"
    shield = _W_SHIELD_MAX_HEALTH_RATIO * float(ctx.stat("health") or 0.0)
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
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    leveling = find_named_leveling(ability, "Physical Damage")
    if leveling is None:
        return None

    def max_health_override(unit: str, value: float) -> float | None:
        """E's '6% of his maximum health' term (Skarner's own health)."""
        if "of his maximum health" not in unit:
            return None
        return value / 100.0 * float(ctx.stat("health") or 0.0)

    damage = sum_modifiers(
        leveling, rank, ctx.stats, ctx.target, modifier_override=max_health_override
    )
    entry = damage_entry(
        ability_name(ability),
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
    # One collision, one blow ("the charge ends, detaching them from him,
    # dealing physical damage, stunning them for 1.1 seconds").
    entry["event_order_certified"] = "single_hit"
    return entry


# Reviewed crowd control, read from the cached kit.  P (Threads of
# Vibration) only stacks Quaking for max-health magic damage.  Q, in both
# variants, ends on the boulder slam "slowing afflicted enemies by 40% for
# 1 second" (Upheaval applies "the same damage and slow").  W (Seismic
# Bastion) deals its shockwave damage "and slow them by 20% for 1 second".
# E (Ixtal's Impact) prices the terrain collision, which ends "dealing
# physical damage, stunning them for 1.1 seconds" — the suppression is the
# grab that precedes it, the stun is what lands with the damage.  R
# (Impale) deals its damage "and impaling up to 3 of the closest enemy
# champions within the area to suppress them for 1.5 seconds".
MODULE_CC = {
    "P": "none",
    "Q": "slow",
    "W": "slow",
    "E": "stun",
    "R": "suppression",
}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Skarner",
    PACKET_SHA256,
    assumption_overrides=(
        "Shattered Earth prices all three empowered basic attacks (Bonus "
        "Physical Damage per Hit x 3 == Total Bonus Physical Damage).",
    ),
    # Impale is one lash ("lashes them forward ... dealing magic damage to
    # enemies hit"), so its single part is a hit the ledger can time.
    single_hit_slots=frozenset({"R"}),
    variant_parsers={
        ("Q", 0): repeat_damage_parser(
            attr="Bonus Physical Damage per Hit",
            dmg_type="physical",
            count=3,
            time_offset=0.0,
            hit_interval=0.0,
            name="Shattered Earth",
        ),
        # Upheaval "explodes upon colliding with the first enemy hit" —
        # one blow, so it certifies the same way Shattered Earth's
        # authored three-swing schedule does.
        ("Q", 1): simple_damage(
            attr="Physical Damage",
            dmg_type="physical",
            ranks="rank",
            source=("Q", 1),
            event_order_certified="single_hit",
        ),
    },
    slot_parsers={
        "W": _seismic_bastion,
        "E": _ixtals_impact,
    },
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "W (Seismic Bastion) shields Skarner for 8% of his maximum health "
    "for 2.5 seconds (cached W prose) via the shared self_shield_events "
    "interface; the shockwave damage is unchanged.",
    "E (Ixtal's Impact) prices the sourced 'Physical Damage' row "
    "(30-150 + 120% bonus AD + 6% of his maximum health by rank, "
    "data/champions.json E) assuming the charged target collides with "
    "terrain; the charge, grab, and stun are state.",
]
