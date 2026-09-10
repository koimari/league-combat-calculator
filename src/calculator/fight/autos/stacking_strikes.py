"""A strike that fires when a counter of landed hits fills.

Kraken Slayer and Hullbreaker count ON-HIT applications, so ability-carried
applications lead one shared counter and the autos continue it; a proc fires
at the effectiveness of the hit that landed the Nth stack, against the
target's health at that moment.
"""

from ..resists import _mitigate
from ..results import (
    AutoAttackResult,
    OnHitResult,
    RotationResult,
    SpellbladeResult,
    SwingStream,
)
from ..rotation.shaped_charge import _strike_declaration
from ..state import FightState, _damage_inputs
from .decaying_health_walk import AutoSwings, _simulate_stacking_on_hit_damage
from .on_hit_stream import _calculate_stacking_procs


def _add_stacking_strikes(
    state: FightState,
    rotation: RotationResult,
    autos: AutoAttackResult,
    on_hits: OnHitResult,
    *,
    spellblade: SpellbladeResult,
    swings: SwingStream,
) -> None:
    """Price every declared counter strike over the fight's shared hit order."""
    num_auto_attacks = state.num_auto_attacks
    apps = rotation.ability_item_applications
    if num_auto_attacks <= 0 and not apps:
        return
    resists = state.resists
    breakdown = state.breakdown
    swing_times, effectiveness = swings

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
        wants_on_attack = effect.counter_trigger == "on_attack"
        counted_hits = [
            app for app in apps if (app.on_attack if wants_on_attack else app.on_hit)
        ]
        # Phantom hits fired by ability attacks re-apply on-hit, so
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

        mechanic = source.previewed_mechanic()
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
            "pair_preview_of": mechanic,
            "declared": _strike_declaration(mechanic, sum(declared_raws)),
        }
        # Every proc fired on a timestamped hit: author its events.
        # Ability-segment procs ride their triggering application's
        # accepted-cast time (the shared counter's leading hits);
        # auto-segment procs ride their swings.  One untimed carrier
        # keeps the row coarse rather than inventing a boundary.
        ability_procs_timed = all(time is not None for time, _ in ability_proc_records)
        autos_stampable = not proc_autos or bool(swing_times)
        if ability_procs_timed and autos_stampable:
            breakdown[source.breakdown_key]["event_phase"] = "auto"
            breakdown[source.breakdown_key]["damage_events"] = [
                {
                    "time": float(time),
                    "damage": damage,
                    "damage_type": source.damage_type,
                    "declared": _strike_declaration(mechanic, declared_raws[position]),
                }
                for position, (time, damage) in enumerate(ability_proc_records)
            ] + [
                {
                    "time": swing_times[auto_index],
                    "damage": damage,
                    "damage_type": source.damage_type,
                    "declared": _strike_declaration(
                        mechanic,
                        declared_raws[len(ability_proc_records) + position],
                    ),
                }
                for position, (auto_index, damage) in enumerate(
                    zip(sorted(proc_autos), auto_proc_damages, strict=False)
                )
            ]
        state.total_damage += total_damage
