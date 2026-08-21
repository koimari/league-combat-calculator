"""Janna's charge-scaled whirlwind, Zephyr damage and utility branches.

E8d ally-support: E (Eye of the Storm, Shield Strength 80-240 + 55% AP, scope
one_teammate) shields the selected teammate; R (Monsoon, Total Heal 300-600 +
150% AP, scope self_and_all_teammates) heals the caster and all allies.  Both
events are authored by the engine's ally-support scanner from cached leveling
at the cast times; the module declares E/R in SLOTS so the fight rotation
casts them.  R's heal is delivered as the sourced Total Heal at cast time
(the cached per-tick row is the cadence detail: 12 ticks x Heal Per Tick ==
Total Heal).
"""

from __future__ import annotations

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .healing_contract import declare_healing_rule
from .module_helpers import no_damage
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    on_hit_entry,
)
from .source_receipts import load_champion_sources
from ..healing_helpers import _ability, _rank


def _tailwind(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    bonus_ms = max(0.0, float(ctx.option("bonus_movement_speed")))
    value = 0.30 * bonus_ms
    entry = on_hit_entry(ability.get("name", "Tailwind"), value, "magic")
    entry["detail"] = (
        f"30% of the explicit {bonus_ms:g} bonus movement speed is bonus magic damage on attacks and Zephyr."
    )
    return entry


def _howling_gale(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    charge = min(max(float(ctx.option("q_charge")), 0.0), 1.0)
    low = extract_named(ability, "Minimum Magic Damage", rank, ctx.stats, ctx.target)
    high = extract_named(ability, "Maximum Magic Damage", rank, ctx.stats, ctx.target)
    value = low + (high - low) * charge
    entry = damage_entry(
        ability.get("name", "Howling Gale"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value, time_offset=1.25),)
    entry["detail"] = (
        f"{charge:.2f} charge fraction; knock-up and recast direction are utility state."
    )
    return entry


def _zephyr(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    value = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Zephyr"),
        rank,
        extract_cooldown(ability, rank),
        value,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", value),)
    entry["event_order_certified"] = "single_hit"
    entry["detail"] = (
        "Passive movement speed and active slow are sourced utility; the active is one magic hit."
    )
    return entry


SLOTS = {
    "P": _tailwind,
    "Q": _howling_gale,
    "W": _zephyr,
    "E": lambda ctx: no_damage(
        ctx,
        name="Eye of the Storm",
        reason="Shield and bonus attack damage are ally-facing defensive utility.",
    ),
    "R": lambda ctx: no_damage(
        ctx,
        name="Monsoon",
        reason="Knockback and channelled healing are utility; the parent entry has no outgoing champion damage formula.",
    ),
}
# Q's whirlwind deals magic damage "and knock[s] them up"; W's air
# elemental "deals magic damage and slows them for 2 seconds".  P is the
# on-hit bonus row and E/R author no damage part at all (Monsoon's
# knockback has no damage formula in the cached entry).
MODULE_CC = {"Q": "knockup", "W": "slow"}

parse_abilities = build_parser(SLOTS, "Janna", cc_kinds=MODULE_CC)
OPTIONS = [
    {
        "key": "bonus_movement_speed",
        "type": "float",
        "default": 0.0,
        "min": 0.0,
        "max": 500.0,
        "label": "Bonus movement speed",
    },
    {
        "key": "q_charge",
        "type": "float",
        "default": 1.0,
        "min": 0.0,
        "max": 1.0,
        "step": 0.25,
        "label": "Howling Gale charge fraction",
    },
]
ASSUMPTIONS = [
    "Tailwind's 30% bonus-movement-speed on-hit uses the explicit movement-speed input.",
    "Howling Gale interpolates the sourced minimum/maximum charge packet; W's passive movement speed is not double-counted as damage.",
    "Eye of the Storm and Monsoon are visible ally/defensive utility, not TDD.",
    "E (Eye of the Storm) shields the selected teammate for the sourced "
    "Shield Strength (80-240 + 55% AP) for 4s (scanner packet with "
    "selection key shield:E:<cast>); the shield's bonus attack damage "
    "(10-30 + 10% AP while the shield holds) is documented-only — the "
    "roster model prices ally survivability, not ally outgoing damage, "
    "so the AD rider has no survival effect here.",
    "R (Monsoon) heals Janna and every selected teammate the sourced "
    "per-tick stream (12 x Heal Per Tick == Total Heal 300-600 + 150% "
    "AP) via the E1-rule fan-out; the knockback and channel are state.",
]
SOURCES = load_champion_sources("Janna")


# pylint: disable=too-many-arguments,too-many-positional-arguments,unused-argument
# pylint: disable=too-many-locals
def derive_self_healing(
    champion_data,
    champion_stats,
    ability_damages,
    damage_events,
    cast_timeline=None,
    fight_duration_seconds=None,
):
    """Monsoon pays its sourced per-tick heal on its own 0.25s channel.

    Monsoon channels for up to 3 seconds, healing Janna herself and nearby
    allies every 0.25 seconds (wiki: "Heal Per Tick: 25 / 37.5 / 50
    (+ 12.5% AP)"; "Total Heal: 300 / 450 / 600 (+ 150% AP)").  The tick
    count is sourced from the total/per-tick ratio so the authored sum
    stays exact at every rank.

    Issue #143 (phase 2): this rule is the ONE ledger owner of the R heal.
    The support scanner defers the slot (``_MODULE_AUTHORED_HEAL_SLOTS``)
    and the participant timeline fans every tick out to all selected
    teammates (``target_scope: self_and_all_teammates``), so the ally heal
    is the same ticked sourced heal as the self heal instead of the
    scanner's 600 lump.  R emits no damage, so the schedule is the cast's
    own — never inferred from the damage ledger.
    """
    healing: list[dict] = []
    r_rank = _rank(ability_damages, "R")
    ability = _ability(champion_data, "R")
    per_tick = extract_named(ability, "Heal Per Tick", r_rank, champion_stats)
    total = extract_named(ability, "Total Heal", r_rank, champion_stats)
    tick_count = (
        max(1, min(100, int(round(total / per_tick))))
        if per_tick > 0.0 and total > 0.0
        else 12
    )
    if per_tick > 0.0:
        for cast_index, cast in enumerate(cast_timeline or []):
            if cast.get("slot") != "R":
                continue
            start = float(cast.get("time", 0.0))
            for index in range(1, tick_count + 1):
                healing.append(
                    {
                        "time": start + index * 0.25,
                        "amount": float(per_tick),
                        "source": "Monsoon",
                        "kind": "champion_ability",
                        "actor_wide": True,
                        "target_scope": "self_and_all_teammates",
                        "_event_id": f"janna:r:{cast_index}:{index}",
                    }
                )
    return sorted(healing, key=lambda event: (event["time"], event["source"]))


SELF_HEALING_RULE = declare_healing_rule("Janna", derive_self_healing)
