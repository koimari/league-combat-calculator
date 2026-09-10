"""One on-hit application copied onto a second subject."""

from collections.abc import Sequence
from typing import Any

from ...ability_spec import AttackClass
from ...interpreters import secondary_target
from ...survival.pricing import AuthoredDeclaration, BasicAttackSwing, RoutingProvenance
from ..resists import _mitigate
from ..results import OnHitResult, OnHitShare, RotationResult, SpellbladeResult
from ..state import FightState, _damage_inputs
from .decaying_health_walk import DecayingTarget


def _bolt_declaration(
    state: FightState, slot: "secondary_target.SecondaryTargetSlot", raw_bolt: float
) -> tuple[Any, ...]:
    """One Wind's Fury bolt's declaration.

    The bolt is the **router's own packet** and this is the one place that is
    said in code: its magnitude is the declared share of the attacker's damage
    that ``SecondaryTargetSlot.bolt_damage`` compiles, so no other family
    declares it and the declaration carries no routing.  Its sibling row is
    the opposite shape, declared by :func:`_copied_on_hit_declaration`.

    ``AttackClass.BASIC_ATTACK`` is measured rather than defaulted: a bolt is
    priced by :func:`_mitigate_basic_attack_swing`, which multiplies by the
    holder's **basic** amp, so a declaration claiming ``OTHER`` would drop it.

    The two target-side FACTORS fold into the magnitudes and the other two
    terms cannot: the plating multiplier multiplies both branches and the
    target's crit-damage multiplier multiplies the crit branch, and a pure
    factor on a linear mitigation prices to the same real number.  What rides
    as a :class:`~.survival.pricing.BasicAttackSwing` is what no magnitude
    reproduces: the blend of two branches, and Warden's Mail's capped flat
    SUBTRACTION with its cap and its one instance.

    **The blend is authored only where the fight is deterministic**: a
    non-deterministic fight prices the non-crit branch alone.

    The resistance is the armour **this** packet met, transported because a
    bolt is a physical event on the ordinary ledger and
    :func:`_apply_temporary_lethality_windows` can re-price one."""
    plating = float(state.target_basic_damage_multiplier)
    deterministic = bool(state.deterministic)
    crit_raw = (
        raw_bolt
        * state.crit_multiplier
        * state.target_critical_strike_damage_multiplier
        * plating
        if deterministic
        else raw_bolt * plating
    )
    swing = BasicAttackSwing(
        crit_chance=float(state.crit_chance) if deterministic else 0.0,
        crit_raw_amount=crit_raw,
        basic_damage_flat_reduction=float(state.target_basic_damage_flat_reduction),
        basic_damage_flat_reduction_cap=float(
            state.target_basic_damage_flat_reduction_cap
        ),
    )
    return tuple(
        AuthoredDeclaration(
            slot.mechanic_id,
            raw_bolt * plating,
            AttackClass.BASIC_ATTACK.value,
            float(state.resists.effective_armor),
        ).delivered_as_a_swing(swing)
    )


def _copied_on_hit_declaration(
    share: OnHitShare, router_mechanic_id: str
) -> tuple[Any, ...] | None:
    """One copied on-hit packet's declaration, routed at the second subject.

    The magnitude belongs to the family that declared it, so ``rule_id`` is
    the **source** mechanic and the contribution is attributed at
    ``(source mechanic, secondary subject, event_id)``; the router contributes
    the route, recorded as provenance beside it.  The share is ``1.0`` because
    Wind's Fury re-delivers the attack's on-hit packets whole.  ``None`` for a
    contributor no item rule declares, which makes the copied row's stamp
    all-or-nothing."""
    mechanic = share.declared_mechanic()
    if mechanic is None:
        return None
    return tuple(
        AuthoredDeclaration(
            mechanic,
            share.raw,
            AttackClass.OTHER.value,
        ).routed_by(RoutingProvenance(router_mechanic_id, 1.0))
    )


def _copied_on_hit_shares(
    state: FightState,
    on_hits: OnHitResult,
    effectiveness: float,
    target_current_health: float,
) -> list[OnHitShare]:
    """One copied on-hit application, split by the producer that paid it.

    :func:`_copied_on_hit_packet`'s own arithmetic, kept per producer.  The
    fixed-magnitude producers are the record the on-hit layering keeps as it
    pays them, item strikes and champion ability-carried on-hits alike; the
    current-health strike is re-read here against the second subject's own
    health, which is why it is not on that record.
    """
    shares: list[OnHitShare] = [
        share for share in on_hits.static_on_hit_shares if share.mitigated > 0.0
    ]
    for effect in state.per_hit_strikes:
        if not effect.tracks_current_health:
            continue
        raw = (
            effect.source.raw_damage(
                _damage_inputs(state, target_current_health=target_current_health)
            )
            * effectiveness
        )
        if raw <= 0.0:
            continue
        shares.append(
            OnHitShare(
                effect.source.previewed_mechanic(),
                effect.source.damage_type,
                _mitigate(
                    raw,
                    effect.source.damage_type,
                    state.resists,
                    state.magic_amp,
                ),
                float(raw),
            )
        )
    return shares


