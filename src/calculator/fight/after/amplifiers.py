"""Fight-wide amplifiers applied after the ledger, whole-total to Expose Weakness."""

import math
from collections.abc import Mapping
from typing import Any

from ...interpreters import amp_magnitude
from ...item_behavior import AmpChainSlot, Isolation
from ...trigger_stream import is_immobilizing_event
from ..cast_slots import _damaging_cast_times
from ..ledger.event_ledger import _ordered_damage_events
from ..ledger.event_rows import _CAST_TIME_RESOLUTION
from ..results import RotationResult, SpellbladeResult
from ..runes.amplifiers import (
    _add_rune_conditional_amp_damage,
    _add_rune_flat_amp_damage,
)
from ..state import FightState
from .amp_chain import (
    _amp_slot,
    _amp_slot_for,
    _amplifier_delta_events,
    _record_amp_row,
)


def _expose_weakness_pool(state: FightState, rotation: RotationResult) -> list[Any]:
    """The ledger events Expose Weakness amplifies: everything after its arming proc.

    The arming sequence completes when the first spellblade proc lands
    (``Isolation.TRIGGER_SEQUENCE``), so the buff rides every later ledger
    event at that event's own time.  A true-conversion build's first procs
    live on the ``_true`` sibling row (Camille), so the boundary is the
    earliest event of either.  Without an authored proc boundary, or with
    nothing behind it, the pool is empty.
    """
    assert state.item_spellblade is not None
    proc_key = state.item_spellblade.source.breakdown_key
    proc_keys = {proc_key, f"{proc_key}_true"}
    ledger = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
        roster_target_index=state.roster_target_index,
        light=True,
    )
    boundary = min((row[0] for row in ledger if row[3] in proc_keys), default=None)
    if boundary is None:
        return []
    return [row for row in ledger if row[0] > boundary]


def _add_expose_weakness(
    state: FightState,
    rotation: RotationResult,
    spellblade: SpellbladeResult,
) -> None:
    """Add Bloodsong's Expose Weakness amp on damage after the first proc.

    This is the **pair engine's reading** of the mechanic, and the walk's is
    different: it arms a timed modifier per proc, on a cooldown, for every
    roster attacker.  The walk's is the answer, because the pool of amplified
    damage is a roster fact, so this row is a declared *preview*: the honest
    one-attacker-versus-one-defender figure, published in the pair fight's own
    receipt and excluded from everything the roster composes.  The row says
    which mechanic it previews and ``trigger_stream`` says that mechanic's
    pair number is ``THEORETICAL``; neither statement alone demotes it.

    The preview is priced from its own ledger: the bonus is the rate over
    the events after the arming proc, so the row's number and the events it
    authors are the one pool, and a window whose ledger holds nothing after
    that proc has no row at all.

    What is declared here is the exclusion, the chain that armed the buff,
    and the rate.
    """
    if not (spellblade.item and spellblade.procs > 0):
        return
    slot = _amp_slot_for(state, AmpChainSlot.EXPOSE_WEAKNESS, [spellblade.item])
    if slot is None:
        return
    if slot.exclusion() is not Isolation.TRIGGER_SEQUENCE:
        raise amp_magnitude.DeltaAmpInterpretationError(
            f"{slot.owner} declares the {slot.exclusion().value} exclusion and "
            "this engine only knows how to subtract a whole arming sequence"
        )
    expose_rate = slot.bonus_fraction
    if expose_rate <= 0:
        return

    # The arming sequence — the first ability cast, the first auto that
    # consumed it and the first spellblade proc — lands before the buff is
    # up, which is what ``Isolation.TRIGGER_SEQUENCE`` says, so the pool
    # starts after the proc that completed it.
    amped = _expose_weakness_pool(state, rotation)
    expose_bonus = sum(row[1] for row in amped) * expose_rate
    if expose_bonus <= 0:
        return

    state.breakdown[f"expose_weakness_{slot.owner}"] = {
        "name": f"{slot.owner} (Expose Weakness)",
        "amplifier": slot.multiplier,
        "total_damage": expose_bonus,
        "damage_type": "mixed",
        # Which mechanic this row is the pair engine's reading of, taken from
        # the rule the slot resolved rather than spelled again here.  The
        # roster composition reads it; the pair receipt publishes the row
        # regardless.
        "pair_preview_of": slot.rules[0].mechanic_id,
        "damage_events": _amplifier_delta_events(amped, expose_bonus),
        "event_phase": "amplifier",
    }
    state.total_damage += expose_bonus


