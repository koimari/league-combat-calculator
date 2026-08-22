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
  entry is a cooldown-less zero-damage shell whose on-hit dict
  carries ``stacks_required`` for the fight engine's proc grouping.
- E (Condemn) picks its damage attribute by the ``condemn_wall``
  option (default True): "Total Physical Damage" includes the wall
  crash bonus, "Physical Damage" is the unstunned base.
- P (Night Hunter) is movement speed only — not modeled, absent from
  the slot map.

All numeric values are read from the champion JSON data except the
proc cadence: Silver Bolts' every-3rd-hit rule is prose, not leveling
data, hence the module constant.

Coverage: P (Night Hunter) is a self movement-speed buff toward
slowed/immobile enemies — the pinned reviewed packet declares it
``kind: "no_damage"``. It stays off the slot map so the ledger never
invents an enemy hit, and ``MODULE_COVERAGE`` states that reviewed
absence of damage rather than an unmodeled gap.
"""

from typing import Any

from .engine import SlotCtx, build_parser
from .slotlib import (
    ability_name,
    ability_on_hit_entry,
    by_option,
    pct_health_per_hit,
    simple_damage,
    stat_buff,
    with_control_event,
)
from .source_receipts import load_champion_sources
from .inputs import bool_option
from .module_contract import coverage

# Silver Bolts procs on every 3rd basic attack (wiki prose, not JSON).
_SILVER_BOLTS_STACKS = 3

_tumble_damage = simple_damage(
    attr="Bonus Physical Damage",
    dmg_type="physical",
    event_order_certified="single_hit",
)


def _tumble(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: empowered-auto damage entry, cooldown scaled by R's published CDR.

    The attack reset's THROUGHPUT is opt-in through ``q_tumble_reset``,
    which stamps the empower as a self-supplying burst at an infinite
    rate (``hits: 1`` + ``attack_speed: inf``).  The wiki reset prose and
    the binary's Trait_AttackReset tag say "immediately" without a
    magnitude, so an infinite rate is the exact encoding, and the burst
    machinery buys one EXTRA swing per accepted cast with no dead time.
    The default caps casts at the auto count and models no gain.  The
    option is read STRICTLY (``is True``) so junk fails closed.
    """
    entry = _tumble_damage(ctx)
    if entry is not None:
        reduction = ctx.stat("tumble_cd_reduction_percent")
        entry["cooldown"] *= 1.0 - reduction / 100.0
        if ctx.options.get("q_tumble_reset") is True:
            entry["empowers_next_auto"] = {
                "hits": 1,
                "attack_speed": float("inf"),
            }
        else:
            entry["empowers_next_auto"] = True
    return entry


def _silver_bolts(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: %maxHP true damage every 3rd hit, in the on-hit shell."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

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

    name = ability_name(ability)
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
    bool_option("condemn_wall", True, label="E Condemn into wall"),
    bool_option(
        "q_tumble_reset",
        False,
        label="Model Tumble's attack-reset throughput: each accepted Q cast "
        "buys one extra basic attack (the wiki: 'Tumble resets Vayne's "
        "basic attack timer'; the binary Trait_AttackReset tag; the "
        "acceleration magnitude is script-side)",
    ),
]

ASSUMPTIONS = [
    "R (Final Hour) always active if ranked — bonus AD applied",
    "W (Silver Bolts) procs every 3rd hit (on-hit model)",
    "Q (Tumble) damage rides the next auto — casts capped by the auto "
    "count; the dash is an attack reset, so it costs no attack time.  "
    "The reset's THROUGHPUT is opt-in via q_tumble_reset: with the "
    "option on, each accepted Q cast's empowered auto is an EXTRA swing "
    "(the entry becomes a self-supplying burst at an infinite rate — "
    "'fires immediately', the wiki reset prose + the binary "
    "Trait_AttackReset tag; the acceleration magnitude is script-side, "
    "so no finite number is invented); casts lift to the cooldown grid "
    "and the W/on-hit counters ride the augmented stream.  Default "
    "keeps the conservative cap (the reset's gain not modeled).",
    "E stuns for the sourced 1.5 seconds only when Condemn is set to hit a wall",
    "P (Night Hunter) has no enemy-damage formula: the bonus movement "
    "speed toward slowed/immobile enemies is self-directed only "
    "(confirmed by the pinned reviewed packet's kind='no_damage' "
    "declaration for P). P is deliberately absent from SLOTS so the "
    "fight ledger never invents an enemy hit; MODULE_COVERAGE reflects "
    "a sourced no-damage classification rather than an unmodeled gap "
    "(no_damage, not out_of_scope).",
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
            # The wall branch adds the sourced 1.5s stun as its own control
            # event: the slot's declared kind stays the knockback every cast
            # applies, so the no-wall branch cannot report a stun it never
            # lands.
            True: with_control_event(
                simple_damage(
                    attr="Total Physical Damage",
                    dmg_type="physical",
                    event_order_certified="single_hit",
                ),
                kind="stun",
                duration_attr="Stun Duration",
                effect_index=1,
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
# ``condemn_wall`` option carry it; the wall branch adds the sourced stun
# as a control event rather than as the slot's kind.  W is the Silver
# Bolts on-hit shell
# (its true damage rides a basic attack, not an ability event) and R is a
# pure stat buff, so neither authors a part a review could reach.
MODULE_CC = {"Q": "none", "E": "knockback"}

parse_abilities = build_parser(SLOTS, "Vayne", cc_kinds=MODULE_CC)


SOURCES = load_champion_sources("Vayne")

# P damages nothing and is deliberately off the slot map, so it is a
# reviewed no-damage slot rather than the unmodeled gap SLOTS derives.
MODULE_COVERAGE = coverage(no_damage="P")
