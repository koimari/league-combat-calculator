"""First Strike, Press the Attack and Conqueror: stacks that become an amplifier."""

import math
from collections.abc import Mapping
from typing import Any

from ... import rune_effects
from ...item_behavior import AmpChainSlot
from ...state_lifecycle import TriggerGate
from ...state_timeline import EventStamp
from ..after.amp_chain import _required_amp_slot
from ..autos.swing_schedule import _auto_attack_timestamps
from ..config import declared_option_default
from ..ledger.breakdown import _is_auto_stream_key
from ..ledger.coverage import _event_timeline_coverage
from ..ledger.event_ledger import _ordered_damage_events
from ..results import RotationResult
from ..state import FightState
from .streams import _page_effects, _record_rune_proc_row


def _certified_only_pool(
    state: FightState, rotation: RotationResult
) -> tuple[list[dict[str, Any]], set[str], list[str]]:
    """Build the ``Pool.CERTIFIED_ONLY`` event pool, with what it excluded.

    A rule declaring ``Pool.CERTIFIED_ONLY`` prices only sources that carry
    certified event times; coarse-timed rows (DoTs whose totals resolve past
    their cast, item effects with no authored events, auto-coupled casts) are
    excluded and disclosed, so omitting a source can only understate a bonus
    and never overstate it.  The pool constructor is named for the declared
    pool rather than for the ledger it reads, so "certified" has one
    structural definition — ``_event_timeline_coverage``'s — and every rule
    that names the pool gets that one.
    """
    events = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
        roster_target_index=state.roster_target_index,
    )
    coverage = _event_timeline_coverage(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        num_auto_attacks=state.num_auto_attacks,
    )
    return events, set(coverage["exact_sources"]), coverage["coarse_sources"]


def _add_rune_window_amp_damage(state: FightState, rotation: RotationResult) -> None:
    """Price every selected opening-window rune (First Strike-class)."""
    for effect in _page_effects(state, rune_effects.RuneWindowAmpEffect):
        _price_rune_window_amp(state, rotation, effect)


def _price_rune_window_amp(
    state: FightState,
    rotation: RotationResult,
    effect: "rune_effects.RuneWindowAmpEffect",
) -> None:
    """Add one opening-window rune's bonus damage (First Strike-class).

    The buff activates once at combat start — a continuous fight never
    re-enters combat, so the rune's out-of-combat cooldown is moot. Its
    bonus is a sourced ratio of the post-mitigation damage dealt inside
    the opening window, read from the ordered damage ledger, and lands
    as true damage. The gold it generates (flat activation gold plus the
    melee/ranged share of the bonus) is reported on the breakdown row
    and in the fight notes; gold is not damage and never joins the total.

    Runs after every damage row exists and before fight-wide amplifiers:
    amp rows carry no event times, so the window is summed pre-amp — a
    conservative understatement whenever an amplifier is active.
    """
    window = _required_amp_slot(state, AmpChainSlot.OPENING_WINDOW, effect)
    # The pool, the window and the ratio are the rule's; the ledger is the
    # engine's. `Pool.CERTIFIED_ONLY` is why coarse-timed rows are excluded
    # and disclosed below.
    events, certified, coarse_sources = _certified_only_pool(state, rotation)
    _, window_end = window.window()
    contributing = [
        event
        for event in events
        if event["source_key"] in certified and event["time"] < window_end
    ]
    window_damage = sum(event["damage"] for event in contributing)

    bonus_ratio = window.fractions[0]
    bonus = bonus_ratio * window_damage
    gold = effect.activation_gold + effect.gold_conversion(state.is_melee) * bonus
    if window_damage > 0:
        auto_stream_damage = sum(
            event["damage"]
            for event in contributing
            if _is_auto_stream_key(event["source_key"])
        )
        state.breakdown[effect.breakdown_key] = {
            "name": effect.display_name,
            "total_damage": bonus,
            "damage_type": window.uniform_bonus_damage_type(),
            "count": 1,
            "event_phase": "effect",
            "gold_generated": gold,
            "auto_attack_fraction": auto_stream_damage / window_damage,
            "damage_events": [
                {
                    "time": event["time"],
                    "damage": bonus_ratio * event["damage"],
                    "damage_type": window.bonus_damage_type(event["damage_type"]),
                }
                for event in contributing
            ],
        }
        state.total_damage += bonus
    # The activation itself (and its flat gold) does not depend on any
    # window damage being certified — the notes always surface.
    state.notes.append(
        f"{effect.rune_name} assumes you initiate combat; it generated "
        f"{gold:.0f} gold ({effect.activation_gold:.0f} on activation plus "
        f"{effect.gold_conversion(state.is_melee) * 100:.0f}% of "
        f"{bonus:.0f} bonus true damage)."
    )
    if coarse_sources:
        state.notes.append(
            f"{effect.rune_name} window excludes sources without "
            f"certified event times ({', '.join(sorted(coarse_sources))}); "
            "its bonus is a floor, not an estimate."
        )


