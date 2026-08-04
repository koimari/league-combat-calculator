"""Vi — sourced one-rotation damage and Denting Blows ordering.

The certified sequence is Q -> E -> R. Q and the primary-target E attack
each apply one Denting Blows stack. When either hit consumes the third stack,
the passive damage is priced at the target's old armor and its 20% armor
reduction is applied only to later hits. E is represented as the attack it
modifies on the primary target and as cone damage on secondary roster targets.

Timed fights fail closed in :mod:`calculator.pipeline` until ability casts,
attack resets, ambient attacks, W stack expiry, and W's four-second attack-
speed/shred windows share one event ledger.
"""

from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import (
    damage_entry,
    extract_cooldown,
    extract_named,
    extract_recharge,
    extract_value,
)

_Q_MAX_CHARGE_SECONDS = 1.25
_Q_MIN_RANGE = 250.0
_Q_MAX_RANGE = 725.0
_Q_MIN_SPEED = 1450.0
_Q_MAX_SPEED = 1540.0
_Q_MAX_BONUS_MULTIPLIER = 1.5

_W_STACKS_REQUIRED = 3
_W_ARMOR_REDUCTION_PERCENT = 20.0
_W_DEBUFF_DURATION = 4.0

_R_CAST_TIME = 0.25
_R_GRAB_DAMAGE_DELAY = 0.75
_R_GRAB_RANGE = 300.0
_R_INITIAL_SPEED = 800.0


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def _q_geometry(ctx: SlotCtx) -> tuple[float, float, float, float]:
    """Return charge fraction, clamped distance, speed, and hit time."""
    charge = _clamp(
        float(ctx.options.get("q_charge_seconds", _Q_MAX_CHARGE_SECONDS)),
        0.0,
        _Q_MAX_CHARGE_SECONDS,
    )
    fraction = charge / _Q_MAX_CHARGE_SECONDS
    allowed_range = _Q_MIN_RANGE + (_Q_MAX_RANGE - _Q_MIN_RANGE) * fraction
    requested_distance = max(0.0, float(ctx.options.get("q_dash_distance", 725.0)))
    distance = min(requested_distance, allowed_range)
    speed = _Q_MIN_SPEED + (_Q_MAX_SPEED - _Q_MIN_SPEED) * fraction
    return fraction, distance, speed, charge + distance / speed


def _is_primary_target(ctx: SlotCtx) -> bool:
    return int(ctx.target.get("roster_target_index", 0.0)) == 0


def _w_trigger_slot(ctx: SlotCtx) -> str | None:
    """Which hit consumes W in the certified Q -> E sequence, if any."""
    if ctx.rank_for("W") < 1:
        return None
    stacks = int(
        _clamp(
            float(ctx.options.get("denting_blows_starting_stacks", 0)),
            0.0,
            2.0,
        )
    )
    if ctx.rank_for("Q") > 0:
        stacks += 1
        if stacks >= _W_STACKS_REQUIRED:
            return "Q"
    stacks %= _W_STACKS_REQUIRED
    if ctx.rank_for("E") > 0 and _is_primary_target(ctx):
        stacks += 1
        if stacks >= _W_STACKS_REQUIRED:
            return "E"
    return None


def _w_proc(ctx: SlotCtx, hit_time: float) -> dict[str, Any]:
    ability = ctx.ability("W")
    if ability is None:
        raise ValueError("Vi W data is unavailable")
    rank = ctx.rank_for("W")
    base_percent = extract_value(ability, "Bonus Physical Damage", rank)
    per_100_bonus_ad = extract_value(
        ability, "Bonus Physical Damage", rank, modifier_index=1
    )
    bonus_ad = float(ctx.stats.get("bonus_attack_damage", 0.0))
    max_health = float(ctx.target.get("target_max_health", 0.0))
    percent = base_percent + per_100_bonus_ad * bonus_ad / 100.0
    raw = max_health * percent / 100.0

    def max_health_damage(
        _missing_ratio: float,
        live_target_max_health: float | None = None,
    ) -> float:
        live_max = (
            max_health if live_target_max_health is None else live_target_max_health
        )
        return live_max * percent / 100.0

    return {
        "name": ability.get("name", "Denting Blows"),
        "breakdown_key": "passive_proc_W",
        "parts": (
            DamagePart(
                "physical",
                raw,
                hp_scaled_damage=max_health_damage,
                time_offset=hit_time,
            ),
        ),
        "target_debuff": {
            "armor_reduction_percent": _W_ARMOR_REDUCTION_PERCENT,
            "duration": _W_DEBUFF_DURATION,
        },
        "detail": (
            f"third stack: {percent:g}% target max HP, then "
            f"{_W_ARMOR_REDUCTION_PERCENT:g}% armor reduction"
        ),
    }


