"""The row a cooldown-gated item proc publishes."""

from typing import Any

from ... import item_effects
from ...ability_spec import AttackClass
from ...survival.pricing import AuthoredDeclaration
from ..resists import _mitigate
from ..results import RotationResult
from ..rotation.cast_schedule import _CAST_SCHEDULE_EPS
from ..state import FightState, _damage_inputs
from .eclipse_stack_gate import _stacked_champion_proc_times
from .proc_triggers import (
    _ability_damage_proc_triggers,
    _champion_damage_proc_triggers,
    _damage_threshold_trigger_time,
)


def _proc_declaration(
    source: item_effects.DamageSource, raw_amount: float, ability_amped: bool
) -> tuple[Any, ...]:
    """One cast-proc packet's declaration: rule, magnitude, attack class.

    ``ability_amped`` is the engine's answer for *this* packet, not the rule's:
    the ability part amp rides an item active on a window and the proc loops
    gate it per trigger, so reading the class off ``source.is_ability_damage``
    alone would claim the amp for a proc that fired after the window closed."""
    return tuple(
        AuthoredDeclaration(
            source.previewed_mechanic(),
            raw_amount,
            (AttackClass.ABILITY if ability_amped else AttackClass.OTHER).value,
        )
    )


def _charged_proc_target_share(
    state: FightState,
    source: item_effects.DamageSource,
) -> float:
    """Return this roster target's share of one charged proc application."""
    if source.multi_target_charges <= 0:
        return 1.0
    target_count = max(1, state.roster_target_count)
    target_index = max(0, state.roster_target_index)
    unique_targets = min(target_count, source.multi_target_charges)
    if target_index == 0:
        desired_multiplier = (
            1.0
            + max(
                0,
                source.multi_target_charges - unique_targets,
            )
            * source.repeated_target_multiplier
        )
    elif target_index < unique_targets:
        desired_multiplier = 1.0
    else:
        desired_multiplier = 0.0
    return desired_multiplier / source.single_target_multiplier


