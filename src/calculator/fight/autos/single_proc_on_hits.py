"""Items that proc once or on a stack counter rather than per hit."""

from typing import Any

from ... import item_effects
from ...interpreters import cast_proc, charged_strike
from ..items.cast_procs import _proc_declaration
from ..items.eclipse_stack_gate import _stacked_champion_proc_times
from ..items.energized_packets import _author_energized_ability_proc
from ..items.muramana import _muramana_proc_events
from ..ledger.event_rows import _damage_type_fields
from ..mitigation import _mitigate_basic_attack_swing
from ..resists import _mitigate
from ..results import AutoAttackResult, OnHitResult, RotationResult, SpellbladeResult
from ..rotation.shaped_charge import _strike_declaration
from ..state import FightState, _damage_inputs
from .copied_on_hit import (
    _add_copied_stacking_on_hit_packets,
    _bolt_declaration,
    _copied_on_hit_declaration,
    _copied_on_hit_packet,
    _copied_on_hit_shares,
    _copied_packets_by_type,
)
from .decaying_health_walk import (
    AutoSwings,
    DecayingTarget,
    _simulate_stacking_on_hit_damage,
)
from .on_hit_stream import _calculate_stacking_procs
from .swing_profile import _on_hit_effectiveness
from .swing_schedule import _auto_attack_timestamps


