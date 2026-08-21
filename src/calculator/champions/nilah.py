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
"""

from .packet_module import build_packet_module
from .engine import SlotCtx, build_parser
from .slotlib import damage_entry, extract_cooldown, extract_named

PACKET_SHA256 = "95ce830b00c9c829930974899e20cda18a55eb0bb6ab1cc16360b57113671fe5"

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
)
PACKET_SPEC = SLOTS.packet_spec

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
_NILAH_R_HEAL_TO_SHIELD_MAX_RATIO = 0.50
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
    crit_chance = min(
        max(float(ctx.stats.get("critical_strike_chance", 0.0)) / 100.0, 0.0), 1.0
    )
    multiplier = 1.0 + (_Q_CRIT_MULTIPLIER_AT_MAX - 1.0) * crit_chance
    total = min_damage * multiplier
    entry = damage_entry(
        ability.get("name", "Formless Blade"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["detail"] = (
        "Minimum Physical Damage row (0% crit) scaled by "
        f"{multiplier:.4f} = 1 + 0.91 x {crit_chance:.2f} crit chance"
    )
    return entry


SLOTS = dict(SLOTS)
SLOTS["Q"] = _formless_blade
parse_abilities = build_parser(SLOTS, "Nilah")

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
]
MODULE_COVERAGE = {
    slot: ("modeled" if slot in {"Q", "E", "R"} else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"

from .. import healing_helpers as _healing  # pylint: disable=wrong-import-position


# pylint: disable=protected-access,too-many-arguments,too-many-locals,too-many-positional-arguments,unused-argument,wrong-import-position
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Nilah self-healing events from its authored packet."""
    healing = []
    crit = max(
        0.0,
        min(
            100.0,
            float(champion_stats.get("critical_strike_chance", 0.0) or 0.0),
        ),
    )
    q_ratio = 0.20 * crit / 100.0
    r_ratio = 0.20 + 0.30 * crit / 100.0
    for event in damage_events:
        source = _healing._event_source(event)
        if source in ("Q", "auto_attacks") and q_ratio > 0.0:
            _healing._heal_from_damage(
                healing,
                event,
                float(event.get("damage", 0.0)) * q_ratio,
                "Formless Blade",
            )
        elif source == "R" and r_ratio > 0.0:
            _healing._heal_from_damage(
                healing,
                event,
                float(event.get("damage", 0.0)) * r_ratio,
                "Apotheosis",
            )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


from .healing_contract import (
    declare_healing_rule,
)  # pylint: disable=wrong-import-position

SELF_HEALING_RULE = declare_healing_rule("Nilah", derive_self_healing)