def _refreshing_stack_proc_times(
    state: FightState, effect: "rune_effects.RuneProcAmpEffect"
) -> tuple[list[float], bool]:
    """Walk the simulated auto swings with a refreshing stack rule.

    Only basic attacks stack this keystone class — ability casts never
    do. Every application refreshes all stacks, so the count survives
    while consecutive swings land within ``stack_duration_seconds`` of
    each other. Reaching the required stacks procs on that swing and
    clears them. Stacks are assumed not to build during the per-target
    cooldown — the wiki does not document this either way, and the
    assumption can only delay a proc, never invent one. Returns the
    proc times plus whether that assumption gated any swing, so the
    caller can disclose it.
    """
    proc_times: list[float] = []
    stacks = 0
    last_stack_time = float("-inf")
    gate = TriggerGate(effect.cooldown_seconds, inclusive=False)
    cooldown_gated = False
    for swing_time in _auto_attack_timestamps(state):
        if not gate.accepts(swing_time):
            cooldown_gated = True
            continue
        if swing_time - last_stack_time >= effect.stack_duration_seconds:
            stacks = 0
        stacks += 1
        last_stack_time = swing_time
        if stacks >= effect.stacks_required:
            proc_times.append(swing_time)
            gate.arm(swing_time)
            stacks = 0
    return proc_times, cooldown_gated


def _conqueror_trigger_events(
    state: FightState, rotation: RotationResult
) -> list[dict[str, Any]]:
    """Group certified ability casts and basic attacks into Conqueror hits.

    Conqueror grants one stack packet per ability cast instance. A multi-hit
    cast must not grant one packet per hit. Basic-attack and on-hit rows at
    one landing share one packet, so the max-stack heal sees the full
    post-mitigation attack damage.
    """
    ordered = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
        roster_target_index=state.roster_target_index,
    )
    detailed = [event for event in ordered if isinstance(event, Mapping)]
    ability_events = [
        event
        for event in detailed
        if event.get("is_ability") and float(event["damage"]) > 0.0
    ]
    cast_times: dict[str, list[float]] = {}
    for cast in rotation.cast_events:
        slot = str(cast.get("slot", ""))
        if slot in state.cast_order:
            cast_times.setdefault(slot, []).append(float(cast.get("time", 0.0)))

    triggers: list[dict[str, Any]] = []
    for slot, times in cast_times.items():
        slot_events = [
            event for event in ability_events if event.get("source_key") == slot
        ]
        for index, cast_time in enumerate(times):
            next_cast = times[index + 1] if index + 1 < len(times) else math.inf
            cast_events = [
                event
                for event in slot_events
                if cast_time - 1e-9 <= float(event["time"]) < next_cast - 1e-9
            ]
            if not cast_events:
                continue
            trigger_time = min(float(event["time"]) for event in cast_events)
            triggers.append(
                {
                    "time": trigger_time,
                    "sequence": min(int(event["sequence"]) for event in cast_events),
                    "source_key": slot,
                    "source": slot,
                    "damage": sum(float(event["damage"]) for event in cast_events),
                    "packet": "ability_cast",
                }
            )

    auto_events = [
        event
        for event in detailed
        if str(event.get("phase", "")) == "auto" and float(event["damage"]) > 0.0
    ]
    auto_groups: dict[float, list[Mapping[str, Any]]] = {}
    for event in auto_events:
        time = round(float(event["time"]), 9)
        auto_groups.setdefault(time, []).append(event)
    for time, events in auto_groups.items():
        triggers.append(
            {
                "time": time,
                "sequence": min(int(event["sequence"]) for event in events),
                "source_key": "auto_attacks",
                "source": "auto_attacks",
                "damage": sum(float(event["damage"]) for event in events),
                "packet": "basic_attack",
            }
        )
    return sorted(
        triggers,
        key=lambda event: (float(event["time"]), int(event["sequence"])),
    )


