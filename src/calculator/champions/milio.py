"""Milio: full-entry-reviewed packet module.

W (Cozy Campfire) and R (Breath of Life) heal allies and E (Warm Hugs) shields
one.  W's ally half is the sourced Total Heal delivered as one lump packet at
the cast, because the per-tick cadence is priced only for Milio's own self-heal
stream below and the scanner fails closed on a "Heal per Tick" packet with no
authored cadence.  R's heal is authored here and fanned out to allies by the
participant timeline, Milio sitting in
``support_effects._MODULE_AUTHORED_HEAL_SLOTS`` so the scanner defers.
Milio's own W self-heal is 25 sourced ticks, the per-tick row times 25 equalling
the cached Total Heal, through ``derive_self_healing``.
"""

import re
from typing import Any

from .. import healing_helpers as _healing
from ..ability_prose import CachedSentence
from ..cast_event_row import cast_time as _row_cast_time
from .charge_cadence import ChargeRule
from .engine import ONHIT, SlotCtx
from .healing_contract import SelfHealCtx, self_healing_rule
from .inputs import int_option
from .module_helpers import rank_gated_no_damage_parser
from .packet_module import build_packet_module
from .shared_mechanics import per_level_on_hit
from .slot_extract import extract_named

PACKET_SHA256 = "fce2851d13e50c61a320c2195e1618e540b56a81742d3e44cfaa4a0ffe2c163f"

# "Cozy Campfire may grant Fired Up! upon being summoned and at most once
# every 3 seconds thereafter" — one enchantment per cast is the default.
_FIRED_UP_PROCS_PER_CAST = 1

# The burn's ability-power share, on top of the cached per-level row.  The
# AD share of the same hit ("7% / 11% / 15% (based on level) of enchanted
# target's AD") is prose with no cached row and no stated level breakpoints
# on the wiki either, and it reads the *enchanted target's* AD (an ally this
# single-attacker engine cannot stand in for), so it is disclosed rather
# than guessed; the burn is the half the cache sources.
_FIRED_UP_AP_RATIO = 0.20


def _fired_up_detail(burn: float, procs: int) -> str:
    return (
        f"{procs} enchanted hit(s) applying the sourced burn {burn:.2f} "
        "(10 : 50 based on level + 20% of Milio's AP over 1.5s, priced at "
        "the hit); the 7% / 11% / 15% of the enchanted target's AD on the "
        "same hit has no cached row and no sourced level breakpoints"
    )


# How long a Fired Up! enchantment waits, from the cached innate.
_ENCHANTMENT = CachedSentence(
    re.compile(r"grant an enchantment for (?P<value>\d+(?:\.\d+)?) seconds"),
    missing=(
        "Milio P: the cached innate no longer states the enchantment's life "
        "('grant an enchantment for N seconds')"
    ),
)


