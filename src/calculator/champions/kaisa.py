"""Kai'Sa: sourced Q and W, ordered Plasma, and a timed shared timeline.

One-rotation keeps the certified W then Q sequence, so Void Seeker and
its Plasma applications resolve before Icathian Rain and every damage
event stays in one order.  The travel-inclusive W cast time that buys
the wait is confined to that branch; timed casts occupy their real ones.
Timed mode runs the kit on the shared cast timeline.  Plasma stacks
persist across the window on the merged basic-attack and Void Seeker
stream with the sourced 4-second expiry, and the walked ledger rides
Killer Instinct's single timed cast (``post_hit_proc``), the one engine
path that prices the %missing-health ruptures against tracked target
health.  Supercharge's recurring 4-second windows become one average
grant weighted by duration, the swing scheduler being uniform-rate, and
evolved Void Seeker's 75% refund shortens W's recast cadence.
E and R are ``no_damage`` and P has no SLOTS entry: Plasma publishes
``passive_plasma`` through the ``post_hit_proc`` channel, W's in
one-rotation and R's in timed.  R's sourced shield stays an assumption
because the shield ledger rides damage events and R deals none.
"""

import math
from collections.abc import Iterable
from typing import Any

from ..ability_spec import DamagePart
from ..binary_roots import data_value, spell_object
from ..stat_formulas import effective_cooldown
from .contract_vocabulary import coverage
from .engine import BUFF, SlotCtx, build_parser
from .inputs import float_option, int_option
from .module_helpers import clamp, ranked_slot
from .slot_entries import damage_entry
from .slot_extract import (
    ability_name,
    extract_cast_time,
    extract_cooldown,
    extract_named,
    extract_value,
    find_named_leveling,
    sum_modifiers,
)
from .source_receipts import load_champion_sources

_Q_FIRST_HIT_DELAY = 0.4
_Q_VOLLEY_DURATION = 1.0
_Q_NORMAL_MISSILES = 6
_Q_EVOLVED_MISSILES = 12
_W_MISSILE_SPEED = 1750.0
_W_MAX_RANGE = 3000.0
_W_NORMAL_STACKS = 2
_W_EVOLVED_STACKS = 3
_PLASMA_STACKS_TO_RUPTURE = 5
_KAISA_P_SPELL = spell_object("Kai'Sa", "KaisaPassive")
_RUPTURE_BASE_MISSING_HEALTH_RATIO = data_value(_KAISA_P_SPELL, "PExecuteRatio")
_RUPTURE_RATIO_PER_AP = data_value(_KAISA_P_SPELL, "PExecuteAPRatio")
_EVOLUTION_THRESHOLD = 100.0
# HARDCODED: verify on patch updates — these live in cached description
# prose (data/champions.json Kaisa P effect[1], W effect[1], E effects
# [0]-[2]), not in leveling arrays:
# - Plasma stacks last 4s, refreshing on application.
# - Evolved Void Seeker refunds 75% of its cooldown on champion hit.
# - Supercharge grants its bonus attack speed for 4s after the charge, its
#   current cooldown drops 0.5s on-attack, and the charge (castTime
#   "1.2 : 0.6 (based on bonus attack speed)") scales 1.2s -> 0.6s over
#   0-100% bonus attack speed.
_PLASMA_STACK_DURATION = data_value(_KAISA_P_SPELL, "PDuration")
_W_EVOLVED_COOLDOWN_REFUND = 0.75
_E_WINDOW_SECONDS = 4.0
_E_ATTACK_CD_REFUND_SECONDS = 0.5
_E_CHARGE_TIME_MAX = 1.2
_E_CHARGE_TIME_MIN = 0.6

# Plasma application stream kinds; W applications sort before basic attacks
# on equal timestamps (casts lead the fight model, as in damage.py).
_W_HIT = 0
_AUTO_HIT = 1


