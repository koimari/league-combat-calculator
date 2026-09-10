"""A strike that spends a charge on one swing rather than paying every hit.

The Energized items (Rapid Firecannon, Stormrazor, Voltaic Cyclosword,
Statikk Shiv) and the first-hit strikes (Dead Man's Plate, Heartsteel): one
declaration each, with its own readiness gate, charge schedule and arc.
"""

from collections.abc import Collection

from ..items.energized_packets import _author_energized_ability_proc
from ..items.secondary_delivery import _add_chain_copied_delivery
from ..resists import _mitigate
from ..results import (
    OnHitResult,
    RotationResult,
    SpellbladeResult,
    SwingStream,
)
from ..rotation.shaped_charge import _strike_declaration
from ..state import FightState, _damage_inputs
from .decaying_health_walk import DecayingTarget


def _author_energized_ability_procs(
    state: FightState, rotation: RotationResult, *, swings: SwingStream
) -> set[str]:
    """Spend each ready charge an ability may consume, and say whose it was.

    Galvanize is ability-capable, and this runs before the auto pass so a
    zero-auto rotation still consumes and prices the ready charge."""
    return {
        effect.source.item_name
        for effect in state.declared.charged_strikes.first_autos
        if _author_energized_ability_proc(state, rotation, effect, swings.effectiveness)
    }


def _add_first_auto_strikes(
    state: FightState,
    rotation: RotationResult,
    on_hits: OnHitResult,
    *,
    spellblade: SpellbladeResult,
    ability_consumed_items: Collection[str],
    swings: SwingStream,
) -> None:
    """Price every declared charge-spending strike over the swing schedule."""
    num_auto_attacks = state.num_auto_attacks
    if num_auto_attacks <= 0:
        return
    resists = state.resists
    breakdown = state.breakdown
    swing_times, effectiveness = swings
    inputs = _damage_inputs(state)

    for effect in state.declared.charged_strikes.first_autos:
        source = effect.source
        if not effect.state_ready(state.items, state.item_options):
            # Blackout's unseen gate is an explicit scenario input.  A
            # equipped Umbral Glaive never guesses that the target was
            # unseen; without the ready receipt, the proc is withheld.
            continue
        chain_target_count = 0
        if effect.chain_targets_max > 0:
            # Statikk's one energized proc is a single chain across the
            # selected roster.  The per-target fight is evaluated once
            # for each roster member, so allocate the packet to the
            # sourced level-scaled prefix instead of duplicating it on
            # every target.  Copied on-hit siblings remain a separate
            # coverage boundary until the roster ledger can replay them.
            chain_target_count = effect.chain_target_count(state.level)
            allocated_targets = min(
                max(1, state.roster_target_count), chain_target_count
            )
            if state.roster_target_index >= allocated_targets:
                continue
        if effect.energized_max_stacks > 0:
            proc_indices = effect.proc_indices(
                num_auto_attacks,
                initial_stacks=(
                    0.0
                    if source.item_name in ability_consumed_items
                    else float(effect.energized_max_stacks)
                ),
            )
            procs = len(proc_indices)
        else:
            proc_indices = tuple(range(min(effect.max_procs, num_auto_attacks)))
            procs = len(proc_indices)
        if procs <= 0:
            continue
        proc_times = [
            swing_times[index] for index in proc_indices if index < len(swing_times)
        ]
        proc_damages: list[float] = []
        # What each packet of this strike declares, before mitigation and
        # before the holder's amps.  The target-side basic multiplier is
        # folded in wherever the engine applies it, because that factor
        # is a pair-local *allocation* the engine applies after
        # mitigation rather than an amplifier the walk can compose, and
        # mitigation is linear so one folded magnitude prices to the same
        # number.  ``declared_raws`` runs beside ``proc_damages``, one
        # entry per authored packet, because an energized proc re-reads
        # the target's falling health and no two of them need be equal.
        declared_raws: list[float] = []
        basic_share = (
            state.target_basic_damage_multiplier
            if source.basic_damage and source.damage_type != "true"
            else 1.0
        )
        for proc_time in proc_times:
            proc_inputs = _damage_inputs(
                state,
                target_current_health=DecayingTarget.ledger_health(state, proc_time),
            )
            raw_proc = source.raw_damage(proc_inputs) * effectiveness
            mitigated_proc = _mitigate(
                raw_proc, source.damage_type, resists, state.magic_amp
            )
            if source.basic_damage and source.damage_type != "true":
                mitigated_proc *= state.target_basic_damage_multiplier
            proc_damages.append(mitigated_proc)
            declared_raws.append(raw_proc * basic_share)
        if not proc_damages:
            raw_damage = source.raw_damage(inputs) * procs * effectiveness
            mitigated = _mitigate(
                raw_damage, source.damage_type, resists, state.magic_amp
            )
            if source.basic_damage and source.damage_type != "true":
                mitigated *= state.target_basic_damage_multiplier
            proc_damages = [mitigated / procs] * procs
            declared_raws = [raw_damage * basic_share / procs] * procs
        else:
            mitigated = sum(proc_damages)
        mechanic = source.previewed_mechanic()
        breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "count": procs,
            "damage_per_hit": mitigated / procs,
            "unit": "procs",
            "total_damage": mitigated,
            "damage_type": source.damage_type,
            # This row is the pair engine's preview of a number the
            # coupled walk owns.  The row-level declaration is what a
            # *coarse* row hands the walk: one whose procs landed on no
            # timestamped swing, so it authors no event of its own and
            # the reconstruction synthesizes one
            # (``_row_declaration_share``).
            "pair_preview_of": mechanic,
            "declared": _strike_declaration(mechanic, sum(declared_raws)),
        }
        if effect.energized_max_stacks > 0:
            breakdown[source.breakdown_key][
                "energized_schedule"
            ] = effect.schedule_receipt()
        if chain_target_count:
            breakdown[source.breakdown_key]["targeting"] = {
                "kind": "chain_lightning",
                "chain_target_count": chain_target_count,
                "allocated_target_index": state.roster_target_index,
                "roster_target_count": state.roster_target_count,
                "copied_on_hit_effects": True,
            }
        temporary_lethality = (
            effect.temporary_lethality_melee
            if state.is_melee
            else effect.temporary_lethality_ranged
        )
        if temporary_lethality > 0 and effect.temporary_lethality_duration > 0:
            breakdown[source.breakdown_key]["temporary_lethality"] = {
                "amount": temporary_lethality,
                "duration": effect.temporary_lethality_duration,
                "applies_before_event": True,
                "applied_to_triggering_event": True,
                "applied_to_later_events": False,
                "note": (
                    "Firmament's additional lethality is applied before its "
                    "own packet and the triggering attack, per the sourced Wiki."
                ),
            }
        # First-hit procs ride the opening swings of the stream.
        if swing_times and all(
            proc_index < len(swing_times) for proc_index in proc_indices
        ):
            breakdown[source.breakdown_key]["event_phase"] = "auto"
            breakdown[source.breakdown_key]["damage_events"] = [
                {
                    "time": swing_times[proc_index],
                    "damage": proc_damages[position],
                    "damage_type": source.damage_type,
                    "declared": _strike_declaration(mechanic, declared_raws[position]),
                }
                for position, proc_index in enumerate(proc_indices)
            ]
        if chain_target_count and state.roster_target_index > 0:
            _add_chain_copied_delivery(
                state,
                rotation,
                on_hits,
                spellblade,
                source=source,
                proc_indices=proc_indices,
                swing_times=swing_times,
                effectiveness=effectiveness,
                procs=procs,
            )
        state.total_damage += mitigated
