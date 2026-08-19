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
from .slotlib import damage_entry, extract_cooldown, extract_named

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
        "name": ability.get("name", "Colossal Smash"),
        "auto_attack_conversion": {
            "name": ability.get("name", "Colossal Smash"),
            "count": conversions,
            "bonus_raw": max(0.0, total_modified_raw - total_ad),
            "damage_type": "magic",
        },
    }


def _winds_of_war(ctx: SlotCtx) -> dict[str, Any] | None:
    """Q: gust at cast end, then four max-health tornado ticks."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

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
        ability.get("name", "Winds of War"),
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
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

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
        ability.get("name", "Shield of Durand"),
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
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    distance = min(
        650.0,
        max(250.0, float(ctx.option("e_dash_distance"))),
    )
    hit_delay = _E_CAST_TIME + distance / _E_DASH_SPEED
    total = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Justice Punch"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", total, time_offset=hit_delay),)
    entry["cast_time"] = hit_delay
    entry["detail"] = f"champion hit after {hit_delay:.2f}s"
    return entry


def _heros_entrance(ctx: SlotCtx) -> dict[str, Any] | None:
    """R: impact damage after the sourced 2.75-second channel."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    total = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    entry = damage_entry(
        ability.get("name", "Hero's Entrance"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", total, time_offset=_R_LANDING_TIME),)
    entry["cast_time"] = _R_LANDING_TIME
    entry["detail"] = "impact after 2.75s channel; allied cast target assumed"
    return entry


OPTIONS: list[dict[str, Any]] = [
    {
        "key": "passive_procs",
        "type": "int",
        "default": 1,
        "label": "Colossal Smash attacks available",
        "min": 0,
        "max": 10,
    },
    {
        "key": "w_charge_seconds",
        "type": "float",
        "default": 1.25,
        "label": "W charge time (seconds)",
        "min": 0.0,
        "max": 2.0,
        "step": 0.16,
    },
    {
        "key": "e_dash_distance",
        "type": "float",
        "default": 650.0,
        "label": "E travel distance",
        "min": 250.0,
        "max": 650.0,
        "step": 50.0,
    },
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

SOURCES = [
    {
        "label": "Galio — Colossal Smash",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Galio/Colossal_Smash",
        "revision_id": 4038336,
        "revision_timestamp": "2026-06-30T08:53:44Z",
    },
    {
        "label": "Galio — Winds of War",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Galio/Winds_of_War",
        "revision_id": 4016962,
        "revision_timestamp": "2026-05-13T14:26:32Z",
    },
    {
        "label": "Galio — Shield of Durand",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Galio/Shield_of_Durand",
        "revision_id": 3990299,
        "revision_timestamp": "2026-02-07T07:08:21Z",
    },
    {
        "label": "Galio — Justice Punch",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Galio/Justice_Punch",
        "revision_id": 4016963,
        "revision_timestamp": "2026-05-13T14:26:54Z",
    },
    {
        "label": "Galio — Hero's Entrance",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Galio/Hero%27s_Entrance",
        "revision_id": 4017997,
        "revision_timestamp": "2026-05-14T13:57:45Z",
    },
]

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


# Authoritative review metadata (issue #161).
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
