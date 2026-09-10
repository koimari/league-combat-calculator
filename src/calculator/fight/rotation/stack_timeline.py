"""When a stacking damage-over-time stack lands, and everything that gates it.

**Case 4 — Hit-timeline stacking DoT** (e.g. Briar passive):
    One entry (usually the passive) declares the DoT::

        "stacking_dot": {
            "name": "Crimson Curse (bleed)",
            "damage_type": "physical",
            "single_stack_raw": 100.0,   # one stack's total over duration
            "duration": 5.0,
            "max_stacks": 5,
            "extra_stack_effectiveness": 0.25,
            "applied_by_autos": True,
        }

    and each castable whose applications add a stack carries
    ``"applies_dot_stack": True``. ``_build_stack_timeline`` builds the
    fight's hit timeline — autos at attack-speed intervals plus ability
    applications at their cast times (t=0 in one-rotation mode) — and
    ``_add_stacking_dot_damage`` integrates the tick rate at the running
    stack count: ``single_dps x (1 + extra_eff x (stacks - 1))``, stacks
    capped at ``max_stacks``. Every application refreshes the shared
    duration; a gap longer than ``duration`` expires the chain.
    Accounting is COMMITTED: the last hit's full ``duration`` of ticks
    counts even past the fight cutoff. An ``empowers_next_auto``
    applier's swing is one of the fight's autos, so its stack rides the
    auto timeline (it is only counted separately when there is no auto
    stream).

**Case 5 — Stack-triggered mid-fight steroid** (e.g. Darius' Noxian
Might): the same entry may declare::

        "stack_triggered_buff": {
            "name": "Noxian Might",
            "trigger_stacks": 5,
            "duration": 5.0,
            "bonus_attack_damage": 280.0,
        }

    Every application that lands ON ``trigger_stacks`` opens (or
    refreshes) a ``duration``-second window of bonus AD, derived from
    the SAME ``StackTimeline`` the DoT integrates — one home for "when
    does a stack land". Casts, autos and DoT ticks inside a window are
    priced against the buffed AD: a part declares how it reacts with
    ``DamagePart.bonus_ad_ratio`` (its derivative in bonus AD), the DoT
    with ``single_stack_bonus_ad_ratio``. The application that opens a
    window is NOT itself buffed — the buff is triggered BY its damage.
    A part may also declare ``dot_stack_scaled`` to hit once per stack
    on the target when the cast lands (Darius R's per-stack bonus).
"""

from typing import Any

from ...ability_atoms import ability_field
from ..autos.swing_schedule import _auto_attack_timestamps
from ..results import CastPlan, StackApplication, StackTimeline
from ..state import FightState


def _find_stacking_dot(state: FightState) -> tuple[str, dict[str, Any]] | None:
    """The entry declaring the fight's stacking DoT — one per champion."""
    return next(
        (
            (key, info["stacking_dot"])
            for key, info in state.ability_damages.items()
            if "stacking_dot" in info
        ),
        None,
    )


def _stack_application_times(
    state: FightState,
    plan: CastPlan,
    spec: dict[str, Any],
) -> list[tuple[float, tuple[str, int] | None, int | None]]:
    """Every stack application as ``(time, cast slot, auto index)``.

    Ability applications land at their cast times (all t=0 in
    one-rotation mode); an ``empowers_next_auto`` applier's swing IS one
    of the fight's autos, so its stack rides the auto timeline whenever
    one exists. Sorting is stable, so casts keep cast order within one
    instant and autos follow them.
    """
    applications: list[tuple[float, tuple[str, int] | None, int | None]] = []
    for ability_key in state.cast_order:
        info = state.ability_damages.get(ability_key)
        if info is None or not info.get("applies_dot_stack"):
            continue
        if info.get("empowers_next_auto") and state.num_auto_attacks > 0:
            continue
        for ordinal, cast_time in enumerate(plan.times[ability_key]):
            applications.append((cast_time, (ability_key, ordinal), None))

    if (
        ability_field(spec, "applied_by_autos", form="stacking_dot")
        and state.num_auto_attacks > 0
    ):
        applications.extend(
            (time, None, index)
            for index, time in enumerate(_auto_attack_timestamps(state))
        )

    applications.sort(key=lambda application: application[0])
    return applications