def _timed_window(ctx: SlotCtx) -> tuple[float, float] | None:
    """(duration, auto uptime) for a timed parse; None in one-rotation.

    The pipeline injects ``fight_duration_seconds`` only for timed fights.
    """
    duration = ctx.options.get("fight_duration_seconds")
    if duration is None or float(duration) <= 0:
        return None
    return float(duration), float(ctx.option("auto_attack_uptime"))


def _basic_ability_haste(ctx: SlotCtx) -> float:
    return ctx.stat("ability_haste") + ctx.stat("basic_ability_haste")


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
    distance = clamp(
        float(ctx.option("w_target_distance")),
        0.0,
        _W_MAX_RANGE,
    )
    return distance, extract_cast_time(ctx.ability("W")) + distance / _W_MISSILE_SPEED


def _evolution_state(
    ctx: SlotCtx,
    option_key: str,
    stat_key: str,
    stat_label: str,
) -> tuple[bool, str]:
    """Resolve Auto/Base/Evolved while accepting old shared-link booleans."""
    selected = ctx.option(option_key)
    if isinstance(selected, bool):
        return selected, "shared-link override"
    if selected == "evolved":
        return True, "forced evolved"
    if selected == "base":
        return False, "forced not evolved"
    if selected != "auto":
        raise ValueError(f"Kai'Sa {option_key} must be auto, base, or evolved")
    owned = float(ctx.stat(stat_key))
    return (
        owned >= _EVOLUTION_THRESHOLD,
        f"automatic: {owned:.1f}/{_EVOLUTION_THRESHOLD:g} {stat_label}",
    )


def _rupture_part(
    rupture_ratio: float, baseline_target_health: float, hit_time: float
) -> DamagePart:
    """One fifth-stack rupture: %missing-health magic damage at ``hit_time``."""

    def rupture_damage(
        missing_ratio: float, live_target_max_health: float | None = None
    ) -> float:
        health = (
            baseline_target_health
            if live_target_max_health is None
            else live_target_max_health
        )
        return health * missing_ratio * rupture_ratio

    return DamagePart("magic", hp_scaled_damage=rupture_damage, time_offset=hit_time)


def _rupture_ratio(ctx: SlotCtx) -> float:
    """Missing-health share one rupture deals: 15% + 6% per 100 AP."""
    return _RUPTURE_BASE_MISSING_HEALTH_RATIO + _RUPTURE_RATIO_PER_AP * float(
        ctx.stat("ability_power")
    )


def _seeded_stacks(ctx: SlotCtx) -> int:
    """The user's pre-fight Plasma stacks, clamped below the rupture count."""
    return int(
        clamp(
            float(ctx.option("plasma_starting_stacks")),
            0.0,
            float(_PLASMA_STACKS_TO_RUPTURE - 1),
        )
    )


def _plasma_proc(ctx: SlotCtx, hit_time: float) -> dict[str, Any]:
    base, per_prior_stack = _plasma_values(ctx)
    stacks = _seeded_stacks(ctx)
    w_evolved, evolution_note = _evolution_state(
        ctx,
        "w_evolved",
        "evolution_ability_power",
        "item AP",
    )
    applications = _W_EVOLVED_STACKS if w_evolved else _W_NORMAL_STACKS
    target_health = float(ctx.target_stat("target_max_health"))
    rupture_ratio = _rupture_ratio(ctx)
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
            parts.append(_rupture_part(rupture_ratio, target_health, hit_time))
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


def _w_timed_base_cooldown(base_cooldown: float, w_evolved: bool) -> float:
    """W's timed recast cooldown pre-haste: evolved refunds 75% on hit."""
    if w_evolved:
        return base_cooldown * (1.0 - _W_EVOLVED_COOLDOWN_REFUND)
    return base_cooldown


