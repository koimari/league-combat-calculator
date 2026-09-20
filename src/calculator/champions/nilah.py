"""Nilah: full-entry-reviewed packet module.

Q (Formless Blade) scales with critical strike chance, and the cache carries
both endpoints: a "Minimum Physical Damage" row at 0% crit and a "Maximum
Physical Damage" row at 100%, worth exactly 1.91 times it at every rank.  The
slot prices the minimum row times ``1 + 0.91 x crit_chance``, exact at both
sourced endpoints and linear between them; pinning the maximum row would price
every fight at 100% crit.
R (Apotheosis) prices four sourced 0.25-second ticks.
P (Joy Unending) amplifies nearby allied heals and shields and converts
self-heal excess into a shield; W (Jubilant Veil) is ghosting, movement speed,
25% magic-damage reduction and a basic-attack dodge.  Neither carries an
enemy-damage clause, so both are ``no_damage``, and the ally amplifier and the
damage-taken reduction remain axes this engine does not have.
"""

from typing import Any

from .. import healing_helpers as _healing
from ..damage_event_row import event_damage as _row_damage
from .charge_cadence import ChargeRule
from .contract_vocabulary import coverage
from .engine import SlotCtx
from .healing_contract import SelfHealCtx, self_healing_rule
from .inputs import champion_stat
from .packet_module import build_packet_module
from .slot_entries import damage_entry
from .slot_extract import ability_name, extract_cooldown, extract_named

PACKET_SHA256 = "95ce830b00c9c829930974899e20cda18a55eb0bb6ab1cc16360b57113671fe5"


# Q's damage "increased by 0% : 70% (+ 0% : 21%) (based on critical
# strike chance)": the Maximum row is the Minimum row x 1.91
# (= 1 + 0.70 + 0.21) at every rank (40 x 1.91 == 76.4;
# 100% AD x 1.91 == 191% AD), so the per-crit multiplier is
# 1 + 0.91 x crit_chance.
_Q_CRIT_MULTIPLIER_AT_MAX = 1.91
# HARDCODED: verify on patch updates — Joy Unending (P) converts each
# self-heal instance beyond maximum health into a shield lasting 6
# seconds (cached passive description).  The conversion is an
# excess-heal mechanic the shared ledger only prices for Bloodthirster
# (its ichorshield path is item-gated), and the conversion % rides the
# healing source itself: Q's Formless Blade autos heal 0% : 20% (based
# on crit chance) of post-mitigation damage, R's Apotheosis heals
# 20% : 50% (based on crit).  The mechanic is documented here with the
# sourced conversion ratios; no flat shield amount is invented because
# the excess is a live healing state, not a parse-time value.
_NILAH_Q_HEAL_TO_SHIELD_MAX_RATIO = 0.20  # Q autos: 0% : 20% by crit
_NILAH_R_HEAL_TO_SHIELD_MIN_RATIO = 0.20  # R: 20% : 50% by crit
_NILAH_EXCESS_SHIELD_DURATION_SECONDS = 6.0