def _add_keystone_conqueror(state: FightState, rotation: RotationResult) -> None:
    """Add Conqueror's stack timeline and max-stack healing receipt.

    The stack timing is kernel-owned (state_lifecycle): the walk feeds the
    certified ability-cast and basic-attack trigger stream into a
    ``TimedStackState`` built from the rune's sourced stack rule, and the
    kernel owns gain, the 5-second expiry/refresh, the 4-second per-cast
    interval gate, and the max-stack cap.  The kernel's transition receipt
    (including expiries and interval denials) rides the breakdown row as
    ``state_transitions``.  Adaptive force stays a typed state receipt: the
    current ability evaluator prices champion formulas before this walk, so
    that force remains withheld until every AD/AP formula can be re-priced
    from a per-cast state.
    """
    effect = state.keystone_effect
    if not isinstance(effect, rune_effects.KeystoneConquerorEffect):
        return

    options = state.keystone_options
    unset = declared_option_default("keystone", "Conqueror", "starting_stacks")
    starting_stacks = int(options.get("starting_stacks", unset) or unset)
    triggers = _conqueror_trigger_events(state, rotation)
    stack_state = rune_effects.conqueror_stack_state(
        effect, starting_stacks=starting_stacks
    )
    stack_events: list[dict[str, Any]] = []
    heal_events: list[dict[str, Any]] = []
    for trigger in triggers:
        trigger_time = float(trigger["time"])
        transitions = stack_state.apply_gain(
            EventStamp(trigger_time, int(trigger.get("sequence", 0))),
            kind=trigger["packet"],
            packet=trigger["packet"],
            meta=trigger,
        )
        gain_transition = None
        for transition in reversed(transitions):
            if transition.kind in (
                "gain",
                "refresh",
                "extend",
                "replace",
                "gain_denied",
            ):
                gain_transition = transition
                break
        detail = gain_transition.detail if gain_transition is not None else {}
        stacks_before = int(detail.get("stacks_before", stack_state.stacks))
        stacks = stack_state.stacks
        stacks_gained = max(0, stacks - stacks_before)
        damage = float(trigger["damage"])
        stack_event = {
            "time": trigger_time,
            "kind": "status",
            "source": "Conqueror · stack",
            "source_key": effect.breakdown_key,
            "target_scope": "self",
            "target_policy": "self",
            "stacks_before": stacks_before,
            "stacks_after": stacks,
            "stacks_gained": stacks_gained,
            "max_stacks": effect.max_stacks,
            "adaptive_force": effect.adaptive_force_at(state.level, stacks),
            "packet": trigger["packet"],
            "trigger_source": trigger["source"],
            "event_precision": "exact",
            "_event_id": f"main:conqueror:stack:{len(stack_events)}",
        }
        if gain_transition is not None and gain_transition.kind == "gain_denied":
            stack_event["denied"] = str(detail.get("reason", ""))
        stack_events.append(stack_event)
        if stacks >= effect.max_stacks and damage > 0.0:
            heal_events.append(
                {
                    "time": trigger_time,
                    "amount": effect.heal_amount(damage, state.is_melee),
                    "trigger_source": trigger["source"],
                    "actor_wide": True,
                    "kind": "keystone",
                    "healing_category": "direct",
                    "stacks": stacks,
                    "_event_id": f"main:conqueror:heal:{len(heal_events)}",
                }
            )

    state.breakdown[effect.breakdown_key] = {
        "name": effect.display_name,
        "informational": True,
        "event_phase": "effect",
        "count": len(stack_events),
        "starting_stacks": starting_stacks,
        "max_stacks": effect.max_stacks,
        "stack_duration_seconds": effect.stack_duration_seconds,
        "stacks_per_application": effect.stacks_per_application,
        "cast_instance_interval_seconds": effect.cast_instance_interval_seconds,
        "adaptive_force_per_stack_at_level": effect.adaptive_force_at(state.level, 1),
        "adaptive_force_at_max": effect.adaptive_force_at(
            state.level, effect.max_stacks
        ),
        "adaptive_force_max_source": effect.max_adaptive_force_at(state.level),
        "adaptive_force_state_applied": False,
        "stack_events": stack_events,
        "state_transitions": stack_state.public_receipt()["transitions"],
    }
    if heal_events:
        total_healing = sum(float(event["amount"]) for event in heal_events)
        state.breakdown[f"heal_{effect.rune_name}"] = {
            "name": f"{effect.display_name} (max-stack heal)",
            "owner": "keystone",
            "count": len(heal_events),
            "amount_per_proc": total_healing / len(heal_events),
            "total_amount": total_healing,
            "unit": "health",
            "heal_events": heal_events,
            "event_phase": "heal",
        }
    if not triggers:
        state.notes.append(
            f"{effect.rune_name} recorded no certified ability-cast or "
            "basic-attack damage packets."
        )
    elif not heal_events:
        state.notes.append(
            f"{effect.rune_name} reached {stack_state.stacks} stack(s), "
            f"below its {effect.max_stacks}-stack healing threshold."
        )
    else:
        state.notes.append(
            f"{effect.rune_name} recorded {len(stack_events)} certified "
            f"stack packet(s) and {len(heal_events)} max-stack heal(s)."
        )
    state.notes.append(
        f"{effect.rune_name} adaptive force is withheld from damage pricing: "
        "champion AD/AP formulas need per-cast re-pricing before this state can "
        "change damage."
    )


