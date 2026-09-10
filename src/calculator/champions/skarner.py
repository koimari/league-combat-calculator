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

from typing import Any

from ..binary_roots import data_value, spell_object
from .engine import SlotCtx
from .module_helpers import ability_cast_times, named_damage
from .packet_module import build_packet_module, repeat_damage_parser
from .shared_mechanics import with_self_shield
from .slot_entries import damage_entry
from .slot_extract import (
    ability_name,
    extract_cooldown,
    extract_value,
    find_named_leveling,
    sum_modifiers,
)
from .slotlib import simple_damage

PACKET_SHA256 = "8cd0eacf4fa3f8ac9dc2353f0b6f6edb853a72c59b2dcf737d60980d28900c2c"


# Rooted in SkarnerW.InitialShieldRatio / ShieldDuration; the cached W
# description corroborates the 8%-maximum-health shield over 2.5 seconds.
_SKARNER_W_SPELL = spell_object("Skarner", "SkarnerW")
_W_SHIELD_MAX_HEALTH_RATIO = data_value(_SKARNER_W_SPELL, "InitialShieldRatio")
_W_SHIELD_DURATION = data_value(_SKARNER_W_SPELL, "ShieldDuration")

# Shattered Earth empowers "up to three of his next basic attacks" (cached
# Q prose), the same three the packet's Bonus Physical Damage per Hit x 3
# prices; the number of casts the walk mirrors is the rotation's.
_Q_EMPOWERED_ATTACKS = 3


def _shattered_earth_attack_speed(packet_q):
    """Q: the empowered attacks' bonus attack speed, weighted by the casts' share.

    Each Shattered Earth cast rates its three attacks at the row's bonus
    attack speed, so the fight-wide grant is that bonus weighted by the
    share of the window the mirrored casts' empowered swings cover: a
    3-second cooldown re-arms it almost every swing.  Upheaval (variant 1)
    throws the boulder instead and grants nothing.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_q(ctx)
        if entry is None or int(ctx.option("q_variant")) != 0:
            return entry
        ability = ctx.ability("Q")
        rank = ctx.rank_for("Q")
        if ability is None or rank < 1:
            return entry
        granted = extract_value(ability, "Bonus Attack Speed", rank)
        duration = float(ctx.option("fight_duration_seconds"))
        if duration <= 0.0:
            share = 1.0
        else:
            buffed = float(ctx.stat("attack_speed")) + float(
                ctx.stat("attack_speed_ratio")
            ) * (granted / 100.0)
            casts = len(ability_cast_times(ctx, duration, ("Q",)))
            share = min(1.0, casts * _Q_EMPOWERED_ATTACKS / buffed / duration)
        published = granted * share
        entry["stat_buff"] = {"bonus_attack_speed": published}
        inherited = str(entry["detail"]).strip() if "detail" in entry else ""
        entry["detail"] = (
            f"+{granted:g}% bonus attack speed on each cast's "
            f"{_Q_EMPOWERED_ATTACKS} empowered attacks ({published:g}% over the "
            "fight window, weighted by the mirrored casts' swings)."
            + (f" {inherited}" if inherited else "")
        )
        return entry

    return parse


# W's shockwave carries the shield the cached description sources, so the
# ledger grants it at the same event.
_seismic_bastion = with_self_shield(
    named_damage("Magic Damage", "magic"),
    shield=lambda ctx: _W_SHIELD_MAX_HEALTH_RATIO * float(ctx.stat("health") or 0.0),
    window=_W_SHIELD_DURATION,
    source="Seismic Bastion",
    detail=lambda ctx, shield: (
        f"W also shields Skarner for {shield:g} "
        f"({_W_SHIELD_MAX_HEALTH_RATIO * 100:g}% of his maximum "
        f"health) for {_W_SHIELD_DURATION:g}s (self)"
    ),
)


def _ixtals_impact(ctx: SlotCtx) -> dict[str, Any] | None:
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
    slot_wrappers={"Q": _shattered_earth_attack_speed},
    cc_kinds=MODULE_CC,
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "Q (Shattered Earth) grants its bonus attack speed on each cast's three "
    "empowered attacks, published as one fight-wide stat buff weighted by "
    "the share of the window those swings cover across the mirrored casts "
    "(Braum-pattern schedule: each cast at t=0 and every hasted cooldown); "
    "the 5-second hold between attacks and Upheaval's early throw are not "
    "modeled, and the Upheaval variant grants nothing.",
    "W (Seismic Bastion) shields Skarner for 8% of his maximum health "
    "for 2.5 seconds (cached W prose) via the shared self_shield_events "
    "interface; the shockwave damage is unchanged.",
    "E (Ixtal's Impact) prices the sourced 'Physical Damage' row "
    "(30-150 + 120% bonus AD + 6% of his maximum health by rank, "
    "data/champions.json E) assuming the charged target collides with "
    "terrain; the charge, grab, and stun are state.",
]
