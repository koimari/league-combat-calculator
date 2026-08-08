"""Taliyah — sourced E -> W -> Q one-rotation event model.

The certified package casts Unraveled Earth, knocks the selected target across
its stones with Seismic Shove, then fires Threaded Volley. Every damaging hit
has an authored time. Worked Ground and the number of stones actually
detonated remain explicit scenario inputs instead of optimistic hidden state.
"""

import math
from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import damage_entry, extract_cooldown, extract_named

_E_CAST_START = 0.0
_W_CAST_START = 0.25
_Q_CAST_START = 0.5
_W_ERUPTION_DELAY = 0.792
_E_ROW_INTERVAL = 0.17
_E_DETONATION_MULTIPLIERS = (1.0, 0.75, 0.5, 0.25)
_Q_CAST_TIME = 0.25
_Q_NORMAL_LAUNCH_OFFSETS = (0.25, 0.75, 1.25, 1.5, 1.75)
_Q_NORMAL_INITIAL_SPEED = 3600.0
_Q_NORMAL_DECELERATION = 5000.0
_Q_WORKED_SPEED = 2000.0
_Q_ORIGIN_OFFSET = 50.0
_Q_MAX_RANGE = 1000.0
_Q_WORKED_COST = 10.0
_Q_WORKED_COOLDOWN_MULTIPLIER = 0.5
_Q_WORKED_MINIMUM_COOLDOWN = 0.75


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def _normal_projectile_time(distance: float) -> float:
    """Travel time for a shard's sourced decelerating projectile."""
    travel = max(0.0, distance - _Q_ORIGIN_OFFSET)
    discriminant = max(
        0.0,
        _Q_NORMAL_INITIAL_SPEED**2 - 2.0 * _Q_NORMAL_DECELERATION * travel,
    )
    return (_Q_NORMAL_INITIAL_SPEED - math.sqrt(discriminant)) / _Q_NORMAL_DECELERATION


def _is_primary_target(ctx: SlotCtx) -> bool:
    return int(ctx.target.get("roster_target_index", 0.0)) == 0


