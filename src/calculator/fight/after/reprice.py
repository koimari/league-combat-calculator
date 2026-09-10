"""Re-pricing a landed packet after the fact, and the mechanics that read the re-priced ledger."""

from collections.abc import Mapping
from typing import Any

from ...item_behavior import AmpChainSlot
from ...program.capability import dropped_preview_mechanics
from ...survival.pricing import restate_declaration
from ..config import FightConfig
from ..ledger.event_rows import _damage_type_fields
from ..ledger.pool_walk import _LIANDRY_BURN_KEY, _simulate_ordered_damage
from ..results import RotationResult
from ..state import FightState
from .amp_chain import _amp_slot


def _apply_liandry_reprice(state: FightState, adjustments: Mapping[str, Any]) -> None:
    """Fold the max-health reprice back onto the burn's own breakdown row.

    The burn's row is where this number belongs: it is more of Liandry's own
    damage, not a bonus some other item granted, and filing it anywhere else
    would attribute one item's damage to another.

    The row's authored ticks are replaced by the repriced ones, so a
    declaration riding a tick is carried across and rescaled by what that tick
    moved by (:func:`restate_declaration`); without that the walk would price
    the burn at its pre-lifeline magnitude and the reprice would vanish from
    every total holding it.
    """
    liandry_delta = float(adjustments["liandry_delta"])
    if abs(liandry_delta) <= 1e-9:
        return
    liandry_row = state.breakdown.get(_LIANDRY_BURN_KEY)
    if liandry_row is None:  # pragma: no cover - registry invariant
        raise RuntimeError("Liandry adjustment has no breakdown row")
    repriced = _carry_declarations_onto_repriced_ticks(
        liandry_row.get("damage_events"), adjustments["liandry_events"]
    )
    liandry_row["total_damage"] = float(liandry_row["total_damage"]) + liandry_delta
    liandry_row["damage_events"] = repriced
    state.total_damage += liandry_delta


def _carry_declarations_onto_repriced_ticks(
    authored: Any, repriced: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Move each authored tick's declaration onto the tick that replaces it.

    The repriced ticks are the same burn's events walked in the same order,
    so the join is positional.  A length the join cannot trust is refused
    rather than guessed, but only where a declaration actually rides one of
    the authored ticks: a burn carrying none has nothing to carry.

    Returns the repriced ticks, so the replacement the caller installs is
    visibly a function of the ticks it replaces, which is what the term
    census reads to tell a re-pricing from an authoring.
    """
    if not isinstance(authored, list):
        return repriced
    carrying = [
        event
        for event in authored
        if isinstance(event, dict) and event.get("declared") is not None
    ]
    if not carrying:
        return repriced
    if len(authored) != len(repriced):
        raise RuntimeError(
            f"Liandry reprice replaced {len(authored)} authored tick(s) with "
            f"{len(repriced)}; {len(carrying)} of them carry a declaration the "
            "walk prices, and a positional carry cannot say which"
        )
    for authored_tick, repriced_tick in zip(authored, repriced, strict=False):
        if not isinstance(authored_tick, dict):
            continue
        authored_damage = float(authored_tick["damage"])
        restate_declaration(
            authored_tick,
            scale=(
                float(repriced_tick["damage"]) / authored_damage
                if authored_damage
                else 1.0
            ),
            onto=repriced_tick,
        )
    return repriced


def _add_shadowflame_cinderbloom(
    state: FightState, config: FightConfig, rotation: RotationResult
) -> None:
    """Run the ordered ledger, then let each mechanic that reads it apply.

    Two mechanics ride one walk (see :func:`_simulate_ordered_damage`): the
    Liandry reprice, which is the burn's own damage, and Cinderbloom, which
    is this function's.  They are applied by two named steps so a change to
    either has an attributable diff.

    A fight a roster composition consumes runs the reprice half alone: the
    composition drops the Cinderbloom row and the coupled walk prices the
    mechanic itself, so computing it here is a number authored to be thrown
    away.
    """
    cinderbloom = _amp_slot(state, AmpChainSlot.CINDERBLOOM)
    if (
        cinderbloom is not None
        and config.roster_composed
        and cinderbloom.rules[0].mechanic_id in dropped_preview_mechanics()
    ):
        cinderbloom = None
    has_threshold_health = config.target_threshold_health_bonus > 0
    if cinderbloom is None and not has_threshold_health:
        return
    (
        shadowflame_bonus,
        bonus_by_type,
        bonus_events,
        adjustments,
    ) = _simulate_ordered_damage(
        cinderbloom,
        state.breakdown,
        state.ability_damages,
        state.target_health,
        state.cast_order,
        cast_events=rotation.cast_events,
        target_magic_shield=config.target_magic_shield,
        target_physical_shield=config.target_physical_shield,
        target_general_shield=config.target_general_shield,
        target_threshold_shield_amount=config.target_threshold_shield_amount,
        target_threshold_shield_health_ratio=(
            config.target_threshold_shield_health_ratio
        ),
        target_threshold_shield_duration=config.target_threshold_shield_duration,
        target_threshold_shield_damage_type=(
            config.target_threshold_shield_damage_type
        ),
        target_threshold_health_bonus=config.target_threshold_health_bonus,
        target_threshold_health_heal=config.target_threshold_health_heal,
        target_threshold_health_ratio=config.target_threshold_health_ratio,
        target_threshold_health_duration=config.target_threshold_health_duration,
        roster_target_index=state.roster_target_index,
    )
    _apply_liandry_reprice(state, adjustments)
    if shadowflame_bonus > 0:
        state.breakdown[f"shadowflame_{cinderbloom.owner}"] = {
            "name": f"{cinderbloom.owner} (Cinderbloom)",
            "total_damage": shadowflame_bonus,
            # Cinderbloom is computed from the ordered source ledger above,
            # and each bonus packet keeps the timestamp of the hit it rode.
            # They go on the row's own ``damage_events`` because that is the
            # only key the ledger reconstruction reads: under any other name
            # the reconstruction synthesizes ONE coarse packet at the last
            # ability time instead, which replays the same total anyway and
            # lands the whole bonus after a target the earlier packets
            # killed.  Death can only stop the packets that really are late.
            "damage_events": bonus_events,
            # Which mechanic this row is the pair engine's reading of, taken
            # from the rule the slot resolved rather than spelled again here.
            # Phase 4 S7 settled which engine owns Cinderbloom — the walk,
            # because the predicate reads the target's health under a whole
            # roster's fire — so this row is the honest one-attacker preview
            # and the roster composition reads the stamp and drops it.  The
            # pair fight's own receipt publishes it unchanged: that surface
            # is the single-attacker question, where the preview is the
            # answer.
            "pair_preview_of": cinderbloom.rules[0].mechanic_id,
            **_damage_type_fields(bonus_by_type),
        }
        state.total_damage += shadowflame_bonus
