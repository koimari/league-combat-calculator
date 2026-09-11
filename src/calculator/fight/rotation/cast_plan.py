"""The plan every admitted cast lands in, its resolver, and the skeleton both walks share."""

import math
from collections.abc import Iterable, Mapping
from typing import Any

from ...ability_atoms import ability_field
from ..empower_declaration import _empower_burst_attack_speed, _empower_hits
from ..results import CastPlan
from ..state import FightState
from .cast_schedule import _CAST_SCHEDULE_EPS, _ridden_parent_slot


def _resolve_cast_plan(
    state: FightState,
    schedule: Mapping[str, list[float]],
) -> CastPlan:
    """Resolve every ability entry's cast count and cast times."""
    counts: dict[str, int] = {}
    times: dict[str, tuple[float, ...]] = {}
    last_cast_time = 0.0

    for ability_key in state.cast_order:
        ability_info = state.ability_damages.get(ability_key)
        if ability_info is None:
            continue

        scheduled: list[float] = []
        if state.combat_events is not None:
            scheduled = list(schedule.get(ability_key, ()))
            num_casts = len(scheduled)
            if scheduled:
                last_cast_time = max(last_cast_time, scheduled[-1])
        elif state.auto_attacks_only:
            num_casts = 0
        elif state.one_rotation:
            num_casts = 1
        else:
            # A recast on its parent's cooldown (e.g. Camille's Q2) matches
            # the parent ability's casts; a zero-cooldown charge does not.
            parent_key = _ridden_parent_slot(ability_info)
            if parent_key and parent_key in counts:
                num_casts = counts[parent_key]
                scheduled = list(times[parent_key])
            else:
                scheduled = schedule[ability_key]
                # Empowered-auto abilities (Vayne Q) only deal damage
                # through the next basic attack(s), so casts can never
                # exceed the autos that consume them (a multi-hit empower
                # like Cho'Gath E consumes ``hits`` autos per cast). The
                # auto count itself is untouched: such casts are attack
                # resets, spent in attack-cooldown dead time (the in-game
                # reset acceleration is not modeled — conservative). With
                # no auto stream at all (zero uptime), each cast forces
                # its own attack(s) instead.
                empower = ability_info.get("empowers_next_auto")
                # A burst that fires at its OWN rate supplies the attacks
                # it needs (Jayce's Hyper Charge), so the ambient auto
                # count never limits it — only its cooldown does.
                if (
                    empower
                    and state.num_auto_attacks > 0
                    and not _empower_burst_attack_speed(empower)
                ):
                    scheduled = scheduled[
                        : state.num_auto_attacks // _empower_hits(empower)
                    ]
                scheduled = _landable_cast_times(state, ability_info, scheduled)
                num_casts = len(scheduled)
                # Burns use the fight-wide last cast as their final refresh.
                if scheduled:
                    last_cast_time = max(last_cast_time, scheduled[-1])

        counts[ability_key] = num_casts
        times[ability_key] = tuple(scheduled) if scheduled else (0.0,) * num_casts

    return CastPlan(counts=counts, times=times, last_cast_time=last_cast_time)


def _landable_cast_times(
    state: FightState,
    ability_info: Mapping[str, Any],
    scheduled: list[float],
) -> list[float]:
    """Drop a cast whose every hit is a single instant past the fight's end.

    Dropped before pricing so the cast count, the cast timeline and every
    proc that counts ability hits agree (#323); a cast that lands anything
    at the boundary, as a tick train or through a next attack is kept and
    cast_parts clips its late hits one by one.
    """
    parts = ability_info.get("parts")
    if not state.clip_to_window or not parts or ability_info.get("empowers_next_auto"):
        return scheduled
    if any(part.time_offset is None or part.hit_interval is not None for part in parts):
        return scheduled
    earliest = min(part.time_offset for part in parts)
    limit = state.fight_duration_seconds + _CAST_SCHEDULE_EPS
    return [cast_time for cast_time in scheduled if cast_time + earliest <= limit]


def _cast_admission_events(
    state: FightState, plan: CastPlan
) -> list[tuple[float, int, int, str]]:
    """The planned casts as (time, cast-order, ordinal, slot), chronological."""
    events: list[tuple[float, int, int, str]] = []
    order = {key: index for index, key in enumerate(state.cast_order)}
    for key, times in plan.times.items():
        events.extend(
            (cast_time, order.get(key, len(order)), ordinal, key)
            for ordinal, cast_time in enumerate(times)
        )
    events.sort()
    return events