def _formless_blade(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: minimum-row physical damage, scaled linearly by crit chance."""
    ranked = ctx.ranked("Q", 0)
    if ranked is None:
        return None
    ability, rank = ranked
    min_damage = extract_named(
        ability, "Minimum Physical Damage", rank, ctx.stats, ctx.target
    )
    crit_chance = min(max(float(ctx.stat("critical_strike_chance")) / 100.0, 0.0), 1.0)
    multiplier = 1.0 + (_Q_CRIT_MULTIPLIER_AT_MAX - 1.0) * crit_chance
    total = min_damage * multiplier
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
        # One crack of the whip-blade in a line — one hit at the cast
        # boundary, which is what carries MODULE_CC's answer for Q into
        # the event ledger.
        event_order_certified="single_hit",
    )
    entry["detail"] = (
        "Minimum Physical Damage row (0% crit) scaled by "
        f"{multiplier:.4f} = 1 + 0.91 x {crit_chance:.2f} crit chance"
    )
    return entry


# Cached kit review.  Q's whip-blade and E's dash only "deal physical
# damage".  R is the kit's one control cast and the module prices its whirl
# ticks (Physical Damage per Tick x4 == Total Physical Damage): "each hit
# also slows targets by 10% for 3 seconds", so the priced hits apply a
# slow.  The pull belongs to the unpriced Burst Physical Damage row, so it
# is not what any emitted part applies.  P and W are absent — the
# heal/shield innate and the mist damage nothing.
MODULE_CC = {"Q": "none", "E": "none", "R": "slow", "P": "none", "W": "none"}

# What this module says about its charge slot (charge_cadence.py).
CHARGE_RULES = {
    "E": ChargeRule(
        why=(
            "E (Slipstream) banks dashes on its cached rechargeRate "
            "(12s at rank 5), not on the 0.5s gap between two banked "
            "dashes, and its cached stock is 2."
        ),
    )
}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Nilah",
    PACKET_SHA256,
    packet_tick_fixes={
        "Apotheosis": {
            "count": 4,
            "first_tick": 0.25,
            "tick_interval": 0.25,
            "dot_duration": 1.0,
        }
    },
    # Slipstream damages once, on the dash it passes through — the boundary
    # claim that carries MODULE_CC's reviewed answer for E into the event
    # ledger.  R already authors its own four-tick timing above, and Q
    # certifies its own hit in ``_formless_blade``.
    single_hit_slots=frozenset({"E"}),
    slot_parsers={
        "Q": _formless_blade,
    },
    cc_kinds=MODULE_CC,
    charge_rules=CHARGE_RULES,
)

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "P (Joy Unending) turns self-heal excess above maximum health into a 6s shield "
    "(cached description).",
    "Its ratios are 0 to 20% on Q autos and 20 to 50% on R by crit chance, module "
    "constants.",
    "The excess is live healing state the ledger prices only for Bloodthirster, so P "
    "is documented.",
    "Q (Formless Blade) prices the cached Minimum Physical Damage row, 0 to 40 + 100% "
    "AD, at 0% crit.",
    "The cached Maximum row, 0 to 76.4 + 191% AD, is exactly 1.91x the Minimum at "
    "every rank.",
    "Q scales linearly with the fight's crit chance, exact at both sourced endpoints.",
    "KNOWN CACHE LAG: E (Slipstream)'s cached cost row is flat 30, and the game files "
    "say 40 at every rank.",
    "Bin NilahE 'mana' [40 x6] and ddragon costBurn '40' both confirm 40, verified on "
    "16.16.1.",
    "Nilah's resource is mana per the CharacterRecord arType.",
    "This module does not model E's resource cost; engine.py stamps it from "
    "data/champions.json.",
    "So the flag traces to the wiki cache, and no test asserts Nilah's resource_cost.",
    "Clearing patch_regression's ability_rows_stale flag needs a cache re-pull, which "
    "is patch-day work.",
    "P (Joy Unending) and W (Jubilant Veil) carry no enemy-damage formula; both slots "
    "are no_damage.",
    "Joy Unending is the excess-heal-to-shield converter documented above.",
    "Jubilant Veil is the ghost self-and-ally buff: movement speed, 25% magic "
    "reduction, attack dodge.",
]
MODULE_COVERAGE = coverage(no_damage="PW")


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Resolve Nilah self-healing events from its authored packet.

    Q passive: basic attacks and Formless Blade heal her for 0%-20%
    (based on critical strike chance) of the post-mitigation damage dealt
    to champions.  Apotheosis (R): 20%-50% on the same basis.  Both are a
    share of "the post-mitigation damage dealt to champions", so both pay
    per hit that dealt some.
    """
    healing = []
    crit = max(
        0.0,
        min(
            100.0,
            champion_stat(ctx.champion_stats, "critical_strike_chance"),
        ),
    )
    q_ratio = 0.20 * crit / 100.0
    r_ratio = 0.20 + 0.30 * crit / 100.0
    for payment in ctx.payments(
        _healing.HealAnchor.DAMAGING_HIT,
        lambda source: source in {"Q", "auto_attacks", "R"},
    ):
        event = payment.event
        source = _healing.ledger_source_key(event)
        if source in ("Q", "auto_attacks") and q_ratio > 0.0:
            _healing.heal_from_damage(
                healing,
                event,
                _row_damage(event) * q_ratio,
                "Formless Blade",
            )
        elif source == "R" and r_ratio > 0.0:
            _healing.heal_from_damage(
                healing,
                event,
                _row_damage(event) * r_ratio,
                "Apotheosis",
            )
    return healing


SELF_HEALING_RULE = self_healing_rule("Nilah")(derive_self_healing)
