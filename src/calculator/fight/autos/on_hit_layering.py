"""The one on-hit authoring site.

Two of the ways a champion ability joins the on-hit system are authored
here.  A cast-armed window is ``empower_windows`` and an ability that
applies the build's item on-hits is ``on_hit_stream``.

**Case 1 — Stack acceleration** (e.g. Vayne W Silver Bolts):
    Abilities that build stacks per auto and proc on reaching N stacks.
    Phantom hits grant an extra stack per proc. The ``phantom_hit_autos``
    set is returned in the fight result so champion-specific calculators
    can model accelerated stack procs. The champion module is responsible
    for counting stacks and determining when procs happen.

**Case 2 — On-hit damage** (e.g. Viego passive % health on auto):
    Abilities that add flat/scaling damage per auto attack. These are
    registered by adding an ``on_hit`` key to the ability's entry in
    ``ability_damages``::

        ability_damages["passive"] = {
            "name": "Blade of the Ruined Blade",
            "on_hit": {
                "name": "Viego Passive (on-hit)",
                "damage_per_hit": 42.0,
                "damage_type": "physical",
            },
        }

    The fight engine processes these alongside item on-hits, and phantom
    hits automatically double them. An optional ``max_procs`` key caps the
    number of applications (Bard meeps: stock + recharge availability) —
    autos beyond the cap land without the on-hit damage. A ``ramping``
    flag (with ``stacks_required``) makes proc k deal k x the per-hit
    damage (Bel'Veth R: stacks accumulate and never reset). A
    ``stack_ramp`` dict (``{"damage_per_stack", "max_stacks"}``) models
    per-target attack stacks amplifying the on-hit damage itself
    (Orianna P): each hit lands at the CURRENT stack count then adds a
    stack, so hit k (0-indexed) deals ``damage_per_hit +
    min(k, max_stacks) x damage_per_stack`` — the natural single-target
    ramp, with stacks assumed never to drop mid-fight.
"""

# file-length-ok: the bulk is the champion-rider region, 24 modules'
# on-hit contracts read through one dict dispatch.  Typing that contract
# is stage 4 of docs/plans/2026-09-09-fight-navigability.md, and a
# stampability predicate that flips there makes a row coarse, which moves
# the coupled golden's leaf set with no number moving.
from collections.abc import Sequence
from typing import Any

from ... import item_effects
from ...ability_atoms import ability_field
from ..items.energized_packets import _first_auto_damage_by_auto_for_health_walk
from ..ledger.event_ledger import _ordered_damage_events
from ..ledger.event_rows import _damage_type_fields
from ..mitigation import _crit_scaled_raw
from ..resists import Resists, _mitigate, _resistance_met_fields
from ..results import (
    CHAMPION_PRODUCER_PREFIX,
    AbilityItemApplication,
    AutoAttackResult,
    OnHitResult,
    OnHitShare,
    RotationResult,
)
from ..state import FightState, _damage_inputs
from .decaying_health_walk import (
    AutoSwings,
    _simulate_current_health_on_hit,
    _simulate_hp_scaled_on_hit_procs,
)
from .empower_windows import (
    _add_empower_window_on_hit,
    _declared_slot_stacks,
    _on_hit_declaration,
    _uniform_swing_schedule,
)
from .on_hit_stream import (
    _ability_applied_on_hit_damage,
    _calculate_phantom_hits,
    _schedule_cooldown_procs,
)
from .swing_profile import _on_hit_effectiveness
from .swing_schedule import _auto_attack_timestamps


def _swing_event_row(
    times: list[float],
    damages: list[float],
    damage_type: str,
    *,
    declarations: list[tuple[Any, ...]] | None = None,
    raws: list[float] | None = None,
    resists: Resists | None = None,
) -> dict[str, Any]:
    """Row fields authoring one typed event per (time, damage) pair.

    ``declarations`` is one per event for a row the walk prices itself, and
    ``None`` for a row delivered as the pair engine's own price.  ``raws`` is
    one per event for a row whose caller priced each application from its own
    pre-mitigation magnitude, and ``None`` where the caller states none, which
    the receipt reads as a refusal rather than as a number.  Both ride through
    the sort beside their own damage rather than being stamped afterwards: the
    events are ordered by time, and an application's magnitude belongs to the
    application, not to the position it lands in.  ``resists`` is what the
    caller mitigated against; one row is one damage class, so its whole
    schedule met one resistance.
    """
    declared = declarations or [None] * len(damages)
    stated = raws or [None] * len(damages)
    met = {} if resists is None else _resistance_met_fields(damage_type, resists)
    ordered = sorted(
        zip(times, damages, declared, stated, strict=False),
        key=lambda packet: float(packet[0]),
    )
    return {
        "event_phase": "auto",
        "damage_events": [
            {
                "time": time,
                "damage": damage,
                "damage_type": damage_type,
                **({} if declaration is None else {"declared": declaration}),
                **({} if raw is None else {"raw_damage": raw}),
                **met,
            }
            for time, damage, declaration, raw in ordered
        ],
    }


