"""Galio — sourced modified attacks and event-timed spell damage.

The generic parser cannot certify this kit: Colossal Smash converts a
bounded number of complete basic attacks to magic damage, Winds of War has
four delayed target-max-health ticks, Shield of Durand is charge-scaled,
Justice Punch has distance-dependent travel, and Hero's Entrance lands only
after its channel. This module authors those states and their hit times.
"""

import math
from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .inputs import float_option, int_option
from .module_helpers import named_damage
from .slotlib import ability_name, damage_entry, extract_cooldown, extract_named
from .source_receipts import load_champion_sources

_Q_CAST_TIME = 0.25
_Q_TORNADO_FIRST_TICK = 0.75
_Q_TORNADO_TICK_INTERVAL = 0.5
_Q_TORNADO_TICKS = 4
_W_MAX_CHARGE = 2.0
_W_DAMAGE_CAP_TIME = 1.25
_W_DAMAGE_STEP = 0.16
_W_RECAST_LOCKOUT = 0.4
_E_CAST_TIME = 0.4
_E_DASH_SPEED = 2300.0
_R_LANDING_TIME = 2.75


def _colossal_smash(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: replace the first N ordinary swings with modified magic attacks."""
    ability = ctx.ability()
    if ability is None:
        return None
    conversions = max(0, int(ctx.option("passive_procs")))
    total_modified_raw = extract_named(
        ability,
        "Bonus Magic Damage",
        ctx.level,
        ctx.stats,
        ctx.target,
    )
    total_ad = float(ctx.stat("attack_damage"))
    return {
        "name": ability_name(ability),
        "auto_attack_conversion": {
            "name": ability_name(ability),
            "count": conversions,
            "bonus_raw": max(0.0, total_modified_raw - total_ad),
            "damage_type": "magic",
        },
    }


def _winds_of_war(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: gust at cast end, then four max-health tornado ticks."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    gust = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    ap = float(ctx.stat("ability_power"))
    target_max_health = float(ctx.target_stat("target_max_health"))
    per_tick = target_max_health * (0.02 + ap * 0.0001)

    def max_health_tick(
        _missing_ratio: float,
        live_target_max_health: float | None = None,
    ) -> float:
        live_max = (
            target_max_health
            if live_target_max_health is None
            else live_target_max_health
        )
        return live_max * (0.02 + ap * 0.0001)

    total = gust + per_tick * _Q_TORNADO_TICKS
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (
        DamagePart("magic", gust, time_offset=_Q_CAST_TIME),
        DamagePart(
            "magic",
            per_tick,
            hp_scaled_damage=max_health_tick,
            count=_Q_TORNADO_TICKS,
            time_offset=_Q_TORNADO_FIRST_TICK,
            hit_interval=_Q_TORNADO_TICK_INTERVAL,
        ),
    )
    entry["cast_time"] = _Q_CAST_TIME
    entry["target_max_health_sensitive"] = True
    entry["detail"] = "1 gust + 4 tornado ticks over 2 seconds"
    return entry


def _shield_of_durand(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: damage grows in eight 25% steps over the first 1.25 seconds."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    charge = min(
        _W_MAX_CHARGE,
        max(0.0, float(ctx.options.get("w_charge_seconds", _W_DAMAGE_CAP_TIME))),
    )
    if charge >= _W_DAMAGE_CAP_TIME - 1e-9:
        steps = 8
    else:
        steps = min(7, math.floor((charge + 1e-9) / _W_DAMAGE_STEP))
    multiplier = 1.0 + 0.25 * steps
    minimum = extract_named(
        ability,
        "Minimum Magic Damage",
        rank,
        ctx.stats,
        ctx.target,
    )
    total = minimum * multiplier
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", total, time_offset=charge),)
    entry["cast_time"] = charge + _W_RECAST_LOCKOUT
    entry["detail"] = f"{charge:g}s charge · {multiplier:g}× minimum damage"
    return entry


def _justice_punch(ctx: SlotCtx) -> dict[str, Any] | None:
    """E: champion damage at cast time plus the selected dash travel."""
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    distance = min(
        650.0,
        max(250.0, float(ctx.option("e_dash_distance"))),
    )
    hit_delay = _E_CAST_TIME + distance / _E_DASH_SPEED
    total = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", total, time_offset=hit_delay),)
    entry["cast_time"] = hit_delay
    entry["detail"] = f"champion hit after {hit_delay:.2f}s"
    return entry


# R: impact damage after the sourced 2.75-second channel.
_heros_entrance = named_damage(
    "Magic Damage",
    "magic",
    time_offset=_R_LANDING_TIME,
    cast_time=_R_LANDING_TIME,
    detail="impact after 2.75s channel; allied cast target assumed",
)


OPTIONS: list[dict[str, Any]] = [
    int_option(
        "passive_procs",
        1,
        minimum=0,
        maximum=10,
        label="Colossal Smash attacks available",
    ),
    float_option(
        "w_charge_seconds",
        1.25,
        minimum=0.0,
        maximum=2.0,
        label="W charge time (seconds)",
        step=0.16,
    ),
    float_option(
        "e_dash_distance",
        650.0,
        minimum=250.0,
        maximum=650.0,
        label="E travel distance",
        step=50.0,
    ),
]

ASSUMPTIONS = [
    "Colossal Smash count is user-set because its five-second cooldown is "
    "reduced by three seconds per spell hit and therefore depends on the "
    "chosen attack weave; each selected proc replaces one complete physical "
    "swing with the sourced modified magic basic attack",
    "W damage uses the sourced 25%-per-0.16s charge steps, caps after 1.25s, "
    "and includes its 0.4s post-release action lockout in timed scheduling",
    "Q assumes both gusts converge and the target remains in all four tornado "
    "ticks; the tornado uses the target's starting maximum health",
    "E assumes a champion collision after the selected 250-650 unit travel",
    "R assumes a valid allied cast target and that the selected enemy remains "
    "inside the landing area after the 2.75s channel",
    "Taunts, knockups, slows, self damage reduction, and allied R shields are "
    "control or defense rather than Galio's damage and are not added to TDD",
]

SOURCES = load_champion_sources("Galio")

SLOTS = {
    "Q": _winds_of_war,
    "W": _shield_of_durand,
    "E": _justice_punch,
    "R": _heros_entrance,
    "P": _colossal_smash,
}

# Q's windblasts and tornado only damage; W's recast "taunts them", E
# "knocks them up for 0.75 seconds", R lands "knocking them back 100
# units".  P is the auto-attack conversion row — it authors no damage part
# of its own, so it carries no reviewable marker.
MODULE_CC = {"Q": "none", "W": "taunt", "E": "knockup", "R": "knockback"}

parse_abilities = build_parser(SLOTS, "Galio", cc_kinds=MODULE_CC)
