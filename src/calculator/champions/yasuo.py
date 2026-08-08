"""Yasuo — Gathering Storm (Q3) and Ride the Wind (E) stack systems.

Stack mechanics modeled (E3):
- Q (Steel Tempest): Gathering Storm stacks up to 2 (6-second window).
  At 2 stacks the next Q cast consumes them to become the Q3 whirlwind.
  The whirlwind deals the SAME sourced damage as a normal Q — the
  empower is a 0.9-second knockup (CC state, not damage). ``q_gathering_storm``
  is the explicit pre-stack state.
- E (Sweeping Blade): Ride the Wind stacks up to 4 on the target. Each
  stack adds the sourced "Bonus Damage per Stack" (17.5 : 32.5 by rank
  + 5% bonus AD + 15% AP), so E at N stacks prices base + N x per-stack;
  at 4 stacks this equals the wiki "Total Combined Damage".
- P (Way of the Wanderer): Flow shield (125 : 674.46 by level) is a
  state row; crit conversion and reduced crit damage are passive stats.

W (Wind Wall) and R (Last Breath) keep the reviewed CP10.10 packet
pricing. All numeric values are read from the champion JSON data.
"""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .module_helpers import no_damage
from .packet_module import build_packet_module
from .source_receipts import load_champion_sources
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
)

PACKET_SHA256 = "94e34c2bf9df12ee71c952261d6c8ca2d69773f4e5eb2fc218cd944bada606ac"

_BATCH_PARSE, _BATCH_SLOTS, _BATCH_ASSUMPTIONS, _BATCH_SOURCES, _BATCH_OPTIONS = (
    build_packet_module("Yasuo", PACKET_SHA256)
)
PACKET_SPEC = _BATCH_SLOTS.packet_spec


# P prose-sourced constants (data/champions.json, Yasuo P): "Yasuo's total
# critical strike chance is doubled from all other sources. Additionally,
# every 1% critical strike chance in excess of 100% is converted into 0.5
# bonus attack damage. Yasuo's critical strikes deal only 90% of the
# critical damage champions usually have."  The 0.9 crit-damage factor is
# also the champion's game stat ``criticalStrikeDamageModifier`` (verified
# in data/champions.json stats).  The engine applies the payload once in
# ``_apply_stat_buff_ultimates`` so auto attacks AND ability parts with
# ``crit_effectiveness`` (Steel Tempest's AD-ratio portion) share the
# converted crit chance/multiplier.
_CRIT_CHANCE_MULTIPLIER = 2.0
_CRIT_DAMAGE_MULTIPLIER_FACTOR = 0.9
_EXCESS_CRIT_BONUS_AD_PER_PERCENT = 0.5


