"""Item damage on a clock: burns, auras, fixed-interval strikes."""

from typing import Any

from ...ability_atoms import ability_field
from ...ability_spec import AttackClass
from ...survival.pricing import AuthoredDeclaration
from ..cast_slots import _damaging_cast_times
from ..ledger.event_rows import _row_declaration_share
from ..resists import _mitigate, _resistance_met_fields
from ..results import RotationResult
from ..rotation.dot_ticks import _periodic_damage_events
from ..state import FightState, _damage_inputs


def _periodic_declaration(mechanic_id: str, raw_amount: float) -> tuple[Any, ...]:
    """One periodic packet's declaration: rule, magnitude, attack class.

    ``AttackClass.OTHER`` is measured, not defaulted: all three cadences reach
    the target through :func:`_mitigate` alone, so none earns a part amp.  All
    seven declared strikes are magic, and ``StaticHolderAmps.factor_for``
    delivers that amp off the damage type, so pre-multiplying it here would be
    a second producer.  *raw_amount* is the cadence's whole raw aggregate."""
    return tuple(
        AuthoredDeclaration(
            mechanic_id,
            raw_amount,
            AttackClass.OTHER.value,
        )
    )


def _declared_periodic_ticks(
    events: list[dict[str, float | str]],
    declaration: tuple[Any, ...],
    total_damage: float,
) -> list[dict[str, float | str]]:
    """Stamp each tick with its share of the row's one declaration.

    :func:`_periodic_damage_events` splits one mitigated aggregate into
    timestamped ticks, so the declaration splits by the same ratio, through
    the one method :func:`_row_declaration_share` and
    :func:`restate_declaration` also use.  Mitigation is linear, so a tick's
    share of the mitigated total is its share of the raw magnitude."""
    for event in events:
        share = _row_declaration_share(
            declaration, float(event["damage"]), total_damage
        )
        if share is not None:
            event["declared"] = share  # type: ignore[assignment]
    return events


