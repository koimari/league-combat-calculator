"""Karthus — sourced alive-state W -> Q -> E -> R model, both fight modes.

Wall of Pain applies its resistance reduction before the damaging sequence
(timed fights time-weight the shred over its 5s windows on the W schedule).
Lay Waste switches between isolated and shared-target formulas and recasts
on its real cooldown in timed fights.  Defile exposes an exact selected
tick count per rotation; in timed fights it is the persistent toggle,
modeled as engine-scheduled one-second pulses (four sourced 0.25s ticks,
one second of the sourced mana drain each) that the ordered resource
timeline shuts off at mana exhaustion.  Requiem lands after its
three-second channel.  Death Defied is deliberately outside the
alive-window model in both modes.
"""

import math
from typing import Any

from ..ability_spec import DamagePart
from .engine import DEBUFF, SlotCtx, build_parser
from .module_helpers import clamp
from .slotlib import ability_name, damage_entry, extract_cooldown, extract_named
from .source_receipts import load_champion_sources
from .inputs import bool_option, int_option

_W_MR_REDUCTION_PERCENT = 25.0
_W_DEBUFF_DURATION = 5.0
_W_CAST_TIME = 0.25
_Q_CAST_TIME = 0.25
_Q_CONSERVATIVE_DETONATION_DELAY = 0.75
_E_FIRST_TICK_TIME = _W_CAST_TIME + _Q_CAST_TIME
_E_TICK_INTERVAL = 0.25
_E_MAX_SELECTED_TICKS = 40
# Timed mode prices the toggle in one-second pulses: the sourced drain is
# "mana per second" and 4 ticks x the sourced per-tick row is exactly the
# sourced "Damage Per Second" row (cross-checked at parse time).
_E_PULSE_SECONDS = 1.0
_R_CAST_START = _E_FIRST_TICK_TIME
_R_CHANNEL_DURATION = 3.0
_R_CAST_TIME = 0.25


