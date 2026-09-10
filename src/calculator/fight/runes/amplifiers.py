"""The two selected-rune amplifier shapes, health-gated and flat."""

from ... import rune_effects
from ...interpreters import amp_magnitude, delta_amp
from ...item_behavior import AmpChainSlot, Comparison, Probe
from ..after.amp_chain import _record_amp_row, _required_amp_slot
from ..ledger.event_ledger import _ordered_damage_events
from ..results import RotationResult
from ..state import FightState
from .streams import _page_effects


def _health_gated_events(
    events: list, slot: "delta_amp.AmpSlot", max_health: float
) -> list:
    """The ledger rows that land while a rune's target-health gate holds.

    The gate reads the target's *current* health, so the ledger is walked in
    its own order with health falling by everything already dealt, and each
    row is offered to the rule's own live predicate. What the walk does not
    model its caller discloses: untimestamped damage, and shields."""
    amped = []
    remaining = max_health
    for row in events:
        if slot.live_predicate_holds(
            Probe.TARGET_HEALTH_FRACTION, remaining, max_health
        ):
            amped.append(row)
        remaining -= row[1]
    return amped


def _health_gate_disclosure(
    effect: "rune_effects.RuneConditionalAmpEffect", slot: "delta_amp.AmpSlot"
) -> str:
    """What one health-gated rune amplified, in the declaration's own numbers."""
    side = "below" if slot.live_comparison() is Comparison.LT else "above"
    share = slot.value(amp_magnitude.LIVE_THRESHOLD_FIELD) * 100
    return (
        f"{effect.rune_name} amplifies exactly the instances that land while "
        f"the target is {side} {share:g}% of its maximum health, read off the "
        "fight's own ordered ledger; damage the ledger cannot timestamp is "
        "never amplified, so the row is a floor."
    )


def _add_rune_conditional_amp_damage(
    state: FightState, rotation: RotationResult
) -> None:
    """Apply every selected health-gated rune amplifier (Coup de Grace-class).

    Runs last among the amplifiers so the ledger it reads is the whole
    fight, which is the ``TARGET_HEALTH_GATE`` chain slot's position.  Only
    gates the walk can evaluate reach here at all — a gate on the holder's
    own health declares no live predicate on the target, so it is refused
    where it compiles rather than booking nothing here.
    """
    effects = _page_effects(state, rune_effects.RuneConditionalAmpEffect)
    if not effects:
        return
    events = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
        roster_target_index=state.ledger_target_index,
        light=True,
    )
    max_health = max(0.0, state.target_health)
    for effect in effects:
        slot = _required_amp_slot(state, AmpChainSlot.TARGET_HEALTH_GATE, effect)
        state.notes.append(_health_gate_disclosure(effect, slot))
        amped = _health_gated_events(events, slot, max_health)
        bonus = sum(row[1] for row in amped) * slot.bonus_fraction
        if bonus <= 0.0:
            state.notes.append(
                f"{effect.rune_name} amplified nothing: no timestamped damage "
                "landed while its health gate held."
            )
            continue
        _record_amp_row(
            state,
            effect.breakdown_key,
            effect.rune_name,
            1.0 + slot.bonus_fraction,
            amped=amped,
            bonus=bonus,
        )
        state.notes.append(
            f"{effect.rune_name}'s gate is walked over the fight's ordered "
            "ledger with the target at full health when it starts and its "
            "shields not yet subtracted; a shielded target would cross a "
            "falling gate later than this."
        )


def _rune_amp_context(state: FightState, slot: str) -> "rune_effects.RuneAmpContext":
    """What a flat rune amplifier reads when it prices one slot's instances."""
    return rune_effects.RuneAmpContext(
        level=state.level,
        is_melee=state.is_melee,
        champion_stats=state.champion_stats,
        target_max_health=max(0.0, state.target_health),
        options=state.rune_options,
        slot=slot,
    )


def _flat_amp_pool(
    state: FightState, effect: "rune_effects.RuneFlatAmpEffect", events: list
) -> tuple[list, float]:
    """The ledger rows one flat rune amp amplifies, and the ratio it pays.

    The rune is asked once per slot the ledger holds, not once per row: its
    kind promises a constant ratio over the set it filters to, so a row's
    answer cannot depend on anything but its slot. Two different ratios back
    would make the breakdown row's single multiplier a fiction, so the walk
    refuses them instead of picking one.
    """
    ability_slots = set(state.cast_order)
    ratios: dict[str, float] = {}
    amped: list = []
    for row in events:
        slot = row[3] if row[3] in ability_slots else ""
        if slot not in ratios:
            ratios[slot] = effect.amp_ratio(_rune_amp_context(state, slot))
        if ratios[slot] > 0.0:
            amped.append(row)
    paid = {ratio for ratio in ratios.values() if ratio > 0.0}
    if len(paid) > 1:
        raise ValueError(
            f"{effect.rune_name} pays {sorted(paid)} to different instances of "
            "one fight; a flat rune amplifier is one ratio over the set it "
            "filters to, and one breakdown row publishes one multiplier"
        )
    return amped, paid.pop() if paid else 0.0


def _add_rune_flat_amp_damage(state: FightState, rotation: RotationResult) -> None:
    """Apply every selected flat rune amplifier (Last Stand-class).

    First among the amplifiers, and deliberately: these price the fight's own
    damage rather than a condition the ledger has to be walked for, so every
    amplifier after them multiplies a total that already carries the rune's
    bonus — which is how the game composes two amplifiers over one hit.
    """
    effects = _page_effects(state, rune_effects.RuneFlatAmpEffect)
    if not effects:
        return
    events = _ordered_damage_events(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        cast_events=rotation.cast_events,
        roster_target_index=state.ledger_target_index,
        light=True,
    )
    for effect in effects:
        state.notes.extend(effect.disclosures)
        amped, ratio = _flat_amp_pool(state, effect, events)
        bonus = sum(row[1] for row in amped) * ratio
        if bonus <= 0.0:
            state.notes.append(
                f"{effect.rune_name} amplified nothing: none of the fight's "
                "timestamped damage was of the kind it amplifies."
            )
            continue
        _record_amp_row(
            state,
            effect.breakdown_key,
            effect.rune_name,
            1.0 + ratio,
            amped=amped,
            bonus=bonus,
        )
