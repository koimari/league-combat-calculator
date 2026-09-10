"""Senna's soul count as a receipt ledger."""

from collections.abc import Iterable, Mapping
from typing import Any

from ..config import _seeded_option_stacks
from ..results import RotationResult
from ..state import FightState
from .account import StackEvent, _resource_ledger, _StackAccount


def _add_senna_souls(
    state: FightState,
    rotation: RotationResult,
    shield_outcome: Mapping[str, Any],
    damage_events: Iterable[dict[str, Any]],
) -> None:
    """Add Senna's Absolution Mist soul-counter ledger (P3 package 3W).

    Mist is a PERMANENT pre-fight counter: the seeded ``senna_mist_stacks``
    option prices the stats at parse time (0.75 bonus AD per soul, 20
    range + 10% crit per 20), and the only ACCEPTED live soul event is
    the fight's champion takedown (``target_ending_health <= 0`` — the
    3K-style synthesis shape; one soul from the champion wraith pickup).
    This walk is documentary: it receipts the gains, the every-20
    threshold crossings, and the fail-closed denials into an additive
    ``resource_ledger["mist"]`` (kind "souls") sub-section — the mana
    account is never replaced — and never re-prices any damage.
    """
    if "senna_mist_stacks" not in (state.champion_options):
        # Not a Senna-configured fight: no souls surface at all.
        return
    from ...champions.senna import SENNA_MIST_RULE

    option = state.champion_options
    seeded = _seeded_option_stacks(option, "champion", "Senna", "senna_mist_stacks")
    account = _StackAccount("souls", seeded, 300)
    thresholds: list[dict[str, Any]] = []
    # The accepted soul event: the champion takedown of the modeled target.
    # (A killed target's 0.0 must not fall back to the survived default.)
    raw_ending = shield_outcome.get("target_ending_health")
    target_health = float(raw_ending if raw_ending is not None else 1.0)
    if target_health <= 0.0:
        kill_time = max(
            (float(event["time"]) for event in damage_events),
            default=0.0,
        )
        account.add(
            StackEvent(
                "gain",
                1.0,
                kill_time,
                "champion takedown",
                accepted=True,
                reason="",
                fields={
                    "event": "takedown",
                    "target": shield_outcome.get("target", "target"),
                    "event_time": round(kill_time, 3),
                },
            )
        )
    else:
        account.add(
            StackEvent(
                "gain",
                0.0,
                0.0,
                "champion takedown",
                accepted=False,
                reason="no_takedown_event",
            )
        )
    # Named fail-closed denials for the unsupported soul sources (the
    # module's documented boundaries): the model never authors these
    # events, but a future source must not silently mint souls.
    for source in ("minion_drop", "wraith_farm", "mark_consume"):
        account.add(
            StackEvent(
                "gain",
                0.0,
                0.0,
                f"unsupported_soul_source:{source}",
                accepted=False,
                reason=f"unsupported_soul_source:{source}",
                fields={"event": source, "event_time": 0.0},
            )
        )
    account.add(
        StackEvent(
            "gain",
            0.0,
            0.0,
            "soul_event_without_identity",
            accepted=False,
            reason="missing_identity",
        )
    )

    # Every-20 threshold crossings: documented, never re-priced.
    threshold_value = seeded // 20 * 20
    while threshold_value <= account.current:
        thresholds.append(
            {
                "threshold": threshold_value,
                "threshold_count": threshold_value,
                "range_delta": 20.0,
                "crit_delta": 10.0,
                "bonus_attack_range": 20.0 * (threshold_value // 20),
                "bonus_critical_strike_chance": 10.0 * (threshold_value // 20),
                "stacks_before": max(0, threshold_value - 20),
                "stacks_after": threshold_value,
                "stat_application": "parse_time_seeded",
            }
        )
        threshold_value += 20

    _resource_ledger(rotation)["souls"] = account.ledger_section(
        seeded, thresholds, SENNA_MIST_RULE.public_receipt()
    )
    state.breakdown["mist"] = {
        "name": SENNA_MIST_RULE.public_receipt()["name"],
        "owner": "champion",
        "informational": True,
        "event_phase": "effect",
        "count": account.gains,
        "starting_stacks": seeded,
        "state": f"{seeded} seeded Mist souls; {account.current} at fight end",
        "max_stacks": 300,
        "soul_events": [
            receipt for receipt in account.receipts if receipt["operation"] == "gain"
        ],
        "threshold_transitions": thresholds,
    }
    if account.gains:
        state.notes.append(
            f"Senna Mist: {account.current} souls at fight end ({account.gains} champion "
            f"takedown soul(s) gained over the seeded {seeded})."
        )
    else:
        state.notes.append(
            f"Senna Mist: {account.current} souls (no champion takedown — the "
            "seeded counter is the whole admission; minion drops and "
            "Wraith-farming are named unsupported sources)."
        )
