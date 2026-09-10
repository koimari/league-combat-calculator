"""Bard's chime count."""

from collections.abc import Mapping
from typing import Any

from ...ability_atoms import ability_field, ability_payload, ability_sub_payload
from ..results import RotationResult
from ..state import FightState
from .account import StackEvent, _resource_ledger, _stack_receipt_row


def _add_bard_travelers_call(state: FightState, rotation: RotationResult) -> None:
    """Add Bard's Traveler's Call chime counter + meep ledger (P3 3Y).

    Chimes are a PERMANENT pre-fight counter: the seeded ``chimes``
    option prices the meep math at parse time (30 + 6 per 5 chimes +
    40% AP; the stock/recharge availability breakpoint tables).  The
    model cannot simulate map chime spawning/collection — no engine
    stream — so chime gains are named fail-closed denials.  The only
    ACCEPTED live events the engine prices are the meep-empowered
    autos: each empowered auto consumes one meep from the availability
    pool (stock + floor(duration / recharge) = the on-hit's
    ``max_procs``), booked as an identity-bearing spend.  This walk is
    documentary: it receipts the spends, the availability, and the
    fail-closed denials into an additive ``resource_ledger["chimes"]``
    (kind "chimes") sub-section — the mana account is never replaced —
    and never re-prices any damage.
    """
    if "chimes" not in (state.champion_options):
        return
    from ...champions.bard import (
        _CHIMES_PER_TIER,
        _DEFAULT_CHIMES,
        _MEEP_AP_RATIO,
        _MEEP_BASE,
        _MEEP_PER_TIER,
        _MEEP_RECHARGE_TIERS,
        _MEEP_STOCK_TIERS,
        BARD_TRAVELERS_CALL_RULE,
        _tier_value,
    )

    option = state.champion_options
    try:
        seeded = int(option.get("chimes", _DEFAULT_CHIMES) or _DEFAULT_CHIMES)
    except (TypeError, ValueError):
        seeded = _DEFAULT_CHIMES
    if not (0 <= seeded <= 200):
        seeded = max(0, min(seeded, 200))

    # The availability the engine actually priced at parse time: the P
    # on-hit's max_procs (stock + floor(duration / recharge) when timed).
    on_hit = ability_sub_payload(
        ability_payload(state.ability_damages, "passive"), "on_hit"
    )
    max_procs = ability_field(on_hit, "max_procs", form="on_hit")
    if on_hit.get("name") != "Traveler's Call (Meep)" or not max_procs:
        opening = 0
    else:
        opening = int(max_procs)

    stock = _tier_value(_MEEP_STOCK_TIERS, seeded)
    recharge = _tier_value(_MEEP_RECHARGE_TIERS, seeded)
    recharges = max(0, opening - stock)
    ap = float(state.champion_stats["ability_power"])
    per_meep = (
        _MEEP_BASE + _MEEP_PER_TIER * (seeded // _CHIMES_PER_TIER) + _MEEP_AP_RATIO * ap
    )

    receipts: list[dict[str, Any]] = []
    current = seeded
    consumed = 0

    def _add_receipt(event: StackEvent) -> None:
        nonlocal current, consumed
        before = current
        if event.accepted:
            current -= event.amount
            consumed += 1
        receipts.append(
            _stack_receipt_row(
                "chimes",
                len(receipts) + 1,
                event,
                current_before=before,
                current_after=current,
                maximum=200,
            )
        )

    # The accepted stream: one meep consumed per meep-empowered auto,
    # with the engine's per-swing timestamps as the event identity.
    meep_row = state.breakdown.get("on_hit_ability_passive")
    events: list[Mapping[str, Any]] = []
    if isinstance(meep_row, dict):
        raw = meep_row.get("damage_events")
        if isinstance(raw, list):
            events = [event for event in raw if isinstance(event, dict)]
    if opening > 0 and events:
        for index, event in enumerate(events, start=1):
            event_time = float(event["time"])
            _add_receipt(
                StackEvent(
                    "spend",
                    1.0,
                    event_time,
                    "meep_empowered_auto",
                    accepted=True,
                    reason="",
                    fields={
                        "event": "meep_auto",
                        "event_index": index,
                        "event_time": round(event_time, 3),
                    },
                )
            )
    elif meep_row is None or opening <= 0:
        _add_receipt(
            StackEvent(
                "deny",
                0.0,
                0.0,
                "no_meep_auto_event",
                accepted=False,
                reason="no_meep_auto_event",
            )
        )
    else:
        _add_receipt(
            StackEvent(
                "deny",
                0.0,
                0.0,
                "meep_auto_without_identity",
                accepted=False,
                reason="missing_identity",
            )
        )

    # Named fail-closed denials for the unsupported chime/meep surfaces.
    for source in ("chime_spawn", "chime_collect"):
        _add_receipt(
            StackEvent(
                "deny",
                0.0,
                0.0,
                f"unsupported_chime_source:{source}",
                accepted=False,
                reason="unsupported_chime_source:"
                + source
                + " — the model cannot simulate map chime spawning/collection",
                fields={"event": source, "event_time": 0.0},
            )
        )
    _add_receipt(
        StackEvent(
            "deny",
            0.0,
            0.0,
            "unsupported_meep_effect:slow",
            accepted=False,
            reason="unsupported_meep_effect:slow — the meep slow (25%..75% at 5+ "
            "chimes) is CC with no damage component",
            fields={"event": "meep_slow", "event_time": 0.0},
        )
    )
    _add_receipt(
        StackEvent(
            "deny",
            0.0,
            0.0,
            "unsupported_meep_effect:splash",
            accepted=False,
            reason="unsupported_meep_effect:splash — the 15+ chime splash/cone "
            "never hits the primary target (single-target model)",
            fields={"event": "meep_splash", "event_time": 0.0},
        )
    )
    _add_receipt(
        StackEvent(
            "deny",
            0.0,
            0.0,
            "meep_event_without_identity",
            accepted=False,
            reason="missing_identity",
        )
    )

    availability = {
        "stock": stock,
        "recharge": recharge,
        "max_procs": opening,
        "recharges": recharges,
        "window_seconds": float(state.fight_duration_seconds),
    }

    _resource_ledger(rotation)["chimes"] = {
        "contract": "resource_ledger_v1",
        "owner": "main",
        "kind": "chimes",
        "opening_maximum": 200,
        "opening_current": seeded,
        "closing_maximum": 200,
        "closing_current": current,
        "base_maximum": 200,
        "bonus_maximum": 0,
        "receipts": receipts,
        "availability": availability,
        "threshold_transitions": [
            {
                "chimes": seeded,
                "per_meep_damage": per_meep,
                "stock": stock,
                "recharge_seconds": recharge,
                "stat_application": "parse_time_seeded",
            }
        ],
        "declaration": BARD_TRAVELERS_CALL_RULE.public_receipt(),
    }
    state.breakdown["chimes"] = {
        "name": BARD_TRAVELERS_CALL_RULE.public_receipt()["name"],
        "owner": "champion",
        "informational": True,
        "event_phase": "auto",
        "count": consumed,
        "starting_stacks": seeded,
        "state": f"{seeded} seeded chimes (permanent); {current} at fight end",
        "max_stacks": 200,
        "spend_events": [
            receipt for receipt in receipts if receipt["operation"] == "spend"
        ],
        "availability": availability,
    }
    if consumed:
        state.notes.append(
            f"Bard Meeps: {consumed} meep-empowered auto(s) consumed "
            f"{consumed} of {opening} available ({stock} stock + "
            f"{recharges} recharge); {current} chimes at fight end."
        )
    else:
        state.notes.append(
            "Bard Meeps: no meep-empowered auto (stocked meeps "
            "unconsumed; chime collection is a named unsupported source)."
        )
