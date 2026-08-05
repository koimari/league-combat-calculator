"""Typed, timestamped ally/team item packets for the participant ledger.

The ordinary item compiler owns damage emitted by the holder.  This module
owns the other side of the same Wiki entries: ally shields/heals, temporary
health, stat buffs, all-source debuffs, and explicit item-actives.  It never
assumes an active or a trigger that is absent from the authored event stream.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import math
from typing import Any

from .item_effects import (
    ALLY_ITEM_EFFECTS,
    ally_item_effect_value,
    ally_item_level_value,
)


def _same_side(attacker: Any, actor: Any) -> bool:
    left = "main" if attacker.team in {"main", "ally"} else attacker.team
    right = "main" if actor.team in {"main", "ally"} else actor.team
    return left == right


def _teammates(attacker: Any, all_actors: Iterable[Any]) -> list[Any]:
    return [
        actor
        for actor in all_actors
        if actor.participant_id != attacker.participant_id
        and _same_side(attacker, actor)
    ]


def _item_names(attacker: Any) -> set[str]:
    return {str(item.get("name", "")) for item in attacker.items}


def _option(attacker: Any, item_name: str, key: str, default: float = 0.0) -> float:
    request = getattr(attacker, "request", None)
    item_options = getattr(request, "item_options", {}) or {}
    options = item_options.get(item_name, {})
    value = options.get(key, default) if isinstance(options, Mapping) else default
    if isinstance(value, bool):
        raise ValueError(f"{item_name}.{key} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{item_name}.{key} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{item_name}.{key} must be finite")
    return parsed


def _event_time(event: Mapping[str, Any]) -> float:
    value = event.get("time", 0.0)
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("item support event time must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError("item support event time must be finite")
    return parsed


def _packet(
    *,
    attacker: Any,
    target: Any,
    time: float,
    kind: str,
    source: str,
    amount: float = 0.0,
    duration: float = 0.0,
    target_scope: str = "one_teammate",
    **fields: Any,
) -> dict[str, Any]:
    if not math.isfinite(float(amount)) or float(amount) < 0.0:
        raise ValueError(f"{source} packet amount must be finite and non-negative")
    if not math.isfinite(float(duration)) or float(duration) < 0.0:
        raise ValueError(f"{source} packet duration must be finite and non-negative")
    return {
        "time": float(time),
        "kind": kind,
        "amount": float(amount),
        "duration": float(duration),
        "source": source,
        "source_key": source,
        "attacker": attacker.participant_id,
        "target": target.participant_id,
        "target_scope": target_scope,
        "target_policy": "explicit_selected_roster_target",
        "_item_support": True,
        **fields,
    }


def _support_triggers(
    trigger_effects: Iterable[Mapping[str, Any]], attacker: Any
) -> list[Mapping[str, Any]]:
    """Return ally heal/shield packets that can trigger item passives."""
    return [
        event
        for event in trigger_effects
        if str(event.get("kind", "")) in {"heal", "shield"}
        and str(event.get("target", "")) != attacker.participant_id
    ]


def _cc_triggers(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return only damage packets with an authored immobilize marker."""
    markers = {"immobilized", "crowd_control", "hard_cc"}
    return [
        event
        for event in result.get("damage_events", [])
        if isinstance(event, Mapping)
        if any(bool(event.get(marker)) for marker in markers)
        or str(event.get("cc_kind", "")).lower()
        in {"immobilize", "stun", "root", "knockup", "suppression"}
    ]