def _add_burn_damage(state: FightState, rotation: RotationResult) -> None:
    """Add burn/DoT item damage: burns, Immolate, and Unending Despair.

    Burns refresh on each ability hit (and on Malignance's Hatefog DoT),
    so the effective burn window stretches across the rotation's cast
    spread, and the final application resolves fully past the fight's
    end (refresh EVENTS stop with the last cast/DoT tick; the burn they
    lit does not).

    A burn is lit by a damaging ability hit and by nothing else, so a
    window with no accepted damaging cast — ``auto_only``, a cast order
    the kit prices at zero, a rotation the resource budget refused — has
    no burn row at all rather than a coarse total.  Auras and
    fixed-interval strikes below are clock-driven and keep firing.
    """
    resists = state.resists
    ability_damages = state.ability_damages
    lit_burns = (
        state.declared.periodics.burns if _damaging_cast_times(state, rotation) else ()
    )

    for effect in lit_burns:
        source = effect.source
        raw_burn = source.raw_damage(_damage_inputs(state))
        burn_duration = effect.duration
        # Burn refreshes on each ability hit (including R dashes —
        # only multi-instance Rs declare cast_instances; default 1).
        # The dashes belong to an R the rotation accepted (``ult_cast``),
        # not to an R the kit merely prices.
        r_info = ability_damages.get("R")
        r_extra = 0
        if r_info and resists.ult_cast:
            r_extra = ability_field(r_info, "cast_instances") - 1
        # Estimate time from first to last ability hit.  In a fast
        # one-rotation combo, casts are ~0.5s apart (GCD-limited).
        inter_cast_delay = 0.5
        cast_spread = (rotation.total_ability_casts - 1 + r_extra) * inter_cast_delay

        # Champion DoTs (e.g. Brand's Blaze) keep dealing ability
        # damage for their ``dot_duration`` tail after the applying
        # cast — every tick refreshes the burn. Ablaze re-applies on
        # each cast, so the tail extends from the LAST cast.
        champion_dot_tail = max(
            (ability_field(info, "dot_duration") for info in ability_damages.values()),
            default=0.0,
        )
        # Other item DoTs (e.g. Malignance Hatefog) deal ability
        # damage that also refreshes burns.  Hatefog starts at the
        # rotation's accepted R cast (``ult_cast`` — the same fact the
        # proc row and the served MR read), so its refresh window begins
        # partway through the cast_spread and a window that never accepts
        # an R extends nothing.
        # In timed mode, abilities recast on cooldown across the whole
        # fight — the last recast (rotation.last_cast_time) refreshes
        # the burn far beyond the GCD combo spread.
        dot_refresh_end = max(cast_spread, rotation.last_cast_time) + champion_dot_tail
        if resists.ult_cast:
            for ultimate_proc in state.declared.cast_procs.ultimate_procs:
                # R1 lands r_extra dashes (x0.5s each) before the last hit
                r_start = cast_spread - r_extra * inter_cast_delay
                hatefog_end = r_start + ultimate_proc.duration
                dot_refresh_end = max(dot_refresh_end, hatefog_end)

        # The final refresh's burn resolves in FULL — DoT consequences
        # of casts made within the fight tick out past its end, in both
        # modes. Capping timed mode at fight_duration priced the burn
        # as rate x fight_duration and undercounted short fights ~3x
        # (user-measured: Cassiopeia + Blackfire over 3s did ~90
        # in-game, the capped model said ~30).
        effective_burn_time = dot_refresh_end + burn_duration
        if effective_burn_time > burn_duration:
            burn_multiplier = effective_burn_time / burn_duration
            raw_burn *= burn_multiplier
        burn_mitigated = _mitigate(raw_burn, "magic", resists, state.magic_amp)

        declaration = _periodic_declaration(source.previewed_mechanic(), raw_burn)
        state.breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "total_damage": burn_mitigated,
            "damage_type": source.damage_type,
            # This row is the pair engine's preview of a number the coupled
            # walk owns: the roster composition reads the stamp and takes the
            # figure above out of every total it composes, while the pair
            # fight's own receipt publishes it unchanged.
            "pair_preview_of": source.previewed_mechanic(),
            "declared": declaration,
            "damage_events": _declared_periodic_ticks(
                _periodic_damage_events(
                    burn_mitigated,
                    source.damage_type,
                    effective_burn_time,
                    effect.tick_interval,
                    resists,
                ),
                declaration,
                burn_mitigated,
            ),
            "event_phase": "effect",
        }
        state.total_damage += burn_mitigated

    for source in state.declared.periodics.auras:
        raw_immolate = source.raw_damage(_damage_inputs(state))
        raw_immolate *= state.fight_duration_seconds
        immolate_mitigated = _mitigate(
            raw_immolate, source.damage_type, resists, state.magic_amp
        )

        declaration = _periodic_declaration(source.previewed_mechanic(), raw_immolate)
        state.breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "total_damage": immolate_mitigated,
            "damage_type": source.damage_type,
            # A preview like the burns above author.  The row-level
            # declaration is also what a *coarse* aura hands the walk -- one
            # whose rule publishes no event interval authors no ticks of its
            # own, and the reconstruction synthesizes one
            # (``_row_declaration_share``).
            "pair_preview_of": source.previewed_mechanic(),
            "declared": declaration,
        }
        if source.event_interval is not None:
            state.breakdown[source.breakdown_key]["damage_events"] = (
                _declared_periodic_ticks(
                    _periodic_damage_events(
                        immolate_mitigated,
                        source.damage_type,
                        state.fight_duration_seconds,
                        source.event_interval,
                        resists,
                    ),
                    declaration,
                    immolate_mitigated,
                )
            )
            state.breakdown[source.breakdown_key]["event_phase"] = "effect"
        state.total_damage += immolate_mitigated

    for effect in state.declared.periodics.intervals:
        source = effect.source
        procs = (
            int(state.fight_duration_seconds / effect.interval)
            if effect.interval > 0
            else 0
        )
        raw_periodic = source.raw_damage(_damage_inputs(state)) * procs
        if raw_periodic > 0:
            periodic_mitigated = _mitigate(
                raw_periodic, source.damage_type, resists, state.magic_amp
            )
            # Anguish begins its fixed cadence when combat starts.  The first
            # authored cast is the engine's sourced combat-start boundary; a
            # no-cast fight starts at zero rather than inventing a delay.
            combat_start = min(
                (float(event["time"]) for event in rotation.cast_events),
                default=0.0,
            )
            damage_per_proc = periodic_mitigated / procs if procs else 0.0
            declaration = _periodic_declaration(
                source.previewed_mechanic(), raw_periodic
            )
            damage_events = [
                {
                    "time": combat_start + (index + 1) * effect.interval,
                    "damage_type": source.damage_type,
                    "damage": damage_per_proc,
                    "event_precision": "exact",
                    "target_range_units": state.declared.periodics.range_units[
                        source.breakdown_key
                    ],
                    "target_scope": "enemy_champions_within_range",
                    "declared": _row_declaration_share(
                        declaration, damage_per_proc, periodic_mitigated
                    ),
                    **_resistance_met_fields(source.damage_type, resists),
                }
                for index in range(procs)
            ]
            row = {
                "name": source.display_name,
                "total_damage": periodic_mitigated,
                "damage_type": source.damage_type,
                # A preview like the other two cadences author: one packet per
                # completed interval, each carrying its share of the row's own
                # declaration.
                "pair_preview_of": source.previewed_mechanic(),
                "declared": declaration,
                "damage_events": damage_events,
                "event_phase": "effect",
            }
            if effect.self_heal_post_mitigation_multiplier > 0.0:
                row["self_heal_post_mitigation_multiplier"] = (
                    effect.self_heal_post_mitigation_multiplier
                )
            state.breakdown[source.breakdown_key] = row
            state.total_damage += periodic_mitigated