def _pay_ability_phantom_on_hits(
    state: FightState,
    result: OnHitResult,
    *,
    apps: Sequence[AbilityItemApplication],
    ability_phantoms: Sequence[int],
    attack_app_indices: Sequence[int],
    phantom_effect: item_effects.PhantomHitEffect | None,
) -> float:
    """Re-apply the build's per-hit effects on each ability-fired phantom hit.

    A phantom fired by an ability attack lands at that attack's own
    effectiveness (a Bel'Veth slash's 8 to 32%) and grants one extra stack on
    the shared ON-HIT counters at that hit's position, which the stacking-proc
    walk consumes off ``result``.  Returns what the phantoms are worth.
    """
    if not ability_phantoms:
        return 0.0
    assert phantom_effect is not None
    on_hit_seq_index = {}
    seq = 0
    for i, app in enumerate(apps):
        if app.on_hit:
            on_hit_seq_index[i] = seq
            seq += 1
    phantom_ability_damage = 0.0
    phantom_by_type: dict[str, float] = {}
    phantom_events: list[dict[str, Any]] | None = []
    for position in ability_phantoms:
        app = apps[attack_app_indices[position]]
        applied = _ability_applied_on_hit_damage(
            state, app.effectiveness, app.target_hp
        )
        for dtype, amount in applied.items():
            phantom_by_type[dtype] = phantom_by_type.get(dtype, 0.0) + amount
        # A phantom re-application fires with its triggering attack, so it
        # shares that hit's authored timestamp; one untimed carrier keeps the
        # row coarse rather than inventing a boundary.
        if phantom_events is not None:
            if app.time is None:
                phantom_events = None
            else:
                phantom_events.extend(
                    {
                        "time": float(app.time),
                        "damage": amount,
                        "damage_type": dtype,
                    }
                    for dtype, amount in applied.items()
                    if amount > 0
                )
        phantom_ability_damage += sum(applied.values())
        mapped = on_hit_seq_index.get(attack_app_indices[position])
        if mapped is not None:
            result.phantom_ability_stack_positions.add(mapped)
    if phantom_ability_damage <= 0:
        return 0.0
    state.breakdown["on_hit_items_phantom"] = {
        "name": f"{phantom_effect.item_name} phantom hits (ability attacks)",
        "count": len(ability_phantoms),
        "total_damage": phantom_ability_damage,
        **_damage_type_fields(phantom_by_type),
    }
    if phantom_events:
        state.breakdown["on_hit_items_phantom"].update(
            {"damage_events": phantom_events, "event_phase": "ability"}
        )
    return phantom_ability_damage


def _application_times(
    state: FightState, result: OnHitResult, *, double_shot_extra: int
) -> tuple[list[float], list[float]]:
    """The fight's swing schedule, and one entry per on-hit application.

    Every auto-segment on-hit application rides a timestamped swing, so the
    rows built from these can author exact per-swing damage events.  The
    applications come out in the shared counter's order: the swing itself, its
    Rageblade phantom re-application, then a double-shot extra, all at that
    swing's authored time.  An unresolvable schedule returns two empty lists,
    which is what keeps the rows that read them coarse.
    """
    swing_times = _auto_attack_timestamps(state)
    if len(swing_times) != state.num_auto_attacks:
        return [], []
    application_times: list[float] = []
    for auto_index, swing_time in enumerate(swing_times):
        application_times.append(swing_time)
        if auto_index in result.phantom_hit_autos:
            application_times.append(swing_time)
        if double_shot_extra:
            application_times.append(swing_time)
    return list(swing_times), application_times


