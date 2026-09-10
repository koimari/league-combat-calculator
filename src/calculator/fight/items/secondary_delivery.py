"""A packet that lands on a subject the attack was not aimed at.

Three deliveries, one per way a packet leaves the subject it was aimed at:
Wind's Fury re-fires the whole attack at further enemies, Cleave splashes a
share of the swing, and a chained strike arcs its own packet plus the on-hit
effects it carries.  Each is priced against the roster member this pair fight
is evaluating, so every one of them is worth zero in a single-target fight.
"""

from collections.abc import Sequence
from typing import Any

from ... import item_effects
from ..autos.copied_on_hit import (
    _add_copied_stacking_on_hit_packets,
    _bolt_declaration,
    _copied_on_hit_declaration,
    _copied_on_hit_packet,
    _copied_on_hit_shares,
    _copied_packets_by_type,
)
from ..autos.decaying_health_walk import DecayingTarget
from ..ledger.event_rows import _damage_type_fields
from ..mitigation import _mitigate_basic_attack_swing
from ..resists import _mitigate
from ..results import (
    OnHitResult,
    RotationResult,
    SpellbladeResult,
    SwingStream,
)
from ..state import FightState


def _add_bolt_delivery(
    state: FightState, on_hits: OnHitResult, *, swings: SwingStream
) -> None:
    """Re-fire each attack at the further enemies the holder's rule reaches.

    Two rows: the bolt's own share of the swing, and the on-hit effects the
    bolt carries with it when the rule says it does.  Both are allocated to
    this fight's roster member, so the primary target receives neither.
    """
    num_auto_attacks = state.num_auto_attacks
    bolts = state.declared.secondary_target_bolts
    if num_auto_attacks <= 0 or bolts is None:
        return
    breakdown = state.breakdown
    swing_times, effectiveness = swings

    secondary_target_count = bolts.bolt_count(state.roster_target_count)
    if 1 <= state.roster_target_index <= secondary_target_count:
        raw_bolt = (
            bolts.bolt_damage(state.champion_stats["attack_damage"]) * effectiveness
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
            bolt_key = bolts.row_key
            router = bolts.mechanic_id
            bolt_declaration = _bolt_declaration(state, bolts, raw_bolt)
            bolt_row: dict[str, Any] = {
                "name": bolts.row_name,
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
                    "kind": bolts.targeting_kind,
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
                event_time = swing_times[index] if index < len(swing_times) else 0.0
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
                copied_key = f"on_hit_{bolts.row_key}"
                # Every contributor of every application declares, or
                # the row is not stamped at all.  A champion's
                # ability-carried on-hit is copied here and no item rule
                # states its magnitude, so a partially declared row
                # would hand the walk a price missing a producer while
                # the stamp took the pair engine's whole figure out of
                # the roster total.  That is the half-performed
                # retirement umbrella Amendment L, Ruling 1 calls worse
                # than neither half.  Unstamped, the pair engine goes on
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
                        share.declared_mechanic() is not None
                        for copied_event in copied_events
                        for share in copied_event["shares"]
                        if share.mitigated > 0.0
                    )
                )
                copied_row: dict[str, Any] = {
                    "name": f"{bolts.owner} copied on-hit (secondary)",
                    "count": num_auto_attacks,
                    "damage_per_hit": copied_total / num_auto_attacks,
                    "unit": "bolts",
                    "total_damage": copied_total,
                    **_damage_type_fields(copied_by_type),
                    "targeting": {
                        "kind": f"{bolts.targeting_kind}_copied_on_hit",
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


def _splash_row(
    state: FightState,
    *,
    name: str,
    kind: str,
    damages: list[float],
    swing_times: Sequence[float],
    secondary_target_count: int,
) -> dict[str, Any]:
    """One splash row: what each swing landed on a subject standing nearby.

    The events are authored only against a schedule that reproduces the priced
    packet count, which is what keeps a splash the stream could not time
    coarse rather than stamped at an invented boundary.
    """
    total = sum(damages)
    row: dict[str, Any] = {
        "name": name,
        "count": len(damages),
        "damage_per_hit": total / len(damages),
        "unit": "packets",
        "total_damage": total,
        "damage_type": "physical",
        "targeting": {
            "kind": kind,
            "secondary_target_count": secondary_target_count,
            "allocated_target_index": state.roster_target_index,
            "roster_target_count": state.roster_target_count,
        },
    }
    if len(swing_times) == len(damages):
        row["event_phase"] = "auto"
        row["damage_events"] = [
            {
                "time": swing_times[index],
                "damage": damage,
                "damage_type": "physical",
            }
            for index, damage in enumerate(damages)
        ]
    return row


def _add_cleave_delivery(state: FightState, *, swings: SwingStream) -> None:
    """Splash each swing's declared share onto the other enemies in reach."""
    num_auto_attacks = state.num_auto_attacks
    if num_auto_attacks <= 0:
        return
    swing_times, effectiveness = swings

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
                state.resists,
                state.magic_amp,
            )
            for _ in range(num_auto_attacks)
        ]
        cleave_total = sum(cleave_damages)
        if cleave_total > 0.0:
            state.breakdown[f"on_hit_secondary_{cleave_item_name}"] = _splash_row(
                state,
                name=f"{cleave_item_name} Cleave (secondary)",
                kind="cleave_secondary",
                damages=cleave_damages,
                swing_times=swing_times,
                secondary_target_count=secondary_target_count,
            )
            state.total_damage += cleave_total


def _add_chain_copied_delivery(
    state: FightState,
    rotation: RotationResult,
    on_hits: OnHitResult,
    spellblade: SpellbladeResult,
    *,
    source: item_effects.DamageSource,
    proc_indices,
    swing_times: list[float],
    effectiveness: float,
    procs: int,
) -> None:
    """Copy the attack's on-hit effects onto each subject the arc reached."""
    breakdown = state.breakdown
    # Electrospark applies on-hit effects to secondary targets.
    # Every per-hit packet, including current-health formulas, is
    # replayed at the proc timestamp. Stack-counter effects are
    # replayed after the ordinary attack/ability applications on
    # the same target ledger, preserving their copied-hit order.
    copied_events = []
    for proc_index in proc_indices:
        proc_time = swing_times[proc_index] if proc_index < len(swing_times) else 0.0
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
            copied_by_type[damage_type] = copied_by_type.get(damage_type, 0.0) + amount
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


def _add_cone_delivery(
    state: FightState,
    *,
    empowered_autos: tuple[int, ...],
    swings: SwingStream,
) -> None:
    """Strike the cone's own max-health packet at each further enemy.

    ``empowered_autos`` are the swings the holder's active empowered, which
    the cone prices at its larger declared ratio.
    """
    num_auto_attacks = state.num_auto_attacks
    if num_auto_attacks <= 0:
        return
    swing_times, effectiveness = swings
    secondary_item_name = item_effects.hydra_secondary_item_name(state.items)
    secondary_active_indices = empowered_autos

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
                _mitigate(raw_cone, "physical", state.resists, state.magic_amp)
            )
        cone_total = sum(cone_damages)
        if cone_total > 0.0:
            state.breakdown[f"secondary_{secondary_item_name}"] = _splash_row(
                state,
                name=f"{secondary_item_name} Cleave (secondary)",
                kind="hydra_cleave",
                damages=cone_damages,
                swing_times=swing_times,
                secondary_target_count=secondary_target_count,
            )
            state.total_damage += cone_total
