"""Active-item damage, skipped when actives are excluded."""

from ... import item_effects
from ...ability_spec import AttackClass
from ...survival.pricing import AuthoredDeclaration
from ..autos.on_hit_stream import _active_lifesteal_amount
from ..cast_slots import _damaging_cast_times
from ..resists import _mitigate, _resistance_met_fields
from ..results import RotationResult, SwingStream
from ..state import FightState, _damage_inputs


def _add_item_active_damage(state: FightState, rotation: RotationResult) -> None:
    """Add active-item damage (skipped when actives are excluded).

    Each active is cast once. The engine's standing assumption — the
    same one the coarse ledger encoded — is that it fires with the end
    of the rotation opener, so its event is stamped at the last accepted
    damaging cast (fight start when there are no casts).

    **This row is a preview.**  The number below is the honest single-attacker
    answer and the pair fight's own receipt publishes it unchanged; the
    roster composition reads ``pair_preview_of``, sees the mechanic's pair
    lane declared ``ViewTag.THEORETICAL``, and takes the number out of every
    total it composes.  The event keeps its place there carrying the
    ``AuthoredDeclaration`` the coupled walk prices instead — the rule, the
    pre-mitigation magnitude, and the attack class that decides which of the
    holder's own amps the packet earns.  ``AttackClass.OTHER`` is that class
    and it is measured rather than assumed: ``_mitigate`` above applies the
    holder's magic amp and no part amp, so an active earns neither the
    ability nor the basic-attack multiplier.  The resistance the packet met
    is left for the ledger to state — absent here because this packet meets
    the fight's published figure, and restated by
    :func:`restate_declaration` at every site that re-prices it afterwards.
    """
    if not state.include_actives:
        return
    resists = state.resists
    active_time = max(_damaging_cast_times(state, rotation), default=0.0)
    secondary_item_name = item_effects.active_secondary_ad_item_name(state.items)
    for source in state.item_actives:
        raw_active = source.raw_damage(_damage_inputs(state))
        active_mitigated = _mitigate(
            raw_active, source.damage_type, resists, state.magic_amp
        )

        damage_events = [
            {
                "time": active_time,
                "damage": active_mitigated,
                "damage_type": source.damage_type,
                "declared": tuple(
                    AuthoredDeclaration(
                        source.previewed_mechanic(),
                        raw_active,
                        AttackClass.OTHER.value,
                    )
                ),
                **_resistance_met_fields(source.damage_type, resists),
            }
        ]
        state.breakdown[source.breakdown_key] = {
            "name": source.display_name,
            "total_damage": active_mitigated,
            "damage_type": source.damage_type,
            "damage_events": damage_events,
            "pair_preview_of": source.previewed_mechanic(),
        }
        if source.lifesteal_effectiveness > 0.0:
            heal_amount = _active_lifesteal_amount(
                state, damage_events[0], source.lifesteal_effectiveness
            )
            if heal_amount is not None:
                state.breakdown[f"heal_{source.item_name}"] = {
                    "name": f"{source.item_name} (life steal)",
                    "count": 1,
                    "proc_times": [active_time],
                    "amount_per_proc": heal_amount,
                    "total_amount": heal_amount,
                    "unit": "health",
                }

        secondary_target_count = max(0, state.roster_target_count - 1)
        if (
            source.item_name == secondary_item_name
            and secondary_target_count > 0
            and 1 <= state.roster_target_index <= secondary_target_count
        ):
            raw_secondary = item_effects.hydra_cleave_secondary_ad_damage(
                total_attack_damage=state.champion_stats["attack_damage"],
                is_melee=state.is_melee,
                item_name=source.item_name,
            )
            secondary_mitigated = _mitigate(
                raw_secondary, source.damage_type, resists, state.magic_amp
            )
            secondary_key = f"secondary_{source.item_name}"
            secondary_event = {
                "time": active_time,
                "damage": secondary_mitigated,
                "damage_type": source.damage_type,
                **_resistance_met_fields(source.damage_type, resists),
            }
            state.breakdown[secondary_key] = {
                "name": f"{source.display_name} (secondary)",
                "count": 1,
                "unit": "packets",
                "total_damage": secondary_mitigated,
                "damage_type": source.damage_type,
                "damage_events": [secondary_event],
                "targeting": {
                    "kind": "active_secondary",
                    "secondary_target_count": secondary_target_count,
                    "allocated_target_index": state.roster_target_index,
                    "roster_target_count": state.roster_target_count,
                },
            }
            if source.lifesteal_effectiveness > 0.0:
                heal_amount = _active_lifesteal_amount(
                    state, secondary_event, source.lifesteal_effectiveness
                )
                if heal_amount is not None:
                    state.breakdown[f"heal_{source.item_name}"] = {
                        "name": f"{source.item_name} (life steal)",
                        "count": 1,
                        "proc_times": [active_time],
                        "amount_per_proc": heal_amount,
                        "total_amount": heal_amount,
                        "unit": "health",
                    }
            state.total_damage += secondary_mitigated
        state.total_damage += active_mitigated


def _add_auto_cooldown_strikes(
    state: FightState, *, swings: SwingStream
) -> tuple[int, ...]:
    """Price the swing each item active empowers on its own cooldown.

    Returns which swings the cone-carrying holder empowered, because that is
    the fact the cone's larger ratio is read against.
    """
    num_auto_attacks = state.num_auto_attacks
    if num_auto_attacks <= 0:
        return ()
    resists = state.resists
    breakdown = state.breakdown
    swing_times, effectiveness = swings
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
        mitigated = _mitigate(raw_damage, source.damage_type, resists, state.magic_amp)
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
                    **_resistance_met_fields(source.damage_type, resists),
                }
                for proc_time in proc_times
            ]
        state.total_damage += mitigated
    return secondary_active_indices