def _hypershot_delta_events(
    state: FightState,
    rotation: RotationResult,
    bonus: float,
) -> list[dict[str, Any]]:
    """Author Horizon Focus's amp onto every event after the trigger cast.

    The first ability cast triggers Hypershot and is not amped, so its
    ledger events are excluded from the attribution pool. If the trigger
    cast cannot be isolated to events matching the rotation's recorded
    trigger damage (e.g. a mixed-type opener whose non-triggering part is
    amped), no events are authored and the row stays explicitly coarse.
    """
    events = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
        roster_target_index=state.roster_target_index,
        light=True,
    )
    trigger_key = next(
        (
            k
            for k in state.cast_order
            if k in state.breakdown
            and float(state.breakdown[k].get("total_damage", 0.0)) > 0.0
        ),
        None,
    )
    trigger_times = [row[0][0] for row in events if row[3] == trigger_key]
    if trigger_key is None or not trigger_times:
        return []
    trigger_time = min(trigger_times)

    trigger_rows = [
        (index, row)
        for index, row in enumerate(events)
        if row[3] == trigger_key and row[0][0] == trigger_time
    ]
    trigger_event_index = next(
        (
            index
            for index, row in trigger_rows
            if math.isclose(
                row[1], rotation.first_ability_damage, rel_tol=1e-6, abs_tol=1e-3
            )
        ),
        None,
    )
    if trigger_event_index is not None:
        excluded = {trigger_event_index}
    elif str(state.breakdown[trigger_key].get("damage_type", "")) != "mixed":
        # A first cast split into several ledger events (multi-hit or
        # multi-tick opener) matches no single event.  The accepted cast
        # ledger scopes the trigger cast instead: every trigger-slot event
        # landing before that slot's second cast belongs to the cast that
        # armed Hypershot.  A mixed opener is the one shape whose priced
        # trigger is a PART of its cast (the non-triggering part IS
        # amped), so it must resolve above or stay coarse.
        slot_cast_times = sorted(
            float(event["time"])
            for event in rotation.cast_events
            if isinstance(event, Mapping) and event.get("slot") == trigger_key
        )
        next_cast_boundary = (
            slot_cast_times[1] - _CAST_TIME_RESOLUTION - 1e-9
            if len(slot_cast_times) > 1
            else float("inf")
        )
        excluded = {
            index
            for index, row in enumerate(events)
            if row[3] == trigger_key and row[0][0] < next_cast_boundary
        }
    else:
        return []
    return _amplifier_delta_events(
        [row for index, row in enumerate(events) if index not in excluded],
        bonus,
    )


def _apply_general_amplifiers(state: FightState, rotation: RotationResult) -> None:
    """Apply whole-total amps — the ``WHOLE_TOTAL`` chain slot.

    Its occupants are additive among themselves, so the slot resolves to one
    multiplier over the running total. Each source still gets its own
    ``damage_amp_<source>`` row, whose delta events ride the pre-amp ledger's
    timestamps.
    """
    slot = _amp_slot(state, AmpChainSlot.WHOLE_TOTAL)
    if slot is None:
        return
    amp_sources = slot.sources()
    amp = slot.multiplier
    if amp <= 1.0:
        return
    amp_bonus = state.total_damage * (amp - 1.0)
    amped_events = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
        roster_target_index=state.roster_target_index,
        light=True,
    )
    # Create per-source breakdown entries
    for source_name, source_amp in amp_sources:
        if source_amp > 0:
            source_bonus = state.total_damage * source_amp
            row = {
                "name": f"Damage Amplification ({source_name})",
                "multiplier": 1.0 + source_amp,
                "total_damage": source_bonus,
            }
            delta_events = _amplifier_delta_events(amped_events, source_bonus)
            if delta_events:
                row["damage_events"] = delta_events
                row["event_phase"] = "amplifier"
            state.breakdown[f"damage_amp_{source_name}"] = row
    state.total_damage += amp_bonus


