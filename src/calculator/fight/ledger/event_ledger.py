"""The engine's certified damage order, reconstructed from its own rows."""

from collections.abc import Mapping
from operator import itemgetter
from typing import Any

from ...ability_atoms import ability_field, ability_payload
from ..cast_control_marker import _declared_cc_marker, _entry_control_scope
from .event_rows import (
    _AUTO_EVENT_FIELDS,
    _EVENT_PHASE_ORDER,
    _NO_EVENT_FIELDS,
    _VAMP_SOURCE_PREFIXES,
    _damage_event_row,
    _row_damage_parts,
    _row_declaration_share,
)


def _ordered_damage_events(
    breakdown: Mapping[str, Any],
    ability_damages: dict[str, dict[str, Any]],
    cast_order: list[str],
    *,
    cast_events: list[dict[str, Any]] | None = None,
    light: bool = False,
    lean: bool = False,
    roster_target_index: int | None = None,
) -> list[Any]:
    """Reconstruct the engine's certified damage order from its own rows.

    Ability rows are split into cast instances and follow the accepted cast
    timeline. Rows with engine-authored ``damage_events`` (autos, per-swing
    on-hit effects, timestamped procs) keep their own event order; item
    effects without authored events retain the coarse phase order after the
    selected rotation. Untyped amplifier rows are distributed across the
    already-known damage composition so shield accounting never invents a
    fourth damage type.

    ``light`` and ``lean`` pick which shape :func:`_damage_event_row` builds
    — the same events in the same ``(time, order, phase, sequence)`` order,
    one shared iteration, and the field list of each shape lives there.
    ``light`` serves the mid-fight consumers (threshold-trigger scans,
    amplifier delta authoring) that never serve the returned ledger
    contract; only the score-only pipeline may ask for ``lean``, because
    public receipts serialize the full rows.

    This ledger is deliberately internal. It is exact at the cast boundary,
    but it does not claim champion-specific spell-shield behavior within a
    multi-hit cast; those target items remain fail-closed until each ability
    supplies the necessary interaction metadata.
    """
    events: list[Any] = []
    sequence = 0
    typed_totals = {"physical": 0.0, "magic": 0.0, "true": 0.0}

    def add(
        source_key: str,
        damage_type: str,
        damage: float,
        *,
        time: float,
        ordinal: int,
        phase: str,
        fields: Mapping[str, Any] = _NO_EVENT_FIELDS,
    ) -> None:
        """Append one row the reconstruction synthesized for a coarse entry."""
        nonlocal sequence
        if damage <= 0 or damage_type not in {"physical", "magic", "true"}:
            return
        typed_totals[damage_type] += damage
        events.append(
            _damage_event_row(
                light,
                lean,
                source_key,
                damage_type,
                damage=damage,
                time=time,
                sequence=sequence,
                order_value=float(sequence),
                phase=phase,
                ordinal=ordinal,
                fields=fields,
                is_ability=source_key in cast_order,
                vamp_source=source_key.startswith(_VAMP_SOURCE_PREFIXES),
                shield_events=None,
            )
        )
        sequence += 1

    def add_declared_events(
        source_key: str,
        entry: Mapping[str, Any],
        *,
        default_phase: str,
    ) -> bool:
        """Append an engine-authored event list, returning whether it existed.

        This is the hot path of ledger reconstruction — module champions
        declare nearly every event.
        """
        nonlocal sequence
        declared_events = entry.get("damage_events")
        if not isinstance(declared_events, list):
            return False
        phase = str(entry.get("event_phase", default_phase))
        if phase not in _EVENT_PHASE_ORDER:
            phase = default_phase
        # Per-entry constants, hoisted out of the per-event loop.
        is_ability_source = source_key in cast_order
        vamp_source = source_key.startswith(_VAMP_SOURCE_PREFIXES)
        shield_events = entry.get("self_shield_events")
        if not isinstance(shield_events, list):
            shield_events = None
        # The delivery facts a row states once for every event it authored.
        # Built only when the row states one, so the hot path stays a read of
        # the event itself; an event that states its own overrides the row's.
        entry_facts = {
            fact: True
            for fact in ("skillshot", "area_damage", "cast_while_disabled")
            if bool(entry.get(fact))
        }
        for ordinal, event in enumerate(declared_events, start=1):
            if not isinstance(event, dict):
                continue
            damage = float(event["damage"])
            damage_type = str(event["damage_type"])
            if damage <= 0 or damage_type not in {"physical", "magic", "true"}:
                continue
            order = event.get("timeline_order")
            typed_totals[damage_type] += damage
            events_append(
                _damage_event_row(
                    light,
                    lean,
                    source_key,
                    damage_type,
                    damage=damage,
                    time=float(event["time"]),
                    sequence=sequence,
                    order_value=float(sequence) if order is None else float(order),
                    phase=phase,
                    ordinal=ordinal,
                    fields=event if not entry_facts else {**entry_facts, **event},
                    is_ability=is_ability_source,
                    vamp_source=vamp_source,
                    shield_events=shield_events,
                )
            )
            sequence += 1
        return True

    events_append = events.append
    # Built on first use: only the no-declared-events fallback below reads
    # it, and module champions declare every event.
    timeline_by_slot: dict[str, list[dict[str, Any]]] | None = None

    last_ability_time = 0.0
    for key in cast_order:
        entry = breakdown.get(key)
        if not entry or entry.get("informational"):
            continue
        casts = max(0, int(entry.get("casts", 0)))
        if casts <= 0:
            continue
        # Champion modules may have emitted a typed event ledger for this
        # ability.  Preserve it (including live target-health metadata)
        # instead of flattening the row back into one aggregate cast value.
        if add_declared_events(key, entry, default_phase="ability"):
            continue
        if timeline_by_slot is None:
            timeline_by_slot = {}
            for cast_event in cast_events or []:
                timeline_by_slot.setdefault(str(cast_event.get("slot", "")), []).append(
                    cast_event
                )
        slot_timeline = timeline_by_slot.get(key, [])
        info = ability_payload(ability_damages, key)
        instances = max(1, int(ability_field(info, "cast_instances")))
        raw_total = float(entry.get("total_raw", 0.0) or 0.0)
        # The control facts belong to the ONE part that authored control, so
        # they are kept apart from the row's shared facts and stamped only on
        # that part's damage type — a two-typed cast must not publish one
        # stun twice.
        authored_parts = tuple(ability_field(info, "parts"))
        cc_scope = _entry_control_scope(info)
        cc_part = next(
            (
                part
                for part in authored_parts
                if part.cc_kind is not None
                and (
                    cc_scope is None
                    or roster_target_index is None
                    or cc_scope.reaches(roster_target_index)
                )
            ),
            None,
        )
        cc_damage_type = cc_part.damage_type if cc_part is not None else None
        cc_fields: dict[str, Any] = {}
        if cc_part is not None:
            durations = [
                float(part.cc_duration)
                for part in authored_parts
                if part.cc_duration > 0.0
            ]
            atoms = tuple(
                atom
                for part in authored_parts
                for atom in part.control_source_atoms
                if isinstance(atom, Mapping)
            )
            cc_fields = {
                "cc_kind": str(cc_part.cc_kind),
                **({"cc_duration": max(durations)} if durations else {}),
                **({"control_source_atoms": atoms} if atoms else {}),
            }
        # An empowering row's lump IS the attack its cast forced (the row
        # already says ``basic_attack``), so it carries the slot's declared
        # control marker — the one ``_author_empowered_swing_events`` lands
        # on the consumed swing when an auto stream exists.  Without it the
        # same reviewed slot certified with the stream on and went coarse
        # with it off.
        cast_fields = {
            **(
                _declared_cc_marker(info, roster_target_index=roster_target_index)
                if info.get("empowers_next_auto")
                else {}
            ),
            "basic_attack": bool(entry.get("basic_attack")),
            "cc_reviewed": bool(info.get("cc_reviewed")),
            "skillshot": bool(entry.get("skillshot")),
            "area_damage": bool(entry.get("area_damage")),
            "cast_while_disabled": bool(entry.get("cast_while_disabled")),
            "raw_damage": (
                raw_total / (casts * instances) if raw_total > 0.0 else None
            ),
        }
        for cast_index in range(casts):
            cast_time = (
                float(slot_timeline[cast_index].get("time", 0.0))
                if cast_index < len(slot_timeline)
                else 0.0
            )
            last_ability_time = max(last_ability_time, cast_time)
            for dtype, amount in _row_damage_parts(entry):
                per_instance = amount / (casts * instances)
                for instance_index in range(instances):
                    add(
                        key,
                        dtype,
                        per_instance,
                        time=cast_time,
                        ordinal=cast_index * instances + instance_index + 1,
                        phase="ability",
                        fields=(
                            cast_fields
                            if dtype != cc_damage_type
                            else {**cast_fields, **cc_fields}
                        ),
                    )

    auto = breakdown.get("auto_attacks")
    if (
        auto
        and not auto.get("informational")
        and not add_declared_events("auto_attacks", auto, default_phase="auto")
    ):
        hits = max(1, int(auto.get("count", 1)))
        for dtype, amount in _row_damage_parts(auto):
            for hit_index in range(hits):
                add(
                    "auto_attacks",
                    dtype,
                    amount / hits,
                    time=last_ability_time,
                    ordinal=hit_index + 1,
                    phase="auto",
                    fields=_AUTO_EVENT_FIELDS,
                )

    skipped = set(cast_order) | {"auto_attacks", "execute"}
    untyped: list[tuple[str, float]] = []
    for key, entry in breakdown.items():
        if key in skipped or entry.get("informational"):
            continue
        if add_declared_events(key, entry, default_phase="effect"):
            continue
        parts = _row_damage_parts(entry)
        if parts:
            # A row with no event list of its own — a proc whose ledger held
            # no certifiable boundary — still has to
            # hand the walk its declaration, or the walk would find a packet
            # stamped as re-priced and nothing to re-price it from.  The row
            # states it once and each synthesized event carries its share
            # (:func:`_row_declaration_share`), so a row that split across
            # damage types cannot hand one declaration to two packets.
            row_total = sum(amount for _, amount in parts)
            for dtype, amount in parts:
                add(
                    key,
                    dtype,
                    amount,
                    time=last_ability_time,
                    ordinal=1,
                    phase="effect",
                    fields={
                        "declared": _row_declaration_share(
                            entry.get("declared"), amount, row_total
                        ),
                        "skillshot": bool(entry.get("skillshot")),
                        "area_damage": bool(entry.get("area_damage")),
                        "cast_while_disabled": bool(entry.get("cast_while_disabled")),
                    },
                )
        else:
            damage = float(entry.get("total_damage", 0.0))
            if damage > 0:
                untyped.append((key, damage))

    # ``typed_totals`` accumulated per add above, in event order.
    # Distribution reads a snapshot so the rows it adds cannot skew a
    # later type's share mid-loop.
    distribution_totals = tuple(typed_totals.items())
    typed_total = (
        typed_totals["physical"] + typed_totals["magic"] + typed_totals["true"]
    )
    if typed_total > 0:
        for key, damage in untyped:
            for dtype, typed_damage in distribution_totals:
                if typed_damage > 0:
                    add(
                        key,
                        dtype,
                        damage * typed_damage / typed_total,
                        time=last_ability_time,
                        ordinal=1,
                        phase="amplifier",
                    )

    # ``_lk`` is the (time, order, phase, sequence) key precomputed at
    # event creation; sorting on it avoids rebuilding the tuple per event
    # for every ledger reconstruction.  Light rows carry the same key as
    # their first element.
    events.sort(key=itemgetter(0) if light else itemgetter("_lk"))
    return events
