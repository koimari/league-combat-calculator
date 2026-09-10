"""What the compiled rune page prices, and what it discloses when it prices nothing."""

from collections.abc import Mapping
from types import MappingProxyType

from ... import rune_effects
from ...state_lifecycle import TriggerGate
from ..cast_slots import _damaging_cast_times
from ..results import RotationResult
from ..state import FightState
from .streams import _page_effects, _record_rune_proc_row, _rune_trigger_times


def _add_rune_proc_damage(state: FightState, rotation: RotationResult) -> None:
    """Add rune proc damage from the fight's real trigger stream.

    Walks the timestamped triggers each rune declares with its sourced
    stack rule: a stack expires ``stack_window_seconds`` after it was
    applied (a rune whose cache states no expiry keeps its stacks), so
    reaching ``stacks_required`` live stacks means that many triggers
    landed within one window. Procs start the cooldown and suppress new
    stacks until the rune is ready again (runes do not stack while on
    cooldown); a rune that consumes its stacks clears them, one that
    does not empowers every later trigger. Each proc is priced once and
    recorded as a timestamped damage event for the ledger and timeline
    consumers, and the rune's own disclosures reach the notes whether
    it procced or not — a withheld half that goes quiet at zero is the
    silent zero this campaign removes.

    A rune whose trigger is an input the fight has no event for reads it
    off the page's declared options through its own ``armed`` rule, and an
    un-armed rune walks no stream at all rather than being priced on one
    that does not stand for its trigger.
    """
    for effect in _page_effects(state, rune_effects.RuneProcEffect):
        armed = effect.armed(state.rune_options)
        proc_times: list[float] = []
        live_stacks: list[float] = []
        gate = TriggerGate(effect.cooldown_seconds, inclusive=False)
        for instance_time in (
            _rune_trigger_times(state, rotation, effect.trigger) if armed else ()
        ):
            if not gate.accepts(instance_time):
                continue
            if effect.stack_window_seconds is not None:
                live_stacks = [
                    applied
                    for applied in live_stacks
                    if instance_time - applied < effect.stack_window_seconds
                ]
            live_stacks.append(instance_time)
            if len(live_stacks) >= effect.stacks_required:
                proc_times.append(instance_time + effect.proc_delay_seconds)
                gate.arm(instance_time)
                if effect.consumes_stacks:
                    live_stacks = []
        state.notes.extend(effect.disclosures)
        if not proc_times:
            _note_rune_never_procced(state, effect, armed=armed)
            continue
        _record_rune_proc_row(state, effect, proc_times)


_RUNE_TRIGGER_SHORTFALLS: Mapping["rune_effects.RuneTrigger", str] = MappingProxyType(
    {
        rune_effects.RuneTrigger.BASIC_ATTACKS: "basic attacks",
        rune_effects.RuneTrigger.DAMAGING_CASTS: "damaging ability casts",
        rune_effects.RuneTrigger.DAMAGE_INSTANCES: (
            "damage instances (damaging ability casts and basic attacks)"
        ),
        rune_effects.RuneTrigger.IMPAIRED_INSTANCES: (
            "damaging ability casts whose own parts apply crowd control"
        ),
        rune_effects.RuneTrigger.SELF_SHIELD_EVENTS: (
            "basic attacks following a self-shield"
        ),
    }
)


def _note_rune_never_procced(
    state: FightState, effect: "rune_effects.RuneProcEffect", *, armed: bool = True
) -> None:
    """Disclose a selected rune whose trigger never armed it.

    Electrocute has always been able to end a fight without proccing; what
    it did not do was say so. Every proc-class rune says it here, in the
    words of the stream it declared — or, for a rune whose trigger is a
    declared option, in the words of the option that stayed off, because
    "the fight produced no damage instances" would be a false reason for a
    fight full of them.
    """
    if not armed:
        state.notes.append(
            f"{effect.rune_name} never procced: the rune page's options do "
            "not arm it, and their defaults are the un-triggered state."
        )
        return
    stream = _RUNE_TRIGGER_SHORTFALLS[effect.trigger]
    shortfall = (
        f"produced no {stream}"
        if effect.stacks_required <= 1
        else f"never landed {effect.stacks_required} {stream} inside its stack rule"
    )
    state.notes.append(
        f"{effect.rune_name} never procced: the simulated fight {shortfall}."
    )


def _add_rune_no_damage_receipts(state: FightState) -> None:
    """Publish the receipts of every selected rune that books no damage: the
    rune's own disposition says whether zero is the answer or a refusal."""
    for effect in _page_effects(state, rune_effects.RuneNoDamageEffect):
        state.notes.extend(effect.receipts)


def _add_rune_receipts_applied_elsewhere(state: FightState) -> None:
    """Publish what every rune applied outside the damage walk assumed: the
    health share a gate was priced at, the stacks a default supplied."""
    for effect in _page_effects(state, rune_effects.RUNE_RECEIPT_ONLY_KINDS):
        state.notes.extend(effect.disclosures)


def _add_dedicated_keystone_receipts(state: FightState) -> None:
    """Publish why the dedicated keystone booked no row, when it booked none.

    Its own walk speaks for a fight it priced.  A fight that met none of its
    conditions (no immobilize for Aftershock, no low-health target for Dark
    Harvest) or that reaches a half this engine holds no channel for is the
    case with nobody left to speak, and a silent zero is the one answer this
    engine never gives.  The words are the rune's, declared beside its
    compiler; running its own walk first leaves a fight that did book
    untouched."""
    effect = state.keystone_effect
    if effect is None:
        return
    receipts = effect.unpriced_receipts
    if not receipts:
        return
    if effect.breakdown_key in state.breakdown:
        return
    state.notes.extend(receipts)


def _add_rune_ability_proc_damage(state: FightState, rotation: RotationResult) -> None:
    """Add ability-cast rune proc damage (Arcane Comet-class).

    Every accepted damaging ability cast hurls the proc when the rune is
    off its leveled cooldown; the damage event lands after the sourced
    flight delay. Basic attacks never trigger this class, and the
    engine's DoT ticks are not cast instances — damage over time neither
    triggers nor extends anything here (unlike the Liandry's burn
    family). Each proc is priced at the compiled assumed travel distance
    and assumed to land; both assumptions are disclosed in the notes.
    """
    for effect in _page_effects(state, rune_effects.RuneAbilityProcEffect):
        proc_times: list[float] = []
        gate = TriggerGate(effect.cooldown_at(state.level), inclusive=False)
        for cast_time in _damaging_cast_times(state, rotation):
            if not gate.accepts(cast_time):
                continue
            proc_times.append(cast_time + effect.proc_delay_seconds)
            gate.arm(cast_time)
        if not proc_times:
            # A selected rune that never fires must say so — only damaging
            # ability casts trigger it, so autos-only fights get zero.
            state.notes.append(
                f"{effect.rune_name} never procced: the simulated fight "
                "cast no damaging abilities."
            )
            continue
        _record_rune_proc_row(state, effect, proc_times)
        state.notes.append(
            f"{effect.rune_name} assumes every comet lands after a "
            f"{effect.assumed_travel_distance:g}-unit flight "
            f"(+{effect.distance_amp_ratio * 100:.0f}% distance damage), never dodged."
        )
