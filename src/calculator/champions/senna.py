"""Senna — reviewed packet slots plus the E3 stack mechanics.

E3 additions over the CP10.7 packet module:
- P (Absolution) becomes a BUFF-phase stack slot with two priced
  mechanics:
  1. Mist (soul) stacks — each stack grants 0.75 bonus attack damage,
     and every 20 stacks grant 20 bonus attack range and 10% critical
     strike chance. The stack count is a user option
     (``senna_mist_stacks``, default 40 — the expected mid-game state);
     the model cannot simulate Wraith-farming, so the pre-stacked count
     is priced (module convention for permanent scaling).
  2. Weakened Soul mark — autos and ability hits apply a 4-second mark;
     the next hit consumes it for bonus physical damage equal to
     1% : 10% (based on level) of the target's CURRENT health. The
     on-hit model prices it as an every-2nd-hit proc
     (``stacks_required`` 2, ``count_ability_hits``) against the
     target's MAX health — the standard engine convention for %health
     on-hits (Vayne W), documented as a boundary: the real term decays
     with the target's current health, the model uses max health.
- The remaining slots keep their reviewed packet reads; Q/W/R scale off
  the Mist-buffed AD because P runs first in the BUFF phase.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import BUFF, SlotCtx, build_parser
from .reviewed_batch_07 import build_batch_module
from .slotlib import extract_value

_packet_parse, _packet_slots, _packet_assumptions, _packet_sources, _packet_options = (
    build_batch_module("Senna")
)

# HARDCODED: verify on patch updates — Mist's per-stack values (0.75 AD,
# 20 range and 10% crit per 20 stacks) are wiki prose; the JSON only
# carries the mark's Current Health Damage leveling and the Relic Cannon
# description.
_MIST_AD_PER_STACK = 0.75  # bonus AD per Mist stack
_MIST_STACKS_PER_THRESHOLD = 20
_MIST_RANGE_PER_THRESHOLD = 20.0  # bonus attack range
_MIST_CRIT_PER_THRESHOLD = 10.0  # % crit chance
_MARK_STACKS = 2  # apply on hit 1, consume on hit 2


def _absolution(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: Mist stat buffs + Weakened Soul every-2nd-hit %health proc."""
    ability = ctx.ability()
    if ability is None:
        return None

    stacks = int(ctx.options.get("senna_mist_stacks", 40))
    stacks = min(max(stacks, 0), 300)
    bonus_ad = _MIST_AD_PER_STACK * stacks
    thresholds = stacks // _MIST_STACKS_PER_THRESHOLD
    bonus_crit = _MIST_CRIT_PER_THRESHOLD * thresholds
    bonus_range = _MIST_RANGE_PER_THRESHOLD * thresholds

    # BUFF phase guarantee: Q/W/R parse against the Mist-buffed AD.
    ctx.stats["bonus_attack_damage"] = (
        ctx.stats.get("bonus_attack_damage", 0.0) + bonus_ad
    )
    ctx.stats["attack_damage"] = ctx.stats.get(
        "base_attack_damage", 0.0
    ) + ctx.stats.get("bonus_attack_damage", 0.0)
    ctx.stats["critical_strike_chance"] = (
        ctx.stats.get("critical_strike_chance", 0.0) + bonus_crit
    )

    # Weakened Soul: bonus physical damage = level-scaled % of the
    # target's current health on the consuming hit. Max-health proxy
    # (see module docstring).
    percent = extract_value(ability, "Current Health Damage", ctx.level)
    max_health = ctx.target.get("target_max_health", 0.0)
    per_proc = percent / 100.0 * max_health

    return {
        "name": ability.get("name", "Absolution"),
        "rank": ctx.level,
        "damage_type": "physical",
        "total_raw": 0.0,
        "parts": (),
        "stat_buff": {
            "bonus_attack_damage": bonus_ad,
            "critical_strike_chance": bonus_crit,
        },
        "on_hit": {
            "name": "Weakened Soul (mark consume)",
            "damage_per_hit": per_proc / _MARK_STACKS,
            "damage_type": "physical",
            "stacks_required": _MARK_STACKS,
            "count_ability_hits": True,
        },
        "detail": (
            f"{stacks} Mist stack(s): +{bonus_ad:g} bonus AD, "
            f"+{bonus_crit:g}% crit, +{bonus_range:g} range; "
            f"mark consume {percent:g}% of target max health per 2 hits"
        ),
    }


_absolution.phase = BUFF


SLOTS = {**_packet_slots, "P": _absolution}
parse_abilities = build_parser(SLOTS, "Senna")

OPTIONS = list(_packet_options) + [
    {
        "key": "senna_mist_stacks",
        "type": "int",
        "default": 40,
        "min": 0,
        "max": 300,
        "label": "Mist (soul) stacks",
    },
]

ASSUMPTIONS = list(_packet_assumptions) + [
    "Mist stack count is user-set (default 40 — the expected mid-game "
    "state); Wraith-farming and mark-consume Mist generation are not "
    "simulated",
    "Each Mist stack grants 0.75 bonus AD; every 20 stacks grant 20 "
    "bonus attack range and 10% crit chance — wiki prose (module "
    "constants)",
    "Weakened Soul procs on every 2nd hit (autos and ability hits "
    "alternate apply/consume); the 4-second mark duration is assumed "
    "not to expire during sustained combat",
    "Weakened Soul's % current-health damage is priced against the "
    "target's MAX health (the engine on-hit convention) — the real "
    "term decays with the target's current health, so the model "
    "overstates late-fight consumes",
    "Relic Cannon's on-hit 20% AD bonus physical damage is not modeled "
    "(the packet has no leveling row for it)",
]

SOURCES = list(_packet_sources)
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"P", "Q", "W", "R"} else "out_of_scope")
    for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
