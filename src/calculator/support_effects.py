"""Sourced ally-targeted shields/heals from champion ability packets."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .capabilities import SUPPORT_TARGET_RESOLUTION_SCOPES
from .champions.slot_extract import extract_named
from .support_bailout import _bailout_denial_rows, _bailout_ramp_metadata
from .support_champion_packets import (
    _morgana_black_shield_metadata,
    _nami_return_bounce_packet,
    _target_max_health_shield_metadata,
    _target_missing_health_heal_metadata,
    _yuumi_best_friend_packet,
    _yuumi_conversion_shield_packet,
)
from .support_row_metadata import (
    _caster_as_recipient,
    _invulnerability_timing_metadata,
    _shield_duration_metadata,
    _slot_rank,
    _slot_rows,
    recipient_max_health_ratio,
)
from .support_scan import (
    _SCOPE_OVERRIDES,
    _SUPPORT_BUFF_SLOTS,
    _SUPPORT_SLOTS,
    _SUPPORT_STATE_SLOTS,
    _ability,
    _has_support_attributes,
    _sourced_cast_time,
    _support_profile,
)

# ---------------------------------------------------------------------------
# Wave-2 champion follow-up packets (HANDOVER 8.5): sourced bounce and
# best-friend riders that ride the base scanner packet of the same cast.
# Every number comes from the cached leveling rows / typed atoms below; the
# two prose coefficients are quoted from the cached descriptions with the
# same documentation style as healing.py's E1 rules and renata_glasc.py.
# ---------------------------------------------------------------------------


def derive_ally_effects(
    champion_data: dict[str, Any],
    level: int,
    stats: dict[str, float],
    cast_timeline: Iterable[dict[str, Any]],
    *,
    ability_ranks: dict[str, int] | None = None,
    champion_options: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return explicit shield/heal packets and their sourced cast times.

    The timeline has no player cursor/target selection, so packets carry a
    sourced target scope for the coupled resolver to apply deterministically:
    ``self``, one selected teammate, or all selected teammates.  A missing
    scope is never silently treated as an area effect.
    """
    champion_name = str(champion_data.get("name", ""))
    if not _has_support_attributes(champion_data) and not any(
        (champion_name, slot) in _SUPPORT_STATE_SLOTS | _SUPPORT_BUFF_SLOTS
        for slot in ("Q", "W", "E", "R")
    ):
        return []
    effects: list[dict[str, Any]] = []
    requested_ranks = ability_ranks or {}
    options = champion_options or {}
    for slot in _SUPPORT_SLOTS:
        ability = _ability(champion_data, slot)
        if not ability:
            continue
        rank = _slot_rank(champion_data, slot, level, requested_ranks)
        if rank < 1:
            continue
        champion_key = (champion_name, slot)
        rows = _slot_rows(champion_name, slot, ability)
        shield_row = next((row for row in rows if row.kind == "shield"), None)
        heal_row = next((row for row in rows if row.kind == "heal"), None)
        target_self, target_scope = False, ""
        if champion_key in _SUPPORT_STATE_SLOTS | _SUPPORT_BUFF_SLOTS:
            # These two branches grant a packet that no leveling row
            # declares, so their recipient comes from the slot's own profile
            # and its sourced override rather than from a row's own
            # sentence.  Fail closed at the emitter: a typo or
            # novel scope must name the champion+slot at the source instead
            # of silently redirecting the packet to teammate zero in the
            # coupled resolver.  A row's own scope is checked in
            # ``_slot_rows``.
            _, _, target_self, target_scope, _ = _support_profile(ability)
            target_scope = _SCOPE_OVERRIDES.get(champion_key, target_scope)
            if target_scope not in SUPPORT_TARGET_RESOLUTION_SCOPES:
                raise ValueError(
                    "Unsupported support target_scope "
                    f"{target_scope!r} for {champion_name} {slot} "
                    f"from source {ability.get('name', slot)!r}; supported "
                    f"scopes: {sorted(SUPPORT_TARGET_RESOLUTION_SCOPES)}"
                )
        if champion_key in _SUPPORT_STATE_SLOTS:
            timing_metadata = _invulnerability_timing_metadata(champion_data, slot)
            casts = [event for event in cast_timeline if event.get("slot") == slot]
            for cast_index, cast in enumerate(casts):
                cast_time = _sourced_cast_time(cast, slot=slot)
                effects.append(
                    {
                        "time": cast_time + timing_metadata["activation_delay"],
                        "kind": "invulnerability",
                        "duration": timing_metadata["duration"],
                        "activation_delay": timing_metadata["activation_delay"],
                        "source": (f"{ability.get('name', slot)} · Invulnerability"),
                        "slot": slot,
                        "target_self": True,
                        "target_scope": target_scope,
                        "rank": rank,
                        "target_selection_key": f"state:{slot}:{cast_index}",
                        **timing_metadata,
                    }
                )
            continue
        if champion_key in _SUPPORT_BUFF_SLOTS:
            # P1-Renata-W: one ramping stat-buff packet per accepted cast.
            # The scope is the sourced self-or-one-ally cast, so a roster
            # fight resolves the selected teammate and a solo fight falls
            # back to the caster (``target_self``).
            ramp = _bailout_ramp_metadata(champion_data, ability, rank, stats)
            for cast_index, cast in enumerate(
                [event for event in cast_timeline if event.get("slot") == slot]
            ):
                cast_time = _sourced_cast_time(cast, slot=slot)
                selection_key = f"buff:{slot}:{cast_index}"
                effects.append(
                    {
                        "time": cast_time,
                        "kind": "stat_buff",
                        "amount": 0.0,
                        "source": f"{ability.get('name', slot)} · Chemtech Formula",
                        "slot": slot,
                        "target_self": target_self,
                        "target_scope": target_scope,
                        "rank": rank,
                        "target_selection_key": selection_key,
                        **ramp,
                    }
                )
                # The same cast's lethal-damage half is withheld: publish
                # its named denial beside the buff so the covered
                # participant's survival row is never read as complete.
                effects.extend(
                    _bailout_denial_rows(
                        ramp,
                        time=cast_time,
                        target_self=target_self,
                        target_scope=target_scope,
                        target_selection_key=selection_key,
                    )
                )
            continue
        if shield_row is None and heal_row is None:
            continue
        casts = [event for event in cast_timeline if event.get("slot") == slot]
        for cast_index, cast in enumerate(casts):
            # Validate every authored support cast, even when its resolved
            # packet is zero or intentionally omitted (for example, a
            # per-tick heal without a complete cadence).
            _sourced_cast_time(cast, slot=slot)
            if shield_row is not None:
                shield_attr = shield_row.attribute
                # The amount is resolved, never taken from the metadata's
                # placeholder: a recipient-scaled row is narrowed to the one
                # recipient the scan holds stats for, so it is PRICED against
                # the caster and granted to him alone.  The metadata's atom
                # receipt rides along, but its ``amount`` of 0.0 would
                # publish the zero this row is meant to be priced or refused
                # instead of.
                amount_metadata = {
                    key: value
                    for key, value in _target_max_health_shield_metadata(
                        champion_data, ability, slot, shield_attr, rank=rank
                    ).items()
                    if key != "amount"
                }
                amount = extract_named(
                    ability,
                    shield_attr,
                    rank,
                    stats,
                    _caster_as_recipient(stats) if shield_row.recipient_scaled else {},
                )
                shield_scope = shield_row.target_scope
                shield_self = shield_row.target_self
                if amount > 0:
                    event = {
                        "time": _sourced_cast_time(cast, slot=slot),
                        "kind": "shield",
                        "amount": float(amount),
                        "source": f"{ability.get('name', slot)} · {shield_attr}",
                        "slot": slot,
                        "target_self": shield_self,
                        "target_scope": shield_scope,
                        "rank": rank,
                        "target_selection_key": f"shield:{slot}:{cast_index}",
                        **amount_metadata,
                    }
                    if shield_row.recipient_max_health:
                        # The amount above is the CASTER's copy.  The ratio
                        # rides the packet so the composition can price each
                        # other recipient off their own maximum health.
                        event["recipient_max_health_ratio"] = (
                            recipient_max_health_ratio(ability, shield_attr, rank)
                        )
                    if shield_attr == "Magic Shield Strength":
                        event["shield_pool"] = "magic"
                    if champion_key == ("Morgana", "E"):
                        event.update(
                            _morgana_black_shield_metadata(
                                champion_data, ability, rank, stats
                            )
                        )
                    else:
                        event.update(_shield_duration_metadata(champion_data, slot))
                    effects.append(event)
            # A module or healing-rule authored heal slot is the
            # exact receipt (level-indexed bases, missing-health terms, and a
            # dragon-form gate the scanner cannot see).  ``_slot_rows`` has
            # already dropped those rows, together with a per-tick row whose
            # cadence is not authored and a ``Heal``-named row whose sentence
            # heals nobody.
            if heal_row is not None:
                heal_attr = heal_row.attribute
                cast_time = _sourced_cast_time(cast, slot=slot)
                amount_metadata: dict[str, Any] = {}
                heal_time = cast_time
                requires_existing_shield = False
                shield_gate_time: float | None = None
                shield_gate_assumed = False
                if champion_key == ("Seraphine", "W"):
                    amount_metadata = _target_missing_health_heal_metadata(
                        champion_data, slot, heal_attr, rank
                    )
                    duration_metadata = _shield_duration_metadata(champion_data, slot)
                    duration = float(duration_metadata["duration"])
                    heal_time = cast_time + duration
                    shield_gate_assumed = (
                        bool(options.get("w_already_shielded", False))
                        and cast_index == 0
                    )
                    requires_existing_shield = not shield_gate_assumed
                    shield_gate_time = cast_time
                # Same rule as the shield row above: the resolved amount is
                # the answer and the metadata never supplies a placeholder
                # zero.  A heal scaling off the recipient's CURRENT or
                # MISSING health resolves to nothing against the caster's
                # scan-time stats, which is a refusal (Seraphine W's pulse),
                # not a zero-valued packet.
                amount_metadata.pop("amount", None)
                amount = extract_named(
                    ability,
                    heal_attr,
                    rank,
                    stats,
                    _caster_as_recipient(stats) if heal_row.recipient_scaled else {},
                )
                source_label = f"{ability.get('name', slot)} · {heal_attr}"
                if amount > 0:
                    event = {
                        "time": heal_time,
                        "kind": "heal",
                        "amount": amount,
                        "source": source_label,
                        "slot": slot,
                        "target_self": heal_row.target_self,
                        "target_scope": heal_row.target_scope,
                        "rank": rank,
                        "target_selection_key": f"heal:{slot}:{cast_index}",
                        **amount_metadata,
                    }
                    if champion_key == ("Seraphine", "W"):
                        event.update(
                            {
                                "requires_existing_shield": requires_existing_shield,
                                "shield_gate_target": "attacker",
                                "shield_gate_time": shield_gate_time,
                                "shield_gate_assumed": shield_gate_assumed,
                            }
                        )
                    effects.append(event)
                    # Wave-2 follow-up packets (HANDOVER 8.5): sourced
                    # riders on the same cast keep the base packet's amount
                    # intact (the E8d pins read the first matching packet),
                    # carry their own target-selection keys, and attach the
                    # atom receipts that prove every number.
                    if champion_key == ("Nami", "W"):
                        effects.append(
                            _nami_return_bounce_packet(
                                champion_data,
                                ability,
                                slot,
                                rank,
                                stats=stats,
                                base_amount=amount,
                                cast_time=heal_time,
                                cast_index=cast_index,
                            )
                        )
                    elif champion_key == ("Yuumi", "R"):
                        best_friend = _yuumi_best_friend_packet(
                            champion_data,
                            slot,
                            level,
                            rank,
                            base_amount=amount,
                            cast_time=heal_time,
                            cast_index=cast_index,
                        )
                        effects.append(best_friend)
                        effects.append(
                            _yuumi_conversion_shield_packet(
                                champion_data,
                                event,
                                slot,
                            )
                        )
                        effects.append(
                            _yuumi_conversion_shield_packet(
                                champion_data,
                                best_friend,
                                slot,
                            )
                        )
    return sorted(effects, key=lambda event: (event["time"], event["kind"]))
