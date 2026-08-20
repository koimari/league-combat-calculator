"""Vayne — slot map for the archetype engine.

Why each slot is non-generic:
- R (Final Hour) is a flat bonus-AD ``stat_buff`` (BUFF phase, so Q/E
  scale off the buffed AD) that also drives Q's cooldown: the "Tumble
  Cooldown Reduction" leveling value is published into the parse
  context via the archetype's ``couples`` param, under the
  ``tumble_cd_reduction_percent`` stash key Q reads below.
- Q (Tumble) is a plain "Bonus Physical Damage" read wrapped to scale
  its cooldown by R's published reduction (100% - reduction), stamped
  ``empowers_next_auto`` so the fight engine caps casts at the auto
  count: the damage only lands through the empowered basic attack.
  Tumble is an attack reset (wiki: "resets Vayne's basic attack
  timer"), so the dash costs no attack time and the auto count is
  unaffected; the reset's throughput gain is not modeled.
- W (Silver Bolts) procs true damage (% of target max health, floored
  at "Minimum Bonus Damage") on every 3rd hit — the shared
  ``pct_health_per_hit`` math in a custom fn, because the emitted
  legacy shape is a cooldown-less zero-damage shell whose on-hit dict
  carries ``stacks_required`` for the fight engine's proc grouping.
- E (Condemn) picks its damage attribute by the ``condemn_wall``
  option (default True): "Total Physical Damage" includes the wall
  crash bonus, "Physical Damage" is the unstunned base.
- P (Night Hunter) is movement speed only — not modeled, absent from
  the slot map.

All numeric values are read from the champion JSON data except the
proc cadence: Silver Bolts' every-3rd-hit rule is prose, not leveling
data, hence the module constant.
"""

from typing import Any

from .engine import SlotCtx, build_parser
from .slotlib import (
    ability_on_hit_entry,
    by_option,
    pct_health_per_hit,
    simple_damage,
    stat_buff,
)

# Silver Bolts procs on every 3rd basic attack (wiki prose, not JSON).
_SILVER_BOLTS_STACKS = 3

_tumble_damage = simple_damage(
    attr="Bonus Physical Damage",
    dmg_type="physical",
    event_order_certified="single_hit",
)


def _tumble(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: empowered-auto damage entry, cooldown scaled by R's published CDR."""
    entry = _tumble_damage(ctx)
    if entry is not None:
        reduction = ctx.stat("tumble_cd_reduction_percent")
        entry["cooldown"] *= 1.0 - reduction / 100.0
        entry["empowers_next_auto"] = True
    return entry


def _silver_bolts(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: %maxHP true damage every 3rd hit, in the legacy on-hit shell."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    per_hit = pct_health_per_hit(
        ability,
        "Bonus True Damage",
        rank,
        ctx.target,
        floor_attr="Minimum Bonus Damage",
        stacks_required=_SILVER_BOLTS_STACKS,
    )
    if per_hit is None:
        return None

    name = ability.get("name", "Silver Bolts")
    return ability_on_hit_entry(
        name,
        rank,
        "true",
        {
            "name": name,
            "damage_per_hit": per_hit,
            "damage_type": "true",
            "stacks_required": _SILVER_BOLTS_STACKS,
        },
    )


OPTIONS = [
    {
        "key": "condemn_wall",
        "type": "bool",
        "default": True,
        "label": "E Condemn into wall",
    },
]

ASSUMPTIONS = [
    "R (Final Hour) always active if ranked — bonus AD applied",
    "W (Silver Bolts) procs every 3rd hit (on-hit model)",
    "Q (Tumble) damage rides the next auto — casts capped by the auto "
    "count; the dash is an attack reset, so it costs no attack time "
    "(reset acceleration not modeled)",
    "Passive (Night Hunter) is utility only — not modeled",
]

SLOTS = {
    "R": stat_buff(
        "Bonus Attack Damage",
        "bonus_attack_damage",
        apply_to=("attack_damage", "bonus_attack_damage"),
        couples=("tumble_cd_reduction_percent", "Tumble Cooldown Reduction"),
    ),
    "Q": _tumble,
    "W": _silver_bolts,
    "E": by_option(
        "condemn_wall",
        {
            True: simple_damage(
                attr="Total Physical Damage",
                dmg_type="physical",
                event_order_certified="single_hit",
            ),
            False: simple_damage(
                attr="Physical Damage",
                dmg_type="physical",
                event_order_certified="single_hit",
            ),
        },
        default=True,
    ),
}

# Tumble only "empowers her next basic attack ... to deal bonus physical
# damage"; Condemn "knocks them back 475 units" on every cast, and adds a
# 1.5s stun only "if the target collides with terrain" — the knockback is
# the control the cast always applies, and both branches of the
# ``condemn_wall`` option carry it.  W is the Silver Bolts on-hit shell
# (its true damage rides a basic attack, not an ability event) and R is a
# pure stat buff, so neither authors a part a review could reach.
MODULE_CC = {"Q": "none", "E": "knockback"}

parse_abilities = build_parser(SLOTS, "Vayne", cc_kinds=MODULE_CC)


SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Vayne",
        "revision_id": 3979075,
        "revision_timestamp": "2025-12-25T10:25:25Z",
    }
]