def _plasma_application_stream(
    ctx: SlotCtx, duration: float, uptime: float, w_evolved: bool
) -> list[tuple[float, int]]:
    """Every Plasma stack application in the fight window, in hit order.

    Mirrors the engine's timed cadence: basic attacks land at ``i / rate``
    with ``rate = attack_speed x uptime`` (the parse-context attack speed
    already carries Supercharge's window-weighted grant), and Void Seeker
    is cast at t=0 then on its effective cooldown (haste, plus the evolved
    75% on-hit refund), each hit applying its 2-3 stacks at the travel-
    delayed impact time.
    """
    events: list[tuple[float, int]] = []

    rate = ctx.stat("attack_speed") * uptime
    if rate > 0:
        count = math.floor(ctx.stat("attack_speed") * duration * uptime)
        events.extend((index / rate, _AUTO_HIT) for index in range(count))

    w_ability = ctx.ability("W")
    w_rank = ctx.rank_for("W")
    if w_ability is not None and w_rank >= 1:
        cooldown = effective_cooldown(
            _w_timed_base_cooldown(extract_cooldown(w_ability, w_rank), w_evolved),
            _basic_ability_haste(ctx),
        )
        _, hit_delay = _w_hit_time(ctx)
        # The cooldown runs from the end of W's cached cast on the shared
        # timeline, so the recast period includes it.
        period = cooldown + extract_cast_time(w_ability)
        casts = 1 + int(duration / period) if period > 0 else 1
        stacks_per_hit = _W_EVOLVED_STACKS if w_evolved else _W_NORMAL_STACKS
        events.extend(
            (cast_index * period + hit_delay, _W_HIT)
            for cast_index in range(casts)
            for _ in range(stacks_per_hit)
        )

    events.sort()
    return events


def _walk_plasma_stacks(
    ctx: SlotCtx, applications: Iterable[tuple[float, int]]
) -> tuple[list[DamagePart], int]:
    """Turn a stack-application stream into parts, counting the ruptures.

    Each application prices the sourced flat magic damage at the stacks
    already on the target, then adds its stack; the fifth consumes them
    all for the %missing-health rupture.  A gap longer than the sourced
    4s expires the chain.  ``plasma_starting_stacks`` seeds the opening
    cycle, exactly as it seeds the one-rotation ledger.
    """
    base, per_prior_stack = _plasma_values(ctx)
    target_health = float(ctx.target_stat("target_max_health"))
    rupture_ratio = _rupture_ratio(ctx)

    stacks = _seeded_stacks(ctx)
    last_application: float | None = None
    parts: list[DamagePart] = []
    ruptures = 0
    for time, _kind in applications:
        if (
            last_application is not None
            and time - last_application > _PLASMA_STACK_DURATION
        ):
            stacks = 0
        parts.append(
            DamagePart("magic", base + per_prior_stack * stacks, time_offset=time)
        )
        stacks += 1
        last_application = time
        if stacks == _PLASMA_STACKS_TO_RUPTURE:
            parts.append(_rupture_part(rupture_ratio, target_health, time))
            ruptures += 1
            stacks = 0
    return parts, ruptures


def _timed_plasma_proc(
    ctx: SlotCtx, duration: float, uptime: float
) -> dict[str, Any] | None:
    """The fight-wide Plasma ledger over the merged auto + Void Seeker stream."""
    w_evolved, evolution_note = _evolution_state(
        ctx,
        "w_evolved",
        "evolution_ability_power",
        "item AP",
    )
    applications = _plasma_application_stream(ctx, duration, uptime, w_evolved)
    parts, ruptures = _walk_plasma_stacks(ctx, applications)
    if not parts:
        return None
    return {
        "name": "Second Skin (Plasma)",
        "breakdown_key": "passive_plasma",
        "parts": tuple(parts),
        "detail": (
            f"{len(applications)} stack applications, {ruptures} ruptures over "
            f"{duration:g}s on the merged auto + Void Seeker stream; "
            f"{evolution_note}"
        ),
    }


