"""Resolving the cast schedule, admitting it against resources, then pricing every cast."""

from dataclasses import replace
from typing import Any

from collections.abc import Mapping, Sequence

from ...ability_atoms import ability_field
from ...champions.armed_procs import declared_rule, stack_levels_for_casts
from ...ability_spec import DamagePart
from ...control_spec import ControlEvent, cc_kind_reviewed
from ..autos.on_hit_stream import _ability_applied_on_hit_damage
from ..autos.swing_schedule import (
    _auto_attack_timestamps,
    _prepare_hail_attack_schedule,
    _prepare_lethal_tempo_attack_schedule,
)
from ..cast_control_marker import _declared_cc_kind, _entry_control_scope
from ..empower_declaration import _empower_authored_timing, _empower_hits
from ..ledger.event_rows import _damage_type_fields
from ..results import AbilityItemApplication, CastPlan, CastPricing, RotationResult
from ..setup.target_debuffs import (
    _ability_mr,
    _apply_target_shred,
    _debuff_coverage,
    _make_shred_ramp,
)
from ..stacks.rengar import _build_ferocity_timeline
from ..state import FightState, _crit_profile
from .burst_autos import _apply_empowered_burst_autos, _resolve_scheduled_auto_rides
from .cast_parts import _apply_post_hit_proc, _evaluate_cast_parts
from .cast_plan import _resolve_cast_plan
from .cast_schedule import (
    _CAST_SCHEDULE_EPS,
    _disclose_ultimate_cast_rule,
    _schedule_shared_casts,
)
from .resource_admission import _apply_resource_limits
from .stack_timeline import _build_stack_timeline


def _with_stack_levels(
    state: FightState,
    ability_info: Mapping[str, Any],
    plan: CastPlan,
    ability_key: str,
    pricing: tuple[CastPricing, ...] | None,
) -> tuple[CastPricing, ...] | None:
    """Fold this slot's own per-cast stack levels into its cast pricing."""
    payload = ability_info.get("stack_window")
    if not payload:
        return pricing
    rule = declared_rule({ability_key: {"name": ability_key, "armed_procs": payload}})
    if rule is None:
        return pricing
    cast_times = plan.times[ability_key]
    levels = stack_levels_for_casts(
        rule[1],
        cast_times,
        _auto_attack_timestamps(state),
        _stacking_ability_hit_times(
            state, rule[1].arming_slots, state.ability_cast_times
        ),
    )
    base = pricing if pricing is not None else (CastPricing(),) * len(cast_times)
    return tuple(
        replace(price, stack_level=level) for price, level in zip(base, levels)
    )


def _stacking_ability_hit_times(
    state: FightState,
    slots: frozenset[str],
    cast_times: Sequence[tuple[str, float]] = (),
) -> tuple[float, ...]:
    """When this kit's ability hits landed, for a window that counts them.

    Read off the breakdown the rotation has already written, which is the
    accepted ledger: a hit the fight refused cannot stack anything. An
    empty *slots* counts every slot's hits, which is what a kit whose
    innate stacks on anything it lands says; a named set counts only its
    own, which is what a slot that stacks ITSELF says (Yasuo's E).
    """
    times: list[float] = []
    for key, row in state.breakdown.items():
        if not isinstance(row, Mapping):
            continue
        if slots and key not in slots:
            continue
        damage = row.get("total_damage")
        if damage is None or float(damage) <= 0.0:
            continue
        events = row.get("damage_events")
        authored = [
            float(event["time"])
            for event in (events if isinstance(events, list) else ())
            if isinstance(event, Mapping) and event.get("phase") == "ability"
        ]
        if authored:
            times += authored
            continue
        # A row that prices damage and authors no per-hit event still HIT:
        # the single-target model lands every accepted cast, so the cast
        # times are what the stack counter reads. Without this a kit whose
        # rows are coarse would stack nothing at all from its own abilities.
        times += [time for cast_key, time in cast_times if cast_key == key]
    return tuple(sorted(times))


