"""Vi — sourced one-rotation damage and Denting Blows ordering.

The certified sequence is Q -> E -> R. Q and the primary-target E attack
each apply one Denting Blows stack. When either hit consumes the third stack,
the passive damage is priced at the target's old armor and its 20% armor
reduction is applied only to later hits. E is represented as the attack it
modifies on the primary target and as cone damage on secondary roster targets.

Timed fights walk W's stack cycle over the merged hit stream (Braum-pattern
module walk): ambient autos plus Q hits — E's empowered attacks ride the
ambient stream itself, so they are already counted as the swings they
consume, and only with no stream do E casts force their own attacks.  An
autos-only fight casts nothing, so its stream is the ambient swings.  Stacks
expire 4 seconds after the last application, every third hit procs the
%max-health damage as an authored exact event, and the 20% shred is carried
as a 4-second ``target_debuff`` on the first ranked cast slot (Q, else E)
whenever the walk procs at least once.
"""

import math
from typing import Any

from ..ability_spec import DamagePart
from ..damage import effective_cooldown
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
_W_STACK_DURATION = 4.0  # stacks expire this long after the last application

# Hit kinds for the timed Denting Blows stream; ability hits sort before
# ambient attacks on equal timestamps (the rotation leads the fight model).
_ABILITY_HIT = 0
_ATTACK = 1

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
    requested_distance = max(0.0, float(ctx.option("q_dash_distance")))
    distance = min(requested_distance, allowed_range)
    speed = _Q_MIN_SPEED + (_Q_MAX_SPEED - _Q_MIN_SPEED) * fraction
    return fraction, distance, speed, charge + distance / speed


def _is_primary_target(ctx: SlotCtx) -> bool:
    return int(ctx.target_stat("roster_target_index")) == 0


