"""The auto stream an empowered burst re-times, and the swings its riders claim."""

from ... import attack_cadence
from ...control_intervals import merged_spans
from ..autos.swing_schedule import _auto_attack_timestamps
from ..empower_declaration import (
    BurstSwingSchedule,
    _empower_burst_attack_speed,
    _empower_hits,
    _empower_rides_scheduled_auto,
)
from ..results import CastPlan
from ..state import FightState


def _apply_empowered_burst_autos(state: "FightState", plan: "CastPlan") -> None:
    """Re-time the auto stream around empowered bursts that set their rate.

    A burst declaring ``attack_speed`` (Jayce's Hyper Charge) fires its
    hits at the cap instead of the champion's ordinary rate, so it costs
    the fight only ``hits / burst_as`` seconds. The rest of the fight
    still runs at the ordinary rate, which means the burst does not just
    re-price attacks — it BUYS extra ordinary autos with the time it
    saved. Total attacks become ``normal autos in the leftover time`` plus
    the burst swings themselves (which the breakdown later moves onto the
    ability's own row).

    The burst fires WHERE ITS CAST IS: each cast lands its hits from its
    own cast time at the burst rate, and only the hits that land before
    the fight ends are bought. Deriving the count from a time budget while
    the schedule laid every swing at the ordinary rate is what put swings
    past the end of the fight (Jayce, 20 s: 24 swings, the last at 28.9 s).

    A fight with no auto stream is left alone: those casts force their
    own swings onto their ability row instead (see the empowered-auto
    branch in the rotation).
    """
    if state.num_auto_attacks <= 0 or state.auto_attack_uptime <= 0:
        return

    duration = state.fight_duration_seconds
    by_ability: dict[str, tuple[float, ...]] = {}
    spans: list[tuple[float, float]] = []
    for ability_key in state.cast_order:
        ability_info = state.ability_damages.get(ability_key)
        if not ability_info:
            continue
        empower = ability_info.get("empowers_next_auto")
        burst_as = _empower_burst_attack_speed(empower) if empower else 0.0
        if burst_as <= 0:
            continue
        phase = state.impact_phase(burst_as)
        impacts: list[float] = []
        for cast_time in plan.times.get(ability_key, ()):
            landed = [
                time
                for time in attack_cadence.counted_impacts(
                    _empower_hits(empower), burst_as, phase, cast_time
                )
                if time < duration
            ]
            if not landed:
                continue
            impacts.extend(landed)
            # The burst holds the attack timer from its cast for one cycle
            # per swing that landed.
            spans.append((cast_time, min(duration, cast_time + len(landed) / burst_as)))
        if impacts:
            by_ability[ability_key] = tuple(impacts)

    if not by_ability:
        return

    schedule = BurstSwingSchedule(by_ability=by_ability, blocks=merged_spans(spans))
    leftover = max(0.0, duration - schedule.seconds)
    state.num_auto_attacks = attack_cadence.impact_count(
        state.attack_speed * state.auto_attack_uptime,
        leftover,
        state.impact_phase(state.attack_speed),
    ) + len(schedule.times)
    state.burst_swings = schedule


def _resolve_scheduled_auto_rides(state: "FightState", plan: "CastPlan") -> None:
    """Claim the stream swing each ``rides_scheduled_auto`` cast is delivered by.

    A burst that sets its own rate re-times the stream and declares its own
    impacts (``BurstSwingSchedule``); any other empower's swing is claimed
    once the ledger exists (``fight/after/empowered_swings.py``), while its
    ``target_debuff`` window opens at the cast.  A rider is carried by a
    swing already on the stream, the first at or after its cast that an
    earlier rider has not taken.  Resolving that here, before the rotation,
    is what lets its ``target_debuff`` window open at the swing too.

    Casts left without a swing keep nothing: the stream ran out, and the
    engine already caps such casts by the autos that consume them.
    """
    if state.num_auto_attacks <= 0:
        return
    rides: dict[str, tuple[float, ...]] = {}
    # A self-rated burst already owns its impacts, so a rider may not take
    # one of them: those swings are spoken for (Jayce's R rides an ordinary
    # swing while his Hyper Charge fires its own three).
    claimed_by_burst = set(state.burst_swings.times if state.burst_swings else ())
    available = [
        time for time in _auto_attack_timestamps(state) if time not in claimed_by_burst
    ]
    taken = 0
    for ability_key in state.cast_order:
        ability_info = state.ability_damages.get(ability_key)
        if not ability_info:
            continue
        empower = ability_info.get("empowers_next_auto")
        if not empower or not _empower_rides_scheduled_auto(empower):
            continue
        hits = _empower_hits(empower)
        claimed: list[float] = []
        for cast_time in plan.times.get(ability_key, ()):
            for _ in range(hits):
                while taken < len(available) and available[taken] < cast_time:
                    taken += 1
                if taken >= len(available):
                    break
                claimed.append(available[taken])
                taken += 1
        if claimed:
            rides[ability_key] = tuple(claimed)
    state.empowered_ride_times = rides
