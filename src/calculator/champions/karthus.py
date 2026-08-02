"""Karthus — sourced alive-state W -> Q -> E -> R one-rotation model.

Wall of Pain applies its resistance reduction before the damaging sequence.
Lay Waste switches between isolated and shared-target formulas, Defile exposes
an exact selected tick count, and Requiem lands after its three-second channel.
Death Defied is deliberately outside this certified alive-state package.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import DEBUFF, SlotCtx, build_parser
from .slotlib import damage_entry, extract_cooldown, extract_named

_W_MR_REDUCTION_PERCENT = 25.0
_W_DEBUFF_DURATION = 5.0
_W_CAST_TIME = 0.25
_Q_CAST_TIME = 0.25
_Q_CONSERVATIVE_DETONATION_DELAY = 0.75
_E_FIRST_TICK_TIME = _W_CAST_TIME + _Q_CAST_TIME
_E_TICK_INTERVAL = 0.25
_E_MAX_SELECTED_TICKS = 40
_R_CAST_START = _E_FIRST_TICK_TIME
_R_CHANNEL_DURATION = 3.0
_R_CAST_TIME = 0.25


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def _wall_of_pain(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    entry: dict[str, Any] = {
        "name": ability.get("name", "Wall of Pain"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "detail": "Target crosses the wall before the damaging sequence",
    }
    if bool(ctx.options.get("wall_contact", True)):
        entry["target_debuff"] = {
            "mr_reduction_percent": _W_MR_REDUCTION_PERCENT,
            "duration": _W_DEBUFF_DURATION,
        }
    else:
        entry["detail"] = "Wall cast, but the selected target does not cross it"
    return entry


_wall_of_pain.phase = DEBUFF


def _lay_waste(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    requested_isolated = bool(ctx.options.get("q_isolated", True))
    roster_count = int(ctx.target.get("roster_target_count", 1.0))
    isolated = requested_isolated and roster_count <= 1
    attribute = "Isolated Enhanced Damage" if isolated else "Magic Damage"
    raw = extract_named(ability, attribute, rank, ctx.stats, ctx.target)
    hit_time = _W_CAST_TIME + _Q_CAST_TIME + _Q_CONSERVATIVE_DETONATION_DELAY
    entry = damage_entry(
        ability.get("name", "Lay Waste"),
        rank,
        extract_cooldown(ability, rank),
        raw,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", raw, time_offset=hit_time),)
    entry["detail"] = (
        "isolated double damage"
        if isolated
        else "shared-target damage; isolation disabled for a multi-target hit"
    )
    return entry


def _defile(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    requested = int(ctx.options.get("e_ticks", 5))
    ticks = int(_clamp(float(requested), 0.0, float(_E_MAX_SELECTED_TICKS)))
    per_tick = extract_named(
        ability, "Magic Damage Per Tick", rank, ctx.stats, ctx.target
    )
    parts = tuple(
        DamagePart(
            "magic",
            per_tick,
            time_offset=_E_FIRST_TICK_TIME + index * _E_TICK_INTERVAL,
        )
        for index in range(ticks)
    )
    active_seconds = max(0.0, (ticks - 1) * _E_TICK_INTERVAL)
    mana_per_second = float(
        (ability.get("cost") or {})
        .get("modifiers", [{}])[0]
        .get("values", [0])[rank - 1]
    )
    entry = damage_entry(
        ability.get("name", "Defile"),
        rank,
        extract_cooldown(ability, rank),
        per_tick * ticks,
        "magic",
    )
    entry["parts"] = parts
    entry["resource_type"] = "MANA"
    entry["resource_cost"] = mana_per_second * active_seconds
    if active_seconds > 0:
        entry["dot_duration"] = active_seconds
    entry["detail"] = (
        f"{ticks} selected tick{'' if ticks == 1 else 's'} at 0.25-second intervals"
    )
    return entry


def _requiem(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    raw = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    hit_time = _R_CAST_START + _R_CAST_TIME + _R_CHANNEL_DURATION
    entry = damage_entry(
        ability.get("name", "Requiem"),
        rank,
        extract_cooldown(ability, rank),
        raw,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", raw, time_offset=hit_time),)
    entry["cast_time"] = _R_CAST_TIME + _R_CHANNEL_DURATION
    entry["detail"] = "damage after the complete 3-second channel"
    return entry


CAST_ORDER = ("W", "Q", "E", "R")
SUPPORTED_FIGHT_MODES = ("one_rotation",)
UNSUPPORTED_FIGHT_MODE_REASON = (
    "Time-based Karthus calculations are withheld until Defile toggles, its "
    "mana drain, Lay Waste cadence, and Death Defied share one persistent "
    "cast timeline. Use One Rotation."
)
CUSTOM_CAST_ORDER_UNAVAILABLE_REASON = (
    "Karthus uses the certified alive-state W -> Q -> E -> R sequence so the "
    "wall reduction is established before damage."
)
COMPARISON_CURVE_UNAVAILABLE_REASON = (
    "Crossover windows are withheld until Defile and Death Defied persist "
    "between rotations."
)

OPTIONS = [
    {
        "key": "wall_contact",
        "type": "bool",
        "default": True,
        "label": "Target crosses Wall of Pain",
    },
    {
        "key": "q_isolated",
        "type": "bool",
        "default": True,
        "label": "Lay Waste hits only one target",
    },
    {
        "key": "e_ticks",
        "type": "int",
        "default": 5,
        "min": 0,
        "max": _E_MAX_SELECTED_TICKS,
        "step": 1,
        "label": "Defile damage ticks",
    },
]

ASSUMPTIONS = [
    "Certified mode is one alive-state W -> Q -> E -> R sequence against each "
    "selected target.",
    "Wall of Pain reduces the selected target's magic resistance by 25% only "
    "when its contact option is on.",
    "Lay Waste doubles only for a single selected target; a multi-target hit "
    "automatically uses the shared-target formula.",
    "Defile uses exactly the selected tick count and charges mana for the "
    "elapsed 0.25-second intervals.",
    "Lay Waste uses the sourced upper 0.75-second detonation delay because the "
    "Wiki records its live delay as inconsistent between 0.5 and 0.75 seconds.",
    "Death Defied is not entered in this alive-state package; timed and "
    "post-death casts remain unavailable.",
]

SOURCES = [
    {
        "label": "Karthus — Death Defied",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Karthus/Death_Defied",
        "revision_id": 3985387,
        "revision_timestamp": "2026-01-20T00:27:21Z",
    },
    {
        "label": "Karthus — Lay Waste",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Karthus/Lay_Waste",
        "revision_id": 4011136,
        "revision_timestamp": "2026-04-21T03:50:49Z",
    },
    {
        "label": "Karthus — Wall of Pain",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Karthus/Wall_of_Pain",
        "revision_id": 3990033,
        "revision_timestamp": "2026-02-04T22:12:43Z",
    },
    {
        "label": "Karthus — Defile",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Karthus/Defile",
        "revision_id": 4006733,
        "revision_timestamp": "2026-04-07T16:32:02Z",
    },
    {
        "label": "Karthus — Requiem",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Karthus/Requiem",
        "revision_id": 4015394,
        "revision_timestamp": "2026-05-04T13:24:38Z",
    },
]

SLOTS = {"W": _wall_of_pain, "Q": _lay_waste, "E": _defile, "R": _requiem}

parse_abilities = build_parser(SLOTS, "Karthus")
