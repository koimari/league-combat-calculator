"""Resolving the cast schedule, admitting it against resources, then pricing every cast."""

from dataclasses import replace
from typing import Any

from collections.abc import Mapping, Sequence

from ...ability_atoms import ability_field
from ...champions.armed_procs import declared_rule, stack_levels_for_casts
from ...control_spec import ControlEvent
from ..autos.swing_schedule import (
    _auto_attack_timestamps,
    _prepare_hail_attack_schedule,
    _prepare_lethal_tempo_attack_schedule,
)
from ..cast_control_marker import _entry_control_scope
from ..results import CastPlan, CastPricing, RotationResult
from ..setup.target_debuffs import _ability_mr, _make_shred_ramp
from ..stacks.rengar import _build_ferocity_timeline
from ..state import FightState, _crit_profile
from .burst_autos import _apply_empowered_burst_autos, _resolve_scheduled_auto_rides
from .cast_parts import _apply_post_hit_proc, _evaluate_cast_parts
from .cast_plan import _resolve_cast_plan
from .cast_schedule import (
    _CAST_SCHEDULE_EPS,
    _disclose_ultimate_cast_rule,
    CooldownRefunds,
    _schedule_shared_casts,
    declares_swing_cooldown_refund,
)
from .cast_slot import (
    _apply_ability_item_on_hits,
    _apply_slot_target_debuff,
    _author_control_events,
    _forced_swing_parts,
)
from .resource_admission import _apply_resource_limits
from .stack_timeline import _build_stack_timeline


def _with_stack_levels(
    state: FightState,
    *,
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
            state,
            rule[1].arming_slots,
            state.ability_cast_times,
            own_slot=ability_key,
            own_cast_times=cast_times,
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
    *,
    own_slot: str = "",
    own_cast_times: Sequence[float] = (),
) -> tuple[float, ...]:
    """When this kit's ability hits landed, for a window that counts them.

    Read off the breakdown the rotation has already written, which is the
    accepted ledger: a hit the fight refused cannot stack anything. An
    empty *slots* counts every slot's hits, which is what a kit whose
    innate stacks on anything it lands says; a named set counts only its
    own, which is what a slot that stacks ITSELF says (Yasuo's E).

    A slot that stacks ITSELF is the one case the breakdown cannot answer:
    the rotation is pricing that slot right now, so its row is not written
    yet and the loop below never reaches it. *own_cast_times* is its cast
    plan, which is what the breakdown row would have reported, and the walk
    excludes each cast's own instant, so a cast is stacked by the casts
    before it and never by itself.
    """
    times: list[float] = []
    if own_slot and (not slots or own_slot in slots):
        if not isinstance(state.breakdown.get(own_slot), Mapping):
            times += [float(time) for time in own_cast_times]
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
    # The swing rate is measured only when something reads it, and TWO things
    # do: Navori Flickerblade's share of what is left, and a kit grant's flat
    # seconds (Sivir's On the Hunt). Gating it on Navori alone left the kit
    # refund walking at zero attacks a second, which fails closed to the
    # unrefunded cooldown and is silent.
    result.autos_per_second = (
        state.attack_speed * state.auto_attack_uptime
        if result.navori_refund > 0 or declares_swing_cooldown_refund(state)
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
        _schedule_shared_casts(state, CooldownRefunds.of(result), basic_ability_haste)
        if timed_mode
        else {}
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
        pricing = _with_stack_levels(
            state,
            ability_info=ability_info,
            plan=plan,
            ability_key=ability_key,
            pricing=pricing,
        )
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
        parts, forced_swings = _forced_swing_parts(
            state, result, ability_info, num_casts
        )
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
        serialized_controls = _author_control_events(
            state,
            result,
            ability_key,
            ability_info,
            control_specs=control_specs,
            cast_times=cast_times,
            plan=plan,
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

        mitigated_damage_dealt = _apply_ability_item_on_hits(
            state,
            result,
            ability_key,
            ability_info,
            num_casts,
            ability_events=ability_events,
            plan=plan,
            running_damage=mitigated_damage_dealt,
        )

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

        _apply_slot_target_debuff(
            state,
            ability_key,
            ability_info,
            num_casts,
            plan=plan,
            shred_ramp=shred_ramp,
        )

    # The rotation's outcome for non-ability damage: the debuff it left on
    # the target, which the remaining damage (autos, on-hit, item procs)
    # meets at full depth.  ``Resists._select_mr`` serves the MR once.
    resists.apply_shred_stacks(vile_decay_stacks)

    return result