def _copied_packets_by_type(shares: Sequence[OnHitShare]) -> dict[str, float]:
    """The pooled per-type packet the two copied-row builders consume."""
    packets: dict[str, float] = {}
    for share in shares:
        if share.mitigated <= 0.0:
            continue
        packets[share.damage_type] = (
            packets.get(share.damage_type, 0.0) + share.mitigated
        )
    return packets


def _copied_on_hit_packet(
    state: FightState,
    on_hits: OnHitResult,
    effectiveness: float,
    target_current_health: float,
) -> dict[str, float]:
    """Resolve one copied on-hit packet, including current-health effects.
    The pooled reading of :func:`_copied_on_hit_shares`; the caller that hands
    the walk a declaration per producer asks for the shares instead."""
    return _copied_packets_by_type(
        _copied_on_hit_shares(state, on_hits, effectiveness, target_current_health)
    )


def _add_copied_stacking_on_hit_packets(
    state: FightState,
    rotation: RotationResult,
    on_hits: OnHitResult,
    spellblade: SpellbladeResult,
    *,
    copied_events: list[dict[str, Any]],
    proc_indices: Sequence[int],
    swing_times: Sequence[float],
    effectiveness: float,
) -> bool:
    """Replay stack-gated on-hit effects carried by a copied chain hit.

    Electrospark's full Wiki entry explicitly says that its secondary
    packets apply on-hit effects.  A secondary chain packet is an additional
    on-hit application on the same ordered target ledger; it therefore must
    advance Kraken/Hullbreaker's counters, but must not advance canonical
    on-attack effects such as Energized or Phantom Hit.  The normal attack,
    ability, phantom, and Spellblade applications are walked first in their
    existing order, then the copied packet is inserted after the triggering
    swing.  Only the damage attributable to the copied packet is appended to
    ``copied_events``.

    Returns ``True`` when every copied stack packet was timestamped and
    replayed.  A malformed or coarse schedule leaves the caller's existing
    fail-closed coverage intact.
    """
    if (
        not copied_events
        or not proc_indices
        or not state.declared.charged_strikes.stacking_on_hits
    ):
        return True
    if len(swing_times) != state.num_auto_attacks:
        return False

    copied_by_auto: dict[int, list[dict[str, Any]]] = {}
    for event, index in zip(copied_events, proc_indices, strict=False):
        copied_by_auto.setdefault(int(index), []).append(event)
    apps = rotation.ability_item_applications

    for effect in state.declared.charged_strikes.stacking_on_hits:
        if effect.counter_trigger == "on_attack":
            # Statikk's chain carries on-hit effects, not on-attack effects.
            continue

        stacks = 0
        # Ability-carried on-hit applications lead the shared counter.  A
        # phantom hit on an ability application contributes one additional
        # on-hit stack at that same authored position.
        on_hit_sequence_index = 0
        for app in apps:
            if not app.on_hit:
                continue
            stacks += 1
            if stacks >= effect.hits_required:
                stacks = 0
            if on_hit_sequence_index in on_hits.phantom_ability_stack_positions:
                stacks += 1
                if stacks >= effect.hits_required:
                    stacks = 0
            on_hit_sequence_index += 1

        for index, swing_time in enumerate(swing_times):
            applications = 1
            if index in on_hits.phantom_hit_autos:
                applications += 1
            if index < spellblade.double_on_hit_procs:
                applications += 1
            for _application in range(applications):
                stacks += 1
                if stacks >= effect.hits_required:
                    stacks = 0

            copied_at_swing = copied_by_auto.get(index, [])
            if not copied_at_swing:
                continue
            for event in copied_at_swing:
                stacks += 1
                if stacks < effect.hits_required:
                    continue
                stacks = 0
                prior_copied_damage = sum(
                    sum(
                        float(amount)
                        for amount in candidate.get("packets", {}).values()
                        if isinstance(amount, (int, float))
                    )
                    for candidate in copied_events
                    if candidate is not event
                    and float(candidate.get("time", 0.0)) <= swing_time + 1e-9
                )
                target_current_health = max(
                    0.0,
                    DecayingTarget.ledger_health(state, swing_time)
                    - prior_copied_damage,
                )
                raw = (
                    effect.source.raw_damage(
                        _damage_inputs(
                            state, target_current_health=target_current_health
                        )
                    )
                    * effectiveness
                )
                mitigated = _mitigate(
                    raw,
                    effect.source.damage_type,
                    state.resists,
                    state.magic_amp,
                )
                if effect.source.basic_damage and effect.source.damage_type != "true":
                    mitigated *= state.target_basic_damage_multiplier
                packets = event.setdefault("packets", {})
                packets[effect.source.damage_type] = (
                    packets.get(effect.source.damage_type, 0.0) + mitigated
                )
                event.setdefault("stacked_copied_sources", []).append(
                    effect.source.item_name
                )
    return True
