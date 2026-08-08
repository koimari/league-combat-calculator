"""Smolder — CP10.7 full-entry-reviewed packet module (E9-2 fixes).

E9-2 gap fixes over the packet module:
- Q (Super Scorcher Breath) is "increased by 0% : 75% (+ 0% : 22.5%)
  (based on critical strike chance)" — the fireball's damage scales with
  the holder's crit chance (0.75% + 0.225% per 1% crit), so the packet's
  reviewed base (flat + summed AD ratios) is multiplied by
  ``1 + 0.975 x crit_chance``.
- P (Dragon Practice) tier 3 (225 stacks): Q hits set the enemy on fire
  for 3 seconds, dealing true damage equal to 2.5% per 100 bonus AD
  (+ 0.5% per 100 Dragon Practice stacks) of the target's maximum
  health over the duration.  The burn rides Q as a post-hit proc
  (one application per Q hit) priced from the ``p_stacks`` option
  (default 225 = the tier-3 threshold, matching the Sion Q / Kled R
  fully-charged default convention).
- P itself stays a documented zero-damage row whose detail ties the
  stack boundary to the burn; the 25% : 55% (+ 0% : 9% crit) stack-
  scaled bonus magic damage on basic abilities and the 6.5% burn
  execution are documented boundaries, not priced.
- E flight utility remains documented out.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .packet_module import build_packet_module
from .slotlib import with_item_on_hits

PACKET_SHA256 = "25b414368fa8e3421c2471eff320f299ef82d9d07ce34f3a7af74a5db21b8d25"

_packet_parse, _packet_slots, _packet_assumptions, _packet_sources, _packet_options = (
    build_packet_module("Smolder", PACKET_SHA256)
)
PACKET_SPEC = _packet_slots.packet_spec

# HARDCODED: verify on patch updates — wiki prose on Q: "increased by
# 0% : 75% (+ 0% : 22.5%) (based on critical strike chance)" -> the
# damage multiplier is 1 + (0.75 + 0.225) x crit_chance.  The tier-3 burn
# is 2.5% per 100 bonus AD (+ 0.5% per 100 Dragon Practice stacks) of the
# target's maximum health over 3 seconds (cached Q description prose).
_Q_CRIT_INCREASE_PER_CRIT = 0.975
_BURN_BONUS_AD_PER_100 = 2.5
_BURN_STACKS_PER_100 = 0.5
_TIER3_STACKS = 225
_BURN_DURATION = 3.0


def _certified_single_hit(parser):
    """Wrap a simple one-instance parser with the event-order certification."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = parser(ctx)
        if entry is not None and int(entry.get("rank", 0) or 0) >= 1:
            entry["event_order_certified"] = "single_hit"
        return entry

    return parse


