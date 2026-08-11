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
    with_control,
)

# Silver Bolts procs on every 3rd basic attack (wiki prose, not JSON).
_SILVER_BOLTS_STACKS = 3

_tumble_damage = simple_damage(attr="Bonus Physical Damage", dmg_type="physical")


def _tumble(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: empowered-auto damage entry, cooldown scaled by R's published CDR.

    The attack reset's THROUGHPUT is opt-in: with the ``q_tumble_reset``
    option the empower is stamped as a self-supplying burst at an
    infinite rate (``hits: 1`` + ``attack_speed: inf``) — "the auto
    fires immediately" (the wiki reset prose + the binary
    Trait_AttackReset tag; the acceleration magnitude is script-side,
    so the infinite rate is the exact encoding of "immediately", and
    the engine's burst machinery buys one EXTRA swing per accepted
    cast with zero dead time).  Default keeps the conservative
    ``True`` form (casts capped at the auto count; the reset's gain
    not modeled).  The option is read STRICTLY (``is True``) so junk
    values fail closed to the default.
    """
    entry = _tumble_damage(ctx)
    if entry is not None:
        reduction = ctx.stats.get("tumble_cd_reduction_percent", 0.0)
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
    {
        "key": "q_tumble_reset",
        "type": "bool",
        "default": False,
        "label": (
            "Model Tumble's attack-reset throughput: each accepted Q cast "
            "buys one extra basic attack (the wiki: 'Tumble resets Vayne's "
            "basic attack timer'; the binary Trait_AttackReset tag; the "
            "acceleration magnitude is script-side)"
        ),
        # NO rotation metadata — a throughput assertion is not a rotation
        # edge (centrally classified irrelevant, the w_kill_assertion
        # precedent).
    },
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
            True: with_control(
                simple_damage(attr="Total Physical Damage", dmg_type="physical"),
                kind="stun",
                duration_attr="Stun Duration",
                effect_index=1,
            ),
            False: simple_damage(attr="Physical Damage", dmg_type="physical"),
        },
        default=True,
    ),
}

parse_abilities = build_parser(SLOTS, "Vayne")


# Authoritative review metadata (issue #161).
SOURCES = [
    {
        "label": "Local League Wiki cache",
        "url": "https://wiki.leagueoflegends.com/en-us/Vayne",
        "revision_id": 3979075,
        "revision_timestamp": "2025-12-25T10:25:25Z",
    }
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