def _add_item_proc_damage(
    state: FightState,
    rotation: RotationResult,
) -> None:
    """Add the packets this build's cooldown-gated item procs fire."""
    resists = state.resists

    for effect in state.declared.cast_procs.cooldown_procs:
        if effect.late_phase:
            continue
        source = effect.source
        if effect.trigger == "ability_damage":
            proc_triggers = _ability_damage_proc_triggers(state, rotation, effect)
        elif effect.trigger == "champion_damage":
            proc_triggers = _champion_damage_proc_triggers(state, rotation, effect)
        else:
            proc_triggers = []
        if (
            effect.trigger in {"ability_damage", "champion_damage"}
            and not proc_triggers
        ):
            continue
        procs = (
            len(proc_triggers)
            if proc_triggers
            else (
                1 + int(state.fight_duration_seconds / effect.cooldown)
                if effect.repeat_on_cooldown
                else 1
            )
        )
        # A damage-threshold trigger (Stormsurge) fires once, at the
        # ledger moment the rolling burst window first fills.  Resolve
        # the time before this row lands in the breakdown it walks.
        threshold_time = (
            _damage_threshold_trigger_time(state, rotation, effect)
            if effect.trigger == "damage_threshold" and procs == 1
            else None
        )
        if effect.trigger == "damage_threshold" and threshold_time is None:
            # A threshold-gated proc is conditional damage, not a guaranteed
            # cast-boundary packet.  If the certified rolling window never
            # reaches the sourced threshold, the proc never fires and must
            # not inflate the result or downgrade the frontend timeline.
            continue
        raw_per_proc = source.raw_damage(_damage_inputs(state))
        base_mitigated_per_proc = _mitigate(
            raw_per_proc, source.damage_type, resists, state.magic_amp
        )

        # Stormsurge and Zaz'Zak deal ability damage — amplified by
        # Actualizer.  Timestamped trigger receipts split the amp at the
        # explicit expiry boundary; an un-timestamped proc retains the
        # direct-engine active assumption.
        target_share = _charged_proc_target_share(state, source)
        event_damages: list[float] = []
        # What one packet of this proc declares, before mitigation and before
        # the holder's amps.  The target share is folded in because it is a
        # pair-local *allocation* of one application across the roster's
        # targets and not an amplifier: the walk prices this slot's share, so
        # its magnitude is the share.  ``amped`` runs beside it, one entry per
        # authored packet, and says whether the engine paid the holder's
        # ability amp for that packet -- which is what the declaration's
        # attack class has to say, because the gate is per trigger and a
        # declaration claiming ABILITY for every one would hand the walk an
        # amp the pair engine had already declined to pay.
        declared_raw = raw_per_proc * target_share
        amped: list[bool] = []
        if proc_triggers:
            for trigger in proc_triggers:
                trigger_time = float(trigger["time"])
                in_window = source.is_ability_damage and (
                    state.actualizer_active_until <= 0.0
                    or trigger_time < state.actualizer_active_until - _CAST_SCHEDULE_EPS
                )
                amped.append(in_window)
                event_damages.append(
                    base_mitigated_per_proc
                    * (state.ability_amp if in_window else 1.0)
                    * target_share
                )
            proc_mitigated = sum(event_damages)
            mitigated_per_proc = (
                sum(event_damages) / len(event_damages) if event_damages else 0.0
            )
        else:
            amp = state.ability_amp if source.is_ability_damage else 1.0
            in_window = source.is_ability_damage
            if (
                threshold_time is not None
                and state.actualizer_active_until > 0.0
                and threshold_time >= state.actualizer_active_until - _CAST_SCHEDULE_EPS
            ):
                amp = 1.0
                in_window = False
            amped.append(in_window)
            mitigated_per_proc = base_mitigated_per_proc * amp * target_share
            proc_mitigated = mitigated_per_proc * procs

        state.breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "total_damage": proc_mitigated,
            "damage_type": source.damage_type,
            # This row is the pair engine's preview of a number the coupled
            # walk owns: the roster composition reads the stamp and takes the
            # figure below out of every total it composes, while the pair
            # fight's own receipt publishes it unchanged.  The row-level
            # declaration is what a *coarse* row hands the walk: one whose
            # ledger held no certifiable boundary, so it authors no event of
            # its own and the reconstruction synthesizes one
            # (``_row_declaration_share``).
            "pair_preview_of": source.previewed_mechanic(),
            "declared": _proc_declaration(source, declared_raw * procs, any(amped)),
        }
        if proc_triggers:
            state.breakdown[source.breakdown_key]["damage_events"] = [
                {
                    "time": float(trigger["time"]),
                    "timeline_order": float(trigger["order"]) + 0.5,
                    "damage": event_damages[index],
                    "damage_type": source.damage_type,
                    "declared": _proc_declaration(source, declared_raw, amped[index]),
                }
                for index, trigger in enumerate(proc_triggers)
            ]
        elif threshold_time is not None:
            state.breakdown[source.breakdown_key]["damage_events"] = [
                {
                    "time": threshold_time,
                    "damage": proc_mitigated,
                    "damage_type": source.damage_type,
                    "declared": _proc_declaration(
                        source, declared_raw * procs, amped[0]
                    ),
                }
            ]
        if source.multi_target_charges:
            state.breakdown[source.breakdown_key]["targeting"] = {
                "kind": "charged_bounce",
                "charges": source.multi_target_charges,
                "repeat_multiplier": source.repeated_target_multiplier,
                "single_target_multiplier": source.single_target_multiplier,
            }
        state.total_damage += proc_mitigated


