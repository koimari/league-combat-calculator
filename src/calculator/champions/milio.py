"""Milio — CP10.4 full-entry-reviewed packet module.

E2 DoT fix: W (Cozy Campfire) heals 25 sourced ticks (Heal per Tick x25 ==
Total Heal) via this module's ``derive_self_healing``.

E8d ally-support: W (Cozy Campfire, Total Heal 70-150 + 15% AP, scope
one_teammate) and R (Breath of Life, Heal 150-350 + 50% AP, scope
self_and_all_teammates) heal allies, and E (Warm Hugs, Shield Strength
45-165 + 45% AP, scope one_teammate) shields one.  W's ally half is the
sourced Total Heal delivered as one lump packet at the cast — the per-tick
cadence is priced only for Milio's own self-heal stream below, and the
scanner fails closed on "Heal per Tick" packets without an authored
cadence.  R's heal is authored here and fanned out to allies by the
participant timeline (Milio is in ``support_effects._MODULE_AUTHORED_HEAL_SLOTS``
so the scanner defers).
"""

from typing import Any

from .. import healing_helpers as _healing
from .engine import ONHIT, SlotCtx
from .healing_contract import self_healing_rule
from .module_helpers import rank_gated_no_damage_parser
from .packet_module import build_packet_module
from .slotlib import ability_name, extract_named, on_hit_entry
from .inputs import int_option

PACKET_SHA256 = "fce2851d13e50c61a320c2195e1618e540b56a81742d3e44cfaa4a0ffe2c163f"

# "Cozy Campfire may grant Fired Up! upon being summoned and at most once
# every 3 seconds thereafter" — one enchantment per cast is the default.
_FIRED_UP_PROCS_PER_CAST = 1


def _fired_up(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: the burn the enchanted hit applies.

    The AD share of the same hit ("7% / 11% / 15% (based on level) of
    enchanted target's AD") is prose with no cached row and no stated level
    breakpoints on the wiki either, and it reads the *enchanted target's* AD
    (an ally this single-attacker engine cannot stand in for), so it is
    disclosed rather than guessed; the burn is the half the cache sources.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    burn = extract_named(
        ability, "Per-Level Scaling", ctx.level, ctx.stats, ctx.target, level=ctx.level
    ) + 0.20 * float(ctx.stat("ability_power") or 0.0)
    if burn <= 0:
        return None
    procs = max(0, int(ctx.option("p_procs")))
    entry = on_hit_entry(ability_name(ability), burn, "magic")
    entry["on_hit"]["max_procs"] = procs
    entry["detail"] = (
        f"{procs} enchanted hit(s) applying the sourced burn {burn:.2f} "
        "(10 : 50 based on level + 20% of Milio's AP over 1.5s, priced at "
        "the hit); the 7% / 11% / 15% of the enchanted target's AD on the "
        "same hit has no cached row and no sourced level breakpoints"
    )
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
MODULE_CC = {"Q": "stun"}

parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module(
    "Milio",
    PACKET_SHA256,
    # The explosion deals its packet once, at the cast (the fireball's
    # own 0.25-second delay is Milio's cast lockout, not a hit offset) —
    # the boundary claim that carries MODULE_CC into the event ledger.
    single_hit_slots=frozenset({"Q"}),
    slot_parsers={"P": _fired_up, "R": _RANK_GATED_R},
    cc_kinds=MODULE_CC,
)

OPTIONS = list(OPTIONS) + [
    int_option(
        "p_procs",
        _FIRED_UP_PROCS_PER_CAST,
        minimum=0,
        maximum=10,
        label="Fired Up! hits landed",
    ),
]

ASSUMPTIONS = list(ASSUMPTIONS) + [
    "P (Fired Up!) prices the sourced burn the enchanted hit applies "
    "(10 : 50 based on level + 20% of Milio's AP, priced at the hit rather "
    "than over its six 0.25s ticks) once per cast (selectable); the "
    "7% / 11% / 15% of the enchanted target's AD on the same hit has no "
    "cached leveling row and no sourced level breakpoints, so it is "
    "disclosed rather than guessed.",
    "P (Fired Up!)'s withheld burst scales with the ENCHANTED TARGET's AD "
    "and is tagged proc damage when an ally triggers it (cached P notes). "
    "This engine models a single attacker, so the ally-carried case has no "
    "attacker whose AD could source the term.",
    "P (Fired Up!)'s proc count is a selectable option rather than a "
    "derived arming window: the hearth applies Fired Up! every 3 seconds "
    "over W's 6s duration (ddragon healfrequencyseconds, atom "
    "HealFrequencySeconds = 3.0), while damage.py's _empower_window_procs "
    "resolves armed_by slots to cast times only, so declaring W as an "
    "arming slot would undercount its arms.",
    "Cozy Campfire (W) heals each selected teammate the sourced Total "
    "Heal (70-150 + 15% AP) as one lump packet at the cast; the 25-tick "
    "cadence (Heal per Tick x25 over the 6s fuemigo, every 0.264s) is "
    "priced only for Milio's own self-heal stream below, and the ally "
    "branch fails closed on per-tick rows rather than inventing a tick "
    "schedule.",
    "Warm Hugs (E) shields the selected teammate for the sourced Shield "
    "Strength (45-165 + 45% AP) for 2.5s and Breath of Life (R) heals "
    "Milio and every selected teammate the sourced Heal (150-350 + 50% "
    "AP) via the fan-out below; the 65% tenacity and cleanse are utility "
    "state.",
]


# pylint: disable=too-many-arguments,too-many-positional-arguments,unused-argument
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Resolve Milio self-healing events from its authored packet."""
    healing = []
    r_rank = _healing.parsed_rank(ability_damages, "R")
    heal = _healing.extract_named(
        _healing.ability_json(champion_data, "R"), "Heal", r_rank, champion_stats
    )
    if heal > 0.0:
        for cast_index, cast in enumerate(cast_timeline or []):
            if cast.get("slot") != "R":
                continue
            healing.append(
                {
                    "time": float(cast.get("time", 0.0)),
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
    w_rank = _healing.parsed_rank(ability_damages, "W")
    w_ability = _healing.ability_json(champion_data, "W")
    w_per_tick = _healing.extract_named(
        w_ability, "Heal per Tick", w_rank, champion_stats
    )
    w_total = _healing.extract_named(w_ability, "Total Heal", w_rank, champion_stats)
    w_tick_count = (
        max(1, min(100, int(round(w_total / w_per_tick))))
        if w_per_tick > 0.0 and w_total > 0.0
        else 25
    )
    if w_per_tick > 0.0:
        for cast in cast_timeline or []:
            if cast.get("slot") != "W":
                continue
            start = float(cast.get("time", 0.0))
            for index in range(1, w_tick_count + 1):
                healing.append(
                    {
                        "time": start + index * 0.24,
                        "amount": float(w_per_tick),
                        "source": "Cozy Campfire",
                        "kind": "champion_ability",
                        "actor_wide": True,
                    }
                )
    return healing


SELF_HEALING_RULE = self_healing_rule("Milio")(derive_self_healing)