def _takedown_triggers(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return only explicit takedown receipts; never infer a kill from damage."""
    return [
        event
        for event in result.get("takedown_events", [])
        if isinstance(event, Mapping)
        and event.get("time") is not None
        and str(event.get("target", ""))
    ]


def _damage_triggers(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return authored non-reactive champion damage packets for item stacks."""
    return [
        event
        for event in result.get("damage_events", [])
        if isinstance(event, Mapping)
        and float(event.get("damage", 0.0) or 0.0) > 0.0
        and not event.get("_reactive")
        and str(event.get("target", ""))
    ]


def _target_by_id(all_actors: Iterable[Any], participant_id: str) -> Any | None:
    return next(
        (actor for actor in all_actors if actor.participant_id == participant_id), None
    )


def _selected_teammate(attacker: Any, teammates: list[Any]) -> Any | None:
    if not teammates:
        return None
    raw_index = _option(attacker, "Knight's Vow", "worthy_target_index", 0.0)
    index = max(0, min(len(teammates) - 1, int(raw_index)))
    return teammates[index]


def derive_item_support_effects(
    attacker: Any,
    result: Mapping[str, Any],
    all_actors: list[Any],
    trigger_effects: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Compile the holder's explicit cross-participant item packets."""
    if attacker.team == "ally" and not getattr(
        getattr(attacker, "request", None), "ally_effects_enabled", False
    ):
        return []
    names = _item_names(attacker)
    teammates = _teammates(attacker, all_actors)
    packets: list[dict[str, Any]] = []
    triggers = _support_triggers(trigger_effects, attacker)
    cc_events = _cc_triggers(result)
    takedown_events = _takedown_triggers(result)
    damage_events = _damage_triggers(result)

    # Shared target modifiers are emitted only from an authored trigger.  The
    # holder's own pair engine already prices its personal Black Cleaver,
    # Bloodletter, Bloodsong, and Abyssal branches; the ordered participant
    # walk consumes these packets for every other eligible source without
    # double-counting the originating holder.
    if "Abyssal Mask" in names:
        for target in (
            actor for actor in all_actors if not _same_side(attacker, actor)
        ):
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=0.0,
                    kind="damage_modifier",
                    source="Abyssal Mask — Unmake",
                    amount=ally_item_effect_value("Abyssal Mask", "magic_damage_amp"),
                    multiplier=1.0
                    + ally_item_effect_value("Abyssal Mask", "magic_damage_amp"),
                    all_sources=True,
                    persistent=True,
                    range_assumption="within_700_units",
                )
            )

    if "Bloodsong" in names:
        expose_key = (
            "expose_weakness_melee"
            if bool(attacker.stats.get("is_melee", False))
            else "expose_weakness_ranged"
        )
        for event in damage_events:
            if str(event.get("source_key", "")) != "spellblade_Bloodsong":
                continue
            target = _target_by_id(all_actors, str(event.get("target", "")))
            if target is None:
                continue
            rate = ally_item_effect_value("Bloodsong", expose_key)
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=_event_time(event),
                    kind="damage_modifier",
                    source="Bloodsong — Expose Weakness",
                    amount=rate,
                    duration=ally_item_effect_value(
                        "Bloodsong", "expose_weakness_duration"
                    ),
                    multiplier=1.0 + rate,
                    all_sources=True,
                    cooldown=ally_item_effect_value(
                        "Bloodsong", "expose_weakness_cooldown"
                    ),
                    owner=attacker.participant_id,
                    trigger_event_id=event.get("_event_id"),
                )
            )

    reduction_stacks: dict[tuple[str, str], int] = {}
    for event in damage_events:
        target = _target_by_id(all_actors, str(event.get("target", "")))
        if target is None:
            continue
        damage_type = str(event.get("damage_type", ""))
        source_id = str(event.get("_event_id", ""))
        if "Black Cleaver" in names and damage_type == "physical":
            key = (target.participant_id, "armor")
            stacks = min(
                int(
                    ally_item_effect_value(
                        "Black Cleaver", "armor_reduction_max_stacks"
                    )
                ),
                reduction_stacks.get(key, 0) + 1,
            )
            reduction_stacks[key] = stacks
            percent = stacks * ally_item_effect_value(
                "Black Cleaver", "armor_reduction_per_stack"
            )
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=_event_time(event),
                    kind="damage_modifier",
                    source="Black Cleaver — Carve",
                    amount=percent,
                    duration=ally_item_effect_value(
                        "Black Cleaver", "armor_reduction_duration"
                    ),
                    armor_reduction_percent=percent,
                    resistance_type="armor",
                    owner=attacker.participant_id,
                    trigger_event_id=event.get("_event_id", source_id),
                    stack_count=stacks,
                )
            )
        if (
            "Bloodletter's Curse" in names
            and damage_type == "magic"
            and bool(event.get("is_ability"))
        ):
            key = (target.participant_id, "mr")
            stacks = min(
                int(
                    ally_item_effect_value(
                        "Bloodletter's Curse", "mr_reduction_max_stacks"
                    )
                ),
                reduction_stacks.get(key, 0) + 1,
            )
            reduction_stacks[key] = stacks
            percent = stacks * ally_item_effect_value(
                "Bloodletter's Curse", "mr_reduction_per_stack"
            )
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=_event_time(event),
                    kind="damage_modifier",
                    source="Bloodletter's Curse — Vile Decay",
                    amount=percent,
                    duration=ally_item_effect_value(
                        "Bloodletter's Curse", "mr_reduction_duration"
                    ),
                    mr_reduction_percent=percent,
                    resistance_type="magic_resistance",
                    owner=attacker.participant_id,
                    trigger_event_id=event.get("_event_id", source_id),
                    stack_count=stacks,
                )
            )

    for takedown in takedown_events:
        if "Cryptbloom" not in names:
            break
        amount = ally_item_effect_value("Cryptbloom", "life_from_death_base_heal") + (
            float(attacker.stats.get("ability_power", 0.0) or 0.0)
            * ally_item_effect_value("Cryptbloom", "life_from_death_ap_ratio")
        )
        for recipient in (attacker, *teammates):
            packets.append(
                _packet(
                    attacker=attacker,
                    target=recipient,
                    time=_event_time(takedown),
                    kind="heal",
                    source="Cryptbloom — Life From Death",
                    amount=amount,
                    duration=ally_item_effect_value(
                        "Cryptbloom", "life_from_death_nova_duration"
                    ),
                    target_scope="nova_allied_champions",
                    trigger="explicit_takedown_within_damage_window",
                    cooldown=ally_item_effect_value(
                        "Cryptbloom", "life_from_death_cooldown"
                    ),
                )
            )

    # Triggered enchanter passives.  The target is carried by the authored
    # champion packet; no cursor or radius is guessed.
    for trigger in triggers:
        target = _target_by_id(all_actors, str(trigger.get("target", "")))
        if target is None:
            continue
        time = _event_time(trigger)
        if "Ardent Censer" in names:
            packets.extend(
                (
                    _packet(
                        attacker=attacker,
                        target=recipient,
                        time=time,
                        kind="stat_buff",
                        source="Ardent Censer — Sanctify",
                        amount=ally_item_effect_value(
                            "Ardent Censer", "sanctify_bonus_attack_speed"
                        ),
                        duration=ally_item_effect_value(
                            "Ardent Censer", "sanctify_duration"
                        ),
                        bonus_attack_speed_percent=ally_item_effect_value(
                            "Ardent Censer", "sanctify_bonus_attack_speed"
                        ),
                        on_hit_magic_damage=ally_item_effect_value(
                            "Ardent Censer", "sanctify_on_hit_magic"
                        ),
                        recipient_role="holder_and_healed_ally",
                    )
                    for recipient in (attacker, target)
                )
            )
        if "Staff of Flowing Water" in names:
            packets.extend(
                (
                    _packet(
                        attacker=attacker,
                        target=recipient,
                        time=time,
                        kind="stat_buff",
                        source="Staff of Flowing Water — Rapids",
                        amount=ally_item_effect_value(
                            "Staff of Flowing Water", "bonus_ability_power"
                        ),
                        duration=ally_item_effect_value(
                            "Staff of Flowing Water", "duration"
                        ),
                        ability_power=ally_item_effect_value(
                            "Staff of Flowing Water", "bonus_ability_power"
                        ),
                        ability_haste=ally_item_effect_value(
                            "Staff of Flowing Water", "bonus_ability_haste"
                        ),
                        recipient_role="holder_and_healed_ally",
                    )
                    for recipient in (attacker, target)
                )
            )
        if "Moonstone Renewer" in names:
            candidates = [
                actor
                for actor in teammates
                if actor.participant_id != target.participant_id
            ]
            chain_target = candidates[0] if candidates else target
            fraction_key = (
                "heal_chain_fraction"
                if str(trigger.get("kind")) == "heal"
                else "shield_chain_fraction"
            )
            packets.append(
                _packet(
                    attacker=attacker,
                    target=chain_target,
                    time=time,
                    kind=str(trigger.get("kind", "shield")),
                    source="Moonstone Renewer — Starlit Grace",
                    amount=float(trigger.get("amount", 0.0))
                    * ally_item_effect_value("Moonstone Renewer", fraction_key),
                    duration=float(trigger.get("duration", 0.0) or 0.0),
                    target_scope="other_nearest_wounded_ally",
                    chain_fraction=ally_item_effect_value(
                        "Moonstone Renewer", fraction_key
                    ),
                )
            )
        if "Dream Maker" in names:
            packets.extend(
                (
                    _packet(
                        attacker=attacker,
                        target=target,
                        time=time,
                        kind="damage_modifier",
                        source="Dream Maker — Blue Dream Bubble",
                        amount=ally_item_level_value(
                            "Dream Maker",
                            "blue_reduction_min",
                            "blue_reduction_max",
                            target.level,
                        ),
                        duration=ally_item_effect_value(
                            "Dream Maker", "dream_duration"
                        ),
                        damage_reduction=True,
                        next_event_only=True,
                    ),
                    _packet(
                        attacker=attacker,
                        target=target,
                        time=time,
                        kind="on_hit_magic",
                        source="Dream Maker — Purple Dream Bubble",
                        amount=ally_item_level_value(
                            "Dream Maker",
                            "purple_magic_min",
                            "purple_magic_max",
                            target.level,
                        ),
                        duration=ally_item_effect_value(
                            "Dream Maker", "dream_duration"
                        ),
                        next_event_only=True,
                    ),
                )
            )
        if "Echoes of Helia" in names:
            raw_damage = sum(
                max(
                    0.0,
                    float(event.get("raw_damage", event.get("damage", 0.0)) or 0.0),
                )
                for event in result.get("damage_events", [])
            )
            cap = ally_item_level_value(
                "Echoes of Helia", "charge_cap_min", "charge_cap_max", target.level
            )
            charges = min(
                cap,
                raw_damage
                * ally_item_effect_value("Echoes of Helia", "charge_damage_ratio"),
            )
            if charges > 0.0:
                packets.append(
                    _packet(
                        attacker=attacker,
                        target=target,
                        time=time,
                        kind="heal",
                        source="Echoes of Helia — Soul Siphon",
                        amount=charges,
                        target_scope="healed_or_shielded_ally",
                        charges_consumed=charges,
                    )
                )
                # Soul Charges are consumed by the first qualifying heal or
                # shield; subsequent triggers in this authored window do not
                # duplicate the same stored pool.
                break
        if "Diadem of Songs" in names:
            wounded = target
            packets.append(
                _packet(
                    attacker=attacker,
                    target=wounded,
                    time=time,
                    kind="heal",
                    source="Diadem of Songs — Consonance",
                    amount=float(attacker.stats.get("mana", 0.0))
                    * ally_item_effect_value(
                        "Diadem of Songs", "consonance_max_mana_ratio"
                    ),
                    target_scope="nearest_most_wounded_ally",
                    cooldown=ally_item_effect_value(
                        "Diadem of Songs", "consonance_cooldown"
                    ),
                )
            )

    # A hard-CC marker is required for the passives below.  If the reviewed
    # champion module does not emit one, the effect is intentionally absent;
    # callers must not turn an arbitrary cast boundary into a slow/root.
    for cc in cc_events:
        time = _event_time(cc)
        if "Bandlepipes" in names:
            is_melee = bool(attacker.stats.get("is_melee", False))
            duration_key = (
                "fanfare_duration_melee" if is_melee else "fanfare_duration_ranged"
            )
            as_key = (
                "fanfare_ally_attack_speed_melee"
                if is_melee
                else "fanfare_ally_attack_speed_ranged"
            )
            packets.append(
                _packet(
                    attacker=attacker,
                    target=attacker,
                    time=time,
                    kind="movement",
                    source="Bandlepipes — Fanfare",
                    amount=ally_item_effect_value(
                        "Bandlepipes", "fanfare_bonus_move_speed"
                    ),
                    duration=ally_item_effect_value("Bandlepipes", duration_key),
                    bonus_move_speed_percent=ally_item_effect_value(
                        "Bandlepipes", "fanfare_bonus_move_speed"
                    ),
                    target_scope="self",
                    trigger="authored_immobilize_or_slow",
                )
            )
            for recipient in (attacker, *teammates):
                packets.append(
                    _packet(
                        attacker=attacker,
                        target=recipient,
                        time=time,
                        kind="stat_buff",
                        source="Bandlepipes — Fanfare",
                        amount=ally_item_effect_value("Bandlepipes", as_key),
                        duration=ally_item_effect_value("Bandlepipes", duration_key),
                        bonus_attack_speed_percent=ally_item_effect_value(
                            "Bandlepipes", as_key
                        ),
                        trigger="authored_immobilize_or_slow",
                    )
                )
        if "Solstice Sleigh" in names and teammates:
            target = teammates[0]
            for recipient in (attacker, target):
                packets.append(
                    _packet(
                        attacker=attacker,
                        target=recipient,
                        time=time,
                        kind="temporary_health",
                        source="Solstice Sleigh — Going Sledding",
                        amount=ally_item_level_value(
                            "Solstice Sleigh",
                            "temporary_health_min",
                            "temporary_health_max",
                            recipient.level,
                        ),
                        duration=ally_item_effect_value("Solstice Sleigh", "duration"),
                        bonus_move_speed_percent=ally_item_effect_value(
                            "Solstice Sleigh", "bonus_move_speed_percent"
                        ),
                        cooldown=ally_item_effect_value("Solstice Sleigh", "cooldown"),
                        target_scope=(
                            "self" if recipient is attacker else "most_wounded_ally"
                        ),
                    )
                )
        if "Imperial Mandate" in names:
            target = _target_by_id(all_actors, str(cc.get("target", "")))
            if target is not None:
                packets.append(
                    _packet(
                        attacker=attacker,
                        target=target,
                        time=time,
                        kind="damage_modifier",
                        source="Imperial Mandate — Command",
                        amount=ally_item_effect_value(
                            "Imperial Mandate", "command_damage_amp"
                        ),
                        duration=ally_item_effect_value(
                            "Imperial Mandate", "command_duration"
                        ),
                        multiplier=1.0
                        + ally_item_effect_value(
                            "Imperial Mandate", "command_damage_amp"
                        ),
                        all_sources=True,
                    )
                )

    # Explicit item-actives.  A non-zero timestamp is the complete trigger
    # contract; the packet is not emitted at t=0 by default.
    active_time = _option(attacker, "Locket of the Iron Solari", "active_seconds")
    if "Locket of the Iron Solari" in names and active_time > 0.0:
        for target in (attacker, *teammates):
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=active_time,
                    kind="shield",
                    source="Locket of the Iron Solari — Devotion",
                    amount=ally_item_level_value(
                        "Locket of the Iron Solari",
                        "shield_min",
                        "shield_max",
                        target.level,
                    ),
                    duration=ally_item_effect_value(
                        "Locket of the Iron Solari", "shield_duration"
                    ),
                    target_scope="all_selected_teammates",
                )
            )
    active_time = _option(attacker, "Mikael's Blessing", "active_seconds")
    if "Mikael's Blessing" in names and active_time > 0.0 and teammates:
        target = teammates[0]
        packets.append(
            _packet(
                attacker=attacker,
                target=target,
                time=active_time,
                kind="heal",
                source="Mikael's Blessing — Purify",
                amount=ally_item_level_value(
                    "Mikael's Blessing", "heal_min", "heal_max", target.level
                ),
                target_scope="explicit_selected_ally",
                cleanse=True,
            )
        )
    active_time = _option(attacker, "Redemption", "active_seconds")
    if "Redemption" in names and active_time > 0.0:
        for target in (attacker, *teammates):
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=active_time + 2.5,
                    kind="heal",
                    source="Redemption — Intervention",
                    amount=ally_item_level_value(
                        "Redemption", "heal_min", "heal_max", target.level
                    ),
                    target_scope="redemption_allies_in_radius",
                    beam_delay=2.5,
                )
            )
    active_time = _option(attacker, "Shurelya's Battlesong", "active_seconds")
    if "Shurelya's Battlesong" in names and active_time > 0.0:
        for target in (attacker, *teammates):
            packets.append(
                _packet(
                    attacker=attacker,
                    target=target,
                    time=active_time,
                    kind="movement",
                    source="Shurelya's Battlesong — Inspiring Speech",
                    amount=ally_item_effect_value(
                        "Shurelya's Battlesong", "bonus_move_speed_percent"
                    ),
                    duration=ally_item_effect_value(
                        "Shurelya's Battlesong", "duration"
                    ),
                    bonus_move_speed_percent=ally_item_effect_value(
                        "Shurelya's Battlesong", "bonus_move_speed_percent"
                    ),
                    target_scope="all_selected_teammates",
                )
            )
    return packets


