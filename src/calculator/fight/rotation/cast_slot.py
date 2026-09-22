"""One slot of the rotation: what it swings, controls, carries and leaves behind."""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from ...ability_atoms import ability_field
from ...ability_spec import DamagePart
from ...control_spec import ControlEvent, cc_kind_reviewed
from ..autos.on_hit_stream import _ability_applied_on_hit_damage
from ..cast_control_marker import _declared_cc_kind
from ..empower_declaration import _empower_authored_timing, _empower_hits
from ..ledger.event_rows import _damage_type_fields
from ..results import AbilityItemApplication, CastPlan, RotationResult
from ..setup.target_debuffs import _apply_target_shred, _debuff_coverage
from ..state import FightState


def _forced_swing_parts(
    state: FightState,
    result: RotationResult,
    ability_info: Mapping[str, Any],
    num_casts: int,
) -> tuple[Sequence[DamagePart], int]:
    """This slot's damage parts with the basic attacks it forces, and how many.

    An empowered-auto cast with no auto stream to ride (one-rotation mode,
    or a timed fight at zero auto uptime) still forces its basic attack(s):
    the consumed swings ride the ability's own row, matching the in-game
    "attack + bonus" hit (Blitzcrank E, Vayne Q; Cho'Gath E forces ``hits``
    = 3 swings).  Timed fights WITH autos never reach the branch, because
    casts are capped by the auto count and the auto stream itself carries
    the swings.  A dict-valued flag may carry module-authored
    ``swing_parts`` replacing the default expected-crit swing (Camille Q:
    the whole attack cannot crit and may convert to true damage).
    """
    parts = ability_info["parts"]
    empower = ability_info.get("empowers_next_auto")
    if not (empower and num_casts > 0 and state.num_auto_attacks == 0):
        return parts, 0
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
                        hit_interval=(attack_interval if part.count > 1 else None),
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
    return parts, forced_swings


def _author_control_events(
    state: FightState,
    result: RotationResult,
    ability_key: str,
    ability_info: Mapping[str, Any],
    *,
    control_specs: Sequence[ControlEvent],
    cast_times: Sequence[float],
    plan: CastPlan,
) -> list[dict[str, Any]]:
    """Author one slot's control events, and return the row's declaration.

    A targeted cast holds one enemy, so *control_specs* is already filtered
    to what this target held: the returned declaration cannot claim a
    control the breakdown row never delivered.  One event per control per
    cast per count, at the control's own offset and interval off the cast.
    """
    if not control_specs:
        return []
    serialized_controls: list[dict[str, Any]] = []
    serialized_controls.extend(
        {
            "kind": "crowd_control",
            "cc_kind": control.kind,
            "cc_duration": float(control.duration),
            **({"cc_magnitude": float(control.magnitude)} if control.magnitude else {}),
            "time_offset": control.time_offset,
            "count": int(control.count),
            "hit_interval": control.hit_interval,
            "skillshot": bool(control.skillshot or ability_info.get("skillshot")),
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
                float(control.time_offset) if control.time_offset is not None else 0.0
            )
            interval = float(control.hit_interval or 0.0)
            reviewed = cc_kind_reviewed(control.kind)
            for control_index in range(control.count):
                result.control_events.append(
                    {
                        "time": float(cast_time) + offset + interval * control_index,
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
    return serialized_controls


def _apply_ability_item_on_hits(
    state: FightState,
    result: RotationResult,
    ability_key: str,
    ability_info: Mapping[str, Any],
    num_casts: int,
    *,
    ability_events: Sequence[Mapping[str, Any]],
    plan: CastPlan,
    running_damage: float,
) -> float:
    """Apply this slot's carried item on-hits, and return the running total.

    Ability-carried item applications (Bel'Veth Q/E): each hit applies the
    build's per-hit on-hit item effects at the slot's declared
    effectiveness.  The per-hit damage comes from the same compiled specs
    the auto stream reads; each application decays the modeled target HP, so
    BoRK's current-health formula ramps down through the combo, which is why
    the running mitigated total enters and leaves here rather than being
    folded in as one delta.  The slot's effectiveness is its own modifier --
    a champion ``auto_attack_override`` effectiveness applies to autos only.
    The spec's ``triggers`` declare what the application carries: "on_hit"
    (per-hit item damage and on-hit counters) and/or "on_attack" (counts as
    an attack for on-attack cadences like Guinsoo's phantom hit).  Counter
    procs themselves fire in ``_add_stacking_strikes`` and
    ``_layer_on_hit_effects`` from the records kept here.
    """
    breakdown = state.breakdown
    target_health = state.target_health
    on_hit_spec = ability_info.get("applies_item_on_hits")
    if not (on_hit_spec and num_casts > 0):
        return running_damage
    applications = num_casts * int(on_hit_spec["hits"])
    effectiveness = float(on_hit_spec["effectiveness"])
    triggers = frozenset(ability_field(on_hit_spec, "triggers", form="on_hit"))
    is_on_hit = "on_hit" in triggers
    applied_total = 0.0
    applied_by_type: dict[str, float] = {}
    application_times = [
        float(event["time"]) for event in ability_events if isinstance(event, dict)
    ]
    if len(application_times) < applications:
        # A carrier may have several ordered hits inside a cast while
        # the ability itself has no sourced sub-hit delay.  Preserve
        # the cast's authored boundary for each application instead
        # of leaving the shared on-hit counter untimestamped.  The
        # order remains the module's part order; no fractional
        # average or target-health guess is introduced.
        cast_times = [float(time) for time in plan.times.get(ability_key, ())]
        hits_per_cast = max(1, int(ability_field(on_hit_spec, "hits", form="on_hit")))
        fallback_times = [
            cast_time for cast_time in cast_times for _ in range(hits_per_cast)
        ]
        if len(fallback_times) >= applications:
            application_times = fallback_times[:applications]
    application_events: list[dict[str, Any]] | None = []
    for application_index in range(applications):
        hp_now = max(0.0, target_health - running_damage)
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
        running_damage += applied_sum
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
    return running_damage


def _apply_slot_target_debuff(
    state: FightState,
    ability_key: str,
    ability_info: Mapping[str, Any],
    num_casts: int,
    *,
    plan: CastPlan,
    shred_ramp: Any,
) -> None:
    """Land this slot's target debuff, after its own damage was priced.

    A target debuff (Kog'Maw Q resistance shred) lands AFTER the slot's own
    damage, so later abilities benefit from the shred and the source ability
    does not.  A slot that never gets cast (autos-only mode) shreds nothing,
    and a ramped debuff already staged itself across the slot's own hits, so
    only its unfired remainder lands here.
    """
    resists = state.resists
    target_debuff = ability_info.get("target_debuff")
    if not (target_debuff and num_casts > 0):
        return
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
    debuff_times = state.empowered_ride_times.get(ability_key) or plan.times.get(
        ability_key, ()
    )
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
