"""Splitting post-mitigation damage into shield absorption and health damage."""

from collections.abc import Iterable
from typing import Any

from ... import shield_ledger, shield_pools
from ...survival.pricing import restate_declaration
from ...survival.transitions import evaluate_live_raw_formula
from ..config import FightConfig
from ..ledger.pool_walk import _ThresholdHealDrip
from ..state import FightState


def _walk_end_time(
    config: FightConfig, damage_events: Iterable[dict[str, Any]]
) -> float:
    """When a shield walk's window closes, for the timed state it expires.
    The authored fight duration, unless the ledger runs past it: a burst
    request carries no duration and its packets are the only clock."""
    latest = max(
        (float(event["time"]) for event in damage_events),
        default=0.0,
    )
    return max(float(config.fight_duration_seconds), latest)


def _resolve_starting_shield_outcome(
    state: FightState, config: FightConfig, damage_events: list[dict[str, Any]]
) -> dict[str, float]:
    """Split post-mitigation TDD into shield absorption and health damage.

    TDD remains damage dealt. Shields are reported as a separate defensive
    outcome so the UI does not hide how much of that damage reached health.

    A max-health- or missing-health-scaled packet is re-priced here against
    the target's live pools, which makes this the third site that changes what
    an already-authored packet is worth — the one umbrella Amendment N's prose
    did not name and its Ruling 2 census found.  Each such packet's
    declaration is restated by the ratio the packet moved by, and rides back
    onto the authored event with the number
    (:func:`restate_declaration`, Ruling 1's *kept in step*).
    """
    repriced = False
    pools = shield_pools.build_pools(
        state.target_health,
        magic_shield=config.target_magic_shield,
        physical_shield=config.target_physical_shield,
        general_shield=config.target_general_shield,
        threshold_shield_amount=config.target_threshold_shield_amount,
        threshold_shield_health_ratio=config.target_threshold_shield_health_ratio,
        threshold_shield_duration=config.target_threshold_shield_duration,
        threshold_shield_damage_type=config.target_threshold_shield_damage_type,
        threshold_health_bonus=config.target_threshold_health_bonus,
        threshold_health_heal=config.target_threshold_health_heal,
        threshold_health_ratio=config.target_threshold_health_ratio,
        threshold_health_duration=config.target_threshold_health_duration,
    )
    heal_drip = _ThresholdHealDrip()
    threshold_health = pools.threshold_health
    if shield_pools.is_inert(pools):
        # No shield can absorb and no threshold state can arm: every
        # per-event absorption below is exactly ``- 0.0``, so the walk
        # reduces bit-for-bit to sequential floored health subtraction.
        current_health = pools.health
        for event in damage_events:
            current_health = max(0.0, current_health - event["damage"])
            # P4: the single-fight walk mirrors the survival terminal
            # transition's execute gate (inclusive <=, after the event's
            # own damage) so /api/calculate agrees with the pair/timeline
            # surface (Zeri's Living Battery).
            ratio = float(event.get("execute_threshold_ratio", 0.0) or 0.0)
            if (
                ratio > 0.0
                and current_health > 0.0
                and current_health <= pools.max_health * ratio
            ):
                current_health = 0.0
        pools.health = current_health
    else:
        for event in damage_events:
            event_time = float(event["time"])
            heal_drip.advance_to(pools, event_time)
            remaining = float(event["damage"])
            raw_formula = event.get("raw_formula")
            raw_damage = float(event.get("raw_damage", 0.0) or 0.0)
            if callable(raw_formula) and raw_damage > 0.0:
                missing_ratio = max(
                    0.0,
                    min(
                        1.0,
                        1.0 - pools.health / max(pools.max_health, 1e-12),
                    ),
                )
                live_raw = evaluate_live_raw_formula(
                    raw_formula, missing_ratio, pools.max_health
                )
                live_damage = remaining * live_raw / raw_damage
                if abs(live_damage - remaining) > 1e-9:
                    repriced = True
                    # The declaration moves by exactly what the packet moved
                    # by (Amendment N, Ruling 1, through the site Ruling 2's
                    # census added to the kept-in-step list).
                    restate_declaration(event, scale=live_damage / remaining)
                    remaining = live_damage
                    event["damage"] = live_damage
            outcome = shield_ledger.absorb(
                pools, remaining, event["damage_type"], event_time
            )
            if outcome.threshold_health_triggered:
                heal_drip.start(pools, event_time, outcome)
        # The window edge, the way the survival walk's ``finalize_states``
        # closes one: a Lifeline armed by the last packet still owes its
        # remaining ticks and its expiry inside the authored fight.
        heal_drip.advance_to(pools, _walk_end_time(config, damage_events))

    if repriced:
        # Each source's repriced packets, and the declaration each of them
        # came out carrying: the ledger this walk mutated is a copy of the
        # rows' own events, so a restatement made above reaches the authored
        # packet only by riding back with the number beside it.
        repriced_by_source: dict[str, list[tuple[float, Any]]] = {}
        for event in damage_events:
            repriced_by_source.setdefault(str(event["source_key"]), []).append(
                (float(event["damage"]), event.get("declared"))
            )
        for source_key, entry in state.breakdown.items():
            values = repriced_by_source.get(source_key)
            if not values:
                continue
            entry["total_damage"] = sum(damage for damage, _ in values)
            declared = entry.get("damage_events")
            if isinstance(declared, list):
                for index, nested in enumerate(declared):
                    if isinstance(nested, dict) and index < len(values):
                        nested["damage"], declaration = values[index]
                        if declaration is not None:
                            nested["declared"] = declaration
        state.total_damage = sum(
            float(entry.get("total_damage", 0.0))
            for entry in state.breakdown.values()
            if isinstance(entry, dict) and not entry.get("informational")
        )

    absorbed = pools.shield_absorbed
    return {
        "shield_absorbed": absorbed,
        "magic_shield_absorbed": pools.magic_absorbed,
        "physical_shield_absorbed": pools.physical_absorbed,
        "general_shield_absorbed": pools.general_absorbed,
        "threshold_shield_absorbed": pools.threshold_absorbed,
        "health_damage": max(0.0, state.total_damage - absorbed),
        "threshold_health_triggered": heal_drip.triggered,
        "threshold_health_cadence_certified": heal_drip.cadence_certified(),
        "threshold_health_heal_ticks": heal_drip.ticks_delivered,
        "threshold_health_expired": (
            threshold_health is not None and threshold_health.expired
        ),
        "threshold_health_bonus_gained": (
            threshold_health.bonus
            if threshold_health is not None and threshold_health.triggered
            else 0.0
        ),
        "target_healing_received": heal_drip.healing_received,
        "target_ending_health": pools.health,
        "target_effective_max_health": pools.max_health,
    }
