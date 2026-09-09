"""A passive a cast arms and a later action spends.

**Case 2b — Cast-armed proc windows** (Taric P Bravado, Milio P Fired
Up!): a passive that a CAST arms and a later ACTION spends declares an
``empower_window`` inside its ``on_hit`` payload::

        "on_hit": {
            "name": "Bravado (on-attack)",
            "damage_per_hit": 63.0,
            "damage_type": "magic",
            "empower_window": {
                "armed_by": ("Q", "W", "E", "R"),
                "duration": 5.0,
                "charges_per_arm": 2,
                "max_charges": 2,
                "consumed_by": ("auto",),
                "refresh_on_consume": True,
            },
        }

    ``_empower_window_procs`` walks the accepted cast timeline against
    the fight's consuming actions (``"auto"`` swings and ``"ability_hit"``
    instances) and returns one timestamp per charge actually spent. This
    is the DEDUP mechanism ``empowers_next_auto`` lacks: that key
    multiplies flatly by cast count, so two arming casts inside one live
    window would double-count a buff the source only refreshes. Charges
    add up to ``max_charges`` and every arm restarts ``duration``; with
    ``charges_per_arm == max_charges`` the window is pure refresh-not-
    stack. At an identical timestamp consumers are walked BEFORE arms so
    an action can never spend a charge armed at that same instant (a
    named conservative boundary — one-rotation mode collapses every cast
    to t=0). Like the other schedule-gated procs the row stays out of
    ``static_on_hit_per_hit``, so phantom hits, double shots, and the
    BoRK/spellblade per-auto simulations never re-apply it.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from operator import itemgetter
from typing import Any

from ...ability_atoms import ability_field
from ...ability_spec import AttackClass
from ...interpreters import on_hit_strike
from ...survival.pricing import AuthoredDeclaration
from ..resists import _mitigate
from ..results import RotationResult
from ..state import FightState
from .swing_schedule import _swings_at_rate


def _on_hit_declaration(item_name: str, raw_amount: float) -> tuple[Any, ...]:
    """One on-hit packet's declaration: rule, magnitude, attack class.

    ``AttackClass.OTHER`` is measured, not defaulted: all eight declared
    strikes reach the target through :func:`_mitigate` alone, so none earns a
    part amp, and ``StaticHolderAmps.factor_for`` delivers the magic amp off
    the damage type.  *raw_amount* already carries the carrying application's
    on-hit effectiveness, which allocates rather than amplifies."""
    return tuple(
        AuthoredDeclaration(
            on_hit_strike.strike_mechanic_id(item_name),
            raw_amount,
            AttackClass.OTHER.value,
        )
    )


# Timestamps inside this tolerance are the same instant. The engine
# stamps cast times rounded to milliseconds and derives swing times from
# a float rate, so an exact `==` would split events that the fight model
# considers simultaneous.
_EMPOWER_WINDOW_EPS = 1e-9


def _empower_window_procs(
    window: Mapping[str, Any],
    arm_times: Sequence[float],
    consumer_times: Sequence[tuple[float, str]],
) -> list[float]:
    """Consumed-charge timestamps of a cast-armed, refreshing proc window.

    The shared dedup primitive behind champion passives that arm a consumable
    buff on a CAST and spend it on a later ACTION (Taric's Bravado, Milio's
    Fired Up!).  ``empowers_next_auto`` cannot express them: it multiplies
    flatly by the cast count, so two arming casts inside one live window would
    double-count a buff the source says is only refreshed.

    Window semantics, all declared by the champion module from its cached
    wiki text:

    ``armed_by``
        Slots whose accepted casts arm the window, resolved by the caller.
    ``duration``
        Seconds the buff lives after the instant that (re)armed it.
    ``charges_per_arm`` / ``max_charges``
        An arming cast ADDS ``charges_per_arm`` charges, clamped to
        ``max_charges``, and restarts the duration. With
        ``charges_per_arm == max_charges`` this is exactly "refresh, do
        not stack" — Milio's "Subsequent applications of Fired Up! only
        refresh the duration" and Taric's "Bravado may only grant up to
        two empowered attacks".
    ``refresh_on_consume``
        Spending a charge also restarts the duration (Taric's "The first
        attack refreshes Bravado's duration"). Absent, the window keeps
        running from its last arm (Milio's flat 4 seconds).

    At an identical timestamp CONSUMERS are walked before ARMS, so an action
    can never consume a charge armed at that same instant.  One-rotation mode
    collapses every cast to t=0, and arming first there would let a
    simultaneous ability hit spend a buff that did not exist when it landed,
    the direction that INVENTS damage.  Returns one timestamp per consumed
    charge, in ascending time order."""
    duration = float(window["duration"])
    if duration <= 0.0:
        raise ValueError("An empower window must declare a positive duration")
    charges_per_arm = int(window["charges_per_arm"])
    max_charges = int(window.get("max_charges", charges_per_arm))
    if charges_per_arm < 1 or max_charges < 1:
        raise ValueError("An empower window must grant at least one charge")
    consumed_by = frozenset(window["consumed_by"])
    refresh_on_consume = bool(window.get("refresh_on_consume"))

    # Phase 0 = consumer, phase 1 = arm: the documented tie-break falls
    # out of the sort key instead of a special case inside the walk.
    events: list[tuple[float, int, str]] = [
        (float(time), 0, kind) for time, kind in consumer_times if kind in consumed_by
    ]
    events.extend((float(time), 1, "") for time in arm_times)
    events.sort(key=itemgetter(0, 1))

    procs: list[float] = []
    charges = 0
    expires_at = float("-inf")
    for time, phase, _kind in events:
        if charges > 0 and time > expires_at + _EMPOWER_WINDOW_EPS:
            charges = 0  # the window lapsed before this event
        if phase == 1:
            charges = min(charges + charges_per_arm, max_charges)
            expires_at = time + duration
        elif charges > 0:
            procs.append(time)
            charges -= 1
            if refresh_on_consume:
                expires_at = time + duration
    return procs


def _uniform_swing_schedule(state: "FightState", num_auto_attacks: int) -> list[float]:
    """Even swing times when the authored schedule is unresolvable.

    The same fallback the scheduled current-health procs use: rows that
    ride it stay coarse in timing but keep an exact count.
    """
    if num_auto_attacks <= 0:
        return []
    autos_per_second = state.attack_speed * state.auto_attack_uptime
    if autos_per_second <= 0:
        return []
    return _swings_at_rate(num_auto_attacks, autos_per_second)


# pylint: disable-next=too-many-arguments,too-many-positional-arguments,too-many-locals
def _add_empower_window_on_hit(
    state: "FightState",
    rotation: "RotationResult",
    ability_key: str,
    on_hit_data: Mapping[str, Any],
    *,
    auto_times: Sequence[float],
    ability_hit_times: Sequence[float],
    effectiveness: float,
    swing_event_row: Callable[[list[float], list[float], str], dict[str, Any]],
) -> float:
    """Price one cast-armed empower window and author its breakdown row.

    Resolves the arming casts from the accepted cast timeline, walks the
    dedup primitive over the fight's consuming actions, and prices ONE
    flat packet per consumed charge. The row is deliberately kept out of
    ``static_on_hit_per_hit``: schedule-gated procs do not land on every
    auto, so Rageblade phantoms, double shots, and the BoRK/spellblade
    per-auto simulations must not re-apply them (the same rule the
    ``proc_cooldown`` / ``proc_window`` schedules follow).

    Returns the mitigated damage added to the fight total.
    """
    window = on_hit_data["empower_window"]
    # Fail closed on a packet the module forgot to price: an armed window
    # with no damage key is a broken declaration, not a zero-damage one,
    # and must never be read as "this passive deals nothing".
    if "damage_per_hit" not in on_hit_data:
        raise KeyError(
            f"{ability_key} declares an empower_window without "
            "'damage_per_hit'; a cast-armed proc must price its packet"
        )
    raw_base = float(on_hit_data["damage_per_hit"])
    if raw_base <= 0.0:
        return 0.0

    armed_by = frozenset(window["armed_by"])
    arm_times = [
        float(event["time"])
        for event in rotation.cast_events
        if event.get("slot") in armed_by
    ]
    consumers: list[tuple[float, str]] = [(time, "auto") for time in auto_times]
    consumers.extend((time, "ability_hit") for time in ability_hit_times)
    proc_times = _empower_window_procs(window, arm_times, consumers)
    if not proc_times:
        return 0.0

    damage_type = str(ability_field(on_hit_data, "damage_type", form="on_hit"))
    # Scaled by the fight's on-hit effectiveness for the same reason every
    # other champion on-hit row is (a proxy attacker's reduced on-hit
    # application, e.g. Azir soldiers); it is 1.0 for an ordinary attacker.
    per_proc = _mitigate(
        raw_base * effectiveness, damage_type, state.resists, state.magic_amp
    )
    total = per_proc * len(proc_times)
    row = {
        "name": on_hit_data.get("name", f"{ability_key} (on-hit)"),
        "count": len(proc_times),
        "damage_per_hit": per_proc,
        "total_damage": total,
        "damage_type": damage_type,
        "unit": "procs",
    }
    # Each charge is spent by one dated action, so the row carries an exact
    # event ledger. The auto phase is the shared on-hit phase; a charge
    # spent by an ability hit still lands at that hit's own timestamp.
    row.update(
        swing_event_row(list(proc_times), [per_proc] * len(proc_times), damage_type)
    )
    state.breakdown[f"on_hit_ability_{ability_key}"] = row
    return total


def _declared_slot_stacks(
    on_hit_data: Mapping[str, Any],
    ability_hit_ledger: Iterable[tuple[str, float]],
) -> tuple[int, list[float]]:
    """Stacks a kit's own named slots feed one on-hit counter.

    ``count_ability_hits`` counts every damaging ability hit the rotation
    landed, which is the whole kit; a counter that only some slots feed
    declares them instead — ``{"W": 2}`` is Xin Zhao's Wind Becomes
    Lightning, whose first slash hit and thrust each generate a
    Determination stack, and whose row is one aggregate hit at the cast.
    A stack is generated by a landed HIT, so the count rides that slot's
    own entries in the ability ledger: every stack carries the timestamp
    of the hit that made it, and a slot the ledger never saw feeds nothing
    rather than inventing a boundary.
    """
    declared = ability_field(on_hit_data, "ability_stack_slots", form="on_hit")
    if not declared:
        return 0, []
    stacks = 0
    times: list[float] = []
    for slot, per_hit_stacks in sorted(declared.items()):
        count = int(per_hit_stacks)
        if count <= 0:
            continue
        slot_times = [time for key, time in ability_hit_ledger if key == slot]
        stacks += count * len(slot_times)
        times.extend(time for time in slot_times for _ in range(count))
    return stacks, times
