"""The on-hits that read the target's live health: the current-health walk down the
swings, and the schedule-gated procs."""

from collections.abc import Sequence
from typing import Any

from ...ability_atoms import ability_field
from ..cast_slots import slot_cast_start
from ..ledger.breakdown import source_casts
from ..resists import Resists, _resistance_met_fields
from ..results import AutoAttackResult, OnHitResult
from ..state import FightState, _damage_inputs
from .decaying_health_walk import (
    AutoSwings,
    _simulate_current_health_on_hit,
    _simulate_hp_scaled_on_hit_procs,
)
from .empower_windows import _on_hit_declaration
from .on_hit_stream import _schedule_cooldown_procs


def _swing_event_row(
    times: list[float],
    damages: list[float],
    damage_type: str,
    *,
    declarations: list[tuple[Any, ...]] | None = None,
    raws: list[float] | None = None,
    resists: Resists | None = None,
) -> dict[str, Any]:
    """Row fields authoring one typed event per (time, damage) pair.

    ``declarations`` is one per event for a row the walk prices itself, and
    ``None`` for a row delivered as the pair engine's own price.  ``raws`` is
    one per event for a row whose caller priced each application from its own
    pre-mitigation magnitude, and ``None`` where the caller states none, which
    the receipt reads as a refusal rather than as a number.  Both ride through
    the sort beside their own damage rather than being stamped afterwards: the
    events are ordered by time, and an application's magnitude belongs to the
    application, not to the position it lands in.  ``resists`` is what the
    caller mitigated against; one row is one damage class, so its whole
    schedule met one resistance.
    """
    declared = declarations or [None] * len(damages)
    stated = raws or [None] * len(damages)
    met = {} if resists is None else _resistance_met_fields(damage_type, resists)
    ordered = sorted(
        zip(times, damages, declared, stated, strict=False),
        key=lambda packet: float(packet[0]),
    )
    return {
        "event_phase": "auto",
        "damage_events": [
            {
                "time": time,
                "damage": damage,
                "damage_type": damage_type,
                **({} if declaration is None else {"declared": declaration}),
                **({} if raw is None else {"raw_damage": raw}),
                **met,
            }
            for time, damage, declaration, raw in ordered
        ],
    }


def _pay_current_health_on_hit(
    state: FightState,
    autos: AutoAttackResult,
    result: OnHitResult,
    *,
    effect: Any,
    application_times: Sequence[float],
    effectiveness: float,
    first_auto_damage_by_auto: Any,
) -> float:
    """Walk the current-health on-hit down the auto stream, and price it.

    BoRK: the target's current HP decays per auto attack, so the walk
    prices each application at the health the ones before it left.  A
    phantom-hit auto procs it twice, at different current HP, and a double
    shot (Akshan) procs it once more per auto.  First-auto packets are
    priced here as HP-only inputs; their damage row and fight total stay
    with ``_add_first_auto_strikes``.
    """
    resists = state.resists
    breakdown = state.breakdown
    magic_amp = state.magic_amp
    num_auto_attacks = state.num_auto_attacks
    decayed = _simulate_current_health_on_hit(
        effect=effect,
        base_inputs=_damage_inputs(state),
        swings=AutoSwings(
            target_health=state.target_health,
            num_auto_attacks=num_auto_attacks,
            auto_damage_per_hit=autos.auto_damage_per_hit,
            other_on_hit_per_hit=result.static_on_hit_per_hit,
            resists=resists,
            magic_amp=magic_amp,
        ),
        phantom_hit_autos=result.phantom_hit_autos,
        double_hit_all=autos.double_shot_info is not None,
        effectiveness=effectiveness,
        first_auto_damage_by_auto=first_auto_damage_by_auto,
    )
    result.current_health_on_hit_avg = (
        decayed.total_damage / decayed.hits if decayed.hits > 0 else 0.0
    )
    result.current_health_damage_type = effect.source.damage_type

    source = effect.source
    mechanic = source.previewed_mechanic()
    breakdown[source.breakdown_key] = {
        "name": source.display_name,
        "count": decayed.hits,
        "damage_per_hit": result.current_health_on_hit_avg,
        "total_damage": decayed.total_damage,
        "damage_type": source.damage_type,
        # A preview like the static strikes above author, and the one of
        # the eight whose applications do not share a magnitude: the
        # declaration on each event below is that application's own raw
        # value, and the row's is their sum rather than an average
        # multiplied back up.
        "pair_preview_of": mechanic,
        "declared": _on_hit_declaration(
            mechanic,
            sum(proc.raw for proc in decayed.procs),
        ),
    }
    # The simulation walks the same application order the swing
    # schedule authored, so its per-hit values stamp one event each.
    if application_times and len(decayed.procs) == len(application_times):
        breakdown[source.breakdown_key].update(
            _swing_event_row(
                application_times,
                [proc.mitigated for proc in decayed.procs],
                source.damage_type,
                declarations=[
                    _on_hit_declaration(mechanic, proc.raw) for proc in decayed.procs
                ],
                resists=resists,
            )
        )
    return decayed.total_damage


