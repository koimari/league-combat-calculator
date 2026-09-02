"""Typed roster composition primitives used by the participant timeline."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, MutableMapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from .defensive_effects import StartingDefenses
from .interpreters.stat_derivation import declared_stat_derivations
from .interpreters.sustain import SustainSlot, declared_sustain
from .item_behavior import DerivedStat, ManaSpentHealRule, StatAuraRule
from .pipeline import FightParams

if TYPE_CHECKING:
    from .scenario import ResolvedLoadout


@dataclass(frozen=True, slots=True)
class ActorRequest:
    """What a participant's request contributes to the fight it runs.

    One shape for both producers -- a roster card's ``ChampionLoadout``
    and the main champion's ``FightParams`` -- so every consumer reads
    the fields directly.  ``None`` and ``{}`` are different answers and
    are carried as the producer gave them: an absent rank map skips rank
    validation, and an absent item-option map is the direct-caller
    default an empty one overrides
    (``item_effects.actualizer_active_seconds``).
    """

    role: str = ""
    role_quest_complete: bool = False
    ability_ranks: dict[str, int] | None = None
    champion_options: dict[str, Any] | None = None
    support_target_selections: dict[str, int] | None = None
    cast_order: list[str] | None = None
    item_options: dict[str, dict[str, int]] | None = None
    ally_effects_enabled: bool = False
    # The authored starting health of a roster card, bounded to
    # (0, max health] by its parser.  ``None`` is full health -- the one
    # way a participant enters the fight already wounded, read by
    # ``survival.transitions.participant_pools``.
    current_health: float | None = None

    @classmethod
    def of_params(cls, params: FightParams) -> ActorRequest:
        """The main champion's request, off the selected fight params."""
        return cls(
            role=params.role,
            role_quest_complete=params.role_quest_complete,
            ability_ranks=params.ability_ranks,
            champion_options=params.champion_options,
            support_target_selections=params.support_target_selections,
            cast_order=params.cast_order,
            item_options=params.item_options,
        )


@dataclass(frozen=True, slots=True)
class Combatant:  # pylint: disable=too-many-instance-attributes
    """One participant with its resolved stats and build."""

    participant_id: str
    team: str
    champion_data: dict[str, Any]
    level: int
    items: tuple[dict[str, Any], ...]
    stats: dict[str, float]
    defenses: StartingDefenses
    request: ActorRequest = field(default_factory=ActorRequest)
    is_practice_dummy: bool = False

    def __post_init__(self) -> None:
        # Every walk-side consumer reads ``defenses`` and ``request`` by
        # direct attribute, so a stand-in object is refused here, by
        # name, not on its first read.
        if not isinstance(self.defenses, StartingDefenses):
            raise TypeError(
                f"{self.participant_id}: defenses must be a StartingDefenses, "
                f"not {type(self.defenses).__name__}"
            )
        if not isinstance(self.request, ActorRequest):
            raise TypeError(
                f"{self.participant_id}: request must be an ActorRequest, "
                f"not {type(self.request).__name__}"
            )


def coalesce_darius_q_heals(
    healing: MutableMapping[str, list[dict[str, Any]]],
) -> None:
    """Combine Darius Q pair receipts into one live heal per cast."""
    for events in healing.values():
        groups: dict[tuple[float, int], tuple[int, int]] = {}
        kept: list[dict[str, Any]] = []
        for event in events:
            marker = event.get("_darius_q_group")
            if not isinstance(marker, tuple) or len(marker) != 2:
                kept.append(event)
                continue
            key = (float(marker[0]), int(marker[1]))
            first = groups.get(key)
            if first is None:
                groups[key] = (len(kept), 1)
                kept.append(event)
            else:
                groups[key] = (first[0], first[1] + 1)
        for index, count in groups.values():
            kept[index] = {
                **kept[index],
                "amount_formula": (
                    lambda current_health, maximum_health, count=count: (
                        max(0.0, maximum_health - current_health)
                        * min(0.51, 0.17 * count)
                    )
                ),
            }
        events[:] = kept