def _compute_ability_rotation(state: FightState) -> RotationResult:
    """Cast the ability rotation and accumulate mitigated ability damage.

    In time-based mode abilities recast when their cooldown expires within
    the fight duration (with ability haste, Spear of Shojin basic-ability
    haste, and Navori auto-attack CD refunds); in one-rotation mode each
    ability is cast exactly once. Damage arithmetic is evaluated from each
    entry's typed DamageParts (_evaluate_cast_parts) — champion-specific
    scaling lives in champion-module closures, never here. This function
    owns scheduling plus Malignance's pre/post-ult MR, Bloodletter's Vile
    Decay stacking, and target shreds applied AFTER the shredding
    ability's own damage.

    On return the rotation's Vile Decay stacks are folded into
    ``effective_mr`` — remaining damage sources occur during/after the
    full rotation.
    """
    resists = state.resists
    breakdown = state.breakdown
    ability_damages = state.ability_damages
    target_health = state.target_health

    result = RotationResult()
    vile_decay_stacks = 0  # Bloodletter's Curse MR reduction stacks
    mitigated_damage_dealt = 0.0  # Running total for missing-HP scaling
    # The same total, but keyed by WHEN it landed.  An HP-scaled part reads
    # this rather than the running total, so a part that lands before an
    # ability evaluated ahead of it is not credited with damage that has not
    # happened yet (Veigar R against his own W meteor).  Rotation order and
    # landing order agree for almost every kit, and where they agree the two
    # answers are identical.
    landed_ledger: list[tuple[float, float]] = []

    def _landed_by(instant: float) -> float:
        """Mitigated damage on the target strictly before *instant*."""
        return sum(
            amount
            for when, amount in landed_ledger
            if when < instant - _CAST_SCHEDULE_EPS
        )

    first_ability_key: str | None = None

    # NOTE: Blackfire Torch's 4% AP amp is baked into champion_stats, but
    # the first ability in cast_order fires before any target is burning
    # (so it should use ~4% less AP).  This is a known minor inaccuracy
    # (~2% on the first ability) that would require re-parsing ability
    # damages mid-fight to fix properly.

    # Basic attacks may reduce basic ability cooldowns.  A build declaring no
    # refund gets a zero here rather than a slot, which is what the rest of
    # the rotation's arithmetic reads.
    refund = _crit_profile(state).cooldown_refund
    result.navori_refund = refund.fraction if refund is not None else 0.0
    result.has_navori = result.navori_refund > 0
    result.autos_per_second = (
        state.attack_speed * state.auto_attack_uptime
        if result.navori_refund > 0
        else 0.0
    )

    basic_ability_haste = state.champion_stats["basic_ability_haste"]

    # Timed mode: all abilities share one cast timeline (cast times lock
    # out other casts). One-rotation and autos-only modes never recast,
    # so they skip scheduling entirely.
    timed_mode = state.combat_events is not None or not (
        state.one_rotation or state.auto_attacks_only
    )
    schedule = (
        _schedule_shared_casts(state, result, basic_ability_haste) if timed_mode else {}
    )
    _disclose_ultimate_cast_rule(state, timed_mode)

    # Resolve WHEN everything casts before pricing anything: the stack
    # timeline (Case 4/5) must exist before the first cast is priced, and
    # both it and the DoT integration afterwards read this one plan.
    requested_plan = _resolve_cast_plan(state, schedule)
    plan = _apply_resource_limits(state, requested_plan)
    if state.combat_events is not None and plan.counts != requested_plan.counts:
        raise ValueError("combat_events contains a cast with insufficient resource")
    result.last_cast_time = plan.last_cast_time
    result.resource_spent = plan.resource_spent
    result.resource_remaining = plan.resource_remaining
    result.resource_ledger = plan.resource_ledger
    cast_event_order = {slot: index for index, slot in enumerate(state.cast_order)}
    result.cast_events = sorted(
        (
            {
                "time": round(cast_time, 3),
                "slot": ability_key,
                "name": ability_damages[ability_key].get("name", ability_key),
                "ordinal": ordinal + 1,
                "cast_id": f"{ability_key}:{ordinal + 1}",
                "target_id": f"target:{state.roster_target_index}",
                "resource_cost": float(
                    ability_field(ability_damages[ability_key], "resource_cost")
                ),
                **plan.resource_by_cast.get((ability_key, ordinal), {}),
            }
            for ability_key, times in plan.times.items()
            for ordinal, cast_time in enumerate(times)
        ),
        key=lambda event: (
            event["time"],
            cast_event_order.get(event["slot"], len(cast_event_order)),
            event["ordinal"],
        ),
    )
    if plan.omitted_for_resource:
        omitted_counts = {
            key: plan.omitted_for_resource.count(key)
            for key in dict.fromkeys(plan.omitted_for_resource)
        }
        detail = ", ".join(f"{key} x{count}" for key, count in omitted_counts.items())
        state.notes.append(
            f"Started at full resource; insufficient resource omitted {detail}."
        )
    # An empowered burst that sets its own attack speed re-times the auto
    # stream — do it before anything prices an auto or counts an on-hit.
    _apply_empowered_burst_autos(state, plan)
    _prepare_hail_attack_schedule(state)
    _prepare_lethal_tempo_attack_schedule(state)
    # Riders read the finished swing schedule, so they resolve after every
    # keystone that owns one has installed it.
    _resolve_scheduled_auto_rides(state, plan)
    state.stack_timeline = _build_stack_timeline(state, plan)
    timeline = state.stack_timeline
    state.ferocity_timeline = _build_ferocity_timeline(state, plan)
    ferocity_timeline = state.ferocity_timeline
    if ferocity_timeline is not None:
        # P3 package 3V: the Ferocity counter rides the public
        # resource-ledger section (an additive sub-section like
        # auto_restore/mark_refunds — the mana-only account is untouched).
        ledger_section = result.resource_ledger
        if not isinstance(ledger_section, dict):
            ledger_section = {}
            result.resource_ledger = ledger_section
        rule = ferocity_timeline.stack.rule
        stack = ferocity_timeline.stack
        result.resource_ledger = {
            "contract": "resource_ledger_v1",
            "owner": "main",
            "kind": "ferocity",
            "opening_maximum": rule.max_stacks,
            "opening_current": ferocity_timeline.starting_stacks,
            "closing_maximum": rule.max_stacks,
            "closing_current": stack.stacks,
            "base_maximum": rule.max_stacks,
            "bonus_maximum": 0,
            "receipts": ferocity_timeline.receipts,
            "declaration": rule.public_receipt(),
            "state_transitions": stack.public_receipt()["transitions"],
        }

    for ability_key in state.cast_order:
        if ability_key not in ability_damages:
            continue
        ability_info = ability_damages[ability_key]

        num_casts = plan.counts[ability_key]
        # Per-cast timeline pricing: a mid-fight bonus-AD steroid active
        # at that cast, and the DoT stacks on the target when it lands.
        pricing = (
            tuple(
                timeline.cast_pricing(ability_key, ordinal, cast_time)
                for ordinal, cast_time in enumerate(plan.times[ability_key])
            )
            if timeline is not None
            else None
        )
        # Case 6: a slot whose damage reads a stack level its OWN window
        # collected (Tristana's Explosive Charge). The level is walked from
        # the streams the module says stack it, one window per cast, and
        # rides the same per-cast pricing seam the DoT stacks do.
        pricing = _with_stack_levels(state, ability_info, plan, ability_key, pricing)
        # P3 package 3V: Rengar's live Ferocity walk marks the casts that
        # consume the 4-stack cap (empowered); the entry's ferocity_parts
        # replace the base parts for those casts.
        ferocity_timeline = state.ferocity_timeline
        ferocity_empowered = (
            tuple(
                ferocity_timeline.cast_empowered(ability_key, ordinal)
                for ordinal in range(num_casts)
            )
            if ferocity_timeline is not None
            else None
        )
        ferocity_parts = ability_info.get("ferocity_parts")

        # Hatefog's zone opens on an accepted R cast; an R the resource
        # budget refused opens nothing, and the served MR says so.
        if ability_key == "R" and num_casts > 0:
            resists.mark_ult_cast()

        result.total_ability_casts += num_casts
        # Damaging hit instances: each damaging part is one hit per cast
        # (Aurora Q = first cast + recast = 2). Feeds on-hit stack
        # counters that count ability hits (``count_ability_hits``).
        result.total_ability_hits += num_casts * sum(
            part.count
            for part in ability_info["parts"]
            if part.amount > 0 or part.hp_scaled_damage is not None
        )
        damage_type = ability_info["damage_type"]

        # Bloodletter's Curse: magic damage abilities apply a Vile Decay
        # stack. The ability's own damage benefits from its stack.
        ability_stacks = 0
        if resists.mr_shred is not None and resists.mr_shred.accrues_on(damage_type):
            vile_decay_stacks = min(
                vile_decay_stacks + 1,
                resists.mr_shred.max_stacks,
            )
            ability_stacks = vile_decay_stacks
        ability_mr = _ability_mr(resists, ability_stacks)

        # All damage arithmetic is typed DamageParts — champion-specific
        # scaling lives in the champion module's closures, never here.
        parts = ability_info["parts"]
        # An empowered-auto cast with no auto stream to ride (one-rotation
        # mode, or a timed fight at zero auto uptime) still forces its
        # basic attack(s) — carry the consumed swings on the ability's
        # own row, matching the in-game "attack + bonus" hit (Blitzcrank
        # E, Vayne Q; Cho'Gath E forces ``hits`` = 3 swings). Timed
        # fights WITH autos never get here: casts are capped by the auto
        # count above, and the auto stream itself carries the swings. A
        # dict-valued flag may carry module-authored ``swing_parts``
        # replacing the default expected-crit swing (Camille Q: the
        # whole attack cannot crit and may convert to true damage).
        empower = ability_info.get("empowers_next_auto")
        forced_swings = 0
        if empower and num_casts > 0 and state.num_auto_attacks == 0:
            hits = _empower_hits(empower)
            forced_swings = num_casts * hits
            result.forced_basic_attacks += forced_swings
            result.forced_swing_casts += num_casts
            authored_timing = _empower_authored_timing(empower)
            if authored_timing is not None:
                first_delay, attack_interval = authored_timing
                parts = tuple(
                    (
                        replace(
                            part,
                            time_offset=first_delay,
                            hit_interval=(attack_interval if part.count > 1 else None),
                        )
                        if part.count == hits and part.time_offset is None
                        else part
                    )
                    for part in parts
                )
            # The forced attack is this cast's own hit, so its part carries
            # the slot's declared control kind — what ``_apply_module_cc``
            # stamped on the parts the module emitted and what the swing
            # author lands on a consumed swing when a stream exists.
            declared_cc = _declared_cc_kind(parts)
            if isinstance(empower, dict) and "swing_parts" in empower:
                swing_parts = tuple(
                    (
                        replace(part, cc_kind=declared_cc)
                        if declared_cc is not None and part.cc_kind is None
                        else part
                    )
                    for part in empower["swing_parts"]
                )
                if authored_timing is not None:
                    first_delay, attack_interval = authored_timing
                    swing_parts = tuple(
                        (
                            replace(
                                part,
                                time_offset=first_delay,
                                hit_interval=(
                                    attack_interval if part.count > 1 else None
                                ),
                            )
                            if part.count == hits and part.time_offset is None
                            else part
                        )
                        for part in swing_parts
                    )
                parts = parts + swing_parts
            else:
                first_delay = None
                attack_interval = None
                if authored_timing is not None:
                    first_delay, attack_interval = authored_timing
                swing = DamagePart(
                    "physical",
                    state.champion_stats["attack_damage"],
                    count=hits,
                    crit_effectiveness=1.0,
                    basic_damage=True,
                    # A basic attack is 100% total AD, so a mid-fight
                    # bonus-AD steroid raises the forced swing 1:1.
                    bonus_ad_ratio=1.0,
                    time_offset=first_delay,
                    hit_interval=(attack_interval if hits > 1 else None),
                    cc_kind=declared_cc,
                )
                parts = (*parts, swing)
        # A ramped shred (Corki E) stacks up across this ability's own
        # hits; an unramped one lands in full after it (below).
        shred_ramp = _make_shred_ramp(resists, ability_info, ability_stacks)
        cast_times = plan.times.get(ability_key, ())
        if state.combat_events is not None:
            # An area cast reaches every enemy the roster holds, so every
            # pair prices it whoever the author named; any other cast is
            # priced only in the pair whose target the author named. A
            # damage cast may only name an enemy (combat_events certifies
            # the recipients), so "any recipient" here is "any enemy".
            reaches_every_enemy = bool(ability_info.get("area_damage"))
            selected_times = {
                event.time
                for event in state.combat_events
                if event.caster_id == state.event_actor_id
                and event.slot == ability_key
                and (reaches_every_enemy or event.recipient_id == state.event_target_id)
            }
            cast_times = tuple(time for time in cast_times if time in selected_times)
        authored_controls = tuple(ability_field(ability_info, "control_events"))
        for control in authored_controls:
            if not isinstance(control, ControlEvent):
                raise TypeError(
                    f"{ability_key} control_events must contain ControlEvent"
                )
        # A targeted cast holds one enemy, so it is allocated to the first
        # roster index the way a target-limited item proc is; every other
        # pair fight is scored without it.  The row's declaration is
        # filtered with its events so the breakdown cannot claim a control
        # this target never held.
        control_specs = tuple(
            control
            for control in authored_controls
            if state.combat_events is not None
            or control.scope.reaches(state.roster_target_index)
        )
        if control_specs:
            serialized_controls: list[dict[str, Any]] = []
            serialized_controls.extend(
                {
                    "kind": "crowd_control",
                    "cc_kind": control.kind,
                    "cc_duration": float(control.duration),
                    **(
                        {"cc_magnitude": float(control.magnitude)}
                        if control.magnitude
                        else {}
                    ),
                    "time_offset": control.time_offset,
                    "count": int(control.count),
                    "hit_interval": control.hit_interval,
                    "skillshot": bool(
                        control.skillshot or ability_info.get("skillshot")
                    ),
                }
                for control in control_specs
            )
            for cast_index, cast_time in enumerate(cast_times):
                ordinal = (
                    plan.times[ability_key].index(cast_time) + 1
                    if state.combat_events is not None
                    else cast_index + 1
                )
                cast_id = f"{ability_key}:{ordinal}"
                target_id = f"target:{state.roster_target_index}"
                for control in control_specs:
                    offset = (
                        float(control.time_offset)
                        if control.time_offset is not None
                        else 0.0
                    )
                    interval = float(control.hit_interval or 0.0)
                    reviewed = cc_kind_reviewed(control.kind)
                    for control_index in range(control.count):
                        result.control_events.append(
                            {
                                "time": float(cast_time)
                                + offset
                                + interval * control_index,
                                "kind": "crowd_control",
                                "cc_kind": control.kind,
                                "cc_duration": float(control.duration),
                                **(
                                    {"cc_magnitude": float(control.magnitude)}
                                    if control.magnitude
                                    else {}
                                ),
                                "damage": 0.0,
                                "damage_type": "",
                                "source_key": ability_key,
                                "source": ability_info.get("name", ability_key),
                                "is_ability": True,
                                "cast_id": cast_id,
                                "application_id": cast_id,
                                "target_id": target_id,
                                **({"cc_reviewed": True} if reviewed else {}),
                                "skillshot": bool(
                                    control.skillshot or ability_info.get("skillshot")
                                ),
                                "event_precision": (
                                    "exact"
                                    if control.time_offset is not None
                                    else "cast_boundary"
                                ),
                                **(
                                    {
                                        "control_source_atoms": [
                                            dict(atom)
                                            for atom in ability_field(
                                                ability_info, "control_source_atoms"
                                            )
                                        ]
                                    }
                                    if ability_info.get("control_source_atoms")
                                    else {}
                                ),
                                "sequence": 1_000_000 + len(result.control_events),
                            }
                        )
        (
            ability_total,
            first_part_damage,
            ability_by_type,
            ability_events,
        ) = _evaluate_cast_parts(
            state,
            parts,
            len(cast_times) if state.combat_events is not None else num_casts,
            ability_mr,
            mitigated_damage_dealt,
            on_hit=shred_ramp.stage if shred_ramp is not None else None,
            pricing=pricing,
            cast_times=cast_times,
            single_hit_event_certified=(
                ability_info.get("event_order_certified") == "single_hit"
            ),
            damage_over_time=bool(
                ability_info.get("dot_duration")
                or ability_info.get("dot_tick_interval")
            ),
            ferocity_empowered=ferocity_empowered,
            empowered_parts=ferocity_parts,
            cc_reviewed=bool(ability_info.get("cc_reviewed")),
            cc_scope=_entry_control_scope(ability_info),
            landed_by=_landed_by,
        )
        if ability_info.get("cast_while_disabled"):
            # The row states, once, that its damage is not the caster's own
            # action (pets, summons, persistent zones).  Every event it
            # authored carries the fact, because the walk asks it per packet.
            for event in ability_events:
                event["cast_while_disabled"] = True

        # Apply ability-specific damage amplifiers (e.g., Actualizer).  When
        # the active has an authored expiry, exact hit receipts are split at
        # that boundary instead of treating the whole rotation as active.
        ability_amp = state.ability_amp
        active_event_damage = 0.0
        event_base_damage = sum(float(event["damage"]) for event in ability_events)
        if state.actualizer_active_until > 0.0:
            if ability_events:
                active_event_damage = sum(
                    float(event["damage"])
                    for event in ability_events
                    if float(event["time"])
                    < state.actualizer_active_until - _CAST_SCHEDULE_EPS
                )
                if event_base_damage > 0.0:
                    ability_total += active_event_damage * (ability_amp - 1.0)
            elif cast_times:
                active_casts = sum(
                    1
                    for time in cast_times[:num_casts]
                    if float(time) < state.actualizer_active_until - _CAST_SCHEDULE_EPS
                )
                ability_total *= 1.0 + (ability_amp - 1.0) * active_casts / max(
                    1, num_casts
                )
            else:
                # No authored timestamps means the direct engine path cannot
                # split the active window; preserve its explicit active
                # assumption rather than silently dropping the amp.
                ability_total *= ability_amp
        else:
            ability_total *= ability_amp

        # Muramana procs once per DAMAGING ability cast: Shock is gated on
        # "Dealing ability damage to champions" (P3 package 3E), so a cast
        # that deals zero damage (spell-shield slots, rank-0 leftovers,
        # stat-buff ultimates) never procs.  Multi-instance abilities (e.g.
        # Ahri R with 3 dashes) proc once per instance.
        cast_instances = ability_field(ability_info, "cast_instances")
        if num_casts > 0 and ability_total > 0.0:
            result.total_muramana_procs += cast_instances * num_casts

        # Track the first ability hit for Horizon Focus (trigger, not amped).
        # For mixed-type abilities (e.g. Ahri Q: magic outgoing + true return),
        # only the first hit (magic portion) triggers — the return is amped.
        if first_ability_key is None and num_casts > 0 and ability_total > 0.0:
            first_ability_key = ability_key
            if damage_type == "mixed":
                result.first_ability_damage = first_part_damage
            else:
                result.first_ability_damage = ability_total / num_casts

        breakdown[ability_key] = {
            "name": ability_info["name"],
            "casts": num_casts,
            "total_damage": ability_total,
            "damage_type": damage_type,
            "total_raw": sum(
                float(part.amount) * max(1, int(part.count)) for part in parts
            ),
        }
        if bool(ability_info.get("skillshot")) or any(part.skillshot for part in parts):
            breakdown[ability_key]["skillshot"] = True
        if bool(ability_info.get("area_damage")):
            breakdown[ability_key]["area_damage"] = True
        # Module-authored self-shield payloads (E8c) ride the ability's
        # damage events: ``_ordered_damage_events`` copies each aligned
        # entry onto the matching damage-event row as ``self_shield`` so the
        # participant ledger can grant a timed self-shield at that event's
        # timestamp.  The Eclipse item authors the identical breakdown shape
        # (``self_shield_events``), so the ledger path is shared, not new.
        if ability_info.get("self_shield_events") is not None:
            breakdown[ability_key]["self_shield_events"] = ability_info[
                "self_shield_events"
            ]
        timing_is_authored = bool(parts) and all(
            part.time_offset is not None
            and (part.count <= 1 or part.hit_interval is not None)
            for part in parts
        )
        has_dynamic_part = any(part.hp_scaled_damage is not None for part in parts)
        single_hit_certified = ability_info.get("event_order_certified") == "single_hit"
        if (
            timing_is_authored
            or has_dynamic_part
            or (single_hit_certified and ability_events)
        ) and ability_events:
            breakdown[ability_key]["damage_events"] = [
                {
                    **event,
                    "damage": event["damage"]
                    * (
                        ability_amp
                        if state.actualizer_active_until <= 0.0
                        or float(event["time"])
                        < state.actualizer_active_until - _CAST_SCHEDULE_EPS
                        else 1.0
                    ),
                }
                for event in ability_events
            ]
            breakdown[ability_key]["event_phase"] = "ability"
        # With no auto row to report them, the basic attacks this cast
        # forced — and the crit riding them — are otherwise invisible:
        # the UI's "N casts" text says nothing about the swings folded
        # into this row. Crit here is priced as an EXPECTED value, so
        # state the rate rather than inventing an integer crit count.
        if forced_swings > 0:
            # Preserve the fact that this ability row contains a real basic
            # attack when no authored hit timing exists. Reactive defender
            # effects must still recognize the forced swing.
            breakdown[ability_key]["basic_attack"] = True
            detail = f"{num_casts} cast{'' if num_casts == 1 else 's'}"
            detail += f", {forced_swings} attack{'' if forced_swings == 1 else 's'}"
            if state.crit_chance > 0:
                detail += f" @ {round(state.crit_chance * 100)}% crit"
            breakdown[ability_key]["detail"] = detail
        active_damage_types = {
            dtype for dtype, amount in ability_by_type.items() if amount > 0
        }
        if damage_type == "mixed" or len(active_damage_types) > 1:
            # Exact composition for the physical/magic/true split. This also
            # covers an empowered magic on-hit whose forced basic-attack swing
            # adds a physical part to the same visible row (Shen Q).
            breakdown[ability_key]["damage_by_type"] = {
                dtype: amount * state.ability_amp
                for dtype, amount in ability_by_type.items()
                if amount > 0
            }
        # Champion-minted display text (e.g. Aurelion Sol E's execute
        # threshold) rides the entry onto its breakdown row untouched.
        if "detail" in ability_info:
            breakdown[ability_key]["detail"] = ability_info["detail"]
        if control_specs:
            breakdown[ability_key]["control_events"] = serialized_controls
        state.total_damage += ability_total
        mitigated_damage_dealt += ability_total
        # File this ability's damage under the instants it landed at.  A row
        # that authored no event times has no landing instant of its own, so
        # it is filed at its first cast -- the earliest moment any of it
        # could have landed, which is the answer that keeps a later part
        # from under-counting it.
        if ability_events:
            landed_ledger.extend(
                (
                    float(event["time"]),
                    float(event["damage"]) * ability_amp,
                )
                for event in ability_events
            )
        elif ability_total:
            # A row that authored no event times has no clock of its own.
            # The rotation is then the only ordering there is, and it put
            # this row first, so it is filed before every instant -- which
            # is exactly what the running total meant before there were
            # timed rows to disagree with it.
            landed_ledger.append((float("-inf"), ability_total))

        # Ability-carried item applications (Bel'Veth Q/E): each hit
        # applies the build's per-hit on-hit item effects at the slot's
        # declared effectiveness. The per-hit damage comes from the same
        # compiled specs the auto stream reads; each application decays
        # the modeled target HP so BoRK's current-health formula ramps
        # down through the combo. The slot's effectiveness is its own
        # modifier — a champion ``auto_attack_override`` effectiveness
        # applies to autos only. The spec's ``triggers`` declare what
        # the application carries: "on_hit" (per-hit item damage +
        # on-hit counters) and/or "on_attack" (counts as an attack for
        # on-attack cadences like Guinsoo's phantom hit). Counter procs
        # themselves fire in _add_stacking_strikes and
        # _layer_on_hit_effects from the records kept here.
        on_hit_spec = ability_info.get("applies_item_on_hits")
        if on_hit_spec and num_casts > 0:
            applications = num_casts * int(on_hit_spec["hits"])
            effectiveness = float(on_hit_spec["effectiveness"])
            triggers = frozenset(ability_field(on_hit_spec, "triggers", form="on_hit"))
            is_on_hit = "on_hit" in triggers
            applied_total = 0.0
            applied_by_type: dict[str, float] = {}
            application_times = [
                float(event["time"])
                for event in ability_events
                if isinstance(event, dict)
            ]
            if len(application_times) < applications:
                # A carrier may have several ordered hits inside a cast while
                # the ability itself has no sourced sub-hit delay.  Preserve
                # the cast's authored boundary for each application instead
                # of leaving the shared on-hit counter untimestamped.  The
                # order remains the module's part order; no fractional
                # average or target-health guess is introduced.
                cast_times = [float(time) for time in plan.times.get(ability_key, ())]
                hits_per_cast = max(
                    1, int(ability_field(on_hit_spec, "hits", form="on_hit"))
                )
                fallback_times = [
                    cast_time for cast_time in cast_times for _ in range(hits_per_cast)
                ]
                if len(fallback_times) >= applications:
                    application_times = fallback_times[:applications]
            application_events: list[dict[str, Any]] | None = []
            for application_index in range(applications):
                hp_now = max(0.0, target_health - mitigated_damage_dealt)
                authored_time = (
                    application_times[application_index]
                    if application_index < len(application_times)
                    and len(application_times) >= applications
                    else None
                )
                result.ability_item_applications.append(
                    AbilityItemApplication(
                        effectiveness=effectiveness,
                        target_hp=hp_now,
                        on_hit=is_on_hit,
                        on_attack="on_attack" in triggers,
                        time=authored_time,
                    )
                )
                applied = (
                    _ability_applied_on_hit_damage(state, effectiveness, hp_now)
                    if is_on_hit
                    else {}
                )
                applied_sum = sum(applied.values())
                for dtype, amount in applied.items():
                    applied_by_type[dtype] = applied_by_type.get(dtype, 0.0) + amount
                # Each application applies every per-hit item packet at its
                # own triggering hit's authored time; one untimed carrier
                # keeps the row coarse rather than inventing a boundary.
                if application_events is not None:
                    if authored_time is None:
                        application_events = None
                    else:
                        application_events.extend(
                            {
                                "time": authored_time,
                                "damage": amount,
                                "damage_type": dtype,
                            }
                            for dtype, amount in applied.items()
                            if amount > 0
                        )
                applied_total += applied_sum
                mitigated_damage_dealt += applied_sum
            if applied_total > 0:
                breakdown[f"on_hit_items_{ability_key}"] = {
                    "name": f"{ability_info['name']} (item on-hits)",
                    "count": applications,
                    "damage_per_hit": applied_total / applications,
                    "total_damage": applied_total,
                    **_damage_type_fields(applied_by_type),
                }
                if application_events:
                    breakdown[f"on_hit_items_{ability_key}"].update(
                        {
                            "damage_events": application_events,
                            "event_phase": "ability",
                        }
                    )
                state.total_damage += applied_total

        # Stack/combo procs whose resistance debuff begins only AFTER the
        # proc damage (Vi W) live between the triggering hit and the next
        # ability. They are damage events, not additional casts.
        post_hit_total = _apply_post_hit_proc(
            state,
            ability_key,
            ability_info,
            num_casts,
            cast_times=plan.times.get(ability_key, ()),
            running_damage=mitigated_damage_dealt,
            pricing=pricing,
        )
        mitigated_damage_dealt += post_hit_total

        # Apply target debuffs (e.g. Kog'Maw Q resistance shred) AFTER
        # computing this ability's own damage, so subsequent abilities
        # benefit from the shred but the source ability does not. An
        # ability that never gets cast (autos-only mode) shreds nothing.
        # A ramped debuff already staged itself across the ability's own
        # hits; only its unfired remainder lands here.
        target_debuff = ability_info.get("target_debuff")
        if target_debuff and num_casts > 0:
            # A shred that expires is applied time-weighted by how much
            # of the fight its windows actually cover (see
            # ``_debuff_coverage``); one with no declared duration lasts
            # the fight, as it always has.
            # One-rotation mode is a burst: the whole combo lands well
            # inside any shred window, and its ``fight_duration_seconds``
            # is only a nominal cap — weighting by it would be arbitrary.
            # A debuff an empowered swing delivers opens its window at that
            # swing, not at the cast that armed it (Jayce's Cannon
            # Transform shreds when the attack lands).
            debuff_times = state.empowered_ride_times.get(
                ability_key
            ) or plan.times.get(ability_key, ())
            coverage = (
                1.0
                if state.one_rotation
                else _debuff_coverage(
                    debuff_times,
                    ability_field(target_debuff, "duration", form="target_debuff"),
                    state.fight_duration_seconds,
                )
            )
            if shred_ramp is not None:
                shred_ramp.apply_remainder(coverage)
            else:
                _apply_target_shred(resists, target_debuff, coverage)

    # The rotation's outcome for non-ability damage: the debuff it left on
    # the target, which the remaining damage (autos, on-hit, item procs)
    # meets at full depth.  ``Resists._select_mr`` serves the MR once.
    resists.apply_shred_stacks(vile_decay_stacks)

    return result
