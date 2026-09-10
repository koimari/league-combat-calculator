"""The one non-mana account: a clamped pool with a temporary maximum."""

import heapq

from ... import item_effects
from ...ability_atoms import ability_field
from ...interpreters.sustain import declared_sustain
from ...item_behavior import ManaSpentHealRule
from ..results import CastPlan
from ..state import FightState
from .cast_plan import _cast_admission_events, _CastAdmission, _resource_timeline
from .cast_schedule import _CAST_SCHEDULE_EPS


def _apply_energy_resource_limits(state: FightState, plan: CastPlan) -> CastPlan:
    """Admit ENERGY casts against a plain account with a temporary maximum.

    Energy has no ledger receipts of its own: the one mechanic beyond regen
    and spend is the temporary maximum bonus (Akali's W), which the typed
    account cannot hold, so the walk carries a running ``remaining`` rather
    than a ``resource_ledger`` account.  The pool is clamped into the live
    maximum on every pop, the bonus's expiry included.
    """
    base_maximum = float(state.champion_stats["max_mana"])
    remaining = base_maximum
    regen = float(state.champion_stats["resource_regen_per_second"])
    events = _cast_admission_events(state, plan)

    admission = _CastAdmission(state, plan)
    previous_time = 0.0
    maximum_bonus = 0.0
    maximum_bonus_until = -1.0

    schedule_owners = sorted(
        {item_effects.resolved_item_name(item) for item in state.items}
    )
    # The key slot of a restore row is the producer, read off the same
    # declaration the ledger built the row from
    # (``roster_composition.resource_restores``) rather than spelled.  Empty
    # where this build declares none, which is the case where the rows came
    # from a caller staging them directly.
    restore_slot = declared_sustain(schedule_owners, ManaSpentHealRule)
    timeline = _resource_timeline(
        state,
        events,
        restore_producer="" if restore_slot is None else restore_slot.owner,
    )
    heapq.heapify(timeline)
    while timeline:
        (
            cast_time,
            _phase,
            _order_index,
            ordinal,
            kind,
            key,
            restore_amount,
        ) = heapq.heappop(timeline)
        maximum = base_maximum + (
            maximum_bonus if cast_time < maximum_bonus_until else 0.0
        )
        remaining = min(
            maximum, remaining + max(0.0, cast_time - previous_time) * regen
        )
        previous_time = cast_time
        if kind == "maximum_expiry":
            # The temporary maximum ended.  The pop above already re-read the
            # maximum and clamped ``remaining`` into it, which is the whole
            # transition: a pool that outlived its bonus returns to base.
            continue
        if kind == "restore":
            remaining = min(maximum, remaining + restore_amount)
            continue
        info = state.ability_damages[key]
        if admission.recast_parent_denied(info, ordinal):
            admission.omit(key)
            continue
        cost = float(ability_field(info, "resource_cost"))
        if (
            cost > 0.0
            and state.actualizer_active_until > cast_time + _CAST_SCHEDULE_EPS
        ):
            cost *= state.actualizer_resource_cost_multiplier
        if cost > remaining + _CAST_SCHEDULE_EPS:
            admission.omit(key)
            continue
        before = remaining
        remaining -= cost
        admission.spent += cost
        cast_maximum_bonus = float(ability_field(info, "resource_maximum_bonus"))
        if cast_maximum_bonus > 0:
            maximum_bonus = max(maximum_bonus, cast_maximum_bonus)
            maximum_bonus_until = max(
                maximum_bonus_until,
                cast_time
                + float(ability_field(info, "resource_maximum_bonus_duration")),
            )
            maximum = base_maximum + maximum_bonus
            # The bonus is temporary, so its END is an event: without one a
            # pool raised above base stays there for every reader after the
            # last cast (Akali holding 300 of a 200 pool once the shroud is
            # gone).  It rides the restore tier, matching the ``cast_time <
            # maximum_bonus_until`` rule this walk admits by; a refresh
            # leaves the stale row in place, where it clamps nothing.
            if maximum_bonus_until <= state.fight_duration_seconds + _CAST_SCHEDULE_EPS:
                heapq.heappush(
                    timeline,
                    (maximum_bonus_until, 0, -3, ordinal, "maximum_expiry", key, 0.0),
                )

        restored = admission.restore_for(info)
        remaining = min(maximum, remaining + restored)
        admission.accept(
            key,
            ordinal,
            cast_time,
            resource_before=before,
            resource_restored=restored,
            resource_after=remaining,
        )

    return admission.cast_plan(resource_remaining=remaining)
