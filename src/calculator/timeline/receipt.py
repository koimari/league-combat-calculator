"""The published combat receipt: the sorted ledgers, the audit and the objective fold."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from typing import Any

from ..breakdown_row import breakdown_total_damage
from ..composed_event_row import row_target, row_time
from ..heal_event_row import healed_amount, healed_time
from ..item_behavior import PacketKind
from ..program.views import receipt as _receipt_view
from ..program.walk import ObjectiveFold
from ..survival import BARRIER_GRANT_KINDS, TransitionRank, action_key
from .records import SECONDARY_TARGETING_KINDS, Ledgers, Roster, Walked
from .utility import _utility_outcome_receipt


def _annotate_overheal(healing_events: Iterable[MutableMapping[str, Any]]) -> None:
    """Give every published recovery row the overheal figure it publishes.

    The walk's annotator writes ``overheal`` for a recovery it applied: the
    excess that neither temporary health, Ichorshield nor an overheal shield
    absorbed.  A recovery the walk *skipped* never reaches that line, and
    its published overheal is a different quantity, everything the heal
    would have restored and did not.  Both are the composition's answer, and
    this is the one producer of the second, so no projection computes it.
    """
    for event in healing_events:
        if event.get("overheal") is not None:
            continue
        amount = healed_amount(event)
        event["overheal"] = max(
            0.0,
            float(event.get("reduced_amount", amount))
            - float(event.get("applied_amount", amount)),
        )


def _target_allocation_receipt(
    public_events: Iterable[Mapping[str, Any]],
    target_count: int,
    breakdown_rows: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Prove roster allocation for every authored secondary-target packet."""
    rows = [
        event.get("targeting")
        for event in public_events
        if isinstance(event.get("targeting"), Mapping)
    ]
    rows.extend(
        row.get("targeting")
        for row in breakdown_rows
        if isinstance(row.get("targeting"), Mapping)
    )
    for row in breakdown_rows:
        sources = row.get("sources")
        if not isinstance(sources, list):
            continue
        rows.extend(
            source.get("targeting")
            for source in sources
            if isinstance(source, Mapping)
            and isinstance(source.get("targeting"), Mapping)
        )
    secondary = [
        row for row in rows if str(row.get("kind", "")) in SECONDARY_TARGETING_KINDS
    ]
    missing = [row for row in secondary if row.get("allocated_target_index") is None]
    return {
        "contract": "ordered_roster_target_allocation_v1",
        "target_count": max(0, int(target_count)),
        "secondary_packet_count": len(secondary),
        "allocated_secondary_packet_count": len(secondary) - len(missing),
        "complete": not missing,
        "policy": "roster_index_from_engine_targeting" if secondary else "none",
        "unallocated_reasons": (
            ["secondary packet is missing allocated_target_index"] if missing else []
        ),
    }


def _published_support_phase(event: Mapping[str, Any]) -> TransitionRank:
    """Where one support packet sits in the *published* support list.

    Not :func:`support_transition_rank`: this classifies on kind alone, so a
    ``LATE_BARRIER`` publishes beside the barriers the walk arms it after.
    """
    return (
        TransitionRank.BARRIER_GRANT
        if event.get("kind") in BARRIER_GRANT_KINDS
        else TransitionRank.RECOVERY
    )


# The named receipt for a self-shield rider that never found a carrier
# (docs/self-shield-rebinding.md).  A rider is bound
# to ONE carrier packet by ordinal, in ``fight.ledger.event_rows._damage_event_row``, before
# the ordered survival walk decides which packets land; a rider whose payload
# declares ``rebind_on_ability_hit`` moves to the first ability packet that
# does land (``survival.transitions._rebind_self_shields``).  A refusal that
# survives that means every candidate was blocked, and this receipt says so
# beside the zero rather than leaving the reader to read the zero as a
# mechanic that paid nothing.
SELF_SHIELD_CARRIER_DENIAL = "self_shield_carrier_skipped"