def schedule_knights_vow(
    all_actors: list[Any],
    incoming: Mapping[str, list[dict[str, Any]]],
    outgoing: Mapping[str, list[dict[str, Any]]],
    support_effects: dict[str, list[dict[str, Any]]],
) -> None:
    """Attach one deterministic Worthy tether and redirect/heal receipts."""
    for holder in all_actors:
        if "Knight's Vow" not in _item_names(holder):
            continue
        teammates = _teammates(holder, all_actors)
        target = _selected_teammate(holder, teammates)
        if target is None:
            continue
        fraction = ally_item_effect_value("Knight's Vow", "redirect_fraction")
        heal_fraction = ally_item_effect_value("Knight's Vow", "holder_heal_fraction")
        within_range = _option(holder, "Knight's Vow", "worthy_within_range", 1.0)
        holder_health_ready = _option(
            holder, "Knight's Vow", "holder_above_30_percent", 1.0
        )
        # Pledge is unit-targeted and only operates inside 1250 units.  The
        # roster has no spatial coordinates, so the scenario must expose the
        # authored in-range assumption instead of letting the calculator
        # silently guess it.  The holder-health gate is checked again by the
        # ordered survival walk as health changes over time.
        if within_range <= 0.0 or holder_health_ready <= 0.0:
            reason = (
                "worthy_out_of_range"
                if within_range <= 0.0
                else "holder_health_gate_disabled"
            )
            for event in incoming.get(target.participant_id, []):
                if str(event.get("damage_type", "")) in {"physical", "magic"}:
                    event["redirect_skipped_reason"] = reason
            continue
        for event in incoming.get(target.participant_id, []):
            if str(event.get("damage_type", "")) not in {"physical", "magic"}:
                continue
            if event.get("_reactive") or event.get("_deferred"):
                continue
            if event.get("redirect_fraction"):
                continue
            if not any(
                actor.participant_id == str(event.get("attacker", ""))
                and not _same_side(holder, actor)
                for actor in all_actors
            ):
                continue
            event["redirect_fraction"] = fraction
            event["redirect_target"] = holder.participant_id
            event["redirect_source"] = "Knight's Vow — Sacrifice"
            event["redirect_pre_mitigation_required"] = True
            event["redirect_holder_health_ratio"] = ally_item_effect_value(
                "Knight's Vow", "holder_health_threshold_ratio"
            )
            event["redirect_range_units"] = ally_item_effect_value(
                "Knight's Vow", "worthy_range_units"
            )
            event["redirect_source_revision_id"] = int(
                ally_item_effect_value("Knight's Vow", "source_revision_id")
            )
        for event in outgoing.get(target.participant_id, []):
            if str(event.get("damage_type", "")) not in {"physical", "magic", "true"}:
                continue
            amount = max(0.0, float(event.get("damage", 0.0) or 0.0))
            if amount <= 0.0:
                continue
            support_effects[holder.participant_id].append(
                _packet(
                    attacker=holder,
                    target=holder,
                    time=_event_time(event),
                    kind="heal",
                    source="Knight's Vow — Sacrifice",
                    amount=amount * heal_fraction,
                    target_scope="holder_from_worthy_damage",
                    healing_category="knights_vow",
                    requires_holder_health_ratio=ally_item_effect_value(
                        "Knight's Vow", "holder_health_threshold_ratio"
                    ),
                    range_units=ally_item_effect_value(
                        "Knight's Vow", "worthy_range_units"
                    ),
                    source_revision_id=int(
                        ally_item_effect_value("Knight's Vow", "source_revision_id")
                    ),
                )
            )


def has_ordered_item_team_effects(items: Iterable[Mapping[str, Any]]) -> bool:
    """Whether any build requires the legacy event walk for team packets."""
    return any(str(item.get("name", "")) in ALLY_ITEM_EFFECTS for item in items)


__all__ = [
    "derive_item_support_effects",
    "has_ordered_item_team_effects",
    "schedule_knights_vow",
]
