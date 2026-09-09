"""Heimerdinger's W and E charge counters."""

from collections.abc import Mapping
from typing import Any

from ..results import RotationResult
from ..state import FightState
from .account import StackEvent, _resource_ledger, _StackAccount


def _add_heimerdinger_w_e(state: FightState, rotation: RotationResult) -> None:
    """Add Heimerdinger's W/E multi-part receipts (P3 3Z).

    W (Hextech Micro-Rockets) prices one first rocket + (n-1)
    subsequent rockets against the champion target from the degraded
    explicit rows; E (CH-2/CH-3X Electron Storm Grenade) prices ONE
    champion damage instance per cast.  The unsupported multi-target
    claims — the W rocket fan spread, the E grenade bounces, the
    stun/slow control, turret targeting/beam charge, and the R-upgraded
    W swarm (half-parsed W[1] rows) — are named fail-closed denials:
    the model never invents multi-target damage.  This walk is
    documentary: it receipts the engine-priced parts (the per-event
    damage_events identity) and the denials into an additive
    ``resource_ledger["w_e"]`` (kind "w_e") sub-section — the mana
    account is never replaced — and never re-prices any damage.
    """
    if "w_rockets" not in (state.champion_options) and "e_upgrade" not in (
        state.champion_options
    ):
        return
    from ...champions.heimerdinger import (
        HEIMER_E_GRENADE_RULE,
        HEIMER_W_ROCKETS_RULE,
    )

    account = _StackAccount("w_e", 0.0, 0, counting=False)
    # The accepted stream: the engine-priced W/E parts, one receipt per
    # damage_event (the swing/impact identity), amounts = the raw values.
    for slot in ("W", "E"):
        row = state.breakdown.get(slot)
        events: list[Mapping[str, Any]] = []
        if isinstance(row, dict):
            raw = row.get("damage_events")
            if isinstance(raw, list):
                events = [event for event in raw if isinstance(event, dict)]
        if events:
            for index, event in enumerate(events, start=1):
                event_time = float(event["time"])
                account.add(
                    StackEvent(
                        "hit",
                        float(event.get("raw_damage", 0.0)),
                        event_time,
                        f"{slot.lower()}_part",
                        accepted=True,
                        reason="",
                        fields={
                            "event": f"{slot.lower()}_part",
                            "event_index": index,
                            "event_time": round(event_time, 3),
                        },
                    )
                )
        elif row is None:
            account.add(
                StackEvent(
                    "deny",
                    0.0,
                    0.0,
                    f"{slot}_unavailable",
                    accepted=False,
                    reason=f"{slot}_unavailable — no {slot} cast in this fight",
                )
            )
        else:
            account.add(
                StackEvent(
                    "deny",
                    0.0,
                    0.0,
                    f"{slot}_part_without_identity",
                    accepted=False,
                    reason="missing_identity",
                )
            )

    # Named fail-closed denials for the unsupported multi-target claims.
    for source, reason in (
        (
            "rocket_fan_multi_target",
            "unsupported_claim:rocket_fan_multi_target — the W rocket "
            "fan can spread across multiple targets; the model prices "
            "ONE champion target (fail-closed)",
        ),
        (
            "grenade_bounce",
            "unsupported_claim:grenade_bounce — the E grenade bounces "
            "can hit multiple enemies; the model prices ONE champion "
            "damage instance per cast (fail-closed)",
        ),
        (
            "grenade_control",
            "unsupported_claim:grenade_control — the E stun/slow "
            "control is state/utility, not direct champion damage",
        ),
        (
            "turret_targeting",
            "unsupported_claim:turret_targeting — turret targeting and "
            "beam charge are utility; the turret damage is the Q entry",
        ),
        (
            "upgraded_w_swarm",
            "unsupported_claim:upgraded_w_swarm — the R-upgraded "
            "Hextech Rocket Swarm (W[1] rows) is not priced; R is an "
            "empowerment toggle (fail-closed)",
        ),
    ):
        account.add(
            StackEvent(
                "deny",
                0.0,
                0.0,
                source,
                accepted=False,
                reason=reason,
                fields={"event": source, "event_time": 0.0},
            )
        )
    account.add(
        StackEvent(
            "deny",
            0.0,
            0.0,
            "w_e_event_without_identity",
            accepted=False,
            reason="missing_identity",
        )
    )

    _resource_ledger(rotation)["w_e"] = {
        "contract": "resource_ledger_v1",
        "owner": "main",
        "kind": "w_e",
        "opening_maximum": 0,
        "opening_current": 0,
        "closing_maximum": 0,
        "closing_current": 0,
        "base_maximum": 0,
        "bonus_maximum": 0,
        "receipts": account.receipts,
        "declaration": {
            "rockets": HEIMER_W_ROCKETS_RULE.public_receipt(),
            "grenade": HEIMER_E_GRENADE_RULE.public_receipt(),
        },
    }