def _apply_damage_amplifiers(state: FightState, rotation: RotationResult) -> None:
    """Apply fight-wide damage amplifiers and their breakdown rows.

    General amps (Lord Dominik's Regards, Riftmaker-class) multiply the
    whole running total, one ``damage_amp_<source>`` row per source. The
    Actualizer ability amp was already applied per-ability/per-proc, so
    its row is informational only. Horizon Focus amplifies everything
    except the first ability cast (the trigger). Each amp row authors its
    delta back onto the events it amplified, at their times, so shield
    and threshold accounting sees the amp when the damage landed; a row
    whose amplified pool cannot be event-isolated stays coarse and rides
    the ledger's explicit untyped fail-soft instead. The rune amps bracket
    the item ones: a flat rune amp prices the fight's own damage and so runs
    first, while a health-gated one wants the whole ledger behind it and so
    runs last.
    """
    breakdown = state.breakdown
    # Flat rune amps first: they price the ledger as the fight left it, and
    # every amplifier below compounds on the bonus they book.
    _add_rune_flat_amp_damage(state, rotation)
    _apply_general_amplifiers(state, rotation)

    # Actualizer ability damage amp — show as separate breakdown entry.
    # The amp was already applied per-ability in the rotation and per-proc
    # in the item-proc step, so this entry is informational only (damage
    # already counted).
    if state.ability_amp > 1.0:
        # Sum exactly the rows the amp multiplied: rotation ability rows
        # (cast_order keys) and is_ability_damage item procs
        # (Stormsurge / Zaz'Zak). Burns, on-hits, spellblades and
        # other item rows are never ability-amped and must not be counted.
        amped_keys = set(state.cast_order)
        amped_keys.update(
            effect.source.breakdown_key
            for effect in state.declared.cast_procs.cooldown_procs
            if effect.source.is_ability_damage
        )
        amped_base = sum(
            v.get("total_damage", 0)
            for k, v in breakdown.items()
            if isinstance(v, dict) and k in amped_keys
        )
        # The amplified damage = base * amp, so the amp contribution is
        # base * (amp - 1) / amp  (since base already includes the amp).
        actualizer_bonus = amped_base * (state.ability_amp - 1.0) / state.ability_amp
        amp_name = state.ability_amp_owner
        breakdown[f"ability_amp_{amp_name}"] = {
            "name": f"Damage Amplification ({amp_name})",
            "multiplier": state.ability_amp,
            "total_damage": actualizer_bonus,
            "detail": "included in ability/proc totals above",
            "informational": True,
        }

    # Imperial Mandate's Command: the holder's own post-immobilize amp.
    _apply_command_amp(state, rotation)

    # Hypershot: amp all damage except the first ability cast (the first
    # ability triggers the mark; its own damage is not amped).  The exclusion
    # is the rule's declared ExcludeTrigger activation and the multiplier is
    # its declared magnitude; the engine supplies only the ledger.  Its
    # trigger is an ability hit, so a window with no accepted damaging cast
    # never arms it: the row is absent, not a coarse amp over the auto
    # stream.
    hypershot = _amp_slot(state, AmpChainSlot.HYPERSHOT)
    if (
        hypershot is not None
        and hypershot.multiplier > 1.0
        and _damaging_cast_times(state, rotation)
    ):
        amped_damage = state.total_damage - rotation.first_ability_damage
        hypershot_bonus = amped_damage * (hypershot.multiplier - 1.0)
        # The one amp whose pool is not a row list: the trigger cast is
        # excluded by re-walking the ledger, so it authors its own deltas.
        row: dict[str, Any] = {
            "name": f"Damage Amplification ({hypershot.owner})",
            "multiplier": hypershot.multiplier,
            "total_damage": hypershot_bonus,
        }
        delta_events = _hypershot_delta_events(state, rotation, hypershot_bonus)
        if delta_events:
            row["damage_events"] = delta_events
            row["event_phase"] = "amplifier"
        breakdown[f"damage_amp_{hypershot.owner}"] = row
        state.total_damage += hypershot_bonus

    # Health-gated rune amps last: their gate reads the target's current
    # health, so they want the whole fight's ledger behind them.
    _add_rune_conditional_amp_damage(state, rotation)


def _apply_command_amp(state: FightState, rotation: RotationResult) -> None:
    """Price Imperial Mandate's Command for the holder's own fight.

    An authored immobilize event (Syndra E's stun, Ahri's Charm, …) marks
    the target *Vulnerable*: every packet inside the window the immobilize
    opened takes the amp. Without an authored immobilize event the row is
    absent — the amp fails closed exactly like the coupled walk's packet,
    which requires the same reviewed ``cc_kind`` marker. The walk's
    cross-participant packet carries the holder as ``owner`` so this row and
    the walk multiplier can never both price the holder's damage.

    The window's duration, how a second immobilize merges with it and which
    side of its expiry is inside are all the rule's declaration
    (``TriggerWindow(IMMOBILIZE, merge=REFRESH, boundary=OPEN_CLOSED)``); the
    engine supplies only the immobilize timestamps and the ledger.
    """
    slot = _amp_slot(state, AmpChainSlot.POST_IMMOBILIZE)
    if slot is None:
        return
    cc_times = sorted(
        float(event["time"])
        for entry in state.breakdown.values()
        if isinstance(entry, dict)
        for event in entry.get("damage_events") or ()
        if isinstance(event, dict) and is_immobilizing_event(event)
    )
    if not cc_times:
        return
    windows = slot.trigger_windows(cc_times)
    events = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
        roster_target_index=state.roster_target_index,
        light=True,
    )
    amped = [row for row in events if slot.window_holds(windows, row[0][0])]
    bonus = sum(row[1] for row in amped) * slot.bonus_fraction
    if bonus <= 0.0:
        return
    # Shares the ``damage_amp_<source>`` key namespace with
    # ``_apply_general_amplifiers``; item names keep the keys distinct.
    _record_amp_row(
        state,
        f"damage_amp_{slot.owner}",
        f"{slot.owner} — Command",
        slot.multiplier,
        amped=amped,
        bonus=bonus,
    )