def _ability_hit_ledger(
    state: FightState, rotation: RotationResult
) -> list[tuple[str, float]]:
    """Each accepted ability hit's slot and time, for the on-hits they carry.

    An ability-carried on-hit is timestamped from the same accepted ledger
    that prices the cast, which is required for a stack counter such as
    Aurora's Spirit Abjuration: a fractional per-hit average would invent
    damage before the third stack exists.  A kit with no ability-carried
    on-hit skips the reconstruction entirely.
    """
    if not any(
        ability_info.get("on_hit") for ability_info in state.ability_damages.values()
    ):
        return []
    return [
        (str(event.get("source_key")), float(event["time"]))
        for event in _ordered_damage_events(
            state.breakdown,
            state.ability_damages,
            state.cast_order,
            cast_events=rotation.cast_events,
            roster_target_index=state.ledger_target_index,
        )
        if event.get("phase") == "ability"
        and event.get("source_key") in state.ability_damages
    ]


def _layer_on_hit_effects(
    state: FightState,
    autos: AutoAttackResult,
    rotation: RotationResult,
) -> OnHitResult:
    """Layer per-hit on-hit damage (items and abilities) onto the autos.

    Computes Guinsoo's Rageblade phantom hits centrally — they apply ALL
    on-hit effects an additional time — and counts double-shot extra
    applications. Constant-damage on-hit items and ability on-hits
    (e.g. Vayne W stacks, Viego passive) multiply per-hit damage by the
    total application count; BoRK is simulated per-auto against the
    target's decreasing current HP. Ability on-hits flagged
    ``count_ability_hits`` (e.g. Aurora P) also count the rotation's
    damaging ability hits toward their stack counter, and one that names
    ``ability_stack_slots`` counts only the slots it declares (Xin Zhao's
    W). A row whose sourced text says the bonus is affected by critical
    strike modifiers declares ``crit_effectiveness`` (Shaco P: 1.0).

    A champion ``auto_attack_override`` may carry ``on_hit_effectiveness``
    (Azir soldiers: on-hit at 50%) — it scales every per-hit on-hit
    application here, including the BoRK simulation.
    """
    resists = state.resists
    breakdown = state.breakdown
    num_auto_attacks = state.num_auto_attacks
    magic_amp = state.magic_amp

    on_hit_effectiveness = _on_hit_effectiveness(state)

    on_hit_total = 0.0
    current_health_effect = next(
        (effect for effect in state.per_hit_strikes if effect.tracks_current_health),
        None,
    )
    result = OnHitResult(has_current_health_on_hit=current_health_effect is not None)

    # Calculate Guinsoo's Rageblade phantom hits centrally — these apply
    # ALL on-hit effects (items AND abilities) an additional time.
    # Phantom stacking is an ON-ATTACK cadence (item taxonomy), so
    # ability-carried applications that count as attacks (Bel'Veth E
    # slashes) lead the shared attack counter before the autos.
    phantom_effect = state.damage_effects.phantom_hit
    apps = rotation.ability_item_applications
    attack_app_indices: list[int] = []
    if phantom_effect is not None and apps:
        wants_on_attack = phantom_effect.counter_trigger == "on_attack"
        attack_app_indices = [
            i
            for i, app in enumerate(apps)
            if (app.on_attack if wants_on_attack else app.on_hit)
        ]
    ability_phantoms, result.phantom_hit_autos = _calculate_phantom_hits(
        num_auto_attacks, phantom_effect, leading_attacks=len(attack_app_indices)
    )
    result.phantom_hit_count = len(result.phantom_hit_autos)

    on_hit_total += _pay_ability_phantom_on_hits(
        state,
        result,
        apps=apps,
        ability_phantoms=ability_phantoms,
        attack_app_indices=attack_app_indices,
        phantom_effect=phantom_effect,
    )

    # Double shot applies on-hit effects an additional time per auto
    double_shot_extra = num_auto_attacks if autos.double_shot_info else 0
    on_hit_hits = num_auto_attacks + result.phantom_hit_count + double_shot_extra
    swing_times, application_times = _application_times(
        state, result, double_shot_extra=double_shot_extra
    )

    # Process fixed-formula per-hit effects. Current-health effects are
    # simulated below because each application changes the next one's input.
    # Class-restricted branches (P3-3M) join the same stream only when the
    # fight's target class arms them, so they ride the identical
    # mitigation, phantom/double-shot counting, breakdown row, and
    # per-swing event authoring as every other on-hit item.
    damage_inputs = _damage_inputs(state)
    for effect in (
        *state.per_hit_strikes,
        *state.class_restricted_strikes,
    ):
        if effect.tracks_current_health:
            continue

        source = effect.source
        mechanic = source.previewed_mechanic()
        raw_per_hit = source.raw_damage(damage_inputs) * on_hit_effectiveness
        if raw_per_hit <= 0:
            continue

        per_hit = _mitigate(raw_per_hit, source.damage_type, resists, magic_amp)

        # All on-hit items get phantom hit bonus procs.
        hits = on_hit_hits
        item_damage = per_hit * hits
        on_hit_total += item_damage
        result.static_on_hit_per_hit += per_hit
        result.static_on_hit_shares.append(
            OnHitShare(mechanic, source.damage_type, per_hit, raw_per_hit)
        )

        declaration = _on_hit_declaration(mechanic, raw_per_hit)
        breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "count": hits,
            "damage_per_hit": per_hit,
            "total_damage": item_damage,
            "damage_type": source.damage_type,
            # This row is the pair engine's preview of a number the coupled
            # walk owns: the roster composition reads the stamp and takes the
            # figure above out of every total it composes, while the pair
            # fight's own receipt publishes it unchanged.  The row-level
            # declaration is what a *coarse* row hands the walk: one whose
            # applications landed on no resolvable swing schedule, so it
            # authors no event of its own and the reconstruction synthesizes
            # one (``_row_declaration_share``).
            "pair_preview_of": mechanic,
            "declared": _on_hit_declaration(mechanic, raw_per_hit * hits),
        }
        if application_times:
            breakdown[source.breakdown_key].update(
                _swing_event_row(
                    application_times,
                    [per_hit] * hits,
                    source.damage_type,
                    declarations=[declaration] * hits,
                    resists=resists,
                )
            )

    ability_hit_ledger = _ability_hit_ledger(state, rotation)
    ability_hit_times = [time for _, time in ability_hit_ledger]
    combined_application_times = ability_hit_times + application_times

    # Process ability on-hit effects (Case 2: abilities that add damage per
    # auto attack, e.g. Viego passive % health on-hit). These are passed in
    # ability_damages with an "on_hit" key containing per-hit damage info.
    # Phantom hits also apply these an additional time.
    for ability_key, ability_info in state.ability_damages.items():
        on_hit_data = ability_info.get("on_hit")
        if not on_hit_data:
            continue
        if (
            "proc_cooldown" in on_hit_data
            or "proc_window" in on_hit_data
            or "missing_health_amp" in on_hit_data
        ):
            continue  # procs that read the target's live health are below
        if "empower_window" in on_hit_data:
            on_hit_total += _add_empower_window_on_hit(
                state,
                rotation,
                ability_key,
                on_hit_data,
                auto_times=(
                    list(swing_times)
                    if swing_times
                    else _uniform_swing_schedule(state, num_auto_attacks)
                ),
                ability_hit_times=ability_hit_times,
                effectiveness=on_hit_effectiveness,
                swing_event_row=_swing_event_row,
            )
            continue  # cast-armed charges are scheduled, never per-auto
        counts_ability_hits = bool(on_hit_data.get("count_ability_hits"))
        carries_on_ability_on_hits = bool(on_hit_data.get("applies_on_ability_on_hits"))
        slot_stacks, slot_stack_times = _declared_slot_stacks(
            on_hit_data, ability_hit_ledger
        )
        if (
            num_auto_attacks == 0
            and not counts_ability_hits
            and not carries_on_ability_on_hits
            and slot_stacks == 0
        ):
            continue

        raw_base = float(ability_field(on_hit_data, "damage_per_hit", form="on_hit"))
        if raw_base <= 0:
            continue

        dmg_type = ability_field(on_hit_data, "damage_type", form="on_hit")
        # A champion on-hit row whose sourced text says the bonus is
        # affected by critical strike modifiers declares its effectiveness
        # here — the same axis, and the same formula, ability parts carry as
        # ``DamagePart.crit_effectiveness`` (Shaco's Backstab: 1.0).
        crit_effectiveness = float(
            ability_field(on_hit_data, "crit_effectiveness", form="on_hit")
        )
        raw_base = _crit_scaled_raw(state, raw_base, crit_effectiveness, dmg_type)
        raw_per_hit = raw_base * on_hit_effectiveness
        per_hit = _mitigate(raw_per_hit, dmg_type, resists, magic_amp)

        hits = (
            on_hit_hits
            + (rotation.total_ability_hits if counts_ability_hits else 0)
            + slot_stacks
        )

        # Some champion on-hits explicitly ride ability-carried on-hit
        # instances as well as ordinary attacks. Bel'Veth R is the canonical
        # case: Q and E each apply the ramping true damage through their own
        # effectiveness, while ambient autos use Death in Lavender's 75%.
        # Preserve the actual carrier order because hit k deals k times the
        # base value. Ability-fired and auto-fired Guinsoo phantoms are extra
        # applications immediately after their carrier; Akshan-style double
        # shots likewise add one application per ambient attack.
        carrier_effectiveness: list[float] | None = None
        carrier_times: list[float] | None = None
        leading_carrier_hits = 0
        if carries_on_ability_on_hits:
            carrier_effectiveness = []
            carrier_times = []
            on_hit_position = 0
            for app in apps:
                if not app.on_hit:
                    continue
                carrier_effectiveness.append(app.effectiveness)
                if app.time is not None:
                    carrier_times.append(float(app.time))
                else:
                    carrier_times = None
                if on_hit_position in result.phantom_ability_stack_positions:
                    carrier_effectiveness.append(app.effectiveness)
                    if carrier_times is not None:
                        carrier_times.append(float(app.time))
                on_hit_position += 1
            # Ability-carried applications have no authored timestamps
            # unless the carrier module supplied them.  While any lead
            # carrier is untimed, this row stays coarse rather than inventing
            # an average boundary.
            leading_carrier_hits = len(carrier_effectiveness)
            for auto_index in range(num_auto_attacks):
                carrier_effectiveness.append(on_hit_effectiveness)
                if carrier_times is not None:
                    if auto_index < len(application_times):
                        carrier_times.append(float(application_times[auto_index]))
                    else:
                        carrier_times = None
                if auto_index in result.phantom_hit_autos:
                    carrier_effectiveness.append(on_hit_effectiveness)
                    if carrier_times is not None:
                        if auto_index < len(application_times):
                            carrier_times.append(float(application_times[auto_index]))
                        else:
                            carrier_times = None
                if autos.double_shot_info:
                    carrier_effectiveness.append(on_hit_effectiveness)
                    if carrier_times is not None:
                        if auto_index < len(application_times):
                            carrier_times.append(float(application_times[auto_index]))
                        else:
                            carrier_times = None
            hits = len(carrier_effectiveness)

        # Availability-limited on-hits (Bard meeps: stock + recharge)
        # apply at most max_procs times; autos beyond the cap are plain.
        max_procs = ability_field(on_hit_data, "max_procs", form="on_hit")
        if max_procs is not None:
            hits = min(hits, int(max_procs))

        stacks_required = ability_field(on_hit_data, "stacks_required", form="on_hit")
        ramping = bool(on_hit_data.get("ramping"))
        stack_ramp = on_hit_data.get("stack_ramp")

        # Per-swing events are authorable only when every counted hit is
        # an auto-segment application with an authored swing time —
        # ability-carried hits (leading carriers, shared auto+ability
        # counters) have no timestamps yet and keep the row coarse.
        stampable = (
            bool(application_times)
            and leading_carrier_hits == 0
            and not (counts_ability_hits and rotation.total_ability_hits > 0)
            and slot_stacks == 0
            and hits <= len(application_times)
        )
        # Declared per-slot stacks arrive on their own ability hits, so the
        # row stays exact: their authored times join the swing schedule.
        slot_stack_application_times = slot_stack_times + application_times
        slot_stack_stampable = (
            slot_stacks > 0
            and len(slot_stack_times) == slot_stacks
            and len(slot_stack_application_times) >= hits
        )
        carrier_stampable = (
            carrier_effectiveness is not None
            and carrier_times is not None
            and len(carrier_times) >= hits
        )
        if carrier_stampable:
            stampable = True
        ability_counter_stampable = (
            counts_ability_hits
            and rotation.total_ability_hits > 0
            and len(combined_application_times) >= hits
        )
        if ability_counter_stampable:
            stampable = True
        event_times: list[float] | None = None
        event_damages: list[float] | None = None
        # The pre-mitigation magnitude each stamped application was priced
        # from, in the same order, so the receipt states this rider's raw.
        event_raws: list[float] | None = None
        if stack_ramp:
            # Stack-ramped on-hit (Orianna P): each hit lands at the
            # CURRENT stack count then adds a stack (capped), so hit k
            # deals per_hit + min(k, max_stacks) x per_stack. Stacks are
            # assumed never to drop mid-fight (sustained attacking).
            raw_per_stack = (
                _crit_scaled_raw(
                    state,
                    float(stack_ramp["damage_per_stack"]),
                    crit_effectiveness,
                    dmg_type,
                )
                * on_hit_effectiveness
            )
            per_stack = _mitigate(raw_per_stack, dmg_type, resists, magic_amp)
            max_stacks = int(stack_ramp["max_stacks"])
            stacked_hits = sum(min(k, max_stacks) for k in range(hits))
            ability_on_hit_damage = per_hit * hits + per_stack * stacked_hits
            if stampable:
                # Hit k lands at the CURRENT stack count — its own value.
                event_times = application_times[:hits]
                event_damages = [
                    per_hit + min(k, max_stacks) * per_stack for k in range(hits)
                ]
                event_raws = [
                    raw_per_hit + min(k, max_stacks) * raw_per_stack
                    for k in range(hits)
                ]
        elif ramping:
            # Ramping proc k deals k x its base. When abilities can carry the
            # on-hit, each application has its own effectiveness; otherwise
            # the ordinary auto effectiveness is uniform. ``stacks_required``
            # remains supported for pre-26.15 every-Nth formulations.
            procs = hits // max(1, stacks_required)
            if carrier_effectiveness is not None and stacks_required <= 1:
                carrier_raws = [
                    raw_base * effectiveness * stack
                    for stack, effectiveness in enumerate(
                        carrier_effectiveness, start=1
                    )
                ]
                carrier_damages = [
                    _mitigate(raw, dmg_type, resists, magic_amp) for raw in carrier_raws
                ]
                ability_on_hit_damage = sum(carrier_damages)
                if stampable:
                    # No leading carriers: the carrier order IS the
                    # auto-segment application order.
                    event_times = (
                        carrier_times[:hits]
                        if carrier_stampable
                        else application_times[:hits]
                    )
                    event_damages = carrier_damages
                    event_raws = carrier_raws
            else:
                ability_on_hit_damage = per_hit * procs * (procs + 1) / 2.0
                if stampable:
                    # Proc j fires on the application landing its Nth stack.
                    interval = max(1, stacks_required)
                    event_times = [
                        application_times[j * interval - 1] for j in range(1, procs + 1)
                    ]
                    event_damages = [per_hit * j for j in range(1, procs + 1)]
                    event_raws = [raw_per_hit * j for j in range(1, procs + 1)]
        elif stacks_required > 1 and counts_ability_hits:
            # Shared auto+ability stack counter (e.g. Aurora P): only
            # complete procs deal damage — partial stacks expire.
            ability_on_hit_damage = (
                per_hit * stacks_required * (hits // stacks_required)
            )
            if ability_counter_stampable:
                event_times = [
                    combined_application_times[j * stacks_required - 1]
                    for j in range(1, hits // stacks_required + 1)
                ]
                event_damages = [per_hit * stacks_required] * (hits // stacks_required)
                event_raws = [raw_per_hit * stacks_required] * (hits // stacks_required)
        else:
            # Autos-only on-hit (e.g. Vayne W): smooth per-hit average.
            # The total includes partial stacks, so events are the same
            # per-swing shares — the ledger must sum to the row exactly.
            ability_on_hit_damage = per_hit * hits
            if slot_stack_stampable:
                event_times = slot_stack_application_times[:hits]
            elif stampable:
                event_times = application_times[:hits]
            if event_times is not None:
                event_damages = [per_hit] * hits
                event_raws = [raw_per_hit] * hits
        on_hit_total += ability_on_hit_damage
        if max_procs is None and not ramping and not stack_ramp:
            static_share = per_hit
        elif on_hit_hits > 0:
            # Capped on-hits don't land on every auto — feed the HP
            # simulations (BoRK, spellblade doubling) the per-auto average.
            static_share = ability_on_hit_damage / on_hit_hits
        else:
            static_share = 0.0
        # What this rider is, in the one vocabulary a champion's on-hit
        # magnitude has: the slot behind the champion prefix.  It is not an
        # item mechanic, so it names no rule and prices nothing in the walk.
        mechanic = f"{CHAMPION_PRODUCER_PREFIX}{ability_key}"
        if static_share > 0:
            result.static_on_hit_per_hit += static_share
            result.static_on_hit_shares.append(
                OnHitShare(
                    mechanic,
                    dmg_type,
                    static_share,
                    static_share / per_hit * raw_per_hit if per_hit > 0 else 0.0,
                )
            )

        ability_name = on_hit_data.get("name", f"{ability_key} (on-hit)")
        if stacks_required > 1:
            # Stack-based on-hit (e.g. Vayne W): display as procs.
            # Ramping procs escalate, so their per-proc figure is the
            # average (total / procs) rather than a fixed amount.
            proc_count = hits // stacks_required
            if ramping and proc_count > 0:
                damage_per_proc = ability_on_hit_damage / proc_count
            else:
                damage_per_proc = per_hit * stacks_required
            breakdown[f"on_hit_ability_{ability_key}"] = {
                "name": ability_name,
                "count": proc_count,
                "damage_per_hit": damage_per_proc,
                "total_damage": ability_on_hit_damage,
                "damage_type": dmg_type,
                "unit": "procs",
                "mechanic": mechanic,
            }
        else:
            # Stack-ramped hits escalate, so their per-hit figure is the
            # average (total / hits) rather than the 0-stack base.
            breakdown[f"on_hit_ability_{ability_key}"] = {
                "name": ability_name,
                "count": hits,
                "damage_per_hit": (
                    ability_on_hit_damage / hits if stack_ramp and hits else per_hit
                ),
                "total_damage": ability_on_hit_damage,
                "damage_type": dmg_type,
                "mechanic": mechanic,
            }
        if event_times is not None and event_damages is not None:
            breakdown[f"on_hit_ability_{ability_key}"].update(
                _swing_event_row(
                    event_times,
                    event_damages,
                    dmg_type,
                    raws=event_raws,
                    resists=resists,
                )
            )

    # BoRK: simulate with decreasing target current HP per auto attack.
    # Phantom hit autos cause BoRK to proc twice (at different current HP).
    # Double shot (e.g. Akshan) also procs BoRK an extra time per auto.
    # First-auto packets are priced here as HP-only inputs; their damage row
    # and fight total remain owned by _add_first_auto_strikes.
    first_auto_damage_by_auto = _first_auto_damage_by_auto_for_health_walk(
        state,
        rotation,
        num_auto_attacks,
        swing_times,
        effectiveness=on_hit_effectiveness,
    )
    if current_health_effect is not None and num_auto_attacks > 0:
        (
            current_health_total,
            current_health_hits,
            current_health_hit_damages,
        ) = _simulate_current_health_on_hit(
            effect=current_health_effect,
            base_inputs=_damage_inputs(state),
            swings=AutoSwings(
                target_health=state.target_health,
                num_auto_attacks=num_auto_attacks,
                auto_damage_per_hit=autos.auto_damage_per_hit,
                other_on_hit_per_hit=result.static_on_hit_per_hit,
                resists=resists,
                magic_amp=magic_amp,
            ),
            phantom_hit_autos=result.phantom_hit_autos,
            double_hit_all=autos.double_shot_info is not None,
            effectiveness=on_hit_effectiveness,
            first_auto_damage_by_auto=first_auto_damage_by_auto,
        )
        result.current_health_on_hit_avg = (
            current_health_total / current_health_hits
            if current_health_hits > 0
            else 0.0
        )
        result.current_health_damage_type = current_health_effect.source.damage_type
        on_hit_total += current_health_total

        source = current_health_effect.source
        mechanic = source.previewed_mechanic()
        breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "count": current_health_hits,
            "damage_per_hit": result.current_health_on_hit_avg,
            "total_damage": current_health_total,
            "damage_type": source.damage_type,
            # A preview like the static strikes above author, and the one of
            # the eight whose applications do not share a magnitude: the
            # declaration on each event below is that application's own raw
            # value, and the row's is their sum rather than an average
            # multiplied back up.
            "pair_preview_of": mechanic,
            "declared": _on_hit_declaration(
                mechanic,
                sum(proc.raw for proc in current_health_hit_damages),
            ),
        }
        # The simulation walks the same application order the swing
        # schedule authored, so its per-hit values stamp one event each.
        if application_times and len(current_health_hit_damages) == len(
            application_times
        ):
            breakdown[source.breakdown_key].update(
                _swing_event_row(
                    application_times,
                    [proc.mitigated for proc in current_health_hit_damages],
                    source.damage_type,
                    declarations=[
                        _on_hit_declaration(mechanic, proc.raw)
                        for proc in current_health_hit_damages
                    ],
                    resists=resists,
                )
            )

    # Scheduled live-health on-hits ride the fight's auto timeline and
    # read the target's decayed current HP per proc. Three schedules:
    # ``proc_cooldown`` (Jarvan IV's Martial Cadence) procs the first
    # auto, then the first auto at/after (last proc + per-target
    # cooldown); ``proc_window`` (Camille R's rider) procs every auto
    # landing inside the window after the ability is cast — so a fight
    # that never casts it (auto-only mode) gets nothing;
    # ``missing_health_amp`` (Samira's blade rider) procs the swings a
    # range gate admits, ``max_procs`` of them. Schedule-gated
    # procs don't land on every auto, which is why phantom hits / double
    # shots never add procs and why the proc stays out of
    # static_on_hit_per_hit (spellblade doubling and the BoRK simulation
    # must not re-apply it).
    if num_auto_attacks > 0:
        autos_per_second = state.attack_speed * state.auto_attack_uptime
        # Both proc schedules read the same authored swing times that stamp
        # their events; the uniform fallback only covers an unresolvable
        # schedule, whose rows stay coarse anyway.
        proc_schedule = swing_times or (
            [i / autos_per_second for i in range(num_auto_attacks)]
            if autos_per_second > 0
            else []
        )
        for ability_key, ability_info in state.ability_damages.items():
            on_hit_data = ability_info.get("on_hit")
            if not on_hit_data:
                continue
            if "proc_cooldown" in on_hit_data:
                proc_autos = _schedule_cooldown_procs(
                    proc_schedule, on_hit_data["proc_cooldown"]
                )
            elif "missing_health_amp" in on_hit_data:
                # A range-gated rider on the basic-attack stream: it rides
                # every swing inside the gate, and ``max_procs`` is how many
                # of them the request says land there.
                gated = ability_field(on_hit_data, "max_procs", form="on_hit")
                proc_autos = list(
                    range(
                        num_auto_attacks
                        if gated is None
                        else min(num_auto_attacks, int(gated))
                    )
                )
            elif "proc_window" in on_hit_data:
                if breakdown.get(ability_key, {}).get("casts", 0) < 1:
                    continue  # rider exists only after the ability is cast
                # The triggering auto at t=0 always fits a positive window.
                autos_in_window = max(
                    1,
                    sum(
                        1 for time in proc_schedule if time < on_hit_data["proc_window"]
                    ),
                )
                proc_autos = list(range(min(num_auto_attacks, autos_in_window)))
            else:
                continue
            if not proc_autos:
                continue
            proc_damages = _simulate_hp_scaled_on_hit_procs(
                on_hit_data,
                AutoSwings(
                    target_health=state.target_health,
                    num_auto_attacks=num_auto_attacks,
                    auto_damage_per_hit=autos.auto_damage_per_hit,
                    other_on_hit_per_hit=result.static_on_hit_per_hit
                    + result.current_health_on_hit_avg,
                    resists=resists,
                    magic_amp=magic_amp,
                ),
                proc_autos=proc_autos,
                effectiveness=on_hit_effectiveness,
            )
            proc_total = sum(proc_damages)
            on_hit_total += proc_total
            proc_damage_type = ability_field(on_hit_data, "damage_type", form="on_hit")
            breakdown[f"on_hit_ability_{ability_key}"] = {
                "name": on_hit_data.get("name", f"{ability_key} (on-hit)"),
                "count": len(proc_autos),
                "damage_per_hit": proc_total / len(proc_autos),
                "total_damage": proc_total,
                "damage_type": proc_damage_type,
                "unit": "procs",
            }
            if swing_times:
                # Each proc rides one specific swing — stamp its time.
                breakdown[f"on_hit_ability_{ability_key}"].update(
                    _swing_event_row(
                        [swing_times[i] for i in proc_autos],
                        proc_damages,
                        proc_damage_type,
                        resists=resists,
                    )
                )

    state.total_damage += on_hit_total
    return result
