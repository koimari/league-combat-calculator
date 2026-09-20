"""Smolder: full-entry-reviewed packet module.

Q (Super Scorcher Breath) scales with the holder's crit chance, 0.75% plus
0.225% per 1%, so the reviewed base is multiplied by
``1 + 0.975 x crit_chance``.
P (Dragon Practice) tier 3 sets Q's target on fire for 3 seconds of true
damage worth 2.5% per 100 bonus AD (+ 0.5% per 100 stacks) of maximum health.
The burn rides Q as a post-hit proc, one application per Q hit, priced from
``p_stacks``, default 225, the tier-3 threshold.  P's own row is zero damage;
its stack-scaled bonus magic on basic abilities and its 6.5% execution are
documented boundaries, not priced.
W and E each read the cache's total rather than one leg.  W (Achooo!) lands
both glob and explosion on a champion, so "Total Physical Damage On Champion
Hit" is the pair; E (Flap, Flap, Flap) fires at least five bolts, so "Minimum
Total Physical Damage" is that floor.  Neither is one hit, so both declare
their aggregate at the cast boundary, and the stack-scaled sixth bolt onward
stays unpriced.
"""

from dataclasses import replace
from typing import Any

from .. import healing_helpers as _healing
from ..ability_spec import DamagePart
from ..binary_roots import calculation_coefficient, data_value, spell_object
from .contract_vocabulary import coverage
from .engine import SlotCtx
from .healing_contract import SelfHealCtx, self_healing_rule
from .inputs import int_option
from .module_helpers import ability_slot, typed_damage
from .packet_module import build_packet_module
from .slot_entries import damage_entry
from .slot_extract import ability_name, extract_named
from .slotlib import with_item_on_hits

PACKET_SHA256 = "25b414368fa8e3421c2471eff320f299ef82d9d07ce34f3a7af74a5db21b8d25"


# HARDCODED: verify on patch updates — wiki prose on Q: "increased by
# 0% : 75% (+ 0% : 22.5%) (based on critical strike chance)" -> the
# damage multiplier is 1 + (0.75 + 0.225) x crit_chance.  The tier-3 burn
# ratio is rooted in the Q binary below; its stack rider and duration remain
# sourced from the binary/cache rows.
_Q_CRIT_INCREASE_PER_CRIT = 0.975
_SMOLDER_Q_SPELL = spell_object("Smolder", "SmolderQ")
_BURN_BONUS_AD_PER_100 = (
    calculation_coefficient(_SMOLDER_Q_SPELL, "Tier3_Burn") * 10000.0
)
_BURN_STACKS_PER_100 = data_value(_SMOLDER_Q_SPELL, "Tier3_Burn_Stack_Mult") * 10000.0
_TIER3_STACKS = int(data_value(_SMOLDER_Q_SPELL, "StackTier3"))
_BURN_DURATION = data_value(_SMOLDER_Q_SPELL, "Tier3_DotLength")


@ability_slot("P")
def _dragon_practice(ctx: SlotCtx, ability: dict[str, Any]) -> dict[str, Any] | None:
    """P: documented zero-damage row tied to the tier-3 burn on Q."""
    stacks = max(0, int(ctx.options.get("p_stacks", _TIER3_STACKS)))
    return damage_entry(
        ability_name(ability),
        ctx.level,
        0.0,
        0.0,
        "true",
        parts=(),
        detail=(
            f"{stacks} Dragon Practice stack(s).  At 225 stacks (tier 3) "
            "Q hits set the enemy on fire for 3s, dealing true damage "
            "equal to 2.5% per 100 bonus AD (+ 0.5% per 100 stacks) of "
            "the target's maximum health — priced as Q's post-hit burn.  "
            "The 25% : 55% (+ 0% : 9% crit) stack-scaled bonus magic "
            "damage on basic abilities and the 6.5% burn execution are "
            "documented boundaries."
        ),
    )


def _super_scorcher_breath(packet_q):
    """Q: reviewed packet base, scaled by crit chance, plus the tier-3 burn."""

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_q(ctx)
        if entry is None:
            return None

        crit_chance = min(
            1.0,
            max(0.0, float(ctx.stat("critical_strike_chance") or 0.0) / 100.0),
        )
        factor = 1.0 + _Q_CRIT_INCREASE_PER_CRIT * crit_chance
        if abs(factor - 1.0) > 1e-12:
            # Only the amount changes: rebuilding the part field by field
            # silently drops every declaration the part carries beyond the
            # ones named (cc_duration, skillshot, zero_policy, control atoms).
            entry["parts"] = tuple(
                replace(part, amount=part.amount * factor) for part in entry["parts"]
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
MODULE_CC = {"Q": "none", "W": "slow", "E": "none", "R": "none", "P": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Smolder",
    PACKET_SHA256,
    single_hit_slots=frozenset({"Q", "R"}),
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

OPTIONS: list[dict[str, Any]] = [
    *list(OPTIONS),
    int_option(
        "p_stacks",
        _TIER3_STACKS,
        minimum=0,
        maximum=400,
        label="Dragon Practice stacks (225+ = tier-3 true-damage burn on Q)",
        rotation={"role": "self_state", "slot": "P"},
    ),
]

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "Q (Super Scorcher Breath) rises 0 to 75% (+ 0 to 22.5%) by crit chance, cached Q "
    "prose.",
    "The packet's flat and AD-ratio price is multiplied by 1 + 0.975 x crit chance.",
    "P (Dragon Practice) tier 3, 225 stacks, sets a Q-hit enemy on fire for 3 "
    "seconds.",
    "The burn is true damage of 2.5% per 100 bonus AD + 0.5% per 100 stacks of target "
    "maximum health.",
    "P prices one post-hit burn per Q hit, at p_stacks (default 225).",
    "The 25 to 55% (+ 0 to 9% crit) stack-scaled bonus magic on basic abilities is "
    "not priced.",
    "The 6.5%-health burn execution is a documented limit, not priced.",
    "E (Flap, Flap, Flap) flight utility remains a documented " "out-of-scope row.",
    "W (Achooo!) prices the whole champion hit: the cached Total Physical Damage On "
    "Champion Hit row.",
    "That is 70/105/140/175/210 + 110% bonus AD + 80% AP, glob plus explosion.",
    "The explosion's delay behind the glob is not authored.",
    "The 75% falloff on repeat explosions against the same target is unpriced.",
    "E (Flap, Flap, Flap) prices the five-bolt floor: the cached Minimum Total "
    "Physical Damage row.",
    "That is 50/75/100/125/150 + 150% AD == 5 x Physical Damage per Hit.",
    "The extra bolt per 100 Dragon Practice stacks and the bolts' 1.25s cadence are "
    "not priced.",
]

MODULE_COVERAGE = coverage(no_damage="P")


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Resolve Smolder self-healing events from its authored packet."""
    healing = []
    r = _healing.ability_json(ctx.champion_data, "R")
    r_rank = _healing.parsed_rank(ctx.ability_damages, "R")
    r_heal = extract_named(r, "Self Heal", r_rank, ctx.champion_stats)
    # The flat self heal is paid once per cast, so a wave the module prices
    # as several hits still heals once.
    for payment in ctx.payments(_healing.HealAnchor.CAST, "R"):
        _healing.heal_from_damage(
            healing, payment.event, r_heal, "MMOOOMMMM!", link_to_damage=False
        )
    return healing


SELF_HEALING_RULE = self_healing_rule("Smolder")(derive_self_healing)