def from_loadout(
    participant_id: str,
    team: str,
    loadout: ResolvedLoadout,
) -> Combatant:
    """Create a typed roster participant from one resolved loadout."""
    card = loadout.request
    return Combatant(
        participant_id=participant_id,
        team=team,
        champion_data=loadout.champion_data,
        level=card.level,
        items=loadout.item_data,
        stats=loadout.stats,
        defenses=loadout.defenses,
        request=ActorRequest(
            role=card.role,
            role_quest_complete=card.role_quest_complete,
            ability_ranks=card.ability_ranks,
            champion_options=card.champion_options,
            support_target_selections=card.support_target_selections or None,
            cast_order=card.cast_order,
            item_options=card.item_options,
            ally_effects_enabled=card.ally_effects_enabled,
            current_health=card.current_health,
        ),
        is_practice_dummy=card.is_practice_dummy,
    )


def main_combatant(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    champion_data: dict[str, Any],
    level: int,
    items: list[dict[str, Any]],
    *,
    stats: dict[str, float],
    defenses: StartingDefenses,
    params: FightParams,
) -> Combatant:
    """Create the selected main champion's roster participant."""
    return Combatant(
        participant_id="main",
        team="main",
        champion_data=champion_data,
        level=level,
        items=tuple(items),
        stats=stats,
        defenses=defenses,
        request=ActorRequest.of_params(params),
    )


def actor_params(base: FightParams, actor: Combatant) -> FightParams:
    """Use a roster actor's role while preserving the selected fight window."""
    request = actor.request
    return replace(
        base,
        role=request.role,
        role_quest_complete=request.role_quest_complete,
        # An empty rank map is "no manual allocation", which is what
        # the engine reads ``None`` as; the two are one answer here.
        ability_ranks=request.ability_ranks or None,
        champion_options=request.champion_options,
        support_target_selections=request.support_target_selections,
        cast_order=request.cast_order,
        item_options=request.item_options,
        ally_stat_bonuses=None,
        keystone=base.keystone if actor.participant_id == "main" else "",
        keystone_options=(
            base.keystone_options if actor.participant_id == "main" else {}
        ),
    )


def _attack_speed_aura_multiplier(defender: Combatant) -> float:
    """What a defender's declared attack-speed auras do to its attacker.

    A stat aura is the one stat derivation whose subject is the enemy, so
    the roster reads it off the *defender* and hands the attacker the
    multiplier.  Read through the declaration rather than by item name: the
    shape decides, so a second item growing an attack-speed aura arrives
    here on the commit its declaration lands.

    The granted stat is what selects, so an aura reducing something else is
    not silently spent on attack speed; it is simply not this field's input.
    Two holders of the *same* stat is a named stop, not a silent pick:
    nothing declares whether two auras multiply, sum or take the strongest,
    and guessing is how an unreviewed number reaches a live fight.
    """
    slots = [
        slot
        for slot in declared_stat_derivations(
            sorted({str(item.get("name", "")) for item in defender.items}),
            StatAuraRule,
        )
        if slot.granted is DerivedStat.ATTACK_SPEED_PERCENT
    ]
    if not slots:
        return 1.0
    if len(slots) > 1:
        raise ValueError(
            f"{[slot.owner for slot in slots]} all declare an attack-speed "
            "aura and nothing declares how two of them compose on one "
            "defender"
        )
    return 1.0 - float(slots[0].value("reduction"))


def target_overrides(defender: Combatant) -> dict[str, float | str]:
    """Return every target field read by a one-pair fight."""
    defenses = defender.defenses
    attack_speed_multiplier = _attack_speed_aura_multiplier(defender)
    return {
        "target_health": float(defender.stats.get("health", 0.0)),
        "target_bonus_health": float(defender.stats.get("bonus_health", 0.0)),
        "target_armor": float(defender.stats.get("armor", 0.0)),
        "target_magic_resistance": float(defender.stats.get("magic_resistance", 0.0)),
        "target_magic_shield": float(defenses.magic_shield),
        "target_physical_shield": float(defenses.physical_shield),
        "target_general_shield": float(defenses.general_shield),
        "target_basic_damage_multiplier": float(defenses.basic_damage_multiplier),
        "target_basic_damage_flat_reduction": float(
            defenses.basic_damage_flat_reduction
        ),
        "target_basic_damage_flat_reduction_cap": float(
            defenses.basic_damage_flat_reduction_cap
        ),
        "target_critical_strike_damage_multiplier": float(
            defenses.critical_strike_damage_multiplier
        ),
        "attacker_attack_speed_multiplier": attack_speed_multiplier,
        "target_threshold_shield_amount": float(defenses.threshold_shield_amount),
        "target_threshold_shield_health_ratio": float(
            defenses.threshold_shield_health_ratio
        ),
        "target_threshold_shield_duration": float(defenses.threshold_shield_duration),
        "target_threshold_shield_damage_type": str(
            defenses.threshold_shield_damage_type
        ),
        "target_threshold_health_bonus": float(defenses.threshold_health_bonus),
        "target_threshold_health_heal": float(defenses.threshold_health_heal),
        "target_threshold_health_ratio": float(defenses.threshold_health_ratio),
        "target_threshold_health_duration": float(defenses.threshold_health_duration),
    }