def _add_rune_proc_amp_damage(state: FightState, rotation: RotationResult) -> None:
    """Price every selected stacked-proc-plus-amp rune (Press the Attack-class)."""
    for effect in _page_effects(state, rune_effects.RuneProcAmpEffect):
        _price_rune_proc_amp(state, rotation, effect)


def _price_rune_proc_amp(
    state: FightState,
    rotation: RotationResult,
    effect: "rune_effects.RuneProcAmpEffect",
) -> None:
    """Add one Press the Attack-class proc's damage and its lasting amplifier.

    The stacked proc prices leveled adaptive damage per proc, exactly
    like an Electrocute-class row. From the first proc onward the buff
    amplifies every certified non-true damage event by the sourced
    ratio until combat ends — a continuous fight never drops it. The
    triggering swing and the first proc itself predate the buff, so
    only events strictly after the first proc time are amplified;
    coarse-timed sources are excluded and disclosed, keeping the amp a
    floor, never an estimate.
    """
    lasting = _required_amp_slot(state, AmpChainSlot.LASTING_PROC_AMP, effect)
    proc_times, cooldown_gated = _refreshing_stack_proc_times(state, effect)
    if not proc_times:
        # A selected keystone that never fires must say so — only basic
        # attacks stack it, so ability-only or slow-swing fights get zero.
        state.notes.append(
            f"{effect.rune_name} never procced: the simulated fight "
            f"never landed {effect.stacks_required} basic attacks within "
            f"its {effect.stack_duration_seconds:g}s stack duration."
        )
        return
    _record_rune_proc_row(state, effect, proc_times)
    if cooldown_gated:
        state.notes.append(
            f"{effect.rune_name} stacks are assumed not to build during "
            f"its {effect.cooldown_seconds:g}s per-target cooldown (the wiki "
            "does not document this); re-procs may land late, so the proc "
            "count is a floor."
        )

    # The amp reads the ledger after the proc row exists, so later procs
    # (adaptive, never true damage) are amplified while the first — which
    # lands the same instant the buff turns on — is excluded by the
    # strictly-after cut, matching the wiki's triggering-attack rule.
    events, certified, coarse_sources = _certified_only_pool(state, rotation)
    amp_ratio = lasting.fractions[0]
    # The buff turns on with the first proc.  Which events that leaves inside
    # it is the rule's: `AfterTrigger(strict=True)` excludes the swing that
    # armed it, and the declared typing excludes true damage.
    amplified = [
        event
        for event in events
        if event["source_key"] in certified
        and lasting.applies_after(event["time"], proc_times[0])
        and lasting.prices_damage_type(event["damage_type"])
    ]
    if amplified:
        amp_by_type: dict[str, float] = {}
        for event in amplified:
            bonus = amp_ratio * event["damage"]
            amp_by_type[event["damage_type"]] = (
                amp_by_type.get(event["damage_type"], 0.0) + bonus
            )
        amp_total = sum(amp_by_type.values())
        state.breakdown[effect.amp_breakdown_key] = {
            "name": effect.amp_display_name,
            "total_damage": amp_total,
            "damage_by_type": amp_by_type,
            "count": 1,
            "event_phase": "effect",
            "damage_events": [
                {
                    "time": event["time"],
                    "damage": amp_ratio * event["damage"],
                    "damage_type": lasting.bonus_damage_type(event["damage_type"]),
                }
                for event in amplified
            ],
        }
        state.total_damage += amp_total
    if coarse_sources:
        state.notes.append(
            f"{effect.rune_name} amp excludes sources without "
            f"certified event times ({', '.join(sorted(coarse_sources))}); "
            "its bonus is a floor, not an estimate."
        )
