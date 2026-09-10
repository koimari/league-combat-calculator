"""Ability damage that fires a fixed number of times."""

import math
from typing import Any

from ...ability_atoms import ability_field
from ..autos.swing_schedule import _auto_attack_timestamps
from ..ledger.event_ledger import _ordered_damage_events
from ..ledger.event_rows import _row_time
from ..mitigation import _apply_basic_amp
from ..resists import _mitigate
from ..results import RotationResult
from ..state import FightState


def _add_precomputed_proc_damage(
    state: FightState, rotation: RotationResult | None = None
) -> None:
    """Add fixed-count ability proc damage (e.g. Akali passive).

    Ability entries with a ``proc_count`` field represent damage that
    occurs a fixed number of times, not tied to cooldowns or auto attacks.
    """
    resists = state.resists
    for key, info in state.ability_damages.items():
        if key in state.cast_order or "on_hit" in info or "stat_buff" in info:
            continue
        proc_count = ability_field(info, "proc_count")
        if proc_count <= 0:
            continue
        authored_proc_times: list[float] | None = None
        if (
            info.get("timeline_event_model") == "ziggs_short_fuse"
            and not state.one_rotation
            and state.num_auto_attacks > 0
            and rotation is not None
        ):
            # Short Fuse starts ready, then enters its 12s cooldown after the
            # empowered swing.  Every ability cast reduces the remaining
            # cooldown at cast start by the sourced level refund.
            cooldown = float(ability_field(info, "short_fuse_cooldown"))
            refund = float(ability_field(info, "short_fuse_refund"))
            auto_times = _auto_attack_timestamps(state)
            cast_times = sorted(float(event["time"]) for event in rotation.cast_events)
            ready_at = 0.0
            cast_index = 0
            authored_proc_times = []
            for auto_time in auto_times:
                while (
                    cast_index < len(cast_times) and cast_times[cast_index] <= auto_time
                ):
                    if ready_at > cast_times[cast_index]:
                        ready_at = max(cast_times[cast_index], ready_at - refund)
                    cast_index += 1
                if auto_time + 1e-9 < ready_at:
                    continue
                authored_proc_times.append(auto_time)
                ready_at = auto_time + cooldown
                if len(authored_proc_times) >= int(proc_count):
                    break
            proc_count = len(authored_proc_times)
            if proc_count <= 0:
                continue
        elif (
            info.get("timeline_event_model") == "ziggs_short_fuse"
            and state.one_rotation
            and rotation is not None
            and state.num_auto_attacks >= int(proc_count)
        ):
            # A one-rotation request supplies a fixed Short Fuse proc count.
            # When the authored auto stream contains at least that many
            # swings, attach each proc to its corresponding swing so the
            # candidate timeline is ordered rather than leaving every build
            # partial merely because the passive row was aggregated.
            authored_proc_times = _auto_attack_timestamps(state)[: int(proc_count)]
        if (
            info.get("event_order_certified") == "auto_stack_proc"
            and not state.one_rotation
        ):
            # The module's packet count is an upper bound; a stack-triggered
            # proc cannot occur before its required ambient swings land.
            every = max(1, int(ability_field(info, "auto_stack_every")))
            proc_count = min(int(proc_count), int(state.num_auto_attacks) // every)
            if proc_count <= 0:
                continue
        coupled_to_autos = bool(info.get("requires_auto_timeline_coupling"))
        if coupled_to_autos:
            # A champion cannot consume more empowered-attack stacks than
            # there are authored auto swings in this window.  The old fixed
            # proc count made Ambessa's passive damage appear even with no
            # attacks and overstated both damage and healing.
            proc_count = min(int(proc_count), int(state.num_auto_attacks))
            if proc_count <= 0:
                continue

        parts = info["parts"]
        if any(part.hp_scaled_damage is not None for part in parts):
            raise ValueError(
                f"proc entry {info.get('name', key)!r}: hp-scaled parts are "
                "not supported outside the cast rotation (procs have no "
                "target-HP context)"
            )
        dtype = info["damage_type"]
        # Keep the existing aggregate arithmetic, but retain the priced
        # per-instance values for champion passives that explicitly need an
        # authored event ledger.  Caitlyn's Headshot is one proc row whose
        # parts may contain several distinct basic-attack instances (a trap
        # headshot, E-granted headshots, and natural cadence headshots).  A
        # single phase-order row made every Caitlyn build look uncertified to
        # the coupled optimizer even when no other source was partial.
        priced_part_instances: list[tuple[str, float]] = []
        per_proc = 0.0
        for part in parts:
            mitigated_part = _apply_basic_amp(
                state,
                part,
                _mitigate(part.amount, part.damage_type, resists, state.magic_amp),
                procs=part.count * proc_count,
            )
            per_proc += mitigated_part * part.count
            priced_part_instances.extend(
                (part.damage_type, mitigated_part) for _ in range(part.count)
            )
        if per_proc <= 0:
            continue

        proc_total = per_proc * proc_count
        state.breakdown[key] = {
            "name": info.get("name", key),
            "count": proc_count,
            "damage_per_hit": per_proc,
            "total_damage": proc_total,
            "damage_type": dtype,
        }
        # Module-authored self-shield payloads (E8c) ride proc rows too: the
        # rebuilt damage-event ledger is aligned by ordinal against this list
        # in ``_ordered_damage_events`` (Akshan's Dirty Fighting proc shield
        # grants on the first completed 3-stack detonation).
        if info.get("self_shield_events") is not None:
            state.breakdown[key]["self_shield_events"] = info["self_shield_events"]
        if (
            rotation is not None
            and info.get("timeline_event_model") == "brand_blaze"
            and int(proc_count) == 1
        ):
            # Brand's packet supplies the 0.25s tick cadence and the
            # two-second ring delay. The accepted cast ledger supplies the
            # actual stack-application times, including Pyroclasm's sourced
            # 0.15s bounce spacing, so no phase-order estimate is used.
            stack_count = int(ability_field(info, "dot_stack_count"))
            tick_interval = float(ability_field(info, "dot_tick_interval"))
            ability_events = _ordered_damage_events(
                state.breakdown,
                state.ability_damages,
                state.cast_order,
                cast_events=rotation.cast_events,
                roster_target_index=state.roster_target_index,
            )
            stack_times = [
                float(event["time"])
                for event in ability_events
                if event.get("phase") == "ability"
                and event.get("source_key") in state.ability_damages
            ][:stack_count]
            dot_damage = (
                priced_part_instances[0][1]
                if stack_count > 0 and priced_part_instances
                else 0.0
            )
            detonation_damage = (
                priced_part_instances[stack_count][1]
                if len(priced_part_instances) > stack_count
                else 0.0
            )
            if (
                stack_count > 0
                and tick_interval > 0
                and len(stack_times) == stack_count
            ):
                authored: list[dict[str, Any]] = []
                ticks = round(
                    float(ability_field(info, "dot_duration")) / tick_interval
                )
                for stack_time in stack_times:
                    authored.extend(
                        {
                            "time": stack_time + tick_index * tick_interval,
                            "damage_type": dtype,
                            "damage": dot_damage / ticks,
                            "event_precision": "exact",
                        }
                        for tick_index in range(1, ticks + 1)
                    )
                if detonation_damage > 0:
                    authored.append(
                        {
                            "time": stack_times[-1] + 2.0,
                            "damage_type": dtype,
                            "damage": detonation_damage,
                            "event_precision": "exact",
                        }
                    )
                if authored and math.isclose(
                    sum(event["damage"] for event in authored),
                    proc_total,
                    rel_tol=1e-9,
                    abs_tol=1e-6,
                ):
                    state.breakdown[key]["damage_events"] = authored
                    state.breakdown[key]["event_phase"] = "effect"
        declared_events = info.get("damage_events")
        if info.get("timeline_event_model") == "braum_concussive" and isinstance(
            declared_events, list
        ):
            raw_event_total = sum(
                float(event["damage"])
                for event in declared_events
                if isinstance(event, dict)
            )
            if raw_event_total > 0:
                scale = proc_total / raw_event_total
                state.breakdown[key]["damage_events"] = [
                    {
                        **event,
                        "damage_type": dtype,
                        "damage": float(event["damage"]) * scale,
                        "event_precision": "exact",
                    }
                    for event in declared_events
                    if isinstance(event, dict)
                ]
                state.breakdown[key]["event_phase"] = "effect"
        elif authored_proc_times is not None and len(authored_proc_times) == proc_count:
            state.breakdown[key]["damage_events"] = [
                {
                    "time": time,
                    "damage_type": dtype,
                    "damage": per_proc,
                    "event_precision": "exact",
                }
                for time in authored_proc_times
            ]
            state.breakdown[key]["event_phase"] = "auto"
        elif isinstance(declared_events, list) and len(declared_events) == proc_count:
            # Champion modules may provide a sourced phase-order ledger for
            # fixed-count procs (for example Akali's passive).  Re-price each
            # declared event with the same mitigation used for the aggregate
            # row while preserving its authored ordering metadata.
            state.breakdown[key]["damage_events"] = [
                {
                    **event,
                    "damage_type": dtype,
                    "damage": per_proc,
                    "raw_damage": sum(part.amount * part.count for part in parts),
                }
                for event in declared_events
                if isinstance(event, dict)
            ]
            state.breakdown[key]["event_phase"] = str(
                ability_field(info, "event_phase")
            )
        elif (
            info.get("event_order_certified") == "auto_stack_proc"
            and state.num_auto_attacks > 0
        ):
            # A champion-owned stack proc can certify its timing when the
            # module supplies the sourced stack cadence (Akshan: every
            # third damaging attack).  Do not invent times when the fight
            # contains fewer swings than the requested proc packet.
            every = max(1, int(ability_field(info, "auto_stack_every")))
            required_swings = proc_count * every
            auto_times = _auto_attack_timestamps(state)
            if required_swings <= len(auto_times):
                state.breakdown[key]["damage_events"] = [
                    {
                        "time": auto_times[(index + 1) * every - 1],
                        "damage_type": dtype,
                        "damage": per_proc,
                        "event_precision": "exact",
                    }
                    for index in range(proc_count)
                ]
                state.breakdown[key]["event_phase"] = "auto"
        elif (
            key == "passive"
            and info.get("name") == "Headshot"
            and priced_part_instances
        ):
            # Headshot's module owns the ordering assumptions: with no
            # ambient autos, the E/trap attacks are forced at the combo
            # boundary; with autos, the first converted swings land on the
            # same authored timestamps as the auto stream.  The parser's
            # aggregate packet stays unchanged, so this ledger is runtime
            # evidence rather than a new guessed formula.
            if state.num_auto_attacks > 0 and state.auto_attack_uptime > 0:
                auto_times = _auto_attack_timestamps(state)
                # Caitlyn's timed packet emits the trap rider as the final
                # part after the common E/cadence rider.  The Wiki ordering
                # is trap first, then E grants, then natural cadence.
                if len(priced_part_instances) > 1:
                    ordered_instances = [
                        priced_part_instances[-1],
                        *priced_part_instances[:-1],
                    ]
                else:
                    ordered_instances = priced_part_instances
                event_times = auto_times[: len(ordered_instances)]
                event_phase = "auto"
            else:
                ordered_instances = priced_part_instances
                event_times = [0.0] * len(ordered_instances)
                event_phase = "effect"
            state.breakdown[key]["damage_events"] = [
                {
                    "time": event_times[index] if index < len(event_times) else 0.0,
                    "damage_type": event_type,
                    "damage": event_damage,
                    "event_precision": "exact",
                }
                for index, (event_type, event_damage) in enumerate(ordered_instances)
            ]
            state.breakdown[key]["event_phase"] = event_phase
        elif coupled_to_autos and state.num_auto_attacks > 0:
            auto_times = _auto_attack_timestamps(state)
            authored_events = [
                {
                    "time": auto_times[index] if index < len(auto_times) else 0.0,
                    "damage_type": dtype,
                    "damage": per_proc,
                }
                for index in range(proc_count)
            ]
            # Ability hits can advance a coupled passive between autos
            # (Aurora's Spirit Abjuration). Keep the public ledger
            # chronological even when those authored hit times arrive out
            # of order relative to the ambient auto cadence.
            authored_events.sort(key=_row_time)
            state.breakdown[key]["damage_events"] = authored_events
            state.breakdown[key]["event_phase"] = "auto"
        # Champion-minted display text (e.g. Braum P's cycle summary) and
        # count label (e.g. Diana's "cleaves") ride the entry onto its
        # breakdown row, as in the rotation.
        for display_key in ("detail", "unit"):
            if display_key in info:
                state.breakdown[key][display_key] = info[display_key]
        state.total_damage += proc_total
