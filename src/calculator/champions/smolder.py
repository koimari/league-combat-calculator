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

Row-selection fix (W and E).  Both generated packets priced one leg of a
multi-hit cast where the cache also carries the cast's total:
- W (Achooo!) "deals physical damage to enemies hit ... Hitting an enemy
  champion creates an explosion that deals physical damage to nearby
  enemies".  The packet priced "Glob Physical Damage"
  (60/70/80/90/100 + 60% bonus AD) alone; against a champion both land,
  and the cache's "Total Physical Damage On Champion Hit" row
  (70/105/140/175/210 + 110% bonus AD + 80% AP) is glob + explosion.
- E (Flap, Flap, Flap) "fires up to 5 (+ 1 per 100 Dragon Practice
  stacks) bolts ... dealing physical damage with each hit".  The packet
  priced "Physical Damage per Hit" (10/15/20/25/30 + 30% AD), one bolt;
  the cache's "Minimum Total Physical Damage" row
  (50/75/100/125/150 + 150% AD) is the five-bolt floor at every rank.

Neither row is one hit any more, so both declare their aggregate at the
cast boundary rather than certifying a single hit; the explosion's delay
and the bolts' cadence across the 1.25-second flight are left for the
timing wave, as is the stack-scaled sixth bolt onward.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx
from .healing_contract import declare_healing_rule
from .module_helpers import typed_damage
from .packet_module import build_packet_module
from .slotlib import with_item_on_hits

PACKET_SHA256 = "25b414368fa8e3421c2471eff320f299ef82d9d07ce34f3a7af74a5db21b8d25"


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


def _super_scorcher_breath(packet_q):
    """Q: reviewed packet base, scaled by crit chance, plus the tier-3 burn."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_q(ctx)
        if entry is None:
            return None
        entry["event_order_certified"] = "single_hit"

        crit_chance = min(
            1.0,
            max(0.0, float(ctx.stat("critical_strike_chance") or 0.0) / 100.0),
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
            target_max = float(ctx.target_stat("target_max_health") or 0.0)
            bonus_ad = float(ctx.stat("bonus_attack_damage") or 0.0)
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

    return with_item_on_hits(
        parse, effectiveness=1.0, hits=1, triggers=("on_hit", "on_attack")
    )


def _achooo(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: glob plus the champion-hit explosion, declared at the cast."""
    return typed_damage(
        ctx, "Total Physical Damage On Champion Hit", "physical", time_offset=0.0
    )


def _flap_flap_flap(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: the five-bolt floor of the flight, declared at the cast."""
    return typed_damage(
        ctx, "Minimum Total Physical Damage", "physical", time_offset=0.0
    )


# Reviewed crowd control, read from the cached kit.  Q (Super Scorcher
# Breath) "spits a fireball at the target enemy that deals physical
# damage" and its tiers add explosions, bolts and a burn — no control.  W
# (Achooo!) "deals physical damage to enemies hit and slows them by 35%
# for 1.5 seconds".  E (Flap, Flap, Flap) "fires up to 5 ... bolts ...
# dealing physical damage with each hit" and applies none.  R
# (MMOOOMMMM!) reads "none" because of the row it prices: the slow is
# gated on the centre ("with those in the center taking 50% increased
# damage and becoming slowed by 40% for 2 seconds") and the packet prices
# the cached outer "Physical Damage" row (150/250/350 + 100% bonus AD),
# not the "Increased Physical Damage" centre row — if a later pass prices
# the centre, R's answer becomes "slow".
MODULE_CC = {"Q": "none", "W": "slow", "E": "none", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Smolder",
    PACKET_SHA256,
    single_hit_slots=frozenset({"R"}),
    slot_parsers={
        "P": _dragon_practice,
        "W": _achooo,
        "E": _flap_flap_flap,
    },
    slot_wrappers={
        "Q": _super_scorcher_breath,
    },
    cc_kinds=MODULE_CC,
)

OPTIONS: list[dict[str, Any]] = list(OPTIONS) + [
    {
        "key": "p_stacks",
        "type": "int",
        "default": _TIER3_STACKS,
        "min": 0,
        "max": 400,
        "label": ("Dragon Practice stacks (225+ = tier-3 true-damage burn on Q)"),
    },
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
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
    "W (Achooo!) prices the whole champion hit — the cached Total "
    "Physical Damage On Champion Hit row (70/105/140/175/210 + 110% "
    "bonus AD + 80% AP) == Glob Physical Damage + Explosion Physical "
    "Damage.  The generated packet priced the glob alone.  The "
    "explosion's delay behind the glob is not authored, and the 75% "
    "falloff on repeat explosions against the same target is unpriced.",
    "E (Flap, Flap, Flap) prices the five-bolt floor — the cached "
    "Minimum Total Physical Damage row (50/75/100/125/150 + 150% AD) == "
    "5 x Physical Damage per Hit, the row the generated packet priced "
    "once.  The extra bolt per 100 Dragon Practice stacks and the bolts' "
    "cadence across the 1.25-second flight are not priced.",
]

MODULE_COVERAGE = {
    "P": "no_damage",
    "Q": "modeled",
    "W": "modeled",
    "E": "modeled",
    "R": "modeled",
}

SELF_HEALING_RULE = declare_healing_rule("Smolder")
