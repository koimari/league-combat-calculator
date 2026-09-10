"""What the target's own defenses do to an instance that already met resistance."""

from ..ability_spec import DamagePart
from .resists import _mitigate
from .state import FightState


def _apply_basic_amp(
    state: "FightState", part: DamagePart, mitigated: float, procs: int = 1
) -> float:
    """Amplify a basic-damage part (Hexoptics C44), tracking the info-row bonus.
    Resistance is linear in raw damage, so amplifying post-mitigation is exact.
    Non-basic parts pass through untouched.  ``procs`` scales only the tracked
    bonus, for callers that multiply the returned per-proc value afterwards."""
    if not part.basic_damage or state.basic_amp <= 1.0:
        return mitigated
    amped = mitigated * state.basic_amp
    state.basic_amp_ability_bonus += (amped - mitigated) * procs
    return amped


def _apply_target_basic_damage_reduction(
    state: "FightState",
    post_mitigation_damage: float,
    *,
    hits: int = 1,
    rock_solid_instances: int = 1,
) -> float:
    """Apply target-side percentage and capped-flat basic-damage defenses.

    Plating is a percentage modifier and therefore composes
    multiplicatively with armor and attacker amplifiers. Rock Solid is
    explicitly post-mitigation: it removes 15 from the first basic-damage
    instance of each cast, but never more than 20% of that instance.
    ``hits`` lets a multi-hit basic-damage part receive Plating on every hit
    while consuming Rock Solid only once for its cast instance.
    """
    if hits <= 0:
        return post_mitigation_damage
    reduced = post_mitigation_damage * state.target_basic_damage_multiplier
    # Negative parts are algebraic modifiers to a swing (Jayce W below
    # rank 5), not a separate incoming event. Plating scales the modifier,
    # but a flat defensive proc cannot be consumed by negative damage.
    if reduced <= 0:
        return reduced
    flat = state.target_basic_damage_flat_reduction
    cap = state.target_basic_damage_flat_reduction_cap
    instances = min(max(0, rock_solid_instances), hits)
    if flat <= 0 or cap <= 0 or instances <= 0:
        return reduced
    per_hit = reduced / hits
    reduction_per_instance = min(flat, per_hit * cap)
    return max(0.0, reduced - reduction_per_instance * instances)


def _apply_target_champion_damage_reduction(
    state: "FightState",
    post_mitigation_damage: float,
    *,
    hits: int = 1,
    damage_over_time: bool = False,
) -> float:
    """Apply a sourced flat reduction to champion attack or spell packets."""
    if hits <= 0 or post_mitigation_damage <= 0.0:
        return post_mitigation_damage
    reduction = (
        state.target_champion_dot_damage_flat_reduction
        if damage_over_time
        else state.target_champion_damage_flat_reduction
    )
    if reduction <= 0.0:
        return post_mitigation_damage
    return max(0.0, post_mitigation_damage - reduction * hits)


def _crit_scaled_raw(
    state: "FightState",
    raw: float,
    crit_effectiveness: float,
    damage_type: str,
) -> float:
    """Raw damage of an instance that crits at *crit_effectiveness*.

    ``crit_effectiveness`` scales the crit PROBABILITY, not the multiplier
    (Akshan R: 0.3, a full-effectiveness rider: 1.0), and the result is the
    probability-weighted value — never a roll, so a crit-capable build stays
    reproducible.  Both channels that carry a champion's own crit modifier
    read it here: ``DamagePart.crit_effectiveness`` on an ability part and
    ``on_hit["crit_effectiveness"]`` on an on-hit row.
    """
    if crit_effectiveness <= 0:
        return raw
    crit_probability = min(1.0, crit_effectiveness * state.crit_chance)
    target_crit_multiplier = (
        1.0 if damage_type == "true" else state.target_critical_strike_damage_multiplier
    )
    return raw * (
        1.0
        - crit_probability
        + crit_probability * state.crit_multiplier * target_crit_multiplier
    )


def _mitigate_basic_attack_swing(
    state: "FightState",
    raw_damage: float,
    damage_type: str = "physical",
    *,
    critical_strike: bool = False,
) -> float:
    """Resolve one primary basic-attack damage instance against the target."""
    mitigated = _mitigate(
        raw_damage,
        damage_type,
        state.resists,
        state.magic_amp,
    )
    mitigated *= state.basic_amp
    if critical_strike:
        mitigated *= state.target_critical_strike_damage_multiplier
    if damage_type != "true":
        mitigated = _apply_target_basic_damage_reduction(state, mitigated)
        mitigated = _apply_target_champion_damage_reduction(state, mitigated)
    return mitigated


def _mitigate_hits(
    state: "FightState",
    part: DamagePart,
    raw: float,
    ability_mr: float,
    *,
    hits: int,
    rock_solid_instances: int = 0,
    damage_over_time: bool = False,
) -> float:
    """Mitigated damage for *hits* identical hits of one damage part."""
    # ``DamagePart.__post_init__`` refuses a class outside the vocabulary, so
    # no part reaches here whose type ``_mitigate`` pays raw.
    one_hit = _mitigate(
        raw, part.damage_type, state.resists, state.magic_amp, ability_mr=ability_mr
    )
    mitigated = one_hit * hits
    mitigated = _apply_basic_amp(state, part, mitigated)
    if part.basic_damage and part.damage_type != "true":
        mitigated = _apply_target_basic_damage_reduction(
            state,
            mitigated,
            hits=hits,
            rock_solid_instances=rock_solid_instances,
        )
    if part.damage_type != "true":
        mitigated = _apply_target_champion_damage_reduction(
            state,
            mitigated,
            hits=hits,
            damage_over_time=damage_over_time,
        )
    return mitigated
