"""Tristana — slot map for the archetype engine (E3 stack systems).

Why each slot is non-generic:
- E (Explosive Charge) is the stack system: the charge attaches to the
  target and each of Tristana's basic attacks / abilities against it
  increases the detonation damage by 25%, stacking up to 4 times (100%)
  and detonating instantly at max stacks. The detonation is priced from
  the ``e_stacks`` option (default 4 = the sourced max): "Minimum
  Physical Damage" (the 0-stack base) plus ``e_stacks`` x "Bonus Damage
  Per Stack" — at 4 stacks this equals the wiki's "Full Stack Physical
  Damage" row at every rank. The charge detonates once per cast.
- Q (Rapid Fire) is the attack-speed steroid, and for a marksman whose
  output is basic attacks it is the biggest number in the kit: the
  cached "Bonus Attack Speed" row (60-120%) rides a BUFF-phase
  ``stat_buff`` so the fight engine's auto count scales with it.
- P (Draw a Bead) is attack range only: an emitted zero-damage row.
- W (Rocket Jump) and R (Buster Shot) are plain attribute reads; W's
  takedown/max-stack-detonation reset is CC/state only, and R's
  knockback/stun is CC only.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .module_helpers import buff_window_share
from .slotlib import (
    STEROID_ZERO,
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
    simple_damage,
)
from .source_receipts import load_champion_sources

# HARDCODED: verify on patch updates — the 4-stack cap is wiki prose
# ("stacking up to 4 times for a maximum 100% increase"); the damage
# rows themselves are read from the JSON.
_E_MAX_STACKS = 4

# HARDCODED: verify on patch updates — Rapid Fire's window is cached Q
# prose ("gaining bonus attack speed for 7 seconds"); the percentage is
# the JSON's "Bonus Attack Speed" row.
_Q_DURATION_SECONDS = 7.0


def _explosive_charge(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: the detonation — base + e_stacks x per-stack bonus."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    stacks = min(_E_MAX_STACKS, max(0, int(ctx.options.get("e_stacks", _E_MAX_STACKS))))
    base = extract_named(
        ability, "Minimum Physical Damage", rank, ctx.stats, ctx.target
    )
    per_stack = extract_named(
        ability, "Bonus Damage Per Stack", rank, ctx.stats, ctx.target
    )
    total = base + per_stack * stacks
    entry = damage_entry(
        ability.get("name", "Explosive Charge"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", total),)
    # One detonation, one blow ("The charge then detonates, dealing
    # physical damage to nearby enemies").
    entry["event_order_certified"] = "single_hit"
    entry["detail"] = (
        f"{stacks}/4 stack(s); "
        f"base {base:.2f} + {stacks} x {per_stack:.2f} per-stack bonus"
    )
    return entry


def _rapid_fire(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: the 60-120% attack-speed steroid, priced onto the auto count."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    share = buff_window_share(ctx, _Q_DURATION_SECONDS)
    granted = extract_value(ability, "Bonus Attack Speed", rank)
    bonus_as = granted * share
    entry = damage_entry(
        ability.get("name", "Rapid Fire"),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "physical",
        zero_policy=STEROID_ZERO,
    )
    entry["stat_buff"] = {"bonus_attack_speed": bonus_as}
    entry["detail"] = (
        f"+{granted:g}% bonus attack speed for {_Q_DURATION_SECONDS:g}s "
        f"({bonus_as:g}% over the fight window); no enemy damage"
    )
    return entry


_rapid_fire.phase = BUFF


def _draw_a_bead(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: longer-range basic attacks — no enemy damage beyond the auto."""
    ability = ctx.ability()
    if ability is None:
        return None
    return {
        "name": ability.get("name", "Draw a Bead"),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "physical",
        "total_raw": 0.0,
        "parts": (),
        "detail": (
            "Ranged auto-attack bonus: range/on-hit state only, no " "separate damage."
        ),
    }


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "e_stacks",
        "type": "int",
        "default": _E_MAX_STACKS,
        "min": 0,
        "max": _E_MAX_STACKS,
        "label": (
            "Explosive Charge stacks when it detonates "
            "(4 = max 100% increase, instant detonation)"
        ),
    },
]

ASSUMPTIONS = [
    "E (Explosive Charge) detonates once per cast with e_stacks stacks "
    "(default 4 = the sourced max): Minimum Physical Damage + stacks x "
    "Bonus Damage Per Stack, equal to the wiki's Full Stack Physical "
    "Damage row at 4 stacks",
    "The auto-attack rate that adds stacks in a real fight is not "
    "modeled — the stack count is the option; the fight's own autos "
    "still deal their base AD damage",
    "The charge's 0-40% (+0-12%) crit-chance bonus to its total damage "
    "is not modeled (no crit in the no-items reference)",
    "Q (Rapid Fire) grants the cached Bonus Attack Speed row (60-120%) "
    "for 7 seconds; the fight engine applies it to the auto count, "
    "time-weighted by the share of the fight window the 7-second buff "
    "covers (the whole bonus in one-rotation mode, which has no window)",
    "P (Draw a Bead) is attack range only — an emitted zero-damage row",
    "W's takedown/max-stack reset and R's knockback/stun are " "CC/state only",
]

SLOTS = {
    "Q": _rapid_fire,
    # One landing and one cannonball: each row is one blow the ledger can
    # time, which is what carries its MODULE_CC answer.
    "W": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "E": _explosive_charge,
    "R": simple_damage(
        attr="Magic Damage", dmg_type="magic", event_order_certified="single_hit"
    ),
    "P": _draw_a_bead,
}

# Reviewed crowd control, read from the cached kit.  W (Rocket Jump):
# "Upon landing, she deals magic damage to nearby enemies and slows them
# by 40% for 2 seconds".  E (Explosive Charge) detonates "dealing physical
# damage to nearby enemies" and applies none.  R (Buster Shot) deals its
# damage and the targets "are also knocked back and stunned for a
# duration" — two immobilize kinds, so the reviewed answer is the
# un-narrowed one.  Q and P deal no damage.
MODULE_CC = {"W": "slow", "E": "none", "R": "immobilize"}

parse_abilities = build_parser(SLOTS, "Tristana", cc_kinds=MODULE_CC)

# P is emitted and grants nothing the engine prices (attack range), which
# is what ``no_damage`` states; Q now carries a priced stat_buff row.
MODULE_COVERAGE = {
    slot: ("no_damage" if slot == "P" else "modeled") for slot in "PQWER"
}

SOURCES = load_champion_sources("Tristana")
