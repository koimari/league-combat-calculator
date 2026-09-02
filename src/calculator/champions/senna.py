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

Coverage: E (Curse of the Black Mist) wraps Senna and her team in
camouflage — all five cached effects are self/ally utility prose
(camouflage duration, allied Wraith Form, obscured vision, bonus movement
speed) with no enemy-damage leveling. The pinned reviewed packet
(``static/reviewed-packets.json``) declares E ``kind: "no_damage"``, and
this module does not reassign E, so the slot is emitted as a sourced zero
row rather than left unmodeled.
"""

from functools import partial
from typing import Any

from .. import healing_helpers as _healing
from ..binary_roots import calculation_coefficient, data_value, spell_object
from .engine import BUFF, SlotCtx
from .healing_contract import self_healing_rule
from .inputs import int_option
from .module_contract import coverage
from .packet_module import build_packet_module
from .slotlib import (
    ability_name,
    attach_self_shield,
    extract_named,
    extract_value,
    with_control,
    with_item_on_hits,
)

PACKET_SHA256 = "97538cf620050743705205ae884ef53611e35fbad8ed2808fd3617fb3bc3b7d5"


# Mist's per-stack shape is binary DataValues (SennaPassive.ADPerStack /
# StacksForBonus / BonusRange; CritDamageMod and BonusCritChance carry the
# per-threshold crit terms); the cached prose corroborates.
_SENNA_P_SPELL = spell_object("Senna", "SennaPassive")
_MIST_AD_PER_STACK = data_value(_SENNA_P_SPELL, "ADPerStack")
_MIST_STACKS_PER_THRESHOLD = int(data_value(_SENNA_P_SPELL, "StacksForBonus"))
_MIST_RANGE_PER_THRESHOLD = data_value(_SENNA_P_SPELL, "BonusRange")
_MIST_CRIT_PER_THRESHOLD = 10.0  # % crit chance
_MARK_STACKS = 2  # apply on hit 1, consume on hit 2


class _MistRule:
    """The typed Mist (Absolution) counter declaration (P3 package 3W).

    Mist is a PERMANENT counter: each soul grants 0.75 bonus AD and every
    20 souls grant 20 bonus attack range + 10% critical strike chance.
    The four numbers are wiki prose in the cached P entry (leveling
    empty — no atom exists); the source receipt pins the P template
    revision.  ``public_receipt()`` rides the option's ``state`` and the
    resource-ledger souls declaration.
    """

    def __init__(self) -> None:
        self.per_stack_bonus_ad = _MIST_AD_PER_STACK
        self.stacks_per_threshold = _MIST_STACKS_PER_THRESHOLD
        self.range_per_threshold = _MIST_RANGE_PER_THRESHOLD
        self.crit_per_threshold = _MIST_CRIT_PER_THRESHOLD
        self.permanent = True
        self.source = {
            "label": "Local League Wiki cache — Senna P (Absolution) Mist prose",
            "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Senna/I",
            "revision_id": 2864157,
            "revision_timestamp": "2019-11-03T20:06:33Z",
        }

    def public_receipt(self) -> dict[str, Any]:
        return {
            "name": "Senna — Absolution (Mist souls)",
            "per_stack_bonus_ad": self.per_stack_bonus_ad,
            "stacks_per_threshold": self.stacks_per_threshold,
            "range_per_threshold": self.range_per_threshold,
            "crit_per_threshold": self.crit_per_threshold,
            "permanent": self.permanent,
            "source": dict(self.source),
        }


SENNA_MIST_RULE = _MistRule()

# HARDCODED: verify on patch updates — Relic Cannon's per-auto bonus
# physical damage is 20% of TOTAL AD (wiki prose, P effects[3], leveling
# empty — no atom).  The binary carries the same value: data/bin/
# characters/senna.bin.json Characters/Senna/Spells/SennaPassiveAbility/
# SennaPassive mSpellCalculations.BonusOnHitDamage = StatByCoefficient
# (mStat 2 = attack damage, NO mStatFormula => total AD — the repo-pinned
# convention; Senna Q's mStatFormula 2 is the bonus-AD shape), mCoefficient
# 0.2.  The prose's "20% AD" unqualified matches the total-AD reading
# (the cache writes "60% bonus AD" for Q when bonus-only).
_RELIC_CANNON_AD_RATIO = 0.2
_RELIC_CANNON_DAMAGE_TYPE = "physical"


class _RelicCannonRule:
    """Relic Cannon's per-auto on-hit receipt (wiki + binary)."""

    def public_receipt(self) -> dict[str, Any]:
        return {
            "name": "Relic Cannon (on-hit)",
            "ad_ratio": _RELIC_CANNON_AD_RATIO,
            "damage_type": _RELIC_CANNON_DAMAGE_TYPE,
            "source": {
                "wiki": {
                    "url": "https://wiki.leagueoflegends.com/en-us/Senna",
                    "revision_id": 2864157,  # Template:Data_Senna/I
                    "prose": (
                        "Senna's basic attacks on-hit deal 20% AD bonus "
                        "physical damage ... for 0.5 seconds"
                    ),
                },
                "binary": {
                    "path": (
                        "data/bin/characters/senna.bin.json "
                        "SennaPassive mSpellCalculations.BonusOnHitDamage"
                    ),
                    "formula": "StatByCoefficient(mStat 2, no mStatFormula, "
                    "coefficient 0.2) = 20% of TOTAL AD",
                },
                "notes": (
                    "applied only if the attack deals more than 0 damage; "
                    "not applied against structures; applies an additional "
                    "Black Cleaver Carve stack; the MS-steal (10/15/20% for "
                    "0.5s) is utility and not modeled"
                ),
            },
        }