def _add_single_proc_on_hits(
    state: FightState,
    rotation: RotationResult,
    autos: AutoAttackResult,
    on_hits: OnHitResult,
    *,
    spellblade: SpellbladeResult,
) -> None:
    """Add items that proc once (or on a stack counter) rather than per hit.

    First-hit procs (Dead Man's Plate, Heartsteel, energized Rapid
    Firecannon / Stormrazor / Voltaic Cyclosword / Statikk Shiv), the
    Titanic Hydra Crescent active, stack-counter procs simulated against
    the target's dropping HP (Kraken Slayer, Hullbreaker — phantom hits
    and double on-hits each grant an extra stack), Eclipse, and
    Muramana's per-ability-cast Shock damage.

    Stack counters count ON-HIT applications, so they run on one shared
    hit sequence: the rotation's ability-carried applications (Bel'Veth
    Q/E) lead, then the autos continue the same counter. A proc fires at
    the effectiveness of the hit that landed the Nth stack.

    Replaced autos (Azir soldiers) consume energized effects and build
    stack-counter procs normally, but every auto-triggered proc's damage
    is scaled by the override's on-hit effectiveness (game-verified:
    Statikk Shiv and Kraken Slayer proc at 50% damage).
    """
    resists = state.resists
    breakdown = state.breakdown
    num_auto_attacks = state.num_auto_attacks
    effectiveness = _on_hit_effectiveness(state)

    # Galvanize is an ability-capable Energized trigger.  It is authored once
    # before the auto pass so zero-auto rotations (for example a spell-only
    # one-rotation scenario) still consume and price the ready charge.
    ability_consumed_items = {
        effect.source.item_name
        for effect in state.declared.charged_strikes.first_autos
        if _author_energized_ability_proc(state, rotation, effect, effectiveness)
    }

    # The auto stream's authored per-swing schedule.  Swing-riding procs
    # stamp their events at these times; an empty list (no stream, or a
    # count mismatch) keeps those rows coarse.
    swing_times = _auto_attack_timestamps(state)
    if len(swing_times) != num_auto_attacks:
        swing_times = []

    if num_auto_attacks > 0:
        inputs = _damage_inputs(state)
        bolts = state.declared.secondary_target_bolts
        if bolts is not None:
            secondary_target_count = bolts.bolt_count(state.roster_target_count)
            if 1 <= state.roster_target_index <= secondary_target_count:
                raw_bolt = (
                    bolts.bolt_damage(state.champion_stats["attack_damage"])
                    * effectiveness
                )
                if raw_bolt > 0.0:
                    crit_raw = raw_bolt * state.crit_multiplier
                    if state.deterministic:
                        bolt_damage = state.crit_chance * _mitigate_basic_attack_swing(
                            state, crit_raw, critical_strike=True
                        ) + (1.0 - state.crit_chance) * _mitigate_basic_attack_swing(
                            state, raw_bolt
                        )
                    else:
                        bolt_damage = _mitigate_basic_attack_swing(state, raw_bolt)
                    bolt_total = bolt_damage * num_auto_attacks
                    bolt_key = "secondary_Runaan's Hurricane"
                    router = bolts.mechanic_id
                    bolt_declaration = _bolt_declaration(state, bolts, raw_bolt)
                    bolt_row: dict[str, Any] = {
                        "name": "Runaan's Hurricane (Wind's Fury bolt)",
                        "count": num_auto_attacks,
                        "damage_per_hit": bolt_damage,
                        "unit": "bolts",
                        "total_damage": bolt_total,
                        "damage_type": "physical",
                        # This row is the pair engine's preview of a number the
                        # coupled walk owns: the roster composition reads
                        # the stamp and takes the figure above out of every
                        # total it composes, while the pair fight's own
                        # receipt publishes it unchanged.  The row-level
                        # declaration is what a *coarse* row hands the walk:
                        # one whose bolts landed on no resolvable swing
                        # schedule (``_row_declaration_share``).
                        "pair_preview_of": router,
                        "declared": _bolt_declaration(
                            state, bolts, raw_bolt * num_auto_attacks
                        ),
                        "targeting": {
                            "kind": "runaan_bolt",
                            "secondary_target_count": secondary_target_count,
                            "allocated_target_index": state.roster_target_index,
                            "roster_target_count": state.roster_target_count,
                            "copied_on_hit_scope": "fixed_source_packets",
                        },
                    }
                    if swing_times and len(swing_times) == num_auto_attacks:
                        bolt_row["event_phase"] = "auto"
                        bolt_row["damage_events"] = [
                            {
                                "time": swing_times[index],
                                "damage": bolt_damage,
                                "damage_type": "physical",
                                "declared": bolt_declaration,
                            }
                            for index in range(num_auto_attacks)
                        ]
                    breakdown[bolt_key] = bolt_row
                    state.total_damage += bolt_total

                    copied_events: list[dict[str, Any]] = []
                    for index in range(num_auto_attacks):
                        event_time = (
                            swing_times[index] if index < len(swing_times) else 0.0
                        )
                        copied_events.append(
                            {
                                "time": event_time,
                                "shares": _copied_on_hit_shares(
                                    state,
                                    on_hits,
                                    effectiveness,
                                    DecayingTarget.ledger_health(state, event_time),
                                ),
                            }
                        )
                    for copied_event in copied_events:
                        copied_event["packets"] = _copied_packets_by_type(
                            copied_event["shares"]
                        )
                    copied_by_type: dict[str, float] = {}
                    for copied_event in copied_events:
                        for damage_type, amount in copied_event["packets"].items():
                            copied_by_type[damage_type] = (
                                copied_by_type.get(damage_type, 0.0) + amount
                            )
                    copied_total = sum(copied_by_type.values())
                    if copied_total > 0.0:
                        copied_key = "on_hit_secondary_Runaan's Hurricane"
                        # Every contributor of every application declares, or
                        # the row is not stamped at all.  A champion's
                        # ability-carried on-hit is copied here and no item rule
                        # states its magnitude, so a partially declared row
                        # would hand the walk a price missing a producer while
                        # the stamp took the pair engine's whole figure out of
                        # the roster total — the half-performed retirement
                        # umbrella Amendment L, Ruling 1 calls worse than
                        # neither half.  Unstamped, the pair engine goes on
                        # pricing it exactly as it did.
                        # A COARSE copied row is not stamped either, and for a
                        # reason the bolt row does not share: a row-level
                        # declaration is one magnitude, and this row's is a sum
                        # over several producers, so a row with no authored
                        # events has nothing one declaration could state.
                        declarable = (
                            len(swing_times) == num_auto_attacks
                            and num_auto_attacks > 0
                            and all(
                                share.mechanic_id is not None
                                for copied_event in copied_events
                                for share in copied_event["shares"]
                                if share.mitigated > 0.0
                            )
                        )
                        copied_row: dict[str, Any] = {
                            "name": "Runaan's Hurricane copied on-hit (secondary)",
                            "count": num_auto_attacks,
                            "damage_per_hit": copied_total / num_auto_attacks,
                            "unit": "bolts",
                            "total_damage": copied_total,
                            **_damage_type_fields(copied_by_type),
                            "targeting": {
                                "kind": "runaan_bolt_copied_on_hit",
                                "secondary_target_count": secondary_target_count,
                                "allocated_target_index": state.roster_target_index,
                                "roster_target_count": state.roster_target_count,
                                "copied_on_hit_scope": "per_hit_source_packets",
                            },
                        }
                        if declarable:
                            copied_row["pair_preview_of"] = router
                        if swing_times and len(swing_times) == num_auto_attacks:
                            copied_row["event_phase"] = "auto"
                            # One event per CONTRIBUTING SOURCE rather than per
                            # damage type: a summed event cannot carry one
                            # producer's declaration, and a declaration is one
                            # producer's magnitude (D-60).  Every amount, every
                            # type total and the row total are unchanged.
                            copied_row["damage_events"] = [
                                {
                                    "time": copied_event["time"],
                                    "damage": share.mitigated,
                                    "damage_type": share.damage_type,
                                    **(
                                        {"declared": declaration}
                                        if declarable
                                        and (
                                            declaration := _copied_on_hit_declaration(
                                                share, router
                                            )
                                        )
                                        is not None
                                        else {}
                                    ),
                                }
                                for copied_event in copied_events
                                for share in copied_event["shares"]
                                if share.mitigated > 0.0
                            ]
                        breakdown[copied_key] = copied_row
                        state.total_damage += copied_total

        cleave_item_name = item_effects.cleave_on_hit_item_name(state.items)
        secondary_target_count = max(0, state.roster_target_count - 1)
        if (
            cleave_item_name is not None
            and secondary_target_count > 0
            and 1 <= state.roster_target_index <= secondary_target_count
        ):
            cleave_damages = [
                _mitigate(
                    item_effects.hydra_cleave_secondary_ad_damage(
                        total_attack_damage=state.champion_stats["attack_damage"],
                        is_melee=state.is_melee,
                        item_name=cleave_item_name,
                    )
                    * effectiveness,
                    "physical",
                    resists,
                    state.magic_amp,
                )
                for _ in range(num_auto_attacks)
            ]
            cleave_total = sum(cleave_damages)
            if cleave_total > 0.0:
                cleave_key = f"on_hit_secondary_{cleave_item_name}"
                cleave_row: dict[str, Any] = {
                    "name": f"{cleave_item_name} Cleave (secondary)",
                    "count": num_auto_attacks,
                    "damage_per_hit": cleave_total / num_auto_attacks,
                    "unit": "packets",
                    "total_damage": cleave_total,
                    "damage_type": "physical",
                    "targeting": {
                        "kind": "cleave_secondary",
                        "secondary_target_count": secondary_target_count,
                        "allocated_target_index": state.roster_target_index,
                        "roster_target_count": state.roster_target_count,
                    },
                }
                if swing_times and len(swing_times) == num_auto_attacks:
                    cleave_row["event_phase"] = "auto"
                    cleave_row["damage_events"] = [
                        {
                            "time": swing_times[index],
                            "damage": damage,
                            "damage_type": "physical",
                        }
                        for index, damage in enumerate(cleave_damages)
                    ]
                breakdown[cleave_key] = cleave_row
                state.total_damage += cleave_total

        for effect in state.declared.charged_strikes.first_autos:
            source = effect.source
            if not item_effects.first_auto_state_ready(
                state.items, state.item_options, source.item_name
            ):
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
                chain_target_count = item_effects.statikk_chain_target_count(
                    state.level
                )
                allocated_targets = min(
                    max(1, state.roster_target_count), chain_target_count
                )
                if state.roster_target_index >= allocated_targets:
                    continue
            if effect.energized_max_stacks > 0:
                proc_indices = item_effects.energized_proc_indices(
                    source.item_name,
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
                    target_current_health=DecayingTarget.ledger_health(
                        state, proc_time
                    ),
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
                "pair_preview_of": charged_strike.strike_mechanic_id(source.item_name),
                "declared": _strike_declaration(source.item_name, sum(declared_raws)),
            }
            if effect.energized_max_stacks > 0:
                breakdown[source.breakdown_key]["energized_schedule"] = (
                    item_effects.energized_schedule_receipt(source.item_name)
                )
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
                        "declared": _strike_declaration(
                            source.item_name, declared_raws[position]
                        ),
                    }
                    for position, proc_index in enumerate(proc_indices)
                ]
            if chain_target_count and state.roster_target_index > 0:
                # Electrospark applies on-hit effects to secondary targets.
                # Every per-hit packet, including current-health formulas, is
                # replayed at the proc timestamp. Stack-counter effects are
                # replayed after the ordinary attack/ability applications on
                # the same target ledger, preserving their copied-hit order.
                copied_events = []
                for proc_index in proc_indices:
                    proc_time = (
                        swing_times[proc_index]
                        if proc_index < len(swing_times)
                        else 0.0
                    )
                    copied_events.append(
                        {
                            "time": proc_time,
                            "packets": _copied_on_hit_packet(
                                state,
                                on_hits,
                                effectiveness,
                                DecayingTarget.ledger_health(state, proc_time),
                            ),
                        }
                    )
                copied_stacking_certified = _add_copied_stacking_on_hit_packets(
                    state,
                    rotation,
                    on_hits,
                    spellblade,
                    copied_events=copied_events,
                    proc_indices=proc_indices,
                    swing_times=swing_times,
                    effectiveness=effectiveness,
                )
                copied_by_type: dict[str, float] = {}
                for copied_event in copied_events:
                    for damage_type, amount in copied_event["packets"].items():
                        copied_by_type[damage_type] = (
                            copied_by_type.get(damage_type, 0.0) + amount
                        )
                copied_total = sum(copied_by_type.values())
                if copied_total > 0.0:
                    copied_key = f"on_hit_chain_{source.item_name}"
                    copied_row: dict[str, Any] = {
                        "name": f"{source.display_name} copied on-hit (secondary)",
                        "count": procs,
                        "damage_per_hit": copied_total / procs,
                        "unit": "procs",
                        "total_damage": copied_total,
                        **_damage_type_fields(copied_by_type),
                        "targeting": {
                            "kind": "chain_lightning_copied_on_hit",
                            "source": source.item_name,
                            "allocated_target_index": state.roster_target_index,
                            "roster_target_count": state.roster_target_count,
                            "copied_on_hit_scope": "per_hit_source_packets",
                            "copied_stacking_on_hits": copied_stacking_certified,
                        },
                    }
                    if swing_times and all(
                        proc_index < len(swing_times) for proc_index in proc_indices
                    ):
                        copied_row["event_phase"] = "auto"
                        copied_row["damage_events"] = [
                            {
                                "time": copied_event["time"],
                                "damage": amount,
                                "damage_type": damage_type,
                            }
                            for copied_event in copied_events
                            for damage_type, amount in copied_event["packets"].items()
                        ]
                    breakdown[copied_key] = copied_row
                    state.total_damage += copied_total
            state.total_damage += mitigated

    if num_auto_attacks > 0:
        inputs = _damage_inputs(state)
        secondary_item_name = item_effects.hydra_secondary_item_name(state.items)
        secondary_active_indices: tuple[int, ...] = ()
        for effect in state.damage_effects.auto_cooldowns:
            source = effect.source
            # Prefer the authored swing schedule over a duration quotient:
            # a cooldown is consumed by an actual empowered attack, so an
            # exact fight boundary with no swing must not invent another
            # Titanic Crescent proc.
            proc_indices: list[int] = []
            if swing_times:
                ready = 0.0
                for index, swing_time in enumerate(swing_times):
                    if swing_time + 1e-9 >= ready:
                        proc_indices.append(index)
                        ready = swing_time + effect.cooldown
            if swing_times:
                procs = len(proc_indices)
            else:
                procs = (
                    1 + int(state.fight_duration_seconds / effect.cooldown)
                    if effect.cooldown > 0
                    else 1
                )
                procs = min(procs, num_auto_attacks)
                proc_indices = list(range(procs))
            if procs <= 0:
                continue
            raw_per_proc = source.raw_damage(inputs)
            base_effect = next(
                (
                    per_hit
                    for per_hit in state.per_hit_strikes
                    if per_hit.source.item_name == source.item_name
                ),
                None,
            )
            if base_effect is not None:
                # The ordinary 1% max-health packet is already in the
                # per-hit on-hit row.  Crescent is the replacement 4%
                # packet, so this row carries only its additional 3% delta.
                raw_per_proc -= base_effect.source.raw_damage(inputs)
                if source.item_name == secondary_item_name:
                    secondary_active_indices = tuple(proc_indices)
            raw_damage = raw_per_proc * procs * effectiveness
            mitigated = _mitigate(
                raw_damage, source.damage_type, resists, state.magic_amp
            )
            breakdown[source.breakdown_key] = {
                "name": source.display_name,
                "count": procs,
                "damage_per_hit": mitigated / procs,
                "unit": "procs",
                "total_damage": mitigated,
                "damage_type": source.damage_type,
            }
            # Each empowered swing is the first one at/after the effect's
            # cooldown gate.  Authored only when the swing schedule
            # reproduces the priced proc count exactly.
            proc_times = [
                swing_times[index] for index in proc_indices if index < len(swing_times)
            ]
            if len(proc_times) == procs:
                breakdown[source.breakdown_key]["event_phase"] = "auto"
                breakdown[source.breakdown_key]["damage_events"] = [
                    {
                        "time": proc_time,
                        "damage": mitigated / procs,
                        "damage_type": source.damage_type,
                    }
                    for proc_time in proc_times
                ]
            state.total_damage += mitigated

        # Titanic's Cleave cone strikes one packet on each selected
        # secondary roster target per authored auto.  The empowered swing
        # uses the parser-sourced 9% secondary ratio; ordinary swings use
        # the 3% ratio.  Primary target index 0 receives no cone packet.
        secondary_target_count = max(0, state.roster_target_count - 1)
        if (
            secondary_target_count > 0
            and state.roster_target_index > 0
            and state.roster_target_index <= secondary_target_count
            and secondary_item_name is not None
        ):
            cone_damages: list[float] = []
            active_indices = set(secondary_active_indices)
            for auto_index in range(num_auto_attacks):
                raw_cone = (
                    item_effects.hydra_secondary_target_damage(
                        max_health=state.champion_stats["health"],
                        is_melee=state.is_melee,
                        empowered=auto_index in active_indices,
                        item_name=secondary_item_name,
                    )
                    * effectiveness
                )
                cone_damages.append(
                    _mitigate(raw_cone, "physical", resists, state.magic_amp)
                )
            cone_total = sum(cone_damages)
            if cone_total > 0.0:
                cone_key = "secondary_Titanic Hydra"
                cone_row: dict[str, Any] = {
                    "name": "Titanic Hydra Cleave (secondary)",
                    "count": num_auto_attacks,
                    "damage_per_hit": cone_total / num_auto_attacks,
                    "unit": "packets",
                    "total_damage": cone_total,
                    "damage_type": "physical",
                    "targeting": {
                        "kind": "hydra_cleave",
                        "secondary_target_count": secondary_target_count,
                        "allocated_target_index": state.roster_target_index,
                        "roster_target_count": state.roster_target_count,
                    },
                }
                if swing_times and len(swing_times) == num_auto_attacks:
                    cone_row["event_phase"] = "auto"
                    cone_row["damage_events"] = [
                        {
                            "time": swing_times[index],
                            "damage": damage,
                            "damage_type": "physical",
                        }
                        for index, damage in enumerate(cone_damages)
                    ]
                breakdown[cone_key] = cone_row
                state.total_damage += cone_total

    apps = rotation.ability_item_applications
    if num_auto_attacks > 0 or apps:
        other_on_hit_per_hit = on_hits.static_on_hit_per_hit
        if on_hits.has_current_health_on_hit and on_hits.current_health_on_hit_avg > 0:
            other_on_hit_per_hit += on_hits.current_health_on_hit_avg

        # Auto-segment procs ride specific swings, whose times the auto
        # stream already authored (``swing_times`` above); ability-segment
        # procs have no timestamps yet, so any of those keeps the row coarse.
        for effect in state.declared.charged_strikes.stacking_on_hits:
            source = effect.source
            # The item taxonomy decides which ability applications
            # advance this counter (Kraken/Hullbreaker count ON-HIT
            # applications; an on-attack-gated counter would count only
            # attack-carrying applications like Bel'Veth E slashes).
            wants_on_attack = (
                item_effects.counter_trigger(source.item_name) == "on_attack"
            )
            counted_hits = [
                app
                for app in apps
                if (app.on_attack if wants_on_attack else app.on_hit)
            ]
            # Phantom hits fired by ability attacks re-apply on-hit —
            # one extra stack on on-hit-gated counters at that position.
            extra_stacks = (
                set() if wants_on_attack else on_hits.phantom_ability_stack_positions
            )
            ability_procs, proc_autos = _calculate_stacking_procs(
                num_auto_attacks,
                on_hits.phantom_hit_autos,
                spellblade.double_on_hit_procs,
                hits_required=effect.hits_required,
                leading_ability_hits=len(counted_hits),
                ability_extra_stacks=extra_stacks,
            )
            procs = len(ability_procs) + len(proc_autos)
            if procs <= 0:
                continue

            # Ability-segment procs: the hit that lands the Nth stack
            # fires the proc at ITS effectiveness (Bel'Veth Q 75%, E
            # 8-32%), reading the rotation's modeled target HP (with
            # earlier procs of this effect folded in).
            total_damage = 0.0
            proc_hp_dealt = 0.0
            # The declared magnitude of every packet this strike authors, in
            # the order the packets are authored.  A repeating strike re-reads
            # the target's falling health per proc, so its raws differ from
            # each other and one row total split evenly would price the walk's
            # packets at a number no proc had.  The target-side basic
            # multiplier is folded in for the reason ``_strike_declaration``
            # gives: the engine applies it after mitigation and mitigation is
            # linear.
            declared_raws: list[float] = []
            basic_share = (
                state.target_basic_damage_multiplier
                if source.basic_damage and source.damage_type != "true"
                else 1.0
            )
            ability_proc_records: list[tuple[float | None, float]] = []
            for hit_index in ability_procs:
                app = counted_hits[hit_index]
                inputs = _damage_inputs(state, max(0.0, app.target_hp - proc_hp_dealt))
                raw = source.raw_damage(inputs) * app.effectiveness
                mitigated = _mitigate(raw, source.damage_type, resists, state.magic_amp)
                if source.basic_damage and source.damage_type != "true":
                    mitigated *= state.target_basic_damage_multiplier
                total_damage += mitigated
                proc_hp_dealt += mitigated
                declared_raws.append(raw * basic_share)
                ability_proc_records.append((app.time, mitigated))

            # Auto-segment procs: unchanged auto-timeline behavior at
            # the auto stream's effectiveness.
            auto_proc_damages: list[float] = []
            if proc_autos:
                if effect.tracks_target_health:
                    simulated = _simulate_stacking_on_hit_damage(
                        effect,
                        _damage_inputs(state),
                        AutoSwings(
                            target_health=state.target_health,
                            num_auto_attacks=num_auto_attacks,
                            auto_damage_per_hit=autos.auto_damage_per_hit,
                            other_on_hit_per_hit=other_on_hit_per_hit,
                            resists=resists,
                            magic_amp=state.magic_amp,
                        ),
                        proc_autos=proc_autos,
                        effectiveness=effectiveness,
                        target_basic_damage_multiplier=(
                            state.target_basic_damage_multiplier
                        ),
                    )
                    auto_proc_damages = [proc.mitigated for proc in simulated]
                    declared_raws.extend(proc.raw for proc in simulated)
                    total_damage += sum(auto_proc_damages)
                else:
                    raw = (
                        source.raw_damage(_damage_inputs(state))
                        * len(proc_autos)
                        * effectiveness
                    )
                    auto_segment_total = (
                        _mitigate(raw, source.damage_type, resists, state.magic_amp)
                        * basic_share
                    )
                    total_damage += auto_segment_total
                    auto_proc_damages = [auto_segment_total / len(proc_autos)] * len(
                        proc_autos
                    )
                    declared_raws.extend(
                        [raw * basic_share / len(proc_autos)] * len(proc_autos)
                    )

            breakdown[source.breakdown_key] = {
                "name": source.display_name,
                "count": procs,
                "damage_per_hit": total_damage / procs,
                "unit": "procs",
                "total_damage": total_damage,
                "damage_type": source.damage_type,
                # This row is the pair engine's preview of a number the
                # coupled walk owns.  The row-level declaration is what a
                # row with no authored events hands the walk, which the
                # reconstruction splits (``_row_declaration_share``).
                "pair_preview_of": charged_strike.strike_mechanic_id(source.item_name),
                "declared": _strike_declaration(source.item_name, sum(declared_raws)),
            }
            # Every proc fired on a timestamped hit: author its events.
            # Ability-segment procs ride their triggering application's
            # accepted-cast time (the shared counter's leading hits);
            # auto-segment procs ride their swings.  One untimed carrier
            # keeps the row coarse rather than inventing a boundary.
            ability_procs_timed = all(
                time is not None for time, _ in ability_proc_records
            )
            autos_stampable = not proc_autos or bool(swing_times)
            if ability_procs_timed and autos_stampable:
                breakdown[source.breakdown_key]["event_phase"] = "auto"
                breakdown[source.breakdown_key]["damage_events"] = [
                    {
                        "time": float(time),
                        "damage": damage,
                        "damage_type": source.damage_type,
                        "declared": _strike_declaration(
                            source.item_name, declared_raws[position]
                        ),
                    }
                    for position, (time, damage) in enumerate(ability_proc_records)
                ] + [
                    {
                        "time": swing_times[auto_index],
                        "damage": damage,
                        "damage_type": source.damage_type,
                        "declared": _strike_declaration(
                            source.item_name,
                            declared_raws[len(ability_proc_records) + position],
                        ),
                    }
                    for position, (auto_index, damage) in enumerate(
                        zip(sorted(proc_autos), auto_proc_damages, strict=False)
                    )
                ]
            state.total_damage += total_damage

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
            "pair_preview_of": cast_proc.proc_mechanic_id(source.item_name),
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

    for source in state.damage_effects.per_ability_hits:
        if rotation.total_muramana_procs <= 0:
            # No damaging ability cast consumed Shock: the passive never
            # fired, and no row is authored (P3 package 3E; the
            # Shaped-Charge precedent — no aggregate substitute).
            continue
        raw = source.raw_damage(_damage_inputs(state))
        per_proc = _mitigate(raw, source.damage_type, resists, state.magic_amp)
        total_damage = per_proc * rotation.total_muramana_procs
        breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "total_damage": total_damage,
            "damage_type": source.damage_type,
        }
        proc_events = _muramana_proc_events(
            state,
            rotation,
            lockout_seconds=source.same_target_cast_lockout_seconds,
        )
        if proc_events is None:
            # A malformed or count-mismatched cast ledger withholds the
            # event list: the aggregate price is preserved (the proc count
            # is the trusted cast receipt) but the row is stamped with a
            # NAMED reason (P3 package 3E), and the coverage classifier
            # keeps it coarse.
            breakdown[source.breakdown_key]["event_phase"] = "coarse"
            breakdown[source.breakdown_key][
                "withheld_reason"
            ] = "malformed_proc_receipt"
        else:
            total_damage = per_proc * len(proc_events)
            breakdown[source.breakdown_key]["total_damage"] = total_damage
            breakdown[source.breakdown_key]["lockout_receipt"] = {
                "interval_seconds": source.same_target_cast_lockout_seconds,
                "identity": "target_id|cast:cast_id",
                "candidate_count": rotation.total_muramana_procs,
                "accepted_count": len(proc_events),
                "suppressed_count": rotation.total_muramana_procs - len(proc_events),
            }
            for event in proc_events:
                event["damage"] = per_proc
                event["damage_type"] = source.damage_type
            if proc_events:
                breakdown[source.breakdown_key]["damage_events"] = proc_events
                breakdown[source.breakdown_key]["event_phase"] = "ability"
        state.total_damage += total_damage