@ranked_slot
def _void_seeker(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:

    raw = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    distance, hit_time = _w_hit_time(ctx)
    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        raw,
        "magic",
    )
    entry["parts"] = (DamagePart("magic", raw, time_offset=hit_time),)
    window = _timed_window(ctx)
    if window is None:
        # The certified rotation waits for W to hit before starting Q.
        # Treating the travel as occupied sequence time makes that
        # deliberate wait explicit.  Plasma rides this single cast.
        entry["cast_time"] = hit_time
        entry["post_hit_proc"] = _plasma_proc(ctx, hit_time)
        entry["target_max_health_sensitive"] = True
        entry["detail"] = f"hit at {distance:g} range; Plasma resolves afterwards"
        return entry

    # Timed mode: the real 0.4s cast occupies the shared timeline (the
    # engine stamps it from the cached castTime); each cast's hit keeps
    # its travel-delayed offset, Plasma lives on the fight-wide walked
    # ledger (R's anchor), and evolved W's 75% on-hit refund shortens the
    # recast cadence.
    w_evolved, evolution_note = _evolution_state(
        ctx,
        "w_evolved",
        "evolution_ability_power",
        "item AP",
    )
    entry["cooldown"] = _w_timed_base_cooldown(
        extract_cooldown(ability, rank), w_evolved
    )
    entry["detail"] = (
        f"hit at {distance:g} range"
        + ("; evolved refunds 75% cooldown on hit" if w_evolved else "")
        + f"; {evolution_note}"
    )
    return entry