def target_params(base: FightParams, defender: Combatant) -> FightParams:
    """Apply one defender's typed fields to a pair fight."""
    return replace(base, **target_overrides(defender))


def defensive_signature(defender: Combatant) -> tuple[Any, ...]:
    """Return a hashable signature for the target override fields."""
    return tuple(target_overrides(defender).values())


def mana_spent_heal_slot(items: Iterable[Mapping[str, Any]]) -> SustainSlot | None:
    """The build's declared mana-spent heal, or ``None``.
    The slot carries the damage-taken-to-resource ratio the ordered restore
    ledger below is built from."""
    return declared_sustain(
        sorted({str(item.get("name", "")) for item in items}), ManaSpentHealRule
    )


def resource_restores(
    actor: Combatant,
    incoming: Mapping[str, Iterable[Mapping[str, Any]]],
    duration: float,
) -> tuple[tuple[tuple[float, float], ...], bool]:
    """Derive one actor's restores from complete incoming champion packets."""
    slot = mana_spent_heal_slot(actor.items)
    if slot is None:
        return (), True
    ratio = slot.value("damage_taken_to_mana_ratio")
    restores: list[tuple[float, float]] = []
    for event in incoming.get(actor.participant_id, ()):
        if not isinstance(event, Mapping):
            continue
        source_id = str(event.get("attacker", ""))
        if not source_id or source_id == actor.participant_id:
            continue
        if event.get("_reactive") or event.get("_deferred"):
            continue
        try:
            event_time = float(event.get("time", 0.0))
            raw_damage = float(event.get("raw_damage", 0.0) or 0.0)
        except (TypeError, ValueError):
            return (), False
        if (
            not math.isfinite(event_time)
            or not math.isfinite(raw_damage)
            or event_time < 0.0
        ):
            # A number the packet cannot state is a packet this ledger
            # cannot read, so it refuses rather than guess.  A time before
            # the fight begins is the same kind of unreadable.
            return (), False
        if event_time > duration + 1e-9:
            # A hit past the end of the window is not unreadable, only
            # late, and the survival walk already knows what to do with it:
            # every action past ``duration`` is skipped ``outside_window``
            # (survival/transitions.py), damage included.  Its restore is
            # therefore mana for damage the fight never takes — dropped
            # here rather than clamped forward, which would hand the actor
            # a resource at a moment it never held one and could admit a
            # cast the fight never paid for.  Refusing the whole packet for
            # it would cap every authored ``time_offset`` at the fight
            # length: Aatrox's third Q strike lands at 8.85s in an
            # eight-second roster fight, and the cadence is sourced.
            continue
        if raw_damage <= 0.0:
            continue
        amount = raw_damage * ratio
        if amount > 0.0:
            restores.append((event_time, amount))
    restores.sort(key=lambda row: row[0])
    return tuple(restores), True


def actor_params_with_resource_restores(
    base: FightParams,
    actor: Combatant,
    resource_restores: Mapping[str, tuple[tuple[float, float], ...]] | None,
) -> FightParams:
    """Attach one actor's typed external resource ledger to its fight params."""
    params = actor_params(base, actor)
    return replace(
        params,
        resource_restore_events=(
            tuple(resource_restores.get(actor.participant_id, ()))
            if resource_restores is not None
            else ()
        ),
        resource_ledger_owner=actor.participant_id,
    )