# Dawning Shadow's shield duration and Mist scaling are the binary SennaR
# ShieldDuration DataValue and TotalShield buff-counter coefficient; the
# cached prose corroborates the 150% term applied to the user-set Mist count.
_SENNA_R_SPELL = spell_object("Senna", "SennaR")
_DAWNING_SHADOW_SHIELD_DURATION_SECONDS = data_value(_SENNA_R_SPELL, "ShieldDuration")
_DAWNING_SHADOW_MIST_RATIO = calculation_coefficient(_SENNA_R_SPELL, "TotalShield")


def _absolution(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: Mist stat buffs + Weakened Soul every-2nd-hit %health proc."""
    ability = ctx.ability()
    if ability is None:
        return None

    stacks = int(ctx.option("senna_mist_stacks"))
    stacks = min(max(stacks, 0), 300)
    bonus_ad = _MIST_AD_PER_STACK * stacks
    thresholds = stacks // _MIST_STACKS_PER_THRESHOLD
    bonus_crit = _MIST_CRIT_PER_THRESHOLD * thresholds
    bonus_range = _MIST_RANGE_PER_THRESHOLD * thresholds

    # BUFF phase guarantee: Q/W/R parse against the Mist-buffed AD.
    ctx.stats["bonus_attack_damage"] = ctx.stat("bonus_attack_damage") + bonus_ad
    ctx.stats["attack_damage"] = ctx.stat("base_attack_damage") + ctx.stat(
        "bonus_attack_damage"
    )
    ctx.stats["critical_strike_chance"] = (
        ctx.stat("critical_strike_chance") + bonus_crit
    )

    # Weakened Soul: bonus physical damage = level-scaled % of the
    # target's current health on the consuming hit. Max-health proxy
    # (see module docstring).
    percent = extract_value(ability, "Current Health Damage", ctx.level)
    max_health = ctx.target_stat("target_max_health")
    per_proc = percent / 100.0 * max_health

    return {
        "name": ability_name(ability),
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


def _relic_cannon(ctx: SlotCtx) -> dict[str, Any] | None:
    """P2: Relic Cannon — 20% total AD bonus physical damage per auto.

    The engine's ability-on-hit loop prices ANY entry's ``on_hit``
    payload, including a slot key outside P/Q/W/E/R — the smallest safe
    contract for the second per-auto rider (the P slot already owns the
    Weakened Soul payload).  ``stacks_required``/``count_ability_hits``
    are absent: the rider fires on every basic-attack on-hit (autos +
    phantom hits + double shots), never on ability hits, one breakdown
    row ``on_hit_ability_P2``.  The per-hit value reads the parse-time
    attack damage — the Mist-buffed total (P runs first in the BUFF
    phase; item AD included by the pipeline).
    """
    per_hit = _RELIC_CANNON_AD_RATIO * ctx.stat("attack_damage")
    return {
        "name": "Absolution",
        "rank": ctx.level,
        "damage_type": _RELIC_CANNON_DAMAGE_TYPE,
        "total_raw": 0.0,
        "parts": (),
        "on_hit": {
            "name": "Relic Cannon (on-hit)",
            "damage_per_hit": per_hit,
            "damage_type": _RELIC_CANNON_DAMAGE_TYPE,
        },
        "detail": (
            "Relic Cannon: 20% of total AD bonus physical damage per basic "
            "attack on-hit (source receipt: SENNA_RELIC_CANNON_RULE)"
        ),
    }


_relic_cannon.phase = BUFF


def _dawning_shadow(packet_r):
    """R: the reviewed physical hit plus Senna's own shield payload.

    The light wave shields Senna herself as well as allies; the self
    portion (flat + 50% AP + 150% Mist, 3s) rides the R damage event as
    a ``self_shield_events`` payload.  The generic ally-support scanner
    keeps emitting the ally-targeted Dark Passage-style packet for
    selected teammates (it cannot price the Mist term), so the two
    halves do not overlap on Senna herself.
    """

    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        entry = packet_r(ctx)
        rank = int(entry.get("rank", 0) or 0) if entry is not None else 0
        if entry is None or rank < 1:
            return entry
        ability = ctx.ability()
        shield = extract_named(ability, "Shield Strength", rank, ctx.stats, ctx.target)
        stacks = int(ctx.option("senna_mist_stacks"))
        shield += _DAWNING_SHADOW_MIST_RATIO * stacks
        return attach_self_shield(
            entry,
            amount=shield,
            duration=_DAWNING_SHADOW_SHIELD_DURATION_SECONDS,
            source=entry.get("name", "Dawning Shadow"),
            detail=(
                f"R also shields Senna for {shield:g} for "
                f"{_DAWNING_SHADOW_SHIELD_DURATION_SECONDS:g}s "
                f"(flat + 50% AP + 150% of {stacks} Mist stacks)"
            ),
        )

    return parse


# Cached kit review.  Q's shadow ray "deals physical damage to enemies hit
# and slows them by 15% (+ 15% per 100 bonus AD) (+ 7% per 100 AP)".  W's
# globule "deals physical damage to the first enemy hit and attaches to
# them", then "the black mist spreads out of the target, rooting them and
# surrounding enemies".  R's shadow wave only "deals physical damage to
# enemy champions hit and reveals them"; the light wave shields allies.  E
# (camouflage) deals no damage, and P is a stat/on-hit innate whose mark
# consume rides the auto stream, so neither carries an ability event.
MODULE_CC = {"Q": "slow", "W": "root", "R": "none"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Senna",
    PACKET_SHA256,
    # Piercing Darkness' shadow ray and Last Embrace's globule each
    # deal their packet once, like Dawning Shadow already did — the
    # boundary claim that carries MODULE_CC's reviewed answers into
    # the event ledger.
    single_hit_slots=frozenset({"Q", "R", "W"}),
    slot_parsers={
        "P": _absolution,
        # The Relic Cannon rider rides a SECOND BUFF-phase slot (P2) so
        # the engine's existing ability-on-hit loop prices it with its
        # own row — the P slot already owns the Weakened Soul payload.
        # The packet compiles no P2, so this appends one; both run in the
        # BUFF phase, P first, which is what makes P2's total AD the
        # Mist-buffed one.
        "P2": _relic_cannon,
    },
    slot_wrappers={
        "R": _dawning_shadow,
        "Q": partial(
            with_item_on_hits,
            effectiveness=1.0,
            hits=1,
            triggers=("on_hit", "on_attack"),
        ),
        # The root's duration is sourced ("Root Duration"), so W states
        # the interval rather than only the kind MODULE_CC declares.
        "W": partial(with_control, duration_attr="Root Duration"),
    },
    cc_kinds=MODULE_CC,
)

OPTIONS = [
    *list(OPTIONS),
    int_option(
        "senna_mist_stacks",
        40,
        minimum=0,
        maximum=300,
        label="Mist (soul) stacks",
        state=SENNA_MIST_RULE.public_receipt(),
    ),
]

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
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
    "Relic Cannon's per-auto on-hit is MODELED as 20% of TOTAL AD bonus "
    "physical damage (the wiki prose, P effects[3] — leveling empty, no "
    "atom; the binary SennaPassive BonusOnHitDamage 0.2 x mStat 2 with no "
    "mStatFormula = total AD — see SENNA_RELIC_CANNON_RULE).  It rides "
    "the P2 slot's own on_hit payload: every basic-attack on-hit (autos, "
    "phantom hits, double shots — never ability hits), its own breakdown "
    "row on_hit_ability_P2, the Mist-buffed parse-time AD.  The engine "
    "has no structure or invulnerability concept: the wiki's exclusions "
    "(not vs structures; only when the attack deals >0 damage) are "
    "named boundaries; the MS-steal (10/15/20% for 0.5s) is utility and "
    "not modeled.",
    "R (Dawning Shadow) also shields Senna herself for flat + 50% AP + "
    "150% of the selected Mist stacks for 3s at the cast; the ally "
    "half of the light wave is emitted by the ally-support scanner "
    "without the Mist term (documented boundary)",
    "E (Curse of the Black Mist) has no enemy-damage formula: all five "
    "cached effects are self/ally camouflage and movement-speed utility "
    "(confirmed by the pinned reviewed packet's kind='no_damage' "
    "declaration for E). E is a cast slot in this module (never "
    "reassigned away from build_packet_module's no_damage branch), so "
    "MODULE_COVERAGE reflects a sourced no-damage classification "
    "rather than an unmodeled gap (no_damage, not out_of_scope).",
]

MODULE_COVERAGE = coverage(no_damage="E")


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Senna self-healing events from its authored packet."""
    healing = []
    q = _healing.ability_json(champion_data, "Q")
    q_rank = _healing.parsed_rank(ability_damages, "Q")
    q_heal = extract_named(q, "Healing", q_rank, champion_stats)
    for payment in _healing.payments(
        _healing.HealAnchor.CAST, "Q", damage_events, cast_timeline
    ):
        event = payment.event
        _healing.heal_from_damage(
            healing, event, q_heal, "Piercing Darkness", link_to_damage=False
        )
    return healing


SELF_HEALING_RULE = self_healing_rule("Senna")(derive_self_healing)