def _build_stack_timeline(state: FightState, plan: CastPlan) -> StackTimeline | None:
    """Walk the fight's stack applications once, deriving everything.

    Stack rules (shared by every consumer): each application adds a
    stack up to ``max_stacks`` and refreshes the shared window; a gap of
    ``duration`` or more expires the chain. An application that lands ON
    ``trigger_stacks`` opens or refreshes the stack-triggered steroid
    (Darius' Noxian Might) — including a reapplication at max stacks, so
    holding the target at max holds the buff. Returns None when the
    champion declares no stacking DoT.

    A ``starting_stacks`` spec seeds the target's pre-fight stacks. They
    were put on by pre-fight hits, so if they already meet
    ``trigger_stacks`` the fight opens with the steroid running — the
    t=0 casts are buffed by a window they did not open themselves.
    """
    found = _find_stacking_dot(state)
    buff = next(
        (
            info["stack_triggered_buff"]
            for info in state.ability_damages.values()
            if "stack_triggered_buff" in info
        ),
        None,
    )
    if found is None:
        if buff is not None:
            # The buff is triggered BY stacks; with no stacking DoT to
            # count them it could never fire, and would silently grant
            # nothing rather than failing loudly.
            buff_name = ability_field(buff, "name", form="stack_triggered_buff")
            raise ValueError(
                f"stack_triggered_buff {buff_name!r} declared "
                "without a stacking_dot to trigger it — the buff has no "
                "stack source"
            )
        return None
    dot_key, spec = found

    duration = float(spec["duration"])
    max_stacks = int(spec["max_stacks"])
    trigger_stacks = int(buff["trigger_stacks"]) if buff else 0
    buff_duration = float(buff["duration"]) if buff else 0.0
    buff_bonus_ad = float(buff["bonus_attack_damage"]) if buff else 0.0

    starting_stacks = min(
        int(ability_field(spec, "starting_stacks", form="stacking_dot")), max_stacks
    )

    applications: list[StackApplication] = []
    by_cast: dict[tuple[str, int], int] = {}
    by_auto: dict[int, int] = {}
    windows: list[list[float]] = []
    stacks = starting_stacks
    previous_time = 0.0
    buff_until = 0.0  # never active before the first trigger (times >= 0)
    if buff is not None and starting_stacks > 0 and starting_stacks >= trigger_stacks:
        # Pre-fight hits reached the trigger, so the window is already
        # running when the fight opens.
        buff_until = buff_duration
        windows.append([0.0, buff_until])

    for time, cast_slot, auto_index in _stack_application_times(state, plan, spec):
        if stacks > 0 and time - previous_time >= duration:
            stacks = 0
        stacks_before = stacks
        # The application that opens a window is not itself buffed: the
        # steroid is triggered BY the damage this hit deals.
        active_ad = buff_bonus_ad if time < buff_until else 0.0
        stacks = min(stacks + 1, max_stacks)
        if cast_slot is not None:
            by_cast[cast_slot] = len(applications)
        if auto_index is not None:
            by_auto[auto_index] = len(applications)
        applications.append(StackApplication(time, stacks_before, stacks, active_ad))
        if buff is not None and stacks >= trigger_stacks:
            buff_until = time + buff_duration
            if windows and time <= windows[-1][1]:
                windows[-1][1] = buff_until
            else:
                windows.append([time, buff_until])
        previous_time = time

    return StackTimeline(
        dot_key=dot_key,
        spec=spec,
        applications=tuple(applications),
        buff_windows=tuple((start, end) for start, end in windows),
        buff_bonus_ad=buff_bonus_ad,
        buff_name=str(buff["name"]) if buff else "",
        starting_stacks=starting_stacks,
        _by_cast=by_cast,
        _by_auto=by_auto,
    )