def _threaded_volley(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    ground = str(ctx.options.get("q_ground", "normal"))
    if ground not in {"normal", "worked"}:
        raise ValueError("Taliyah q_ground must be normal or worked")
    distance = _clamp(
        float(ctx.options.get("q_target_distance", 800.0)), 0.0, _Q_MAX_RANGE
    )

    if ground == "worked":
        primary = _is_primary_target(ctx)
        attribute = "Empowered Damage" if primary else "Secondary Target Damage"
        raw = extract_named(ability, attribute, rank, ctx.stats, ctx.target)
        travel = max(0.0, distance - _Q_ORIGIN_OFFSET) / _Q_WORKED_SPEED
        hit_time = _Q_CAST_START + _Q_CAST_TIME + travel
        entry = damage_entry(
            ability.get("name", "Threaded Volley"),
            rank,
            max(
                _Q_WORKED_MINIMUM_COOLDOWN,
                extract_cooldown(ability, rank) * _Q_WORKED_COOLDOWN_MULTIPLIER,
            ),
            raw,
            "magic",
        )
        entry["parts"] = (DamagePart("magic", raw, time_offset=hit_time),)
        entry["resource_type"] = "MANA"
        entry["resource_cost"] = _Q_WORKED_COST
        target_label = "primary" if primary else "secondary"
        entry["detail"] = (
            f"Worked Ground boulder on the {target_label} target at {distance:g} range"
        )
        return entry

    first = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    reduced = extract_named(ability, "Reduced Damage", rank, ctx.stats, ctx.target)
    travel = _normal_projectile_time(distance)
    parts = tuple(
        DamagePart(
            "magic",
            first if index == 0 else reduced,
            time_offset=_Q_CAST_START + launch + travel,
        )
        for index, launch in enumerate(_Q_NORMAL_LAUNCH_OFFSETS)
    )
    total = first + 4.0 * reduced
    entry = damage_entry(
        ability.get("name", "Threaded Volley"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = parts
    entry["detail"] = (
        f"5 shards on one target at {distance:g} range; later shards deal 40%"
    )
    return entry


def _seismic_shove(ctx: SlotCtx) -> dict[str, Any] | None:
    """W deals no damage but spends its sourced cast and mana cost."""
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None
    return {
        "name": ability.get("name", "Seismic Shove"),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "detail": "Knockback used to trigger the selected E stones",
    }


def _unraveled_earth(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    requested = int(ctx.options.get("e_detonations", 4))
    detonations = int(_clamp(float(requested), 0.0, 4.0))
    initial = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    detonation = extract_named(
        ability, "Detonation Magic Damage", rank, ctx.stats, ctx.target
    )
    first_detonation = _W_CAST_START + _W_ERUPTION_DELAY
    parts = [DamagePart("magic", initial, time_offset=_E_CAST_START)]
    parts.extend(
        DamagePart(
            "magic",
            detonation * multiplier,
            time_offset=first_detonation + index * _E_ROW_INTERVAL,
        )
        for index, multiplier in enumerate(_E_DETONATION_MULTIPLIERS[:detonations])
    )
    total = sum(part.amount for part in parts)
    entry = damage_entry(
        ability.get("name", "Unraveled Earth"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "magic",
    )
    entry["parts"] = tuple(parts)
    entry["detail"] = (
        f"initial eruption + {detonations} stone detonation"
        f"{'' if detonations == 1 else 's'}"
    )
    return entry


CAST_ORDER = ("E", "W", "Q")
SUPPORTED_FIGHT_MODES = ("one_rotation",)
UNSUPPORTED_FIGHT_MODE_REASON = (
    "Time-based Taliyah calculations are withheld until Worked Ground areas, "
    "overlapping volleys, and repeated knockback opportunities share one "
    "persistent terrain timeline. Use One Rotation."
)
CUSTOM_CAST_ORDER_UNAVAILABLE_REASON = (
    "Taliyah uses the certified E -> W -> Q sequence so Seismic Shove can "
    "detonate the selected number of stones."
)
COMPARISON_CURVE_UNAVAILABLE_REASON = (
    "Crossover windows are withheld until Worked Ground persists between rotations."
)

OPTIONS = [
    {
        "key": "q_ground",
        "type": "select",
        "default": "normal",
        "label": "Threaded Volley terrain",
        "choices": [
            {"value": "normal", "label": "Fresh ground · 5 shards"},
            {"value": "worked", "label": "Worked Ground · boulder"},
        ],
    },
    {
        "key": "e_detonations",
        "type": "int",
        "default": 4,
        "min": 0,
        "max": 4,
        "step": 1,
        "label": "E stones detonated by the target",
    },
    {
        "key": "q_target_distance",
        "type": "float",
        "default": 800.0,
        "min": 0.0,
        "max": 1000.0,
        "step": 50.0,
        "label": "Threaded Volley target distance",
    },
]

ASSUMPTIONS = [
    "Certified mode is one E -> W -> Q sequence against each selected target.",
    "The target is displaced through exactly the selected number of E stones; "
    "successive detonations deal 100%, 75%, 50%, then 25% damage.",
    "Normal Q places all five shards on one target; later shards deal 40%. "
    "Worked Ground instead uses the primary-target 180% boulder hit.",
    "Target distance prices Q projectile travel while Taliyah remains at that "
    "distance for the volley.",
    "Passive and R are excluded because they deal no enemy damage; timed "
    "terrain state is withheld.",
]

SOURCES = [
    {
        "label": "Taliyah — Threaded Volley",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Taliyah/Threaded_Volley",
        "revision_id": 4013247,
        "revision_timestamp": "2026-04-28T21:36:23Z",
    },
    {
        "label": "Taliyah — Seismic Shove",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Taliyah/Seismic_Shove",
        "revision_id": 4028078,
        "revision_timestamp": "2026-06-13T15:07:57Z",
    },
    {
        "label": "Taliyah — Unraveled Earth",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Taliyah/Unraveled_Earth",
        "revision_id": 3985881,
        "revision_timestamp": "2026-01-21T21:34:03Z",
    },
    {
        "label": "Taliyah — Rock Surfing",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Taliyah/Rock_Surfing",
        "revision_id": 3986175,
        "revision_timestamp": "2026-01-22T03:05:54Z",
    },
    {
        "label": "Taliyah — Weaver's Wall",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Taliyah/Weaver's_Wall",
        "revision_id": 4008075,
        "revision_timestamp": "2026-04-13T05:20:02Z",
    },
]

SLOTS = {"E": _unraveled_earth, "W": _seismic_shove, "Q": _threaded_volley}

parse_abilities = build_parser(SLOTS, "Taliyah")


# Authoritative review metadata (issue #161).
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