def _w_trigger_slot(ctx: SlotCtx) -> str | None:
    """Which hit consumes W in the certified Q -> E sequence, if any."""
    if ctx.rank_for("W") < 1:
        return None
    stacks = int(
        _clamp(
            float(ctx.option("denting_blows_starting_stacks")),
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


def _w_percent(ctx: SlotCtx) -> float:
    """W's sourced %max-health per proc, including the bonus-AD scaling."""
    ability = ctx.ability("W")
    if ability is None:
        raise ValueError("Vi W data is unavailable")
    rank = ctx.rank_for("W")
    base_percent = extract_value(ability, "Bonus Physical Damage", rank)
    per_100_bonus_ad = extract_value(
        ability, "Bonus Physical Damage", rank, modifier_index=1
    )
    return base_percent + per_100_bonus_ad * float(ctx.stat("bonus_attack_damage")) / (
        100.0
    )


def _w_shred_debuff() -> dict[str, float]:
    """W's sourced armor shred as a fight-engine ``target_debuff``."""
    return {
        "armor_reduction_percent": _W_ARMOR_REDUCTION_PERCENT,
        "duration": _W_DEBUFF_DURATION,
    }


def _w_proc(ctx: SlotCtx, hit_time: float) -> dict[str, Any]:
    ability = ctx.ability("W")
    if ability is None:
        raise ValueError("Vi W data is unavailable")
    max_health = float(ctx.target_stat("target_max_health"))
    percent = _w_percent(ctx)
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
        "target_debuff": _w_shred_debuff(),
        "detail": (
            f"third stack: {percent:g}% target max HP, then "
            f"{_W_ARMOR_REDUCTION_PERCENT:g}% armor reduction"
        ),
    }


def _timed_window(ctx: SlotCtx) -> float | None:
    """The injected fight window, or ``None`` in one-rotation mode."""
    duration = ctx.options.get("fight_duration_seconds")
    return None if duration is None else float(duration)


def _timed_cast_starts(ctx: SlotCtx, duration: float) -> dict[str, list[float]]:
    """Q/E cast start times, mirroring the engine's shared-hands schedule.

    One set of hands: Q's charge occupies its cast time, each ability
    recasts when its cooldown — running from the end of the cast — is
    back up and no other cast is in progress, ties break by cast order,
    and a cast counts if it starts within the fight window
    (``damage._schedule_shared_casts``).  Item cooldown modifiers (Navori
    refunds, Actualizer) and mana exhaustion are not mirrored, matching
    the Braum-pattern walk's approximation.
    """
    haste = ctx.stat("ability_haste") + ctx.stat("basic_ability_haste")
    keys: list[str] = []
    cast_times: dict[str, float] = {}
    cooldowns: dict[str, float] = {}
    q_ability = ctx.ability("Q")
    if q_ability is not None and ctx.rank_for("Q") >= 1:
        keys.append("Q")
        cast_times["Q"] = _clamp(
            float(ctx.option("q_charge_seconds")), 0.0, _Q_MAX_CHARGE_SECONDS
        )
        cooldowns["Q"] = effective_cooldown(
            extract_cooldown(q_ability, ctx.rank_for("Q")), haste
        )
    e_ability = ctx.ability("E")
    if e_ability is not None and ctx.rank_for("E") >= 1:
        keys.append("E")
        cast_times["E"] = 0.0
        cooldowns["E"] = effective_cooldown(
            extract_recharge(e_ability, ctx.rank_for("E")), haste
        )

    times: dict[str, list[float]] = {key: [] for key in keys}
    next_ready = dict.fromkeys(keys, 0.0)
    pending = set(keys)
    now = 0.0
    while pending and now <= duration + 1e-9:
        ready = [
            key for key in keys if key in pending and next_ready[key] <= now + 1e-9
        ]
        if not ready:
            now = min(next_ready[key] for key in pending)
            continue
        key = ready[0]
        times[key].append(now)
        if cooldowns[key] <= 0:
            pending.remove(key)
        else:
            next_ready[key] = now + cast_times[key] + cooldowns[key]
        now += cast_times[key]
    return times


def _denting_stream(ctx: SlotCtx, duration: float) -> list[tuple[float, int]]:
    """Vi's stack-applying hits on this target over a timed fight.

    Ambient autos land at ``i / rate`` with ``rate = attack_speed x
    auto_attack_uptime``; Q hits land at each cast start plus the charge
    and travel time and stack every enemy in Q's path.  E's empowered
    attack consumes an ambient swing (the engine models attack resets as
    spending attack-cooldown dead time), so with a stream it is already
    one of the counted autos; with no stream each E cast forces its own
    attack on the primary target only.  An ``auto_attacks_only`` window
    schedules no casts at all, so the stream is the ambient swings alone.
    """
    events: list[tuple[float, int]] = []
    rate = ctx.stat("attack_speed") * float(ctx.option("auto_attack_uptime"))
    if rate > 0:
        events.extend(
            (index / rate, _ATTACK) for index in range(math.floor(rate * duration))
        )
    if not ctx.option("auto_attacks_only"):
        starts = _timed_cast_starts(ctx, duration)
        q_hit_offset = _q_geometry(ctx)[3]
        events.extend(
            (start + q_hit_offset, _ABILITY_HIT) for start in starts.get("Q", ())
        )
        if rate <= 0 and _is_primary_target(ctx):
            events.extend((start, _ABILITY_HIT) for start in starts.get("E", ()))
    events.sort()
    return events


def _denting_blows_timed(ctx: SlotCtx) -> dict[str, Any] | None:
    """W: walk the merged hit stream through stack -> proc -> reset cycles.

    Each counted hit adds a stack (stacks reset when 4s pass without an
    application); the third consumes them all, dealing the %max-health
    physical damage at that hit's time.  ``denting_blows_starting_stacks``
    seeds the counter at t=0.  One-rotation mode emits nothing — Q/E carry
    the proc there — and a window whose stream never completes a cycle
    emits nothing rather than a fractional proc.
    """
    ability = ctx.ability()
    if ability is None:
        return None
    duration = _timed_window(ctx)
    if duration is None or ctx.rank_for("W") < 1:
        return None

    stacks = int(_clamp(float(ctx.option("denting_blows_starting_stacks")), 0.0, 2.0))
    last_application = 0.0 if stacks else None
    proc_times: list[float] = []
    for time, _kind in _denting_stream(ctx, duration):
        if last_application is not None and time - last_application > (
            _W_STACK_DURATION
        ):
            stacks = 0
        stacks += 1
        last_application = time
        if stacks >= _W_STACKS_REQUIRED:
            proc_times.append(time)
            stacks = 0
            last_application = None
    if not proc_times:
        return None

    percent = _w_percent(ctx)
    raw = float(ctx.target_stat("target_max_health")) * percent / 100.0
    procs = len(proc_times)
    return {
        "name": ability.get("name", "Denting Blows"),
        "damage_type": "physical",
        "total_raw": raw * procs,
        "parts": (DamagePart("physical", raw),),
        "proc_count": procs,
        "damage_events": [
            {
                "time": time,
                "damage_type": "physical",
                "damage": raw,
                "event_precision": "exact",
            }
            for time in proc_times
        ],
        "event_phase": "effect",
        "target_max_health_sensitive": True,
        "unit": "procs",
        "detail": (
            f"{procs} third-stack proc(s) ({percent:g}% target max HP each) "
            f"over {duration:g}s"
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
    if _timed_window(ctx) is not None:
        # The timed walk owns W's procs; when it procced at least once
        # ("W" is in the results — the walk runs first in the slot map),
        # Q carries the 4-second shred windows at its cast times.
        if "W" in ctx.results:
            entry["target_debuff"] = _w_shred_debuff()
    elif _w_trigger_slot(ctx) == "Q":
        entry["post_hit_proc"] = _w_proc(ctx, hit_time)
        entry["target_max_health_sensitive"] = True
    return entry


def _e_hit_time(ctx: SlotCtx) -> float:
    q_time = _q_geometry(ctx)[3] if ctx.rank_for("Q") > 0 else 0.0
    delay = _clamp(
        float(ctx.option("e_attack_delay")),
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
    total_ad = float(ctx.stat("attack_damage"))
    ability_power = float(ctx.stat("ability_power"))
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
        if _timed_window(ctx) is None and _w_trigger_slot(ctx) == "E":
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
    if _timed_window(ctx) is not None and "W" in ctx.results and "Q" not in ctx.results:
        # Fallback shred carrier when Q is unranked: the walk's procs
        # still shred, anchored at E's cast times.
        entry["target_debuff"] = _w_shred_debuff()
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
        float(ctx.option("r_start_distance")),
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
CUSTOM_CAST_ORDER_UNAVAILABLE_REASON = (
    "Vi uses the certified Q -> E -> R sequence; custom cast orders are not "
    "available yet."
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
    "One-rotation mode is one Q -> E -> R rotation with the certified "
    "stack ordering; timed mode walks W's stack cycle over the fight's "
    "merged hit stream",
    "Every selected enemy is in Q's path, E's cone, and R's path; enemy 1 is "
    "the primary E/R target",
    "Q and primary-target E each add one W stack; E secondary targets do not",
    "In one rotation, W proc damage uses pre-shred armor, then later hits "
    "use 20% reduced armor",
    "Timed W stacks come from ambient autos and Q hits (E's empowered "
    "attacks consume ambient swings, so they are counted as those swings; "
    "with no auto stream each E cast forces one attack); stacks expire 4s "
    "after the last application, and Q/E are assumed cast on cooldown from "
    "t=0 on one shared cast timeline without item cooldown modifiers or "
    "mana exhaustion",
    "An autos-only fight casts nothing, so only the ambient swings stack "
    "(the pipeline states this with the auto_attacks_only reserved "
    "option) and no cast carries the shred window",
    "Timed W procs are priced against the fight's static target max health "
    "and the 20% shred is time-weighted over 4s windows anchored at the "
    "carrier ability's cast times (Q, else E) — the engine anchors shred "
    "windows to casts, not procs",
    "W's 30-50% attack-speed steroid after a proc is not modeled "
    "(conservative in both modes)",
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

# W runs first: Q/E read its presence in ctx.results to decide whether
# the timed shred has a proc to anchor to.
SLOTS = {
    "W": _denting_blows_timed,
    "Q": _vault_breaker,
    "E": _relentless_force,
    "R": _cease_and_desist,
}

# Reviewed crowd control, read from the cached kit.  Q (Vault Breaker)
# "stops upon hitting an enemy champion, knocking them back over 0.75
# seconds" — the pull in the same sentence reaches "all non-champions
# hit".  E (Relentless Force) is the empowered blast, with no control
# clause.  R (Cease and Desist) grabs the singled-out champion, "knocking
# them up for 1.3 seconds and dealing physical damage after 0.75 seconds
# into the grab duration".  W (Denting Blows) is armour reduction, which
# is not crowd control, and it is the auto-stack row besides.
MODULE_CC = {"Q": "knockback", "E": "none", "R": "knockup"}

parse_abilities = build_parser(SLOTS, "Vi", cc_kinds=MODULE_CC)


# Authoritative review metadata (issue #161).
MODULE_COVERAGE = {
    slot: ("modeled" if slot in SLOTS else "out_of_scope") for slot in "PQWER"
}
REVIEW_STATUS = "reviewed_module"