def _pay_scheduled_live_health_procs(
    state: FightState,
    autos: AutoAttackResult,
    result: OnHitResult,
    *,
    swing_times: Sequence[float],
    effectiveness: float,
    running_damage: float,
) -> float:
    """Price the scheduled live-health on-hits, and return the running total.

    These ride the fight's auto timeline and read the target's decayed
    current HP per proc.  Three schedules: ``proc_cooldown`` (Jarvan IV's
    Martial Cadence) procs the first auto, then the first auto at or after
    (last proc + per-target cooldown); ``proc_window`` (Camille R's rider)
    procs every auto landing inside the window after the ability is cast, so
    a fight that never casts it (auto-only mode) gets nothing;
    ``missing_health_amp`` (Samira's blade rider) procs the swings a range
    gate admits, ``max_procs`` of them.  A schedule-gated proc does not land
    on every auto, which is why phantom hits and double shots never add
    procs and why the proc stays out of ``static_on_hit_per_hit``: spellblade
    doubling and the BoRK walk must not re-apply it.
    """
    resists = state.resists
    breakdown = state.breakdown
    magic_amp = state.magic_amp
    num_auto_attacks = state.num_auto_attacks
    autos_per_second = state.attack_speed * state.auto_attack_uptime
    # Both proc schedules read the same authored swing times that stamp
    # their events; the uniform fallback only covers an unresolvable
    # schedule, whose rows stay coarse anyway.
    proc_schedule = swing_times or (
        [i / autos_per_second for i in range(num_auto_attacks)]
        if autos_per_second > 0
        else []
    )
    for ability_key, ability_info in state.ability_damages.items():
        on_hit_data = ability_info.get("on_hit")
        if not on_hit_data:
            continue
        if "proc_cooldown" in on_hit_data:
            proc_autos = _schedule_cooldown_procs(
                proc_schedule, on_hit_data["proc_cooldown"]
            )
        elif "missing_health_amp" in on_hit_data:
            # A range-gated rider on the basic-attack stream: it rides
            # every swing inside the gate, and ``max_procs`` is how many
            # of them the request says land there.
            gated = ability_field(on_hit_data, "max_procs", form="on_hit")
            proc_autos = list(
                range(
                    num_auto_attacks
                    if gated is None
                    else min(num_auto_attacks, int(gated))
                )
            )
        elif "proc_window" in on_hit_data:
            cast_row = breakdown.get(ability_key)
            row_casts = None if cast_row is None else source_casts(cast_row)
            if row_casts is None or row_casts < 1:
                continue  # rider exists only after the ability is cast
            # The window opens at the slot's first cast (Master Yi E
            # after Q and W's cast times), and the triggering auto
            # always fits a positive window: the first swing at or
            # after the cast procs even when the window closes first.
            start = slot_cast_start(state, ability_key)
            end = start + on_hit_data["proc_window"]
            proc_autos = [
                index for index, time in enumerate(proc_schedule) if start <= time < end
            ] or [index for index, time in enumerate(proc_schedule) if time >= start][
                :1
            ]
        else:
            continue
        if not proc_autos:
            continue
        proc_damages = _simulate_hp_scaled_on_hit_procs(
            on_hit_data,
            AutoSwings(
                target_health=state.target_health,
                num_auto_attacks=num_auto_attacks,
                auto_damage_per_hit=autos.auto_damage_per_hit,
                other_on_hit_per_hit=result.static_on_hit_per_hit
                + result.current_health_on_hit_avg,
                resists=resists,
                magic_amp=magic_amp,
            ),
            proc_autos=proc_autos,
            effectiveness=effectiveness,
        )
        proc_total = sum(proc_damages)
        running_damage += proc_total
        proc_damage_type = ability_field(on_hit_data, "damage_type", form="on_hit")
        breakdown[f"on_hit_ability_{ability_key}"] = {
            "name": on_hit_data.get("name", f"{ability_key} (on-hit)"),
            "count": len(proc_autos),
            "damage_per_hit": proc_total / len(proc_autos),
            "total_damage": proc_total,
            "damage_type": proc_damage_type,
            "unit": "procs",
        }
        if swing_times:
            # Each proc rides one specific swing — stamp its time.
            breakdown[f"on_hit_ability_{ability_key}"].update(
                _swing_event_row(
                    [swing_times[i] for i in proc_autos],
                    proc_damages,
                    proc_damage_type,
                    resists=resists,
                )
            )
    return running_damage