def _vault_breaker(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    minimum = extract_named(
        ability, "Minimum Physical Damage", rank, ctx.stats, ctx.target
    )
    fraction, distance, speed, hit_time = _q_geometry(ctx)
    multiplier = 1.0 + _Q_MAX_BONUS_MULTIPLIER * fraction
    raw = minimum * multiplier
    entry = damage_entry(
        ability.get("name", "Vault Breaker"),
        rank,
        extract_cooldown(ability, rank),
        raw,
        "physical",
    )
    entry["cast_time"] = fraction * _Q_MAX_CHARGE_SECONDS
    entry["parts"] = (DamagePart("physical", raw, time_offset=hit_time),)
    entry["detail"] = (
        f"{fraction * _Q_MAX_CHARGE_SECONDS:.2f}s charge; "
        f"{distance:.0f} range at {speed:.0f} speed"
    )
    if _w_trigger_slot(ctx) == "Q":
        entry["post_hit_proc"] = _w_proc(ctx, hit_time)
        entry["target_max_health_sensitive"] = True
    return entry


def _e_hit_time(ctx: SlotCtx) -> float:
    q_time = _q_geometry(ctx)[3] if ctx.rank_for("Q") > 0 else 0.0
    delay = _clamp(
        float(ctx.options.get("e_attack_delay", 0.25)),
        0.0,
        2.0,
    )
    return q_time + delay


def _relentless_force(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    flat = extract_value(ability, "Physical Damage", rank)
    total_ad = float(ctx.stats.get("attack_damage", 0.0))
    ability_power = float(ctx.stats.get("ability_power", 0.0))
    hit_time = _e_hit_time(ctx)
    primary = _is_primary_target(ctx)

    if primary:
        # The engine supplies the 100% total-AD basic swing. This part is
        # only E's non-basic rider: flat + 10% total AD + 100% AP.
        rider = flat + 0.10 * total_ad + ability_power
        entry = damage_entry(
            ability.get("name", "Relentless Force"),
            rank,
            extract_recharge(ability, rank),
            rider,
            "physical",
        )
        entry["parts"] = (DamagePart("physical", rider, time_offset=hit_time),)
        entry["empowers_next_auto"] = {
            "authored_timing": {
                "first_attack_delay": hit_time,
                "attack_interval": 1.0,
            }
        }
        entry["applies_item_on_hits"] = {
            "effectiveness": 1.0,
            "hits": 1,
            "triggers": ("on_hit", "on_attack"),
        }
        entry["detail"] = "primary empowered attack (attack reset)"
        if _w_trigger_slot(ctx) == "E":
            entry["post_hit_proc"] = _w_proc(ctx, hit_time)
            entry["target_max_health_sensitive"] = True
    else:
        # Secondary cone targets take the same modified physical formula,
        # cannot be critically struck by E, receive no item on-hits, and do
        # not gain a Denting Blows stack.
        raw = flat + 1.10 * total_ad + ability_power
        entry = damage_entry(
            ability.get("name", "Relentless Force"),
            rank,
            extract_recharge(ability, rank),
            raw,
            "physical",
        )
        entry["parts"] = (DamagePart("physical", raw, time_offset=hit_time),)
        entry["detail"] = "secondary cone target; no crit or W stack"
    return entry


def _cease_and_desist(ctx: SlotCtx) -> dict[str, Any] | None:
    ability = ctx.ability()
    if ability is None:
        return None
    rank = ctx.rank_for()
    if rank < 1:
        return None

    raw = extract_named(ability, "Physical Damage", rank, ctx.stats, ctx.target)
    sequence_start = (
        _e_hit_time(ctx)
        if ctx.rank_for("E") > 0
        else (_q_geometry(ctx)[3] if ctx.rank_for("Q") > 0 else 0.0)
    )
    distance = _clamp(
        float(ctx.options.get("r_start_distance", 800.0)),
        _R_GRAB_RANGE,
        800.0,
    )
    approach = max(0.0, distance - _R_GRAB_RANGE) / _R_INITIAL_SPEED
    hit_time = sequence_start + _R_CAST_TIME + approach + _R_GRAB_DAMAGE_DELAY
    entry = damage_entry(
        ability.get("name", "Cease and Desist"),
        rank,
        extract_cooldown(ability, rank),
        raw,
        "physical",
    )
    entry["parts"] = (DamagePart("physical", raw, time_offset=hit_time),)
    entry["detail"] = (
        "primary grab" if _is_primary_target(ctx) else "enemy crossed in R path"
    )
    return entry


CAST_ORDER = ("Q", "E", "R")
SUPPORTED_FIGHT_MODES = ("one_rotation",)
UNSUPPORTED_FIGHT_MODE_REASON = (
    "Time-based Vi calculations are withheld until Denting Blows can be "
    "interleaved with the ambient attack stream. Use One Rotation."
)
CUSTOM_CAST_ORDER_UNAVAILABLE_REASON = (
    "Vi uses the certified Q -> E -> R sequence; custom cast orders are not "
    "available yet."
)
COMPARISON_CURVE_UNAVAILABLE_REASON = (
    "Crossover windows are withheld for Vi until W stacks, attack resets, "
    "and ambient attacks share one timed event ledger."
)

OPTIONS = [
    {
        "key": "q_charge_seconds",
        "type": "float",
        "default": 1.25,
        "min": 0.0,
        "max": 1.25,
        "step": 0.125,
        "label": "Q charge time (seconds)",
    },
    {
        "key": "q_dash_distance",
        "type": "float",
        "default": 725.0,
        "min": 0.0,
        "max": 725.0,
        "step": 25.0,
        "label": "Q distance to target",
    },
    {
        "key": "denting_blows_starting_stacks",
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 2,
        "step": 1,
        "label": "W stacks already on each target",
    },
    {
        "key": "e_attack_delay",
        "type": "float",
        "default": 0.25,
        "min": 0.0,
        "max": 2.0,
        "step": 0.05,
        "label": "Delay from Q hit to E attack",
    },
    {
        "key": "r_start_distance",
        "type": "float",
        "default": 800.0,
        "min": 300.0,
        "max": 800.0,
        "step": 25.0,
        "label": "R starting distance",
    },
]

ASSUMPTIONS = [
    "Certified mode is one Q -> E -> R rotation; time-based Vi is withheld",
    "Every selected enemy is in Q's path, E's cone, and R's path; enemy 1 is "
    "the primary E/R target",
    "Q and primary-target E each add one W stack; E secondary targets do not",
    "W proc damage uses pre-shred armor, then later hits use 20% reduced armor",
    "Blast Shield is defensive only: Q/E may activate its 12% max-health shield, "
    "but it does not change outgoing TDD",
]

SOURCES = [
    {
        "label": "Vi — Blast Shield",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Vi/Blast_Shield",
        "revision_id": 3986701,
        "revision_timestamp": "2026-01-23T00:03:48Z",
    },
    {
        "label": "Vi — Vault Breaker",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Vi/Vault_Breaker",
        "revision_id": 3921391,
        "revision_timestamp": "2025-06-29T22:47:26Z",
    },
    {
        "label": "Vi — Denting Blows",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Vi/Denting_Blows",
        "revision_id": 3932548,
        "revision_timestamp": "2025-07-19T01:58:33Z",
    },
    {
        "label": "Vi — Relentless Force",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Vi/Relentless_Force",
        "revision_id": 3986710,
        "revision_timestamp": "2026-01-23T00:42:37Z",
    },
    {
        "label": "Vi — Cease and Desist",
        "url": "https://wiki.leagueoflegends.com/en-us/Template:Data_Vi/Cease_and_Desist",
        "revision_id": 4004943,
        "revision_timestamp": "2026-04-02T19:30:57Z",
    },
]

SLOTS = {
    "Q": _vault_breaker,
    "E": _relentless_force,
    "R": _cease_and_desist,
}

parse_abilities = build_parser(SLOTS, "Vi")
