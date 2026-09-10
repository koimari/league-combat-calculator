"""The self state windows a champion module authors, expanded over its accepted cast times."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from .support_scan import _sourced_cast_time
from .survival.classify import SUPPORT_RANK_KEY
from .survival.phases import TransitionRank

_SELF_STATE_EVENT_KINDS = frozenset(
    {
        "spell_shield",
        "stasis",
        "invulnerability",
        "untargetable",
        "crowd_control",
        # A timed self damage-reduction window (Briar E charge).  The typed
        # fields the survival kernel reads ride the emitted event verbatim.
        "damage_modifier",
    }
)


def derive_self_state_effects(
    ability_damages: Mapping[str, Any],
    cast_timeline: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Expand module-authored self state atoms over accepted cast times.

    A state packet is authored by a named champion module.  The cast
    timeline supplies the only valid time for that packet.  Unknown kinds,
    invalid durations, and missing sources fail closed at the atom boundary.
    """
    effects: list[dict[str, Any]] = []
    for slot, entry in ability_damages.items():
        if not isinstance(entry, Mapping):
            continue
        raw_events = entry.get("self_state_events")
        if raw_events is None:
            continue
        if not isinstance(raw_events, list):
            raise ValueError(f"{slot} self_state_events must be a list")
        casts = [
            cast
            for cast in cast_timeline
            if isinstance(cast, Mapping) and str(cast.get("slot", "")) == str(slot)
        ]
        for cast_index, cast in enumerate(casts):
            cast_time = _sourced_cast_time(cast, slot=str(slot))
            for state_index, raw_event in enumerate(raw_events):
                if not isinstance(raw_event, Mapping):
                    raise ValueError(
                        f"{slot} self_state_events[{state_index}] must be an object"
                    )
                kind = str(raw_event.get("kind", ""))
                if kind not in _SELF_STATE_EVENT_KINDS:
                    raise ValueError(
                        f"{slot} self state kind {kind!r} is not supported"
                    )
                try:
                    duration = float(raw_event["duration"])
                    time_offset = float(raw_event.get("time_offset", 0.0) or 0.0)
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(
                        f"{slot} self state event needs numeric duration and offset"
                    ) from exc
                if not math.isfinite(duration) or duration <= 0.0:
                    raise ValueError(f"{slot} self state duration must be positive")
                if not math.isfinite(time_offset):
                    raise ValueError(f"{slot} self state time_offset must be finite")
                source = str(raw_event.get("source", ""))
                if not source:
                    raise ValueError(f"{slot} self state source is required")
                event = {
                    "time": cast_time + time_offset,
                    "kind": kind,
                    "duration": duration,
                    "source": source,
                    "source_key": str(slot),
                    "slot": str(slot),
                    "target_self": True,
                    "target_scope": "self",
                    "rank": entry.get("rank", 0),
                    "_event_id": f"self_state:{slot}:{cast_index}:{state_index}",
                }
                for field in (
                    "on_block_heal_amount",
                    "on_block_heal_delay",
                    "on_block_heal_source",
                ):
                    if field in raw_event:
                        event[field] = raw_event[field]
                # Atom receipts authored by the champion module (Sivir E:
                # duration + Heal atoms) ride the arm packet so the kernel
                # contract and the public receipt can prove the source.
                if "source_atoms" in raw_event:
                    atoms = raw_event["source_atoms"]
                    if not isinstance(atoms, list) or not all(
                        isinstance(atom, Mapping) for atom in atoms
                    ):
                        raise ValueError(
                            f"{slot} self state source_atoms must be a list "
                            "of atom objects"
                        )
                    event["source_atoms"] = [dict(atom) for atom in atoms]
                # Timed damage modifiers carry their typed kernel fields
                # (multiplier, all_sources, damage_reduction, persistent,
                # next_event_only, owner/source routing, resistance
                # reduction) plus the source-atom receipts so the public
                # support receipt can prove where each number came from.
                # Invalid numeric payloads fail closed at the atom boundary
                # exactly like a missing duration or source.
                for field in (
                    "multiplier",
                    "amount",
                    "armor_reduction_percent",
                    "mr_reduction_percent",
                ):
                    if field in raw_event:
                        try:
                            number = float(raw_event[field])
                        except (TypeError, ValueError) as exc:
                            raise ValueError(
                                f"{slot} self state {field} must be numeric"
                            ) from exc
                        if not math.isfinite(number):
                            raise ValueError(
                                f"{slot} self state {field} must be finite"
                            )
                        event[field] = number
                # The arm rank a module declares when its kind does
                # not decide it (Briar's E reduction is an aura, not
                # a triggered debuff).  A member of the closed
                # vocabulary or nothing: an author may choose a rank,
                # never invent an ordering.
                if SUPPORT_RANK_KEY in raw_event:
                    try:
                        event[SUPPORT_RANK_KEY] = TransitionRank(
                            raw_event[SUPPORT_RANK_KEY]
                        )
                    except ValueError as exc:
                        raise ValueError(
                            f"{slot} self state {SUPPORT_RANK_KEY} must be "
                            "a TransitionRank member"
                        ) from exc
                for field in (
                    "all_sources",
                    "damage_reduction",
                    "persistent",
                    "next_event_only",
                    "owner",
                    "source_participant",
                    "resistance_type",
                    # D-04: a damage_modifier names its classes on the
                    # module entry; the kernel refuses an empty declaration.
                    "damage_classes",
                    "attack_classes",
                ):
                    if field in raw_event:
                        event[field] = raw_event[field]
                if "source_atoms" in raw_event:
                    atoms = raw_event["source_atoms"]
                    if not isinstance(atoms, list) or not all(
                        isinstance(atom, Mapping) for atom in atoms
                    ):
                        raise ValueError(
                            f"{slot} self state source_atoms must be a list of atoms"
                        )
                    event["source_atoms"] = [dict(atom) for atom in atoms]
                effects.append(event)
    return sorted(
        effects,
        key=lambda event: (
            float(event["time"]),
            str(event["source_key"]),
            str(event["_event_id"]),
        ),
    )