def _resource_timeline(
    state: FightState,
    events: Iterable[tuple[float, int, int, str]],
    *,
    restore_producer: str,
) -> list[tuple[float, int, int, int, str, str, float]]:
    """The heap both resource walks drain: planned casts and external restores.

    Heap entries are (time, phase, cast-order, ordinal, kind, key, amount).
    Restore events sort before a cast at the same timestamp, matching the
    attack landing before a simultaneous ability input is evaluated.  The
    damage-taken restoration is an external, timestamped input from the
    coupled participant ledger; malformed rows are ignored here because the
    producer is required to fail closed before constructing this typed tuple.
    The caller may append its own rows before heapifying.
    """
    timeline: list[tuple[float, int, int, int, str, str, float]] = [
        (cast_time, 1, order_index, ordinal, "cast", key, 0.0)
        for cast_time, order_index, ordinal, key in events
    ]
    for restore_index, (raw_time, raw_amount) in enumerate(
        state.resource_restore_events
    ):
        try:
            restore_time = float(raw_time)
            restore_amount = float(raw_amount)
        except (TypeError, ValueError):
            continue
        if (
            not math.isfinite(restore_time)
            or not math.isfinite(restore_amount)
            or restore_amount <= 0.0
            or restore_time < 0.0
            or restore_time > state.fight_duration_seconds + _CAST_SCHEDULE_EPS
        ):
            continue
        timeline.append(
            (
                restore_time,
                0,
                -1,
                restore_index,
                "restore",
                restore_producer,
                restore_amount,
            ),
        )
    return timeline


class _CastAdmission:
    """The accept/omit bookkeeping both resource walks keep.

    Insertion order is load-bearing — the ledger replays these lists — so an
    accepted time, an omitted slot and a per-cast row are appended exactly
    where the walk produced them.  The fixed-count per-proc restore an ability
    may declare is admitted here too, because it is paid to an accepted cast:
    Ambessa weaves her empowered attacks between casts, so their restores ride
    this same ordered timeline.
    """

    def __init__(self, state: FightState, plan: CastPlan) -> None:
        self.score_only = state.score_only
        self.accepted: dict[str, list[float]] = {key: [] for key in plan.times}
        self.accepted_ordinals: dict[str, set[int]] = {key: set() for key in plan.times}
        self.omitted: list[str] = []
        self.spent = 0.0
        self.resource_by_cast: dict[tuple[str, int], dict[str, float]] = {}
        proc_restore = next(
            (
                info
                for info in state.ability_damages.values()
                if float(ability_field(info, "resource_restore_per_proc")) > 0
                and int(ability_field(info, "proc_count")) > 0
            ),
            None,
        )
        # One entry per declared proc: what this fight has left to pay.
        self._proc_restores: list[float] = (
            [float(proc_restore["resource_restore_per_proc"])]
            * int(ability_field(proc_restore, "proc_count", form="proc_restore"))
            if proc_restore
            else []
        )

    def omit(self, key: str) -> None:
        """Record a cast the walk refused."""
        self.omitted.append(key)

    def recast_parent_denied(self, info: Mapping[str, Any], ordinal: int) -> bool:
        """True when a recast's parent cast at this ordinal was not accepted."""
        parent = info.get("recast_of")
        return bool(parent) and ordinal not in self.accepted_ordinals.get(parent, set())

    def restore_for(self, info: Mapping[str, Any]) -> float:
        """One accepted cast's own restore, plus a proc's while procs are left."""
        restored = float(ability_field(info, "resource_restore"))
        if self._proc_restores:
            restored += self._proc_restores.pop()
        return restored

    def accept(
        self,
        key: str,
        ordinal: int,
        cast_time: float,
        *,
        resource_before: float,
        resource_restored: float,
        resource_after: float,
    ) -> int:
        """Admit one cast and return its accepted ordinal."""
        accepted_ordinal = len(self.accepted[key])
        self.accepted[key].append(cast_time)
        self.accepted_ordinals[key].add(ordinal)
        if not self.score_only:
            # Per-cast resource rows serve only the public cast-timeline
            # receipt; nothing on the scoring path reads them.
            self.resource_by_cast[(key, accepted_ordinal)] = {
                "resource_before": resource_before,
                "resource_restored": resource_restored,
                "resource_after": resource_after,
            }
        return accepted_ordinal

    def cast_plan(self, *, resource_remaining: float, **extra: Any) -> CastPlan:
        """The admitted plan, with whatever receipts the walk's lane adds."""
        counts = {key: len(times) for key, times in self.accepted.items()}
        last_cast_time = max(
            (time for times in self.accepted.values() for time in times), default=0.0
        )
        return CastPlan(
            counts=counts,
            times={key: tuple(times) for key, times in self.accepted.items()},
            last_cast_time=last_cast_time,
            resource_spent=self.spent,
            resource_remaining=resource_remaining,
            omitted_for_resource=tuple(self.omitted),
            resource_by_cast=self.resource_by_cast,
            **extra,
        )