@ranked_slot
def _icathian_rain(
    ctx: SlotCtx, ability: dict[str, Any], rank: int
) -> dict[str, Any] | None:

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
    if _timed_window(ctx) is None:
        # One-rotation cast timestamps are nominally all zero in the shared
        # engine. This module authors the deliberate W-impact wait directly
        # into Q's hit offsets so the damage ledger still reflects
        # W -> Plasma -> Q.
        _, q_start = _w_hit_time(ctx)
        first_hit = q_start + _Q_FIRST_HIT_DELAY
    else:
        # Timed casts carry real per-cast timestamps; the volley starts at
        # its own sourced delay from each cast, with no artificial wait.
        first_hit = _Q_FIRST_HIT_DELAY
    entry = damage_entry(
        ability_name(ability),
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


def _supercharge_uptime(
    ctx: SlotCtx, ability: dict[str, Any], rank: int, duration: float, *, uptime: float
) -> tuple[int, float]:
    """(charges, window duty cycle) for Supercharge over the fight window.

    Casts at t=0 then on the effective cooldown — shortened by the sourced
    0.5s on-attack refund at the fight's attack rate — each opening its 4s
    window after the bonus-AS-scaled charge time.
    """
    charge = max(
        _E_CHARGE_TIME_MIN,
        _E_CHARGE_TIME_MAX
        - (_E_CHARGE_TIME_MAX - _E_CHARGE_TIME_MIN)
        * min(1.0, ctx.stat("bonus_attack_speed") / 100.0),
    )
    cooldown = effective_cooldown(
        extract_cooldown(ability, rank), _basic_ability_haste(ctx)
    )
    attack_rate = ctx.stat("attack_speed") * uptime
    period = charge + cooldown / (1.0 + _E_ATTACK_CD_REFUND_SECONDS * attack_rate)

    active = 0.0
    casts = 0
    cast_start = 0.0
    while cast_start <= duration:
        window_start = min(cast_start + charge, duration)
        active += min(window_start + _E_WINDOW_SECONDS, duration) - window_start
        casts += 1
        cast_start += period
    return casts, min(1.0, active / duration)


def _timed_ranked(ctx: SlotCtx) -> tuple[tuple[float, float], tuple[dict, int]] | None:
    """The timed fight window and the slot's ranked entry, together or not at all."""
    window, ranked = _timed_window(ctx), ctx.ranked()
    return None if window is None or ranked is None else (window, ranked)


def _supercharge(ctx: SlotCtx) -> dict[str, Any] | None:
    """E (timed only): recurring 4s attack-speed windows as an average grant.

    The engine's swing scheduler runs one uniform rate (its buffed-rate-
    first window is item-owned and starts at t=0), so the sourced 40-80%
    window is priced as its duration-weighted average across the fight.
    The grant is applied both to the parse context (so the Plasma walk
    sees the same cadence) and as a ``stat_buff`` the fight engine folds
    into its swing schedule.
    """
    timed = _timed_ranked(ctx)
    if timed is None:
        return None
    (duration, uptime), (ability, rank) = timed

    bonus_percent = extract_value(ability, "Bonus Attack Speed", rank)
    if bonus_percent <= 0:
        # A silent 0 would erase the whole window — fail loudly instead.
        raise ValueError(
            "Kai'Sa E: 'Bonus Attack Speed' leveling entry missing from the "
            "ability JSON — cannot price Supercharge's window"
        )
    casts, duty_cycle = _supercharge_uptime(ctx, ability, rank, duration, uptime=uptime)
    granted = bonus_percent * duty_cycle
    ctx.bump_stat("attack_speed", ctx.stat("attack_speed_ratio") * granted / 100.0)
    return {
        "name": ability_name(ability),
        "rank": rank,
        "stat_buff": {"bonus_attack_speed": granted},
        # E is not in CAST_ORDER (it deals nothing, so the damage rotation
        # omits it) and its grant is the window average above: declared
        # off-rotation so the engine's cast gate keeps it.
        "off_rotation_grant": True,
        "detail": (
            f"{casts} charge(s): {bonus_percent:g}% attack speed for "
            f"{_E_WINDOW_SECONDS:g}s each, priced as a {granted:.1f}% "
            f"average grant over {duration:g}s ({duty_cycle:.0%} uptime)"
        ),
    }


_supercharge.phase = BUFF


def _killer_instinct(ctx: SlotCtx) -> dict[str, Any] | None:
    """R (timed only): the single-cast anchor for the walked Plasma ledger.

    Killer Instinct deals no damage, but its cast is real — 100 mana on
    the shared timeline, cast exactly once by the engine's ultimate rule —
    and that single cast is what lets the fight-wide Plasma ledger price
    through ``post_hit_proc``, the one engine path that evaluates
    %missing-health ruptures against the fight's tracked target health.
    The attack reset and the 2s shield have no engine channel (the swing
    stream is uniform-rate and the shield ledger rides damage events) and
    stay documented assumptions.
    """
    timed = _timed_ranked(ctx)
    if timed is None:
        return None
    window, (ability, rank) = timed

    entry = damage_entry(
        ability_name(ability),
        rank,
        extract_cooldown(ability, rank),
        0.0,
        "magic",
    )
    proc = _timed_plasma_proc(ctx, *window)
    if proc is not None:
        entry["post_hit_proc"] = proc
        entry["target_max_health_sensitive"] = True
    entry["detail"] = (
        "no direct damage; the single timed cast anchors the fight-wide "
        "Plasma ledger (attack reset and shield are documented, not priced)"
    )
    return entry


CAST_ORDER = ("W", "Q", "R")
CUSTOM_CAST_ORDER_REFUSAL = (
    "Kai'Sa uses the certified W -> Q sequence so Plasma resolves before the "
    "volley; custom cast orders are not available yet."
)

OPTIONS = [
    {
        "key": "q_evolved",
        "type": "select",
        "default": "auto",
        "label": "Icathian Rain evolution",
        "rotation": {"role": "irrelevant", "slot": "Q"},
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
        "rotation": {"role": "irrelevant", "slot": "W"},
        "legacy_bool": True,
        "choices": [
            {"value": "auto", "label": "Automatic from build"},
            {"value": "base", "label": "Not evolved"},
            {"value": "evolved", "label": "Evolved"},
        ],
    },
    int_option(
        "plasma_starting_stacks",
        0,
        minimum=0,
        maximum=4,
        label="Plasma stacks already on each target",
        step=1,
        rotation={
            "role": "consume",
            "slot": "W",
            "condition": "plasma",
            "kind": "stack_consume",
        },
    ),
    float_option(
        "w_target_distance",
        800.0,
        minimum=0.0,
        maximum=3000.0,
        label="Void Seeker target distance",
        step=50.0,
        rotation={"role": "self_state", "slot": "W"},
    ),
]

ASSUMPTIONS = [
    "One rotation is the certified W then Q sequence: W and Plasma resolve before Q "
    "is cast.",
    "Timed casts run on the real shared timeline with no artificial wait.",
    "Every Q missile hits one isolated selected target; shared targets would "
    "split the volley",
    "Q and W evolutions follow permanent item stats and level growth; the selector "
    "can force a test state.",
    "plasma_starting_stacks is deliberately NOT monotonic, and the two reasons "
    "compound.",
    "Seeding 4 makes the next application the fifth, so the flat ramp resets to the "
    "bottom of the ladder.",
    "The rupture is a share of missing health, so firing it early prices a barely "
    "damaged target.",
    "Probe at level 18, one rotation, 85 effective MR: passive_plasma is 169.1 / "
    "347.7 / 268.7 at 0 / 2 / 4.",
    "Both halves of the 2 to 4 drop are real: flat 238.1 to 192.1 and rupture 109.6 "
    "to 76.6.",
    "W applies each Plasma stack in turn; a fifth-stack rupture uses health remaining "
    "under running damage.",
    "One rotation counts W and the preceding Caustic Wounds hit; timed counts the "
    "priced casts and hits.",
    "Timed Plasma stacks persist on the merged basic-attack and Void Seeker stream "
    "with the sourced 4s expiry.",
    "The walk mirrors the engine: autos at attack speed x uptime, W at t=0 then on "
    "its effective cooldown.",
    "Only Kai'Sa's own attacks and W apply stacks; ally immobilize stacks are not "
    "modeled.",
    "The timed Plasma ledger rides Killer Instinct's single cast, so it needs R "
    "ranked and cast.",
    "An autos-only or pre-6 timed fight leaves Plasma unpriced, a stated gap rather "
    "than a withhold.",
    "Killer Instinct's attack reset and 2s shield are not priced: no reset channel, "
    "and R deals no damage.",
    "Supercharge is a duration-weighted average attack-speed grant, the swing "
    "scheduler being uniform-rate.",
    "It casts at t=0 then on its effective cooldown, each window 4s after the charge.",
    "Its sourced 0.5s on-attack refund uses the pre-window rate; 30 mana and the "
    "lockout are off the timeline.",
    "Supercharge's charge time scales 1.2s to 0.6s with bonus attack speed (cached "
    "castTime prose).",
    "Its evolution grants brief invisibility only and needs no combat model.",
]

SOURCES = load_champion_sources("Kai'Sa")

SLOTS = {
    "W": _void_seeker,
    "Q": _icathian_rain,
    "E": _supercharge,
    "R": _killer_instinct,
}

# Kai'Sa's damaging casts apply no control: Q's missiles only damage, and
# W's bolt deals magic damage, "applies 2 Plasma, and reveals them".  (Her
# passive reads *other* people's immobilizes to stack Plasma; it applies
# none of its own.)  E and R author no damage part — Supercharge is the
# attack-speed window and Killer Instinct is a shield plus a dash.
MODULE_CC = {"Q": "none", "W": "none", "E": "none", "R": "none"}

parse_abilities = build_parser(SLOTS, "Kai'Sa", cc_kinds=MODULE_CC)

# E and R emit rows and neither deals damage, so both are ``no_damage``;
# P has no slot of its own and can therefore only read ``out_of_scope``,
# which under-reports it — see the module docstring.
MODULE_COVERAGE = coverage(no_damage="ER")

COVERAGE_CHANNELS = {"P": ("post_hit_proc",)}
