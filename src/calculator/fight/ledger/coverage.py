"""Which rows the engine calls certified, and why the rest are coarse."""

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from ... import item_effects
from ...ability_atoms import ability_field, ability_payload
from ...interpreters import ally_packet, threshold_defense
from ...item_behavior import PacketKind, PacketTrigger, Recipients
from ...survival.actions import event_timestamp
from ...trigger_stream import Stream, authored_triggers
from ..state import FightState


def _event_timeline_coverage(
    breakdown: Mapping[str, Any],
    ability_damages: dict[str, dict[str, Any]],
    cast_order: list[str],
    *,
    num_auto_attacks: int = 0,
    lean: bool = False,
) -> dict[str, Any]:
    """Certify which active rows have authored or cast-boundary ordering.

    This is the one definition of "certified": rows whose damage rides
    the ambient auto stream (``requires_auto_timeline_coupling``) are
    downgraded here — not by consumers — so the fight report and
    window-sum effects can never disagree about the same source.
    """
    exact: list[str] = []
    coarse: list[str] = []
    cast_keys = set(cast_order)
    for key, entry in breakdown.items():
        if entry.get("withheld_reason"):
            coarse.append(key)
            continue
        if entry.get("informational") or float(entry.get("total_damage", 0.0)) <= 0:
            continue
        damage_events = entry.get("damage_events")
        # One pass computes the authored total (in list order) and the
        # cast-boundary downgrade together.
        event_total = None
        has_boundary = False
        if isinstance(damage_events, list) and damage_events:
            event_total = 0.0
            for event in damage_events:
                event_total += float(event["damage"])
                if (
                    not has_boundary
                    and isinstance(event, dict)
                    and str(event.get("event_precision", "")) == "cast_boundary"
                ):
                    has_boundary = True
        if has_boundary:
            coarse.append(key)
            continue
        if event_total is not None and math.isclose(
            event_total,
            float(entry["total_damage"]),
            rel_tol=1e-9,
            abs_tol=1e-6,
        ):
            exact.append(key)
            continue
        if key in cast_keys and int(entry.get("casts", 0)) > 0:
            info = ability_payload(ability_damages, key)
            if float(ability_field(info, "dot_duration")) > 0:
                coarse.append(key)
            else:
                exact.append(key)
            continue
        coarse.append(key)
    complete = not coarse
    coupled_auto_sources = {
        key
        for key, info in ability_damages.items()
        if info.get("requires_auto_timeline_coupling")
        and num_auto_attacks > 0
        and int(breakdown.get(key, {}).get("casts", 0)) > 0
    }
    if lean:
        # Score-mode consumers only ever combine coverages by set union
        # (combine_timeline_coverages); the certification strings, notes,
        # and per-fight sorting never survive that, so skip building them.
        if coupled_auto_sources:
            return {
                "complete": False,
                "exact_sources": list(set(exact) - coupled_auto_sources),
                "coarse_sources": list(set(coarse) | coupled_auto_sources),
            }
        return {
            "complete": complete,
            "exact_sources": exact,
            "coarse_sources": coarse,
        }
    coverage = {
        "complete": complete,
        "certification": (
            "event_order_certified" if complete else "partial_event_order"
        ),
        "exact_sources": sorted(exact),
        "coarse_sources": sorted(coarse),
        "note": (
            "Every active damage source has authored event or cast-boundary order."
            if complete
            else (
                f"{len(coarse)} active damage source"
                f"{' uses' if len(coarse) == 1 else 's use'} coarse phase ordering."
            )
        ),
    }
    if coupled_auto_sources:
        coverage["complete"] = False
        coverage["certification"] = "partial_event_order"
        coverage["exact_sources"] = sorted(
            set(coverage["exact_sources"]) - coupled_auto_sources
        )
        coverage["coarse_sources"] = sorted(
            set(coverage["coarse_sources"]) | coupled_auto_sources
        )
        names = ", ".join(sorted(coupled_auto_sources))
        coverage["note"] = (
            f"{names} modifies attacks on the ambient auto stream; its bonus "
            "damage is included, but per-hit auto coupling is not yet "
            "event-order certified."
        )
    return coverage


def _control_armed_holder_shields(
    items: Iterable[dict[str, Any]],
) -> tuple[ally_packet.AllyPacketSlot, ...]:
    """Every producer this build declares that the pair engine owes proof of.
    The shape, not the item: a shield the *holder* receives when a control
    event lands.  Each clause excludes a live producer that would otherwise
    arrive here: Bandlepipes' Fanfare is armed by the same trigger but
    delivers movement, Imperial Mandate's Command delivers to the triggering
    enemy, and Knight's Vow's Sacrifice shields the holder off a different
    trigger.  A pair fight prices a holder-side shield itself, so it is the
    one that must prove the control event happened; every other producer is
    delivered by the roster walk, which certifies its own."""
    return tuple(
        slot
        for slots in ally_packet.resolve_slots(
            [item_effects.resolved_item_name(item) for item in items]
        ).values()
        for slot in slots
        if slot.trigger is PacketTrigger.CROWD_CONTROL
        and slot.emits(PacketKind.SHIELD, Recipients.SELF)
    )


