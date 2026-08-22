"""Nilah — CP10.5 full-entry-reviewed packet module.

E2 DoT fix: R (Apotheosis) prices 4 sourced 0.25s ticks
(this module's packet timing declaration).

E5-2 fix — Formless Blade (Q): the reviewed packet pinned the crit-MAX
"Maximum Physical Damage" row (0-76.4 + 191% AD) as the flat damage, so
every fight priced Nilah at 100% critical strike chance.  The wiki
carries both endpoints: "Minimum Physical Damage" (0-40 + 100% AD at 0%
crit) and "Maximum Physical Damage" (0-76.4 + 191% AD at 100% crit),
"increased by 0% : 70% (+ 0% : 21%) (based on critical strike chance)".
Both cached rows scale by exactly 1.91 (= 1 + 0.70 + 0.21) from the
minimum at every rank, so the Q is modeled as the minimum row times
``1 + 0.91 x crit_chance`` — exact at both sourced endpoints, linear in
between.  The test fights (no items) sit at 0% crit and price exactly
the minimum row.

Coverage: P (Joy Unending) amplifies nearby allied heals and shields and
converts self-heal excess into a shield; W (Jubilant Veil) is ghosting,
bonus movement speed, 25% magic-damage reduction and a basic-attack
dodge.  Neither carries an enemy-damage clause — the pinned packet
declares both ``kind: "no_damage"`` — so both slots are ``no_damage``,
not ``out_of_scope``.  The ally heal/shield amplifier and the
damage-taken reduction remain axes the engine does not have, documented
in ASSUMPTIONS.
"""

from .inputs import champion_stat
from .healing_contract import self_healing_rule
from .packet_module import build_packet_module
from .engine import SlotCtx
from .slotlib import damage_entry, extract_cooldown, extract_named
from .. import healing_helpers as _healing
from .module_contract import coverage

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


def _formless_blade(ctx: SlotCtx):
    """Q: minimum-row physical damage, scaled linearly by crit chance."""
    ability = ctx.ability("Q", 0)
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    min_damage = extract_named(
        ability, "Minimum Physical Damage", rank, ctx.stats, ctx.target
    )
    crit_chance = min(max(float(ctx.stat("critical_strike_chance")) / 100.0, 0.0), 1.0)
    multiplier = 1.0 + (_Q_CRIT_MULTIPLIER_AT_MAX - 1.0) * crit_chance
    total = min_damage * multiplier
    entry = damage_entry(
        ability.get("name", "Formless Blade"),
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
MODULE_CC = {"Q": "none", "E": "none", "R": "slow"}

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
)

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Joy Unending) converts self-heal excess beyond maximum health "
    "into a 6-second shield (cached description); the conversion ratios "
    "are 0%:20% (Q autos) and 20%:50% (R) by critical strike chance "
    "(module constants). The excess is a live healing state the shared "
    "ledger only prices for Bloodthirster, so the conversion is "
    "documented, not emitted as a fixed shield amount",
    "Q (Formless Blade) prices the wiki's 'Minimum Physical Damage' row "
    "(0-40 + 100% AD) as the 0%-crit base. The damage 'increased by "
    "0% : 70% (+ 0% : 21%) (based on critical strike chance)' with the "
    "cached Maximum row (0-76.4 + 191% AD) exactly 1.91x the Minimum at "
    "every rank; the module scales linearly with the fight's crit "
    "chance, exact at both sourced endpoints.",
    "KNOWN CACHE LAG (verified 16.16.1, not fixed here — out of this "
    "module's file scope): E (Slipstream)'s cached cost row is flat 30 "
    "at every rank; the game files say 40 — bin NilahEAbility/NilahE "
    "'mana' [40, 40, 40, 40, 40, 40] and ddragon Nilah.json costBurn "
    "'40' (single value, all ranks) both confirm 40, not 30 (Nilah's "
    "resource is MANA per the CharacterRecord arType). This module does "
    "not model resource costs at all (no extract_cost call, no "
    "hardcoded value to re-pin) — the generic engine.py resource-cost "
    "stamp reads data/champions.json directly, so the flag traces to "
    "the wiki cache, not to this module or its tests (no test currently "
    "asserts Nilah's resource_cost). Clearing patch_regression.py's "
    "ability_rows_stale flag requires a data/champions.json re-pull/"
    "re-cert, which is outside this task's scope (see "
    "docs/patch-day-runbook.md Step 3.A).",
    "P (Joy Unending) and W (Jubilant Veil) carry no enemy-damage "
    "formula of any kind (the reviewed packet's own slot declarations "
    "already carry kind='no_damage' for both): Joy Unending is the "
    "excess-heal-to-shield converter documented above; Jubilant Veil is "
    "the ghost/mist self-and-ally defensive buff (bonus movement speed, "
    "25% magic damage reduction, basic-attack dodge). Reclassified from "
    "out_of_scope to no_damage (a stale label, not a computation "
    "change): both slots were previously mislabeled out_of_scope "
    "despite the packet layer already carrying no enemy-damage formula "
    "for them.",
]
MODULE_COVERAGE = coverage(no_damage="PW")


# pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
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
            champion_stat(champion_stats, "critical_strike_chance"),
        ),
    )
    q_ratio = 0.20 * crit / 100.0
    r_ratio = 0.20 + 0.30 * crit / 100.0
    for payment in _healing.payments(
        _healing.HealAnchor.DAMAGING_HIT,
        lambda source: source in {"Q", "auto_attacks", "R"},
        damage_events,
    ):
        event = payment.event
        source = _healing.event_source(event)
        if source in ("Q", "auto_attacks") and q_ratio > 0.0:
            _healing.heal_from_damage(
                healing,
                event,
                float(event.get("damage", 0.0)) * q_ratio,
                "Formless Blade",
            )
        elif source == "R" and r_ratio > 0.0:
            _healing.heal_from_damage(
                healing,
                event,
                float(event.get("damage", 0.0)) * r_ratio,
                "Apotheosis",
            )
    return healing


SELF_HEALING_RULE = self_healing_rule("Nilah")(derive_self_healing)