def _wall_of_pain(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    entry: dict[str, Any] = {
        "name": ability_name(ability),
        "rank": rank,
        "cooldown": extract_cooldown(ability, rank),
        "damage_type": "magic",
        "total_raw": 0.0,
        "parts": (),
        "detail": "Target crosses the wall before the damaging sequence",
    }
    if bool(ctx.option("wall_contact")):
        entry["target_debuff"] = {
            "mr_reduction_percent": _W_MR_REDUCTION_PERCENT,
            "duration": _W_DEBUFF_DURATION,
        }
    else:
        entry["detail"] = "Wall cast, but the selected target does not cross it"
    return entry


_wall_of_pain.phase = DEBUFF


def _lay_waste(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked

    requested_isolated = bool(ctx.option("q_isolated"))
    roster_count = int(ctx.target_stat("roster_target_count"))
    isolated = requested_isolated and roster_count <= 1
    attribute = "Isolated Enhanced Damage" if isolated else "Magic Damage"
    raw = extract_named(ability, attribute, rank, ctx.stats, ctx.target)
    hit_time = _W_CAST_TIME + _Q_CAST_TIME + _Q_CONSERVATIVE_DETONATION_DELAY
    entry = damage_entry(
        ability_name(ability),
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


def _defile_mana_per_second(ability: dict[str, Any], rank: int) -> float:
    """Defile's sourced toggle drain: its cost row is mana per second."""
    return float(
        (ability.get("cost") or {})
        .get("modifiers", [{}])[0]
        .get("values", [0])[rank - 1]
    )


def _defile_timed(ctx: SlotCtx, ability: dict[str, Any], rank: int) -> dict[str, Any]:
    """E as a persistent toggle: one entry per pulse-second of uptime.

    The engine's shared cast timeline recasts this entry every second
    (each "cast" is one second of the toggle being on) and its ordered
    resource timeline charges each pulse the sourced drain against the
    real pool, regen, and the mana Q/W/R spend — so Defile shuts off at
    mana exhaustion instead of ticking for free.  The part authors the
    four exact 0.25s ticks each accepted pulse spreads over its second;
    ``dot_duration`` + ``dot_tick_interval`` say the same schedule to the
    item burns that refresh across it.
    """
    per_tick = extract_named(
        ability, "Magic Damage Per Tick", rank, ctx.stats, ctx.target
    )
    per_second = extract_named(
        ability, "Damage Per Second", rank, ctx.stats, ctx.target
    )
    ticks_per_pulse = round(_E_PULSE_SECONDS / _E_TICK_INTERVAL)
    if not math.isclose(
        per_tick * ticks_per_pulse, per_second, rel_tol=1e-9, abs_tol=1e-6
    ):
        raise ValueError(
            "Karthus E: the sourced 'Magic Damage Per Tick' x 4 no longer "
            "equals the sourced 'Damage Per Second' row - the 0.25s tick "
            "cadence pinned here has changed upstream"
        )
    # The engine divides every Q/W/E cooldown by (100 + haste) / 100; the
    # toggle's drain cadence is not haste-accelerated, so declare the
    # inverse and land back on the fixed one-second beat.
    haste = ctx.stat("ability_haste") + ctx.stat("basic_ability_haste")
    entry = damage_entry(
        ability_name(ability),
        rank,
        _E_PULSE_SECONDS * (100.0 + haste) / 100.0,
        per_second,
        "magic",
    )
    drain = _defile_mana_per_second(ability, rank)
    # The pulse's ticks carry their own cached beat — the aura "deals magic
    # damage every 0.25 seconds to all nearby enemies" — so the part states
    # the schedule the engine would otherwise have to infer, and the
    # reviewed "the aura only damages" rides it into the event ledger.
    entry["parts"] = (
        DamagePart(
            "magic",
            per_tick,
            count=ticks_per_pulse,
            time_offset=0.0,
            hit_interval=_E_TICK_INTERVAL,
        ),
    )
    entry["resource_type"] = "MANA"
    entry["resource_cost"] = drain * _E_PULSE_SECONDS
    entry["dot_duration"] = _E_PULSE_SECONDS
    entry["dot_tick_interval"] = _E_TICK_INTERVAL
    entry["detail"] = (
        f"toggle as one-second pulses: 4 ticks at 0.25-second intervals, "
        f"{drain:g} mana per second until the shared pool runs dry"
    )
    return entry


def _defile(ctx: SlotCtx) -> dict[str, Any] | None:
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    if ctx.options.get("fight_duration_seconds") is not None:
        return _defile_timed(ctx, ability, rank)

    requested = int(ctx.option("e_ticks"))
    ticks = int(clamp(float(requested), 0.0, float(_E_MAX_SELECTED_TICKS)))
    per_tick = extract_named(
        ability, "Magic Damage Per Tick", rank, ctx.stats, ctx.target
    )
    # Both branches author their own hit times, so the reviewed "the aura
    # only damages" rides the parts in each — which is why E declares its
    # kind here and in _defile_timed rather than in MODULE_CC.
    parts = tuple(
        DamagePart(
            "magic",
            per_tick,
            time_offset=_E_FIRST_TICK_TIME + index * _E_TICK_INTERVAL,
        )
        for index in range(ticks)
    )
    active_seconds = max(0.0, (ticks - 1) * _E_TICK_INTERVAL)
    mana_per_second = _defile_mana_per_second(ability, rank)
    entry = damage_entry(
        ability_name(ability),
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
    ranked = ctx.ranked()
    if ranked is None:
        return None
    ability, rank = ranked
    raw = extract_named(ability, "Magic Damage", rank, ctx.stats, ctx.target)
    hit_time = _R_CAST_START + _R_CAST_TIME + _R_CHANNEL_DURATION
    entry = damage_entry(
        ability_name(ability),
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
CUSTOM_CAST_ORDER_UNAVAILABLE_REASON = (
    "Karthus uses the certified alive-state W -> Q -> E -> R sequence so the "
    "wall reduction is established before damage."
)

OPTIONS = [
    bool_option("wall_contact", True, label="Target crosses Wall of Pain"),
    bool_option("q_isolated", True, label="Lay Waste hits only one target"),
    int_option(
        "e_ticks",
        5,
        minimum=0,
        maximum=_E_MAX_SELECTED_TICKS,
        label="Defile damage ticks (one rotation)",
        step=1,
    ),
]

ASSUMPTIONS = [
    "The certified sequence is the alive-state W -> Q -> E -> R order "
    "against each selected target; timed fights recast it on the engine's "
    "shared cast timeline.",
    "Wall of Pain reduces the selected target's magic resistance by 25% only "
    "when its contact option is on; timed fights time-weight the shred over "
    "its 5-second windows on the W cast schedule.",
    "Lay Waste doubles only for a single selected target; a multi-target hit "
    "automatically uses the shared-target formula.",
    "In one rotation Defile uses exactly the selected tick count and charges "
    "mana for the elapsed 0.25-second intervals; timed fights ignore the "
    "selector and model the toggle as one-second pulses (four sourced ticks, "
    "one second of the sourced drain each) paid on the ordered resource "
    "timeline beside Q/W/R, so Defile shuts off at mana exhaustion.",
    "Toggle pulses are conservative: a pulse begun within the window prices "
    "its full second of ticks, re-arms only at instants the shared cast "
    "timeline leaves free (Requiem's channel and cast times can delay it), "
    "and holds a fixed one-second cadence against ability haste; cooldown "
    "effects beyond haste (Navori) are not counteracted.",
    "Lay Waste uses the sourced upper 0.75-second detonation delay because the "
    "Wiki records its live delay as inconsistent between 0.5 and 0.75 seconds.",
    "Death Defied is outside the alive-window model in both fight modes: the "
    "fight engine has no death event for the attacker, so the 7-second "
    "post-death window stays a documented zero-damage boundary.",
]

SOURCES = load_champion_sources("Karthus")


def _death_defied(ctx: SlotCtx) -> dict[str, Any] | None:
    """P: zero-damage receipt — a death-only trigger outside the fight.

    Death Defied lets Karthus keep casting for 7 seconds after taking
    fatal damage (including a channeled Requiem).  The deterministic
    single-target fight has no death event for the main, so the passive
    contributes zero damage here; this receipt documents the boundary
    with its sourced trigger so the alive-state package is complete.
    """
    ability = ctx.ability("P", 0)
    if ability is None:
        return None
    entry = damage_entry(
        ability_name(ability),
        ctx.level,
        0.0,
        0.0,
        "magic",
    )
    entry["parts"] = ()
    entry["detail"] = (
        "Post-death channel + Requiem: a death-only trigger the deterministic "
        "alive-state fight cannot enter (the main never dies in the model); "
        "priced at zero damage as a documented boundary. Requiem's damage is "
        "already the sourced R row when the alive-state sequence casts it."
    )
    return entry


SLOTS = {
    "W": _wall_of_pain,
    "Q": _lay_waste,
    "E": _defile,
    "R": _requiem,
    "P": _death_defied,
}

# Lay Waste detonates and Requiem lands after its channel; neither applies
# control.  Karthus' only crowd control is W's wall, which damages nothing
# and authors no part, and P is the zombie state.  E's aura is equally
# control-free but its two branches carry that review differently (see
# _defile), so it is authored on the parts.
MODULE_CC = {"Q": "none", "E": "none", "R": "none"}

parse_abilities = build_parser(SLOTS, "Karthus", cc_kinds=MODULE_CC)
