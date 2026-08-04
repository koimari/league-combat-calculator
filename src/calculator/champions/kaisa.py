"""Kai'Sa — sourced isolated-target Q/W and ordered Plasma rupture.

The certified sequence deliberately waits for Void Seeker and its Plasma
applications to resolve before casting Icathian Rain. This keeps every damage
event in one unambiguous order without pretending the current engine models
Supercharge's timed attack-speed window or Killer Instinct's attack reset.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    find_named_leveling,
    sum_modifiers,
)

_Q_FIRST_HIT_DELAY = 0.4
_Q_VOLLEY_DURATION = 1.0
_Q_NORMAL_MISSILES = 6
_Q_EVOLVED_MISSILES = 12
_W_CAST_TIME = 0.4
_W_MISSILE_SPEED = 1750.0
_W_MAX_RANGE = 3000.0
_W_NORMAL_STACKS = 2
_W_EVOLVED_STACKS = 3
_PLASMA_STACKS_TO_RUPTURE = 5
_RUPTURE_BASE_MISSING_HEALTH_RATIO = 0.15
_RUPTURE_RATIO_PER_AP = 0.0006
_EVOLUTION_THRESHOLD = 100.0


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def _plasma_values(ctx: SlotCtx) -> tuple[float, float]:
    passive = ctx.ability("P")
    if passive is None:
        raise ValueError("Kai'Sa passive data is unavailable")
    base = find_named_leveling(passive, "Bonus Magic Damage", occurrence=0)
    per_prior_stack = find_named_leveling(passive, "Bonus Magic Damage", occurrence=1)
    if base is None or per_prior_stack is None:
        raise ValueError("Kai'Sa Plasma damage arrays are unavailable")
    return (
        sum_modifiers(base, ctx.level, ctx.stats, ctx.target),
        sum_modifiers(per_prior_stack, ctx.level, ctx.stats, ctx.target),
    )


def _w_hit_time(ctx: SlotCtx) -> tuple[float, float]:
    """Return clamped W distance and time from cast start to impact."""
    distance = _clamp(
        float(ctx.options.get("w_target_distance", 800.0)),
        0.0,
        _W_MAX_RANGE,
    )
    return distance, _W_CAST_TIME + distance / _W_MISSILE_SPEED


def _evolution_state(
    ctx: SlotCtx,
    option_key: str,
    stat_key: str,
    stat_label: str,
) -> tuple[bool, str]:
    """Resolve Auto/Base/Evolved while accepting old shared-link booleans."""
    selected = ctx.options.get(option_key, "auto")
    if isinstance(selected, bool):
        return selected, "shared-link override"
    if selected == "evolved":
        return True, "forced evolved"
    if selected == "base":
        return False, "forced not evolved"
    if selected != "auto":
        raise ValueError(f"Kai'Sa {option_key} must be auto, base, or evolved")
    owned = float(ctx.stats.get(stat_key, 0.0))
    return (
        owned >= _EVOLUTION_THRESHOLD,
        f"automatic: {owned:.1f}/{_EVOLUTION_THRESHOLD:g} {stat_label}",
    )


def _plasma_proc(ctx: SlotCtx, hit_time: float) -> dict[str, Any]:
    base, per_prior_stack = _plasma_values(ctx)
    stacks = int(
        _clamp(
            float(ctx.options.get("plasma_starting_stacks", 0)),
            0.0,
            float(_PLASMA_STACKS_TO_RUPTURE - 1),
        )
    )
    w_evolved, evolution_note = _evolution_state(
        ctx,
        "w_evolved",
        "evolution_ability_power",
        "item AP",
    )
    applications = _W_EVOLVED_STACKS if w_evolved else _W_NORMAL_STACKS
    target_health = float(ctx.target.get("target_max_health", 0.0))
    ability_power = float(ctx.stats.get("ability_power", 0.0))
    rupture_ratio = (
        _RUPTURE_BASE_MISSING_HEALTH_RATIO + _RUPTURE_RATIO_PER_AP * ability_power
    )
    parts: list[DamagePart] = []
    ruptures = 0
    for _ in range(applications):
        parts.append(
            DamagePart(
                "magic",
                base + per_prior_stack * stacks,
                time_offset=hit_time,
            )
        )
        stacks += 1
        if stacks == _PLASMA_STACKS_TO_RUPTURE:
            parts.append(
                DamagePart(
                    "magic",
                    hp_scaled_damage=(
                        lambda missing_ratio, live_target_max_health=None, ratio=rupture_ratio, baseline_target_health=target_health: (
                            (
                                baseline_target_health
                                if live_target_max_health is None
                                else live_target_max_health
                            )
                            * missing_ratio
                            * ratio
                        )
                    ),
                    time_offset=hit_time,
                )
            )
            ruptures += 1
            stacks = 0

    return {
        "name": "Second Skin (Plasma)",
        "breakdown_key": "passive_plasma",
        "parts": tuple(parts),
        "detail": (
            f"{applications} successive stack applications"
            + (f"; {ruptures} rupture" if ruptures else "")
            + f"; {evolution_note}"
        ),
    }


def _void_seeker(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    raw = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    distance, hit_time = _w_hit_time(ctx)
    entry = damage_entry(
        ability.get("name", "Void Seeker"),
        rank,
        extract_cooldown(ability, rank),
        raw,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", raw, time_offset=hit_time),)
    # The certified rotation waits for W to hit before starting Q. Treating
    # the travel as occupied sequence time makes that deliberate wait explicit.
    entry["cast_time"] = hit_time
    entry["post_hit_proc"] = _plasma_proc(ctx, hit_time)
    entry["target_max_health_sensitive"] = True
    entry["detail"] = f"hit at {distance:g} range; Plasma resolves afterwards"
    return entry


def _icathian_rain(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    evolved, evolution_note = _evolution_state(
        ctx,
        "q_evolved",
        "evolution_attack_damage",
        "AD from items + growth",
    )
    missiles = _Q_EVOLVED_MISSILES if evolved else _Q_NORMAL_MISSILES
    first = extract_named(
        ability, "Physical Damage Per Missile", rank, ctx.stats, ctx.target
    )
    reduced = extract_named(
        ability, "Reduced Damage Per Missile", rank, ctx.stats, ctx.target
    )
    total_attr = (
        "Total Evolved Single-Target Damage"
        if evolved
        else "Total Single-Target Damage"
    )
    total = extract_named(ability, total_attr, rank, ctx.stats, ctx.target)
    interval = _Q_VOLLEY_DURATION / (missiles - 1)
    # One-rotation cast timestamps are nominally all zero in the shared
    # engine. This module authors the deliberate W-impact wait directly into
    # Q's hit offsets so the damage ledger still reflects W -> Plasma -> Q.
    _, q_start = _w_hit_time(ctx)
    first_hit = q_start + _Q_FIRST_HIT_DELAY
    entry = damage_entry(
        ability.get("name", "Icathian Rain"),
        rank,
        extract_cooldown(ability, rank),
        total,
        "physical",
    )
    entry["parts"] = (
        DamagePart("physical", first, time_offset=first_hit),
        DamagePart(
            "physical",
            reduced,
            count=missiles - 1,
            time_offset=first_hit + interval,
            hit_interval=interval,
        ),
    )
    entry["detail"] = (
        f"{missiles} missiles on one isolated target"
        + (" (evolved)" if evolved else "")
        + f"; {evolution_note}"
    )
    return entry


CAST_ORDER = ("W", "Q")
SUPPORTED_FIGHT_MODES = ("one_rotation",)
UNSUPPORTED_FIGHT_MODE_REASON = (
    "Time-based Kai'Sa calculations are withheld until Supercharge's "
    "four-second attack-speed window, on-attack cooldown refunds, Killer "
    "Instinct's attack reset, and Plasma all share one attack timeline. "
    "Use One Rotation."
)
CUSTOM_CAST_ORDER_UNAVAILABLE_REASON = (
    "Kai'Sa uses the certified W -> Q sequence so Plasma resolves before the "
    "volley; custom cast orders are not available yet."
)
COMPARISON_CURVE_UNAVAILABLE_REASON = (
    "Crossover windows are withheld for Kai'Sa until Plasma stacks persist "
    "correctly between rotations."
)

OPTIONS = [
    {
        "key": "q_evolved",
        "type": "select",
        "default": "auto",
        "label": "Icathian Rain evolution",
        "legacy_bool": True,
        "choices": [
            {"value": "auto", "label": "Automatic from build"},
            {"value": "base", "label": "Not evolved"},
            {"value": "evolved", "label": "Evolved"},
        ],
    },
    {
        "key": "w_evolved",
        "type": "select",
        "default": "auto",
        "label": "Void Seeker evolution",
        "legacy_bool": True,
        "choices": [
            {"value": "auto", "label": "Automatic from build"},
            {"value": "base", "label": "Not evolved"},
            {"value": "evolved", "label": "Evolved"},
        ],
    },
    {
        "key": "plasma_starting_stacks",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 4,
        "step": 1,
        "label": "Plasma stacks already on each target",
    },
    {
        "key": "w_target_distance",
        "type": "float",
        "default": 800.0,
        "min": 0.0,
        "max": 3000.0,
        "step": 50.0,
        "label": "Void Seeker target distance",
    },
]

ASSUMPTIONS = [
    "Certified mode is one W -> Q rotation; Kai'Sa waits for W and Plasma to "
    "resolve before casting Q",
    "Every Q missile hits one isolated selected target; shared targets would "
    "split the volley",
    "Q/W evolutions follow permanent item stats and level growth automatically; "
    "the selector can reproduce a not-yet-evolved or forced test state",
    "W applies each Plasma stack successively; a fifth-stack rupture uses "
    "health remaining after W and the preceding Caustic Wounds hit",
    "E and R deal no enemy damage and are excluded; timed attacks are withheld",
]

SOURCES = [
    {
        "label": "Kai'Sa — Second Skin",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Kai'Sa/Second_Skin",
        "revision_id": 4046579,
        "revision_timestamp": "2026-07-28T19:58:33Z",
    },
    {
        "label": "Kai'Sa — Icathian Rain",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Kai'Sa/Icathian_Rain",
        "revision_id": 4038389,
        "revision_timestamp": "2026-06-30T09:21:59Z",
    },
    {
        "label": "Kai'Sa — Void Seeker",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Kai'Sa/Void_Seeker",
        "revision_id": 4034696,
        "revision_timestamp": "2026-06-23T21:14:14Z",
    },
    {
        "label": "Kai'Sa — Supercharge",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Kai'Sa/Supercharge",
        "revision_id": 4038391,
        "revision_timestamp": "2026-06-30T09:23:49Z",
    },
    {
        "label": "Kai'Sa — Killer Instinct",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Kai'Sa/Killer_Instinct",
        "revision_id": 4034697,
        "revision_timestamp": "2026-06-23T21:14:22Z",
    },
]

SLOTS = {"W": _void_seeker, "Q": _icathian_rain}

parse_abilities = build_parser(SLOTS, "Kai'Sa")