def _way_of_the_wanderer(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: Flow shield state row carrying the crit-conversion payload."""
    ability = ctx.ability()
    if ability is None:
        return None
    shield = extract_named(ability, "Bonus Damage", ctx.level, ctx.stats, ctx.target)
    entry = no_damage(
        ctx,
        name=ability.get("name", "Way of the Wanderer"),
        reason=(
            f"Flow reaches 100 stacks (5900/5250/4600 units by level) to "
            f"grant a {shield:.2f} magic-damage shield for 1s.  Intent: "
            "total crit chance doubled (capped at 100%), crits deal 90% of "
            "the normal crit damage, and excess crit chance converts to "
            "bonus AD (0.5 per 1%) — applied by the fight engine to autos "
            "and Steel Tempest's crit-eligible AD portion."
        ),
    )
    entry["crit_modifier"] = {
        "crit_chance_multiplier": _CRIT_CHANCE_MULTIPLIER,
        "crit_damage_multiplier_factor": _CRIT_DAMAGE_MULTIPLIER_FACTOR,
        "excess_crit_bonus_ad_per_percent": _EXCESS_CRIT_BONUS_AD_PER_PERCENT,
    }
    return entry


def _steel_tempest(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: Steel Tempest, empowered into the Q3 whirlwind at 2 Gathering Storm stacks."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    stacks = min(max(int(ctx.options.get("q_gathering_storm", 0)), 0), 2)
    damage = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Steel Tempest"),
        rank,
        extract_cooldown(ability, rank),
        damage,
        "physical",
    )
    # "Steel Tempest's damage based on its AD ratio can critically strike"
    # (cached Q description): the flat 20-120 base never crits, so it is a
    # plain part; the 105% AD portion is a separate crit-eligible part that
    # uses the crit chance/multiplier the engine resolves from P's
    # crit_modifier (which already multiplies the multiplier by 0.9).
    flat = extract_value(ability, "Physical Damage", rank, 0)
    ad_ratio = extract_value(ability, "Physical Damage", rank, 1) / 100.0
    ad_part = ctx.stats.get("attack_damage", 0.0) * ad_ratio
    entry["parts"] = (
        DamagePart("physical", flat),
        DamagePart("physical", ad_part, crit_effectiveness=1.0),
    )
    if stacks >= 2:
        entry["detail"] = (
            "Gathering Storm at 2 stacks: this cast is the Q3 whirlwind — "
            "same sourced damage as a normal thrust, adding a 0.9s "
            "knock-up (crowd-control state, not damage)."
        )
    else:
        entry["detail"] = (
            f"Gathering Storm {stacks}/2 stacks; the Q3 whirlwind at 2 "
            "stacks deals the same sourced damage (the empower is the "
            "knock-up, a crowd-control state)."
        )
    return entry


def _per_target_lockout(ability: dict[str, Any], rank: int) -> float:
    """Sweeping Blade's per-target cooldown (10/9/8/7/6 by rank)."""
    raw = str(ability.get("onTargetCdStatic") or "")
    parts = [p.strip() for p in raw.split("/") if p.strip()]
    if parts:
        return float(parts[min(max(rank - 1, 0), len(parts) - 1)])
    return float(extract_cooldown(ability, rank) or 0.5)


def _sweeping_blade(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: Sweeping Blade with Ride the Wind per-stack bonus damage.

    Single-target fight model: the 0.1s ability cooldown is irrelevant to
    a one-target fight because Sweeping Blade can only hit the same target
    once per its per-target lockout (``onTargetCdStatic``, 10/9/8/7/6 by
    rank); that lockout is the cast-rate limiter here.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    stacks = min(max(int(ctx.options.get("e_stacks", 0)), 0), 4)
    base = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    per_stack = extract_named(
        ability, "Bonus Damage per Stack", rank, ctx.stats, ctx.target
    )
    total = base + stacks * per_stack
    lockout = _per_target_lockout(ability, rank)
    entry = damage_entry(
        ability.get("name", "Sweeping Blade"),
        rank,
        lockout,
        total,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", total),)
    entry["detail"] = (
        f"Ride the Wind {stacks}/4 stacks: base {base:.2f} + {stacks} x "
        f"per-stack bonus {per_stack:.2f} = {total:.2f}; at 4 stacks this "
        "equals the wiki Total Combined Damage (25% per stack, +100% at "
        f"maximum stacks).  Single-target cast rate: one dash per "
        f"{lockout:g}s per-target lockout."
    )
    return entry


SLOTS = {
    "P": _way_of_the_wanderer,
    "Q": _steel_tempest,
    "W": _BATCH_SLOTS["W"],
    "E": _sweeping_blade,
    "R": _BATCH_SLOTS["R"],
}
parse_abilities = build_parser(SLOTS, "Yasuo")

OPTIONS = [
    {
        "key": "q_gathering_storm",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 2,
        "label": "Gathering Storm stacks (2 = Q3 ready)",
    },
    {
        "key": "e_stacks",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 4,
        "label": "Ride the Wind stacks",
    },
]

ASSUMPTIONS = [
    "Q3 (Gathering Storm at 2 stacks) deals the same sourced damage as a "
    "normal Q; its empower is the 0.9s knock-up, modeled as crowd-control "
    "state, so q_gathering_storm only changes the Q row's detail",
    "E (Sweeping Blade) prices Ride the Wind stacks: base + N x "
    "per-stack bonus, capped at 4 stacks (the wiki Total Combined Damage)",
    "P (Way of the Wanderer) Intent is now priced: total crit chance is "
    "doubled (capped at 100%), crits deal 90% of the normal crit damage, "
    "and excess crit chance converts to 0.5 bonus AD per 1% — applied by "
    "the fight engine to autos and Steel Tempest's crit-eligible AD part. "
    "The Flow shield stays state (no enemy damage)",
    "Q (Steel Tempest) splits the flat 20-120 base (never crits) from the "
    "105% AD portion (crits at the converted crit stats, per the cached "
    "description 'damage based on its AD ratio can critically strike')",
    "W (Wind Wall) is utility only; R (Last Breath) keeps the reviewed "
    "CP10.10 packet pricing",
]

SOURCES = load_champion_sources("Yasuo")
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "E"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