def _control_armed_event_coverage(
    items: list[dict[str, Any]],
    damage_events: list[dict[str, Any]],
    control_events: list[dict[str, Any]] | None = None,
    *,
    is_melee: bool = False,
) -> tuple[bool, str, str, str]:
    """Certify a control-armed holder shield against the proc's own trigger.

    Everlasting — the one such producer declared today — is not a generic
    "ability hit" proc.  The Wiki limits it to an immobilize, or a slow for a
    melee holder, and its shield lands after that authored cast.  Which
    authored control arms it is therefore the mechanic's own question, and
    the certificate names the event that answered it: the predicate here is
    :attr:`interpreters.ally_packet.AllyPacketSlot.control_arming`, the same
    ``state_lifecycle.CcTriggerRule`` the roster walk grants the shield
    through, read against the same raw rows.  A reviewed ``"none"`` row is
    not a candidate for it — that is the reviewed absence of control, which
    is evidence the proc did NOT arm — so it can never be the certificate.

    A row nobody reviewed is the refusal: it may carry the immobilize that
    arms the shield or no control at all, and the ledger cannot say which.
    The refusal names the declaration it came from: the receipt token is the
    rule's own ``mechanic_id`` and the note is built from the holder and the
    producer, so a second such producer is reported as itself rather than
    under the first one's name.
    """
    # An ability that carries its control on a ``control_events`` row rather
    # than on a damage packet is the same evidence, so both ledgers feed one
    # scan: a reviewed control row certifies the cast that authored it.
    rows = [
        row
        for row in (*damage_events, *(control_events or ()))
        if isinstance(row, Mapping)
    ]
    ledger = {"damage_events": rows}
    armed_by = ""
    for slot in _control_armed_holder_shields(items):
        rule = slot.control_arming
        for row in rows:
            branch = rule.match(row, is_melee=is_melee)
            if branch and not armed_by:
                armed_by = (
                    f"{slot.owner} — "
                    f"{slot.producer.value.replace('_', ' ').title()} armed by "
                    f"{row.get('source') or row.get('source_key')} ({branch}) at "
                    f"{round(event_timestamp(row), 3)}s"
                )
                break
        # The sixth control-reading site, on the bus.  ``cc_reviewed`` on a
        # Trigger holds when the row carries a vocabulary ``cc_kind``,
        # including the reviewed-no-CC ``"none"``, which narrows nothing and
        # is never a live control kind.  A tuple ledger's positional rows
        # classify as nothing at all, which is the silence the ``isinstance``
        # filter produces.
        unreviewed = [
            trigger
            for trigger in authored_triggers(
                ledger,
                streams=frozenset({Stream.DAMAGE}),
                holder=slot.owner,
            )
            if trigger.is_ability and not trigger.cc_reviewed
        ]
        if not unreviewed:
            continue
        return (
            False,
            slot.rule.mechanic_id.replace(".", "_"),
            f"{slot.owner}'s {slot.producer.value.replace('_', ' ').title()} "
            "arms on an authored immobilize/slow, and "
            f"{sorted({str(trigger.source_key) for trigger in unreviewed})} "
            "reached the ledger with no reviewed crowd-control state.",
            armed_by,
        )
    return True, "", "", armed_by


def _resolve_timeline_coverage(
    state: FightState,
    items: list[dict[str, Any]],
    damage_events: Sequence[Any],
    control_events: Sequence[Any],
    shield_outcome: Mapping[str, Any],
    *,
    threshold_health_heal: float,
    score_only: bool,
) -> dict[str, Any]:
    """What this fight certifies about its own event order, and what it does not.

    Two downgrades ride the certification the row survey produces: an
    authored control the holder's shield arms, and a target-side Lifeline
    heal whose declaration subdivides its window into no ticks at all.
    """
    coverage = _event_timeline_coverage(
        state.breakdown,
        state.ability_damages,
        state.cast_order,
        num_auto_attacks=state.num_auto_attacks,
        lean=score_only,
    )
    control_complete, control_source, control_note, control_armed_by = (
        _control_armed_event_coverage(
            items,
            damage_events,
            control_events,
            is_melee=bool(state.is_melee),
        )
    )
    if control_armed_by:
        # Which authored control armed the holder's shield, named. The
        # roster walk grants it; this is the pair ledger's receipt that the
        # event it grants on is in here, at that instant.
        coverage["control_armed_by"] = control_armed_by
    if not control_complete:
        coverage["complete"] = False
        coverage["certification"] = "partial_event_order"
        coverage["coarse_sources"] = sorted(
            set(coverage["coarse_sources"]) | {control_source}
        )
        coverage["note"] = control_note
    if (
        threshold_health_heal > 0
        and shield_outcome["threshold_health_triggered"]
        and not shield_outcome["threshold_health_cadence_certified"]
    ):
        # The target-side Lifeline downgrade, measured: it fires when the
        # declaration subdivides the sourced window into no ticks at all, so
        # the heal's timing is a total rather than a schedule.  A declared
        # cadence certifies the timeline instead.
        coverage["complete"] = False
        coverage["certification"] = "partial_event_order"
        coverage["coarse_sources"] = sorted(
            set(coverage["coarse_sources"])
            | {threshold_defense.threshold_health_coverage_source()}
        )
        coverage["note"] = (
            f"{threshold_defense.threshold_health_owner()}'s sourced total "
            "healing is spread over its window; its declaration authors no "
            "heal tick cadence to certify that timing against."
        )
    return coverage
