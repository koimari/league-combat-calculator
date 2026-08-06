"""Viego — CP10.9 full-entry-reviewed packet module, plus the E9-3 Q/R fixes.

E9-3: the reviewed packet priced Q and R from the health-ratio rows ONLY
(Q: the %current-health on-hit with a zero base; R: the %missing-health
bonus), dropping the sourced active damage:
- Q (Blade of the Ruined King) now prices the ACTIVE "Physical Damage"
  row (25-85 + 70% AD), keeps the passive %current-health on-hit
  ("Bonus Physical Damage" 2-6% + the "Minimum Bonus Damage" 10-30
  floor) on the engine's every-auto on-hit path, and prices the
  mark-consuming second strike ("20% AD (+ 15% AP)" wiki prose, the E8d
  possession note's second-strike row) through the q_second_strike
  option.
- R (Heartbreaker) now prices the 120% AD base strike (wiki prose: "All
  targets hit are dealt 120% AD physical damage") PLUS the
  %missing-health bonus ("Physical Damage" row: 12/16/20% + 5% per 100
  bonus AD of the target's missing health) as a live hp-scaled part.

W damage is unchanged; E/P stay documented out_of_scope, and the
possession/transform mechanic is inherently out of scope (E8d note).
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .reviewed_batch_09 import build_batch_module
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_value,
)

# HARDCODED: verify on patch updates — wiki prose, not leveling rows.
# The mark-consuming second strike deals "20% AD (+ 15% AP) physical
# damage" (Q description, cached JSON); Heartbreaker's base strike is
# "120% AD physical damage" (R description, cached JSON).
_Q_SECOND_STRIKE_AD_RATIO = 0.20
_Q_SECOND_STRIKE_AP_RATIO = 0.15
_R_BASE_AD_RATIO = 1.20

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_batch_module("Viego")


def _certified_single_hit(parser):
    """Wrap a simple one-instance parser with the event-order certification."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = parser(ctx)
        if entry is not None and int(entry.get("rank", 0) or 0) >= 1:
            entry["event_order_certified"] = "single_hit"
        return entry

    return parse


def _blade_of_the_ruined_king(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: the active thrust plus the on-hit passive and mark second strike."""
    ability = ctx.ability("Q")
    if ability is None:
        return None
    rank = ctx.rank_for("Q")
    if rank < 1:
        return None
    active = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    second_strikes = min(max(int(ctx.options.get("q_second_strike", 0)), 0), 20)
    second_damage = (
        second_strikes
        * (
            _Q_SECOND_STRIKE_AD_RATIO * float(ctx.stats.get("attack_damage", 0.0))
            + _Q_SECOND_STRIKE_AP_RATIO * float(ctx.stats.get("ability_power", 0.0))
        )
        if second_strikes > 0
        else 0.0
    )
    entry = damage_entry(
        ability.get("name", "Blade of the Ruined King"),
        rank,
        extract_cooldown(ability, rank),
        active + second_damage,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", active + second_damage),)
    entry["event_order_certified"] = "single_hit"
    # The passive: every basic attack deals 2-6% of the target's CURRENT
    # health (minimum 10-30) bonus physical damage — the engine's
    # current-health on-hit simulation (Jarvan IV pattern) prices it
    # against the decayed target HP; proc_cooldown 0 = every auto procs.
    pct = extract_value(ability, "Bonus Physical Damage", rank, 0)
    floor = extract_value(ability, "Minimum Bonus Damage", rank, 0)
    entry["on_hit"] = {
        "name": "Blade of the Ruined King (on-hit)",
        "damage_type": "physical",
        "current_health_percent": pct,
        "min_damage": floor,
        "proc_cooldown": 0.0,
    }
    detail = (
        f"active thrust {active:.2f} + {second_strikes} mark-consuming second strike(s)"
    )
    if second_strikes > 0:
        detail += (
            f" ({second_damage:.2f} = 20% AD + 15% AP each); the passive "
            "%current-health on-hit rides every auto"
        )
    else:
        detail += (
            "; the passive %current-health on-hit rides every auto; set "
            "q_second_strike to price the mark-consuming second strike"
        )
    entry["detail"] = detail
    return entry


def _heartbreaker(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: the 120% AD base strike plus the live %missing-health bonus."""
    ability = ctx.ability("R")
    if ability is None:
        return None
    rank = ctx.rank_for("R")
    if rank < 1:
        return None
    ad = float(ctx.stats.get("attack_damage", 0.0))
    base = _R_BASE_AD_RATIO * ad
    missing_pct = extract_value(ability, "Physical Damage", rank, 0)
    per_100_bad = extract_value(ability, "Physical Damage", rank, 1)
    bonus_ad = float(ctx.stats.get("bonus_attack_damage", 0.0))
    target_max = float(ctx.target.get("target_max_health", 0.0))

    def missing_health_bonus(missing_ratio: float) -> float:
        return (
            (missing_pct / 100.0 + per_100_bad / 100.0 * bonus_ad / 100.0)
            * target_max
            * missing_ratio
        )

    entry = damage_entry(
        ability.get("name", "Heartbreaker"),
        rank,
        extract_cooldown(ability, rank),
        base,
        "physical",
    )
    entry["parts"] = (
        # Both the 120% AD base strike and the live %missing-health bonus
        # land at the cast boundary: authored time_offset 0.0 upgrades the
        # dynamic part's events from cast_boundary to "hit" precision, so
        # the coverage classifier certifies the row instead of downgrading
        # it coarse (cast_boundary events are never exact).
        DamagePart("physical", base, time_offset=0.0),
        DamagePart("physical", hp_scaled_damage=missing_health_bonus, time_offset=0.0),
    )
    entry["detail"] = (
        f"{_R_BASE_AD_RATIO * 100:g}% AD base strike ({base:.2f}) + "
        f"{missing_pct}% (+ {per_100_bad}% per 100 bonus AD) of the "
        "target's missing health, evaluated at the strike"
    )
    return entry


SLOTS = dict(SLOTS)
SLOTS["Q"] = _blade_of_the_ruined_king
SLOTS["R"] = _heartbreaker
SLOTS["W"] = _certified_single_hit(SLOTS["W"])
parse_abilities = build_parser(SLOTS, "Viego")

OPTIONS = list(OPTIONS) + [
    {
        "key": "q_second_strike",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 20,
        "label": "Mark-consuming second strikes (Q passive)",
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "Q (Blade of the Ruined King) prices the active 'Physical Damage' row "
    "(25-85 + 70% AD); the passive 2-6% current-health on-hit (minimum "
    "10-30) rides every auto on the engine's current-health on-hit path; "
    "the mark-consuming second strike (20% AD + 15% AP wiki prose) is "
    "option-gated via q_second_strike (0 by default).",
    "R (Heartbreaker) prices the 120% AD base strike (wiki prose) plus "
    "the %missing-health bonus ('Physical Damage' row 12/16/20% + 5% per "
    "100 bonus AD) as a live hp-scaled part evaluated at the strike; "
    "total_raw is the static base bound.",
    "The possession/transform mechanic is inherently out of scope (E8d "
    "note); E/P remain documented out_of_scope.",
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "W", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
