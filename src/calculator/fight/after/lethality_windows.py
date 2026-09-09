"""Authored temporary lethality repricing later physical packets."""

import math
from collections.abc import Mapping
from typing import Any

from ...ability_atoms import ability_field
from ...resistance import apply_armor_penetration, apply_resistance
from ...survival.pricing import restate_declaration
from ..ledger.event_rows import _finite_numeric_receipt
from ..state import FightState


def _apply_temporary_lethality_windows(state: FightState) -> None:
    """Apply authored temporary lethality to later physical event packets.

    Firmament (Voltaic Cyclosword) grants flat lethality *after* its
    energized packet.  The item proc and ordinary attacks are priced before
    the proc is added, so the window is resolved once the complete authored
    ledger exists.  We rescale only later, timestamped physical packets by
    the ratio of the new and old armor multipliers; this preserves crits,
    item amplifiers, and any other post-mitigation modifiers already present
    on the event.  Untimed/coarse rows remain unchanged rather than receiving
    guessed penetration.

    Each rescaled packet's declaration is restated at the armour that packet
    actually met (:func:`restate_declaration`), so the walk prices it inside
    the window rather than at the one figure the fight publishes.
    """
    old_armor = float(state.resists.effective_armor)
    old_multiplier = apply_resistance(1.0, old_armor)
    if not math.isfinite(old_multiplier) or old_multiplier <= 0.0:
        return

    windows: list[dict[str, Any]] = []
    for source_key, row in state.breakdown.items():
        if not isinstance(row, dict):
            continue
        temporary = row.get("temporary_lethality")
        events = row.get("damage_events")
        if not isinstance(temporary, Mapping) or not isinstance(events, list):
            continue
        amount = _finite_numeric_receipt(temporary.get("amount"))
        duration = _finite_numeric_receipt(temporary.get("duration"))
        if amount is None or amount <= 0.0 or duration is None or duration <= 0.0:
            continue
        trigger_times = [
            _finite_numeric_receipt(event.get("time"))
            for event in events
            if isinstance(event, Mapping)
        ]
        trigger_times = [time for time in trigger_times if time is not None]
        if not trigger_times:
            continue
        windows.append(
            {
                "source_key": str(source_key),
                "trigger_time": min(trigger_times),
                "end_time": min(trigger_times) + duration,
                "amount": amount,
                "applies_to_triggering_event": bool(
                    ability_field(
                        temporary, "applied_to_triggering_event", form="temporary_buff"
                    )
                    or ability_field(
                        temporary, "applies_before_event", form="temporary_buff"
                    )
                ),
                "applied_count": 0,
            }
        )

    if not windows:
        return

    for source_key, row in state.breakdown.items():
        if not isinstance(row, dict):
            continue
        events = row.get("damage_events")
        if not isinstance(events, list):
            continue
        row_delta = 0.0
        for event in events:
            if not isinstance(event, dict) or event.get("damage_type") != "physical":
                continue
            event_time = _finite_numeric_receipt(event.get("time"))
            damage = _finite_numeric_receipt(event.get("damage"))
            if event_time is None or damage is None or damage <= 0.0:
                continue
            extra_lethality = 0.0
            active_windows: list[dict[str, Any]] = []
            for window in windows:
                # Firmament is an ordered pre-packet effect: its extra
                # lethality applies to its own damage and to the triggering
                # attack/ability.  Later events use the ordinary strict
                # after-trigger boundary.  Ability events at the same
                # timestamp are excluded unless they are the named Galvanize
                # row; the sourced trigger is still the packet before them.
                same_time_trigger = (
                    window["applies_to_triggering_event"]
                    and abs(event_time - window["trigger_time"]) <= 1e-9
                    and (
                        str(source_key) == window["source_key"]
                        or str(row.get("event_phase", "")) != "ability"
                    )
                )
                later_event = (
                    event_time > window["trigger_time"]
                    and event_time <= window["end_time"] + 1e-9
                )
                if same_time_trigger or later_event:
                    extra_lethality += float(window["amount"])
                    active_windows.append(window)
            if extra_lethality <= 0.0:
                continue
            percent_pen = (
                state.resists.auto_armor_pen_percent
                if str(row.get("event_phase", "")) == "auto"
                else state.resists.ability_armor_pen_percent
            )
            new_armor = apply_armor_penetration(
                state.resists.reduced_armor,
                state.resists.flat_armor_pen + extra_lethality,
                percent_pen,
                state.resists.armor_pen_bonus_percent,
                bonus_armor=state.resists.target_bonus_armor,
            )
            new_multiplier = apply_resistance(1.0, new_armor)
            if not math.isfinite(new_multiplier) or new_multiplier <= 0.0:
                continue
            new_damage = damage * (new_multiplier / old_multiplier)
            if not math.isfinite(new_damage):
                continue
            delta = new_damage - damage
            event["damage"] = new_damage
            # The packet met ``new_armor``, not the figure the fight
            # published, and a declaration is priced at what its own packet
            # met.
            restate_declaration(event, resistance=new_armor)
            row_delta += delta
            for window in active_windows:
                window["applied_count"] += 1
        if row_delta:
            row["total_damage"] = float(row.get("total_damage", 0.0)) + row_delta
            if "damage_per_hit" in row and row.get("count"):
                row["damage_per_hit"] = float(row["total_damage"]) / float(row["count"])
            state.total_damage += row_delta

    for window in windows:
        row = state.breakdown.get(window["source_key"])
        if not isinstance(row, dict):
            continue
        temporary = row.get("temporary_lethality")
        if not isinstance(temporary, dict):
            continue
        applied = int(window["applied_count"])
        temporary["applied_to_triggering_event"] = bool(
            ability_field(
                temporary, "applied_to_triggering_event", form="temporary_buff"
            )
            and applied > 0
        )
        temporary["applied_to_later_events"] = applied > 0
        temporary["applied_event_count"] = applied
        temporary["note"] = (
            "Applied before the triggering Firmament packet and to later "
            "timestamped physical events within the sourced window."
            if applied > 0
            else "No timestamped physical events fell within the window."
        )