def _add_late_phase_proc_damage(state: FightState, rotation: RotationResult) -> None:
    """Price the cooldown procs that read the finished attack ledger.

    Eclipse's Ever Rising Moon needs two hits inside its window, so it is
    priced here, after the strikes that author those hits, rather than beside
    the procs a cast fires.
    """
    resists = state.resists
    breakdown = state.breakdown
    for effect in state.declared.cast_procs.cooldown_procs:
        if not effect.late_phase:
            continue
        source = effect.source
        stack_timing = _stacked_champion_proc_times(state, rotation, effect)
        if stack_timing is None:
            # A malformed ledger withholds event precision: no certifiable
            # attack boundary exists, so the coarse fallback below prices a
            # duration-scaled aggregate.  The row is stamped with NAMED
            # fail-closed reasons, so callers can distinguish a malformed
            # ledger from a passive that never fired and the self-shield
            # loss is receipted, not silent.
            stack_events = None
            stack_gate = None
            stack_source_denials: list[dict[str, Any]] = []
            stack_withheld = "malformed_proc_receipt"
        else:
            stack_events, stack_gate, stack_source_denials = stack_timing
            # A denial is never a withholding — see below — so a walk that
            # ran at all leaves the row unwithheld whatever it denied.
            stack_withheld = None
        if stack_events is not None and not stack_events and not stack_source_denials:
            # No completed stack pair means the passive never fired.  Do not
            # substitute a guaranteed aggregate proc for a condition the
            # authored cast/attack ledger proves did not occur.
            continue
        if stack_events:
            procs = len(stack_events)
        elif stack_source_denials:
            # The source class is valid, but one required identity or timing
            # input is unavailable.  Keep a named zero-damage row.  A denied
            # candidate cannot become a duration-scaled aggregate proc.
            procs = 0
        else:
            # Preserve a coarse price only when the ledger is malformed or
            # explicitly lacks a certifiable attack boundary.
            procs = (
                1 + int(state.fight_duration_seconds / effect.cooldown)
                if effect.repeat_on_cooldown
                else 1
            )
        raw = source.raw_damage(_damage_inputs(state)) * procs
        total_damage = _mitigate(raw, source.damage_type, resists, state.magic_amp)
        breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "total_damage": total_damage,
            "damage_type": source.damage_type,
            "count": procs,
            # A ``cast_proc`` row like the ones ``_add_item_proc_damage``
            # authors, and a preview for the same reason: this family's
            # numbers are the coupled walk's.  The late
            # phase is the one branch that really does fall through to a
            # coarse row -- a ledger with no certifiable attack boundary
            # authors no ``stack_events`` -- so the row-level declaration
            # here is the one the reconstruction splits and hands over.
            "pair_preview_of": source.previewed_mechanic(),
            "declared": _proc_declaration(source, raw, False),
        }
        # A denied candidate is a DISCLOSURE, never a withholding, whether or
        # not a pair completed: ``stack_source_denials`` says which candidates
        # the walk could not date, and the priced pairs are the ones the
        # authored ledger proved.  A window whose trigger never occurred is a
        # measured zero with that disclosure beside it -- the passive really
        # did not fire -- so it certifies rather than going coarse.  Only a
        # malformed receipt is withheld: there the row keeps a coarse,
        # duration-scaled price that no authored boundary supports.
        if stack_withheld is not None:
            breakdown[source.breakdown_key]["event_phase"] = "coarse"
            breakdown[source.breakdown_key]["withheld_reason"] = stack_withheld
            if stack_events is None:
                breakdown[source.breakdown_key][
                    "shield_withheld_reason"
                ] = "self_shield_attached_only_to_certified_proc_events"
        if stack_source_denials:
            breakdown[source.breakdown_key][
                "stack_source_denials"
            ] = stack_source_denials
            if stack_gate is not None:
                breakdown[source.breakdown_key][
                    "state_transitions"
                ] = stack_gate.public_receipt()
        if stack_events:
            self_shield_events: list[dict[str, Any]] = []
            for event in stack_events:
                event["damage"] = total_damage / procs
                event["declared"] = _proc_declaration(source, raw / procs, False)
                if effect.self_shield_duration > 0.0:
                    shield_base = (
                        effect.self_shield_melee_base
                        if state.is_melee
                        else effect.self_shield_ranged_base
                    )
                    shield_ratio = (
                        effect.self_shield_melee_bonus_ad_ratio
                        if state.is_melee
                        else effect.self_shield_ranged_bonus_ad_ratio
                    )
                    self_shield_events.append(
                        {
                            "amount": max(
                                0.0,
                                shield_base
                                + shield_ratio
                                * float(state.champion_stats["bonus_attack_damage"]),
                            ),
                            "duration": effect.self_shield_duration,
                            "source": source.display_name,
                            # The shield arms on the SAME proc event it
                            # rides: its time and event precision are the
                            # completed pair's (P3 package 3C).
                            "time": float(event["time"]),
                            "event_precision": str(
                                event.get("event_precision", "exact")
                            ),
                        }
                    )
            breakdown[source.breakdown_key]["damage_events"] = stack_events
            if self_shield_events:
                breakdown[source.breakdown_key][
                    "self_shield_events"
                ] = self_shield_events
            breakdown[source.breakdown_key]["event_phase"] = "effect"
            # Public kernel receipt: every stack gain, window expiry, proc,
            # and per-target cooldown start in walk order (state_lifecycle).
            if stack_gate is not None:
                breakdown[source.breakdown_key][
                    "state_transitions"
                ] = stack_gate.public_receipt()
        state.total_damage += total_damage