def _self_shield_carrier_denials(
    support_events: Iterable[Mapping[str, Any]],
    damage_events: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Name every self-shield rider whose carriers were all blocked.

    Read-only, post-walk, and deliberately narrow: a rider is named only
    when all three hold.

    1. The rider was refused for a *carrier's* sake, not its own -- the walk
       stamped ``trigger_event_skipped`` (transitions.py's trigger gate),
       which is the one skip reason that means "the packet I was bound to
       did not land".  A rider refused on its own terms (a dead holder, an
       expired window) is a game fact and is left alone.
    2. That carrier packet really is skipped in the published ledger.  The
       cross-check is what keeps the receipt a statement about this fight
       rather than a re-reading of the stamp.
    3. The holder authored at least one in-window ability packet at or
       after the carrier's timestamp and landed none.  A rider that re-binds
       would have taken the first one that landed, so a surviving refusal
       means the holder was blocked through every candidate; the row names
       the last one, which is where the rider gave up.  A holder who
       authored none was never going to be shielded, and a holder who
       landed one is carrying a rider that declared this carrier its only
       one -- neither invents a denial.

    Returns rows in the established ``item_denial`` shape (the section's
    comment in ``program/views/receipt.py`` is the contract: a denial is a
    receipt with no applied amount, published as its own section rather than
    as a zero packet a reader would have to interpret).
    """
    ordered_damage = [
        event
        for event in damage_events
        if isinstance(event, Mapping) and event.get("attacker")
    ]
    # ``_event_id`` is the internal name; the public receipt renames it to
    # ``event_id`` on serialization, and the rider's ``_trigger_event_id``
    # was stamped from the internal one, so the join is on the internal key.
    skipped_by_id = {
        str(event.get("_event_id", "")): event
        for event in ordered_damage
        if event.get("skipped_reason") and event.get("_event_id")
    }
    # Every holder's in-window ability packets in time order, landed or not:
    # one pass here instead of a rescan per rider.  A packet the walk refused
    # ``outside_window`` (transitions.py's first gate) is past the fight's
    # horizon and never reaches a carrier, so it is not a candidate here
    # either.
    ability_packets: dict[str, list[Mapping[str, Any]]] = {}
    for event in ordered_damage:
        if event.get("is_ability") and event.get("skipped_reason") != "outside_window":
            ability_packets.setdefault(str(event["attacker"]), []).append(event)
    for packets in ability_packets.values():
        packets.sort(key=row_time)

    denials: list[dict[str, Any]] = []
    for rider in support_events:
        if not isinstance(rider, Mapping) or not rider.get("_self_shield_rider"):
            continue
        if rider.get("skipped_reason") != "trigger_event_skipped":
            continue
        carrier_id = str(rider.get("_trigger_event_id", ""))
        carrier = skipped_by_id.get(carrier_id)
        if carrier is None:
            continue
        holder = str(rider.get("attacker", ""))
        carrier_time = row_time(carrier)
        candidates = [
            event
            for event in ability_packets.get(holder, ())
            if row_time(event) >= carrier_time
        ]
        if not candidates or any(
            not event.get("skipped_reason") for event in candidates
        ):
            continue
        last_candidate = candidates[-1]
        denials.append(
            {
                "time": round(carrier_time, 3),
                "kind": PacketKind.ITEM_DENIAL.value,
                "source": str(rider.get("source", "")),
                "reason": SELF_SHIELD_CARRIER_DENIAL,
                "attacker": holder,
                "target": str(rider.get("target", holder)),
                "event_id": str(rider.get("_event_id", "")),
                "carrier_event_id": carrier_id,
                "carrier_skipped_reason": str(carrier.get("skipped_reason", "")),
                "last_candidate_event_id": str(last_candidate.get("_event_id", "")),
                "last_candidate_skipped_reason": str(
                    last_candidate.get("skipped_reason", "")
                ),
                "withheld_amount": round(float(rider.get("amount", 0.0) or 0.0), 3),
            }
        )
    return denials


def _compose_receipt(
    focus_id: str, roster: Roster, ledgers: Ledgers, walked: Walked
) -> dict[str, Any]:
    """Sort, audit and publish the composed timeline as one combat receipt."""
    focus_row = next(
        (row for row in walked.public_breakdown if row["participant_id"] == focus_id),
        None,
    )
    focus_support = sum(
        float(event.get("applied_amount", 0.0))
        for events in ledgers.support_effects.values()
        for event in events
        if event.get("attacker") == focus_id
    )
    focus_healing = sum(
        float(event.get("applied_amount", 0.0))
        for event in ledgers.healing.get(focus_id, [])
    )
    public_events = sorted(
        (event for events in ledgers.outgoing.values() for event in events),
        key=lambda event: event.get("_sk")
        or action_key(
            row_time(event),
            (
                TransitionRank.REACTIVE
                if event.get("_reactive")
                else TransitionRank.DAMAGE
            ),
            row_target(event),
            event,
        ),
    )
    public_healing_events = sorted(
        (event for events in ledgers.healing.values() for event in events),
        key=lambda event: event.get("_sk")
        or action_key(
            healed_time(event),
            TransitionRank.RECOVERY,
            str(event.get("attacker", "")),
            event,
        ),
    )
    _annotate_overheal(public_healing_events)
    public_support_events = sorted(
        (event for events in ledgers.support_effects.values() for event in events),
        key=lambda event: (
            float(event.get("time", 0.0)),
            _published_support_phase(event),
            str(event.get("target", "")),
            str(event.get("attacker", "")),
            str(event.get("_event_id", "")),
        ),
    )
    # D-VI-1, audited here because this is the first point at which BOTH
    # resolved ledgers exist: the walk has stamped every skip, and nothing
    # downstream can still change which packets landed.  Read-only -- it
    # adds receipts and moves no number.
    ledgers.item_denial_receipts.extend(
        _self_shield_carrier_denials(public_support_events, public_events)
    )
    support_by_actor = {
        actor.participant_id: [
            event
            for event in public_support_events
            if event.get("attacker") == actor.participant_id
        ]
        for actor in roster.all_actors
    }
    outgoing_by_actor = {
        actor.participant_id: [
            event
            for event in public_events
            if event.get("attacker") == actor.participant_id
        ]
        for actor in roster.all_actors
    }
    utility_by_actor = {
        actor.participant_id: _utility_outcome_receipt(
            actor,
            support_by_actor[actor.participant_id],
            outgoing_by_actor[actor.participant_id],
        )
        for actor in roster.all_actors
    }
    # Every aggregate the objective block publishes, summed once here.  The
    # TDD view republishes them at their declared precisions and adds
    # nothing: a view that sums is a second producer of the total it claims
    # to project, which is the incident's own shape at the aggregate.
    objective = ObjectiveFold(
        main_team_damage_before_death=sum(
            row["total_damage"]
            for row in walked.public_breakdown
            if row["team"] in {"main", "ally"}
        ),
        enemy_team_damage_before_death=sum(
            row["total_damage"]
            for row in walked.public_breakdown
            if row["team"] == "enemy"
        ),
        surviving_main_team=sum(
            1
            for actor in roster.all_actors
            if actor.team in {"main", "ally"}
            and walked.survival[actor.participant_id]["survived_window"]
        ),
        focus_damage_before_death=(
            float(breakdown_total_damage(focus_row)) if focus_row else 0.0
        ),
        focus_support_value=focus_support,
        focus_healing=focus_healing,
        main_team_effective_health=sum(
            float(walked.survival[actor.participant_id]["effective_health"])
            for actor in roster.all_actors
            if actor.team in {"main", "ally"}
        ),
        enemy_team_effective_health=sum(
            float(walked.survival[actor.participant_id]["effective_health"])
            for actor in roster.all_actors
            if actor.team == "enemy"
        ),
        total_support_value=sum(walked.support_by_attacker.values()),
        total_healing_reduced=sum(
            float(state["healing_reduced"]) for state in walked.survival.values()
        ),
    )
    return _receipt_view.receipt(
        walked.program,
        walked.result.projected(
            damage_events=public_events,
            healing_events=public_healing_events,
            support_events=public_support_events,
            utility_by_actor=utility_by_actor,
            target_allocation=_target_allocation_receipt(
                public_events, len(roster.enemy_actors), walked.public_breakdown
            ),
            item_denial_receipts=ledgers.item_denial_receipts,
            objective=objective,
        ),
    )
