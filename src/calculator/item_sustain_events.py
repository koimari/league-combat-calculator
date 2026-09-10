"""The healing an item did, read back off a finished fight result."""

import math
from collections.abc import Mapping
from typing import Any

from . import resource_events
from .interpreters.sustain import declared_sustain
from .item_behavior import PostMitigationHealRule, ResourceDrainRule
from .item_stat_block import get_item_stats


def _item_self_healing_events(
    result: Mapping[str, Any],
    items: list[Mapping[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Materialize only timestamp-certified item self-heal packets.

    Spellblade item rows carry their accepted proc times alongside the
    amount-per-proc.  Rows without that complete receipt remain summary-only
    and are deliberately omitted here rather than being assigned a guessed
    timestamp; the participant ledger can therefore apply only exact item
    healing while the damage breakdown still records the source row.
    """
    events: list[dict[str, Any]] = []
    item_names = sorted({str(item.get("name", "")) for item in (items or ())})
    stats = result.get("champion_stats")
    stats = stats if isinstance(stats, Mapping) else {}
    damage_events = result.get("damage_events")
    damage_events = damage_events if isinstance(damage_events, list) else []
    duration = fight_duration_seconds
    if duration is None:
        schedule = result.get("auto_attack_schedule")
        if isinstance(schedule, Mapping):
            try:
                duration = float(schedule.get("window_seconds", 0.0))
            except (TypeError, ValueError):
                duration = 0.0
        else:
            duration = max(
                (
                    float(event.get("time", 0.0))
                    for event in damage_events
                    if isinstance(event, Mapping)
                ),
                default=0.0,
            )
    duration = max(0.0, float(duration or 0.0))

    # A post-mitigation heal is a *shape*, not an item: a declared share of
    # damage this build already dealt, paid straight back.  Unknown ability
    # scope is conservatively priced at the declared area/pet effectiveness
    # rather than being promoted as full.
    post_mitigation = declared_sustain(item_names, PostMitigationHealRule)
    if post_mitigation is not None:
        ratio = post_mitigation.value("ratio")
        reduced = post_mitigation.value("area_effectiveness")
        heal_events: list[dict[str, Any]] = []
        for event in damage_events:
            if not isinstance(event, Mapping):
                continue
            try:
                amount = float(event.get("damage", 0.0))
                time = float(event.get("time", 0.0))
            except (TypeError, ValueError):
                continue
            if amount <= 0.0 or not math.isfinite(amount) or not math.isfinite(time):
                continue
            source_key = str(event.get("source_key", ""))
            full_effect = bool(event.get("basic_attack")) or source_key.startswith(
                ("auto_attacks", "on_hit_")
            )
            effectiveness = 1.0 if full_effect else reduced
            heal_events.append(
                {
                    "time": time,
                    "amount": amount * ratio * effectiveness,
                    "trigger_source": source_key,
                    "effectiveness": effectiveness,
                }
            )
        if heal_events:
            events.extend(
                {
                    "time": event["time"],
                    "amount": event["amount"],
                    "source": f"{post_mitigation.owner} (Life Draining)",
                    "kind": "item_proc",
                    "healing_modifier": True,
                    "_trigger_source": event["trigger_source"],
                    "_trigger_time": event["time"],
                    "_trigger_sequence": index,
                    "effectiveness": event["effectiveness"],
                }
                for index, event in enumerate(heal_events)
                if event["amount"] > 0.0
            )

    # Drain restores mana first and only heals when the actor cannot gain
    # mana.  The result carries the end-of-window resource receipt, so a
    # manaless/full-resource actor is the only state for which a health heal
    # can be certified without inventing a starting-mana assumption.
    drain = declared_sustain(item_names, ResourceDrainRule)
    if drain is not None:
        max_mana = float(stats.get("max_mana", 0.0) or 0.0)
        remaining = float(result.get("resource_remaining", 0.0) or 0.0)
        can_only_heal = max_mana <= 0.0 or remaining >= max_mana - 1e-9
        if can_only_heal and duration > 0.0:
            base_rate = drain.value("restoration_per_second")
            combat_rate = drain.value("combat_restoration_per_second")
            combat_window = drain.value("combat_window")
            conversion = drain.value("health_conversion")
            tick = drain.value("tick_interval")
            champion_hits: list[float] = []
            for event in damage_events:
                if not isinstance(event, Mapping):
                    continue
                try:
                    hit_time = float(event.get("time", 0.0))
                    hit_damage = float(event.get("damage", 0.0) or 0.0)
                except (TypeError, ValueError):
                    continue
                if hit_damage > 0.0 and math.isfinite(hit_time):
                    champion_hits.append(hit_time)
            time = tick
            sequence = 0
            while time <= duration + 1e-9:
                boosted = any(
                    0.0 <= time - hit <= combat_window for hit in champion_hits
                )
                rate = combat_rate if boosted else base_rate
                events.append(
                    {
                        "time": round(time, 6),
                        "amount": rate * conversion,
                        "source": f"{drain.owner} (Drain)",
                        "kind": "item_proc",
                        "actor_wide": True,
                        "_trigger_sequence": sequence,
                    }
                )
                sequence += 1
                time += tick

    # Catalyst's Eternity heal is a projection of the typed mana resource
    # ledger's ACCEPTED spend receipts (P3 package 3A): the ledger is the
    # single authoritative current/max mana account, and the per-cast and
    # per-second heal caps are applied exactly once there, at the cast
    # timestamp, so every consumer (receipt walk and score-only walk)
    # emits byte-identical heal packets.  The public resource_ledger.catalyst
    # section carries the typed declaration and the heal rows; a fight
    # without the typed account (energy or manaless resource, or resource
    # limits disabled) cannot certify a MANA-spent heal and emits none —
    # an aggregate resource total is never converted into a guessed heal.
    if "Catalyst of Aeons" in item_names:
        ledger_section = result.get("resource_ledger")
        # A catalyst section is only ever built on a mana account, so its
        # presence answers the question even when the ledger row carries no
        # ``kind`` (a unit-level ledger built without the fight's identity).
        mana_account = isinstance(ledger_section, Mapping) and (
            str(ledger_section.get("kind", "")) == resource_events.RESOURCE_KIND_MANA
            or isinstance(ledger_section.get("catalyst"), Mapping)
        )
        if not mana_account:
            # A holder who spends no mana has no Eternity to price.  The
            # fight publishes a resource ledger either way -- Rengar's is a
            # Ferocity account -- so "no catalyst section" means two
            # different things, and only one of them is a defect: a MANA
            # account without one is the ledger failing to build the heal,
            # while any other kind is the mechanic being structurally
            # absent.  Certifying the difference here is what keeps a
            # manaless holder from failing a window it simply does not have.
            notes = result.get("notes")
            if isinstance(notes, list):
                kind = (
                    str(ledger_section.get("kind", ""))
                    if isinstance(ledger_section, Mapping)
                    else ""
                )
                notes.append(
                    "Catalyst of Aeons (Eternity): the holder spends no mana"
                    + (f" ({kind} resource)" if kind else "")
                    + "; the mana-spent heal is structurally zero, not "
                    "withheld."
                )
        else:
            catalyst_section = ledger_section.get("catalyst")
            if not isinstance(catalyst_section, Mapping):
                raise ValueError(
                    "Catalyst of Aeons is equipped but the typed mana "
                    "resource ledger carries no catalyst section; the "
                    "Eternity heal cannot be certified."
                )
            heal_rows = catalyst_section.get("heals")
            if not isinstance(heal_rows, list):
                raise ValueError(
                    "Catalyst of Aeons resource ledger section has no heals "
                    "list; the Eternity heal cannot be certified."
                )
            for heal in heal_rows:
                if not isinstance(heal, Mapping):
                    continue
                try:
                    event_time = float(heal.get("time", 0.0))
                    amount = float(heal.get("amount", 0.0) or 0.0)
                except (TypeError, ValueError):
                    continue
                if (
                    not math.isfinite(event_time)
                    or not math.isfinite(amount)
                    or amount <= 0.0
                ):
                    continue
                events.append(
                    {
                        "time": event_time,
                        "amount": amount,
                        "source": "Catalyst of Aeons (Eternity)",
                        "kind": "item_proc",
                        "_trigger_source": str(heal.get("slot", "cast")),
                        "_trigger_time": event_time,
                        "_trigger_sequence": int(heal.get("ordinal", 1) or 1) - 1,
                    }
                )

    # Item-provided health regeneration is a timestamped stat contribution.
    # Keep champion base regeneration out of the item self-heal stream (the
    # public one-pair result exposes only sourced packets), while still
    # applying every item's flat/percent contribution in the coupled
    # survival ledger.  The contribution is computed from typed item
    # accessors, not from a call-site literal.
    item_regen_flat = 0.0
    item_regen_percent = 0.0
    for item in items or ():
        # Pass the cached item dict itself: a defensive copy would defeat
        # get_item_stats' identity memo and re-validate the full stat map
        # on every optimizer evaluation.
        item_stats = get_item_stats(item if isinstance(item, dict) else dict(item))
        item_regen_flat += float(item_stats["health_regen_flat"])
        item_regen_percent += float(item_stats["health_regen_percent"])
    base_regen_per_second = (
        float(stats.get("base_health_regen_per_five", 0.0) or 0.0) / 5.0
    )
    item_regen = (
        (base_regen_per_second * (1.0 + item_regen_percent / 100.0))
        + item_regen_flat / 5.0
        - base_regen_per_second
    )
    if item_regen > 0.0 and duration > 0.0:
        time = 0.5
        sequence = 0
        while time <= duration + 1e-9:
            events.append(
                {
                    "time": round(time, 6),
                    "amount": item_regen * 0.5,
                    "source": "Health regeneration",
                    "kind": "regen",
                    "actor_wide": True,
                    "_trigger_sequence": sequence,
                }
            )
            sequence += 1
            time += 0.5

    breakdown = result.get("breakdown", {})
    if not isinstance(breakdown, Mapping):
        return events
    for source_key, row in breakdown.items():
        if not isinstance(source_key, str) or not isinstance(row, Mapping):
            continue
        # Periodic item packets may carry a sourced self-heal multiplier on
        # each exact post-mitigation damage event (Unending Despair/Anguish).
        # Malformed event rows are withheld rather than assigned a timestamp.
        if source_key.startswith("periodic_"):
            raw_multiplier = row.get("self_heal_post_mitigation_multiplier")
            damage_events = row.get("damage_events")
            if raw_multiplier is None or not isinstance(damage_events, list):
                continue
            try:
                multiplier = float(raw_multiplier)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(multiplier) or multiplier <= 0.0:
                continue
            source = str(row.get("name", source_key))
            for sequence, damage_event in enumerate(damage_events):
                if not isinstance(damage_event, Mapping):
                    continue
                try:
                    event_time = float(damage_event["time"])
                    damage = float(damage_event["damage"])
                except (KeyError, TypeError, ValueError):
                    continue
                if not math.isfinite(event_time) or not math.isfinite(damage):
                    continue
                amount = damage * multiplier
                if amount <= 0.0:
                    continue
                events.append(
                    {
                        "time": event_time,
                        "amount": amount,
                        "source": f"{source} (self-heal)",
                        "kind": "item_proc",
                        "_trigger_source": source_key,
                        "_trigger_time": event_time,
                        "_trigger_sequence": sequence,
                    }
                )
            continue
        if not source_key.startswith("heal_"):
            continue
        if row.get("unit") != "health":
            continue
        if row.get("owner") == "keystone":
            continue
        raw_heal_events = row.get("heal_events")
        if isinstance(raw_heal_events, list):
            source = str(row.get("name", source_key))
            for sequence, raw_event in enumerate(raw_heal_events):
                if not isinstance(raw_event, Mapping):
                    continue
                try:
                    event_time = float(raw_event["time"])
                    amount = float(raw_event["amount"])
                except (KeyError, TypeError, ValueError):
                    continue
                if (
                    not math.isfinite(event_time)
                    or not math.isfinite(amount)
                    or amount <= 0.0
                ):
                    continue
                materialized = {
                    "time": event_time,
                    "amount": amount,
                    "source": source,
                    "kind": "item_proc",
                    "_trigger_source": str(raw_event.get("trigger_source", source_key)),
                    "_trigger_time": event_time,
                    "_trigger_sequence": sequence,
                }
                if raw_event.get("healing_category"):
                    materialized["healing_category"] = raw_event["healing_category"]
                if raw_event.get("actor_wide"):
                    materialized["actor_wide"] = True
                amount_formula = raw_event.get("amount_formula")
                if callable(amount_formula):
                    materialized["amount_formula"] = amount_formula
                if raw_event.get("overheal_to_temporary_health"):
                    materialized["overheal_to_temporary_health"] = True
                    materialized["temporary_health_duration"] = max(
                        0.0,
                        float(raw_event.get("temporary_health_duration", 0.0) or 0.0),
                    )
                events.append(materialized)
            continue
        proc_times = row.get("proc_times")
        if not isinstance(proc_times, list):
            continue
        try:
            count = int(row["count"])
            amount = float(row["amount_per_proc"])
        except (KeyError, TypeError, ValueError):
            continue
        if count <= 0 or len(proc_times) != count or amount <= 0.0:
            continue
        parsed_times: list[float] = []
        for raw_time in proc_times:
            try:
                event_time = float(raw_time)
            except (TypeError, ValueError):
                parsed_times = []
                break
            if not math.isfinite(event_time):
                parsed_times = []
                break
            parsed_times.append(event_time)
        if len(parsed_times) != count:
            continue
        source = str(row.get("name", source_key))
        for sequence, event_time in enumerate(parsed_times):
            events.append(
                {
                    "time": event_time,
                    "amount": amount,
                    "source": source,
                    "kind": "item_proc",
                    "_trigger_source": source_key,
                    "_trigger_time": event_time,
                    "_trigger_sequence": sequence,
                }
            )
    events.sort(
        key=lambda event: (event["time"], event["source"], event["_trigger_sequence"])
    )
    return events


def _timestamped_damage_events(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The fight's damage rows that carry a usable time and amount."""
    usable: list[Mapping[str, Any]] = []
    for row in result.get("damage_events") or ():
        if not isinstance(row, Mapping):
            continue
        try:
            time = float(row.get("time", 0.0))
            damage = float(row.get("damage", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if damage > 0.0 and math.isfinite(time):
            usable.append(row)
    return sorted(usable, key=lambda row: float(row.get("time", 0.0)))