def _dragon_practice(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: documented zero-damage row tied to the tier-3 burn on Q."""
    ability = ctx.ability("P", 0)
    if ability is None:
        return None
    stacks = max(0, int(ctx.options.get("p_stacks", _TIER3_STACKS)))
    return {
        "name": ability.get("name", "Dragon Practice"),
        "rank": ctx.level,
        "cooldown": 0.0,
        "damage_type": "true",
        "total_raw": 0.0,
        "parts": (),
        "detail": (
            f"{stacks} Dragon Practice stack(s).  At 225 stacks (tier 3) "
            "Q hits set the enemy on fire for 3s, dealing true damage "
            "equal to 2.5% per 100 bonus AD (+ 0.5% per 100 stacks) of "
            "the target's maximum health — priced as Q's post-hit burn.  "
            "The 25% : 55% (+ 0% : 9% crit) stack-scaled bonus magic "
            "damage on basic abilities and the 6.5% burn execution are "
            "documented boundaries."
        ),
    }


def _super_scorcher_breath(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: reviewed packet base, scaled by crit chance, plus the tier-3 burn."""
    entry = _packet_slots["Q"](ctx)
    if entry is None:
        return None
    entry["event_order_certified"] = "single_hit"

    crit_chance = min(
        1.0,
        max(0.0, float(ctx.stats.get("critical_strike_chance", 0.0) or 0.0) / 100.0),
    )
    factor = 1.0 + _Q_CRIT_INCREASE_PER_CRIT * crit_chance
    if abs(factor - 1.0) > 1e-12:
        entry["parts"] = tuple(
            DamagePart(
                part.damage_type,
                amount=part.amount * factor,
                count=part.count,
                hp_scaled_damage=part.hp_scaled_damage,
                crit_effectiveness=part.crit_effectiveness,
                basic_damage=part.basic_damage,
                bonus_ad_ratio=part.bonus_ad_ratio,
                dot_stack_scaled=part.dot_stack_scaled,
                time_offset=part.time_offset,
                hit_interval=part.hit_interval,
                cc_kind=part.cc_kind,
            )
            for part in entry["parts"]
        )
        entry["total_raw"] = float(entry.get("total_raw", 0.0)) * factor

    stacks = max(0, int(ctx.options.get("p_stacks", _TIER3_STACKS)))
    if stacks >= _TIER3_STACKS:
        target_max = float(ctx.target.get("target_max_health", 0.0) or 0.0)
        bonus_ad = float(ctx.stats.get("bonus_attack_damage", 0.0) or 0.0)
        burn_total = target_max * (
            _BURN_BONUS_AD_PER_100 * bonus_ad / 100.0 / 100.0
            + _BURN_STACKS_PER_100 * stacks / 100.0 / 100.0
        )
        if burn_total > 0.0:
            entry["post_hit_proc"] = {
                "name": "Dragon Practice · Tier 3 Burn",
                "breakdown_key": "dragon_practice_burn",
                # The burn rides the Q hit that applied it: the proc lands
                # at the cast boundary (Varus blight-detonation precedent),
                # so damage.py marks the row's timing as authored.
                "parts": (DamagePart("true", burn_total, time_offset=0.0),),
                "detail": (
                    f"{stacks} Dragon Practice stacks: 3s burn of "
                    f"{burn_total:g} true damage (2.5% per 100 bonus AD "
                    "+ 0.5% per 100 stacks of the target's maximum "
                    "health)"
                ),
            }
            entry["dot_duration"] = _BURN_DURATION
            entry["total_raw"] = float(entry.get("total_raw", 0.0)) + burn_total
    return entry


SLOTS = dict(_packet_slots)
SLOTS["P"] = _dragon_practice
SLOTS["Q"] = _super_scorcher_breath
SLOTS["W"] = _certified_single_hit(SLOTS["W"])
SLOTS["E"] = _certified_single_hit(SLOTS["E"])
SLOTS["R"] = _certified_single_hit(SLOTS["R"])
SLOTS["Q"] = with_item_on_hits(
    SLOTS["Q"], effectiveness=1.0, hits=1, triggers=("on_hit", "on_attack")
)
parse_abilities = build_parser(SLOTS, "Smolder")

OPTIONS: list[dict[str, Any]] = list(_packet_options) + [
    {
        "key": "p_stacks",
        "type": "int",
        "default": _TIER3_STACKS,
        "min": 0,
        "max": 400,
        "label": ("Dragon Practice stacks (225+ = tier-3 true-damage burn on Q)"),
    },
]

ASSUMPTIONS = list(_packet_assumptions) + [
    "Q (Super Scorcher Breath) is increased by 0% : 75% (+ 0% : 22.5%) "
    "based on critical strike chance (cached Q description prose): the "
    "packet's flat + AD-ratio price is multiplied by 1 + 0.975 x crit "
    "chance",
    "P (Dragon Practice) tier 3 (225 stacks) sets enemies hit by Q on "
    "fire for 3 seconds: true damage equal to 2.5% per 100 bonus AD "
    "(+ 0.5% per 100 stacks) of the target's maximum health over the "
    "duration — priced as one post-hit burn per Q hit (p_stacks option, "
    "default 225)",
    "The 25% : 55% (+ 0% : 9% crit) stack-scaled bonus magic damage on "
    "basic abilities and the 6.5%-health burn execution are documented "
    "boundaries, not priced",
    "E (Flap, Flap, Flap) flight utility remains a documented " "out-of-scope row.",
]

SOURCES = list(_packet_sources)
MODULE_COVERAGE = {
    "P": "no_damage",
    "Q": "modeled",
    "W": "modeled",
    "E": "modeled",
    "R": "modeled",
}
REVIEW_STATUS = "reviewed_module"

from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Smolder")