def _fired_up(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the burn the enchanted hit applies."""
    entry = per_level_on_hit(
        ctx,
        ap_ratio=_FIRED_UP_AP_RATIO,
        count_option="p_procs",
        detail=_fired_up_detail,
    )
    ability = ctx.ability("P")
    if entry is None or ability is None:
        return entry
    # An ability hit on Milio or an ally grants the enchantment and the next
    # basic attack OR ability hit against an enemy spends it, so how many
    # land is the fight's question (champions/armed_procs.py).
    entry["armed_procs"] = {
        "arming_slots": ("Q", "W", "E", "R"),
        "max_stacks": 1,
        "per_cast": 1,
        "stack_seconds": _ENCHANTMENT.value(ability),
        "spent_by_ability_hits": True,
        "armed_at_start": False,
        "requested": ctx.options.get("p_procs") is not None,
    }
    return entry


_fired_up.phase = ONHIT

# Breath of Life is heal/cleanse-only (no outgoing damage) AND
# unlearnable-while-absent — an R rank 0 must not book a cast (the engine
# rotates every SLOT at every rank, and the heal below gates on the rank).
_RANK_GATED_R = rank_gated_no_damage_parser(
    "R",
    reason="The pinned Wiki packet contains no enemy-damage formula for "
    "this slot; it is modeled as a non-damaging/state-only ability.",
)

# Cached kit review: Q "knocks back and stuns the first enemy it hits over
# 1 second" — the enemy the bounced explosion this packet prices then
# damages (and slows).  W, E and R are ally heals/shields and P is an
# enchantment on allies, so no other slot emits an enemy damage event.
MODULE_CC = {"Q": "stun", "P": "none", "W": "none", "E": "none", "R": "none"}

# What this module says about its charge slot (charge_cadence.py).
CHARGE_RULES = {
    "E": ChargeRule(
        why=(
            "E (Warm Hugs) banks casts on its cached rechargeRate (13s "
            "at rank 5); the cached cooldown is the gap between two "
            "banked casts, and the cached stock is 2."
        ),
    )
}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Milio",
    PACKET_SHA256,
    # The explosion deals its packet once, at the cast (the fireball's
    # own 0.25-second delay is Milio's cast lockout, not a hit offset) —
    # the boundary claim that carries MODULE_CC into the event ledger.
    single_hit_slots=frozenset({"Q"}),
    slot_parsers={"P": _fired_up, "R": _RANK_GATED_R},
    cc_kinds=MODULE_CC,
    charge_rules=CHARGE_RULES,
)

OPTIONS = [
    *list(OPTIONS),
    int_option(
        "p_procs",
        _FIRED_UP_PROCS_PER_CAST,
        minimum=0,
        maximum=10,
        label=(
            "Fired Up! hits; unset derives them from the casts that enchant and "
            "the attacks or ability hits that spend it"
        ),
        derives=True,
        rotation={"role": "self_state", "slot": "P"},
    ),
]

ASSUMPTIONS = [
    *list(ASSUMPTIONS),
    "P (Fired Up!) prices the enchanted hit's burn, 10 to 50 by level + 20% of "
    "Milio's AP, once per cast.",
    "It is priced at the hit rather than over its six 0.25s ticks, and the count is "
    "selectable.",
    "The 7/11/15% of the enchanted target's AD has no cached row, so it is disclosed, "
    "not guessed.",
    "P's withheld burst scales with the enchanted target's AD, tagged proc damage on "
    "an ally trigger.",
    "This engine models one attacker, so the ally-carried case has no AD to source "
    "the term.",
    "P's proc count is a selectable option, not a derived arming window.",
    "The hearth applies Fired Up! every 3s over W's 6s (ddragon "
    "healfrequencyseconds, atom HealFrequencySeconds 3.0).",
    "_empower_window_procs resolves armed_by slots to cast times only, so arming on W "
    "would undercount.",
    "Cozy Campfire (W) heals each selected teammate the sourced 70 to 150 + 15% AP as "
    "one lump at the cast.",
    "Its 25-tick cadence over the 6s fuemigo, every 0.264s, is priced for Milio's own "
    "self-heal only.",
    "The ally branch fails closed on per-tick rows rather than inventing a tick "
    "schedule.",
    "Warm Hugs (E) shields the selected teammate for the sourced 45 to 165 + 45% AP "
    "over 2.5s.",
    "Breath of Life (R) heals Milio and every selected teammate the sourced 150 to "
    "350 + 50% AP.",
    "R's 65% tenacity and its cleanse are utility state.",
]


def derive_self_healing(ctx: SelfHealCtx) -> list[dict[str, Any]]:
    """Resolve Milio self-healing events from its authored packet."""
    healing = []
    r_rank = _healing.parsed_rank(ctx.ability_damages, "R")
    heal = extract_named(
        _healing.ability_json(ctx.champion_data, "R"),
        "Heal",
        r_rank,
        ctx.champion_stats,
    )
    if heal > 0.0:
        for cast_index, cast in enumerate(ctx.cast_timeline or []):
            if cast.get("slot") != "R":
                continue
            healing.append(
                {
                    "time": _row_cast_time(cast),
                    "amount": heal,
                    "source": "Breath of Life",
                    "kind": "champion_ability",
                    "actor_wide": True,
                    "target_scope": "self_and_all_teammates",
                    "_event_id": f"milio:r:{cast_index}",
                }
            )
    # Cozy Campfire (W): the fuemigo heals Milio himself — "Milio counts
    # as an allied champion for this ability" — every tick over its
    # 6-second duration (wiki: "Heal per Tick: 2.8 / 3.6 / 4.4 / 5.2 / 6
    # (+ 0.6% AP)"; "Total Heal: 70 / 90 / 110 / 130 / 150 (+ 15% AP)").
    # The tick count is sourced from the Total/PerTick ratio (25) and
    # spread across the 6s duration -> 0.24s intervals.  The 0.264s
    # cadence in the description does not reconcile to the sourced 25
    # ticks, so the ratio-derived count wins, exactly as Janna's Monsoon
    # is handled.  W deals no enemy damage, so the W cast timeline is
    # the sourced trigger.
    w_rank = _healing.parsed_rank(ctx.ability_damages, "W")
    w_ability = _healing.ability_json(ctx.champion_data, "W")
    w_per_tick = extract_named(w_ability, "Heal per Tick", w_rank, ctx.champion_stats)
    w_total = extract_named(w_ability, "Total Heal", w_rank, ctx.champion_stats)
    w_tick_count = (
        max(1, min(100, round(w_total / w_per_tick)))
        if w_per_tick > 0.0 and w_total > 0.0
        else 25
    )
    if w_per_tick > 0.0:
        for cast in ctx.cast_timeline or []:
            if cast.get("slot") != "W":
                continue
            start = _row_cast_time(cast)
            healing.extend(
                {
                    "time": start + index * 0.24,
                    "amount": float(w_per_tick),
                    "source": "Cozy Campfire",
                    "kind": "champion_ability",
                    "actor_wide": True,
                }
                for index in range(1, w_tick_count + 1)
            )
    return healing


SELF_HEALING_RULE = self_healing_rule("Milio")(derive_self_healing)
