"""Champion-owned healing derived from the reviewed ability packets.

Healing is deliberately kept separate from item/stat heuristics.  A result
contains post-mitigation, ordered damage events; this module applies only
champion-specific Wiki rules to those events and returns another ordered
ledger for the participant simulator.
"""

from __future__ import annotations

import re
import math
from typing import Any, Iterable

from .champions.slotlib import extract_named


def _leveling_value(ability: dict[str, Any], attribute: str, rank: int) -> float:
    """Read one sourced leveling attribute without inventing a fallback."""
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") != attribute:
                continue
            modifiers = leveling.get("modifiers", [])
            if not modifiers:
                return 0.0
            values = modifiers[0].get("values", [])
            if not values:
                return 0.0
            return float(values[min(max(rank, 1) - 1, len(values) - 1)])
    return 0.0


def _ability(champion_data: dict[str, Any], slot: str) -> dict[str, Any]:
    entries = champion_data.get("abilities", {}).get(slot, [])
    return entries[0] if entries and isinstance(entries[0], dict) else {}


def _event_source(event: dict[str, Any]) -> str:
    return str(event.get("source_key", ""))


def _is_persistent(event: dict[str, Any]) -> bool:
    """Return the source-certified persistent/periodic damage boundary.

    The engine's own source keys are stable public receipts for these rows;
    no damage amount or champion archetype is guessed here.
    """
    source = _event_source(event).lower()
    return (
        source.startswith("burn_")
        or source.startswith("stacking_dot_")
        or "tibbers_aura" in source
        or source.startswith("immolate_")
    )


def _attributed_events(
    events: Iterable[dict[str, Any]],
    predicate,
) -> list[dict[str, Any]]:
    return [event for event in events if predicate(_event_source(event), event)]


def _rank(ability_damages: dict[str, dict[str, Any]], slot: str) -> int:
    """Use the parser's sourced rank; omitted ranks are already level-derived."""
    try:
        return max(0, int(ability_damages.get(slot, {}).get("rank", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _trigger_fields(event: dict[str, Any]) -> dict[str, Any]:
    """Carry a stable internal receipt for the damage that caused a heal."""
    fields: dict[str, Any] = {
        "_trigger_source": _event_source(event),
        "_trigger_time": float(event.get("time", 0.0)),
    }
    if event.get("sequence") is not None:
        fields["_trigger_sequence"] = int(event["sequence"])
    return fields


def _heal_from_damage(
    healing: list[dict[str, Any]],
    event: dict[str, Any],
    amount: float,
    source: str,
    *,
    later_target_amount: float | None = None,
    link_to_damage: bool = True,
) -> None:
    """Append one sourced self-heal tied to a damage event.

    ``later_target_amount`` is the explicit receipt for a per-champion flat
    heal that pays a reduced amount to targets after the first (Vladimir's
    Hemoplague).  The participant ledger re-prices the heal to that amount
    for every defender past the roster's first target, so each target keeps
    its own event instead of the engine re-authoring the full amount per
    pair fight.

    ``link_to_damage=False`` marks flat heals that trigger at cast/detonation
    regardless of whether the paired damage event landed (Vladimir Q/R); the
    trigger fields still link the receipt to the cast for audit.
    """
    amount = max(0.0, float(amount))
    if amount <= 0.0:
        return
    if link_to_damage and float(event.get("damage", 0.0)) <= 0.0:
        return
    heal: dict[str, Any] = {
        "time": float(event.get("time", 0.0)),
        "amount": amount,
        "source": source,
        "kind": "champion_ability",
        **_trigger_fields(event),
    }
    if later_target_amount is not None:
        heal["_later_target_amount"] = max(0.0, float(later_target_amount))
    healing.append(heal)


# Every champion with a sourced self-heal rule in ``derive_self_healing``'s
# dispatch below.  The scoring fast path reads this to know a fight's event
# ledger feeds no heal author at all; a rule branch added without extending
# this set would be silently skipped, so the pairing is pinned by a source
# test in tests/test_participant_timeline.py.
HEALING_RULE_CHAMPIONS = frozenset(
    {
        "Aatrox",
        "Ambessa",
        "Darius",
        "Warwick",
        "Dr. Mundo",
        "Irelia",
        "Renekton",
        "Soraka",
        "Briar",
        "Vladimir",
        "Rakan",
        "Sona",
        "Janna",
        "Milio",
        "Taric",
    }
)


def derive_self_healing(
    champion_data: dict[str, Any],
    champion_stats: dict[str, float],
    ability_damages: dict[str, dict[str, Any]],
    damage_events: list[dict[str, Any]],
    cast_timeline: list[dict[str, Any]] | None = None,
    fight_duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Return sourced self-heal events in the engine's event order.

    Only champion packets with an explicit Wiki formula are handled.  An
    unsupported champion therefore returns an empty list instead of a role or
    archetype estimate.
    """
    name = str(champion_data.get("name", ""))
    if name not in HEALING_RULE_CHAMPIONS:
        return []
    healing: list[dict[str, Any]] = []

    if name == "Aatrox":
        # Deathbringer Stance: heals for the post-mitigation bonus damage.
        passive_events = _attributed_events(
            damage_events,
            lambda source, _event: "passive" in source.lower(),
        )
        # The reviewed packet says E healing is 16% + 1.1% per 100 bonus HP.
        e_description = " ".join(
            effect.get("description", "")
            for effect in _ability(champion_data, "E").get("effects", [])
        )
        ratio_match = re.search(
            r"heals for\s+(\d+(?:\.\d+)?)%\s*\(\+\s*(\d+(?:\.\d+)?)%\s*per\s*100\s*bonus health",
            e_description,
            flags=re.IGNORECASE,
        )
        base_ratio = float(ratio_match.group(1)) / 100.0 if ratio_match else 0.0
        per_100 = float(ratio_match.group(2)) / 100.0 if ratio_match else 0.0
        e_ratio = base_ratio + per_100 * (
            float(champion_stats.get("bonus_health", 0.0)) / 100.0
        )
        r_rank = int(ability_damages.get("R", {}).get("rank", 0) or 0)
        r_inc = _leveling_value(
            _ability(champion_data, "R"), "Increased Healing", r_rank
        )
        healing_amp = 1.0 + r_inc / 100.0 if r_rank > 0 else 1.0

        for event in passive_events:
            amount = max(0.0, float(event.get("damage", 0.0))) * healing_amp
            if amount > 0:
                healing.append(
                    {
                        "time": float(event.get("time", 0.0)),
                        "amount": amount,
                        "source": "Deathbringer Stance",
                        "kind": "champion_passive",
                        **_trigger_fields(event),
                    }
                )

        # E's passive excludes persistent damage; it is post-mitigation damage
        # dealt to champions, then amplified by R.  Damage is already ordered
        # and mitigated by this point.
        for event in damage_events:
            if _is_persistent(event):
                continue
            amount = max(0.0, float(event.get("damage", 0.0))) * e_ratio * healing_amp
            if amount > 0:
                healing.append(
                    {
                        "time": float(event.get("time", 0.0)),
                        "amount": amount,
                        "source": "Umbral Dash",
                        "kind": "champion_passive",
                        **_trigger_fields(event),
                    }
                )

    elif name == "Ambessa":
        r_rank = int(ability_damages.get("R", {}).get("rank", 0) or 0)
        ratio = _leveling_value(
            _ability(champion_data, "R"), "Healing Percentage", r_rank
        )
        # Public Execution heals from post-mitigation active ability damage.
        if ratio > 0:
            for event in damage_events:
                source = _event_source(event)
                if source not in {"Q", "Q2", "W", "E", "R"}:
                    continue
                amount = max(0.0, float(event.get("damage", 0.0))) * ratio / 100.0
                if amount > 0:
                    healing.append(
                        {
                            "time": float(event.get("time", 0.0)),
                            "amount": amount,
                            "source": "Public Execution",
                            "kind": "champion_passive",
                            **_trigger_fields(event),
                        }
                    )

    elif name == "Darius":
        # Decimate's outer blade heals for 17% of missing health per enemy
        # champion hit, capped at 51% for three or more champions. Pair
        # packets mark the cast so the coupled timeline coalesces those
        # per-target receipts before applying one live heal.
        for event in damage_events:
            if _event_source(event) != "Q":
                continue
            trigger_time = float(event.get("time", 0.0))
            trigger_sequence = int(event.get("sequence", 0) or 0)

            def missing_health_heal(
                current_health: float,
                maximum_health: float,
                ratio: float = 0.17,
            ) -> float:
                return max(0.0, maximum_health - current_health) * ratio

            healing.append(
                {
                    "time": trigger_time,
                    "amount": 0.0,
                    "amount_formula": missing_health_heal,
                    "source": "Decimate",
                    "kind": "champion_ability",
                    "_darius_q_group": (trigger_time, trigger_sequence),
                    **_trigger_fields(event),
                }
            )

    # The following packets are deliberately formula-only.  They do not use
    # a class/archetype multiplier and are emitted only when the triggering
    # ability event exists in the ordered damage ledger.
    elif name == "Warwick":
        q = _ability(champion_data, "Q")
        q_rank = _rank(ability_damages, "Q")
        q_ratio = extract_named(q, "Healing Percentage", q_rank, champion_stats, {})
        for event in damage_events:
            source = _event_source(event)
            if source == "Q":
                _heal_from_damage(
                    healing,
                    event,
                    float(event.get("damage", 0.0)) * q_ratio / 100.0,
                    "Jaws of the Beast",
                )
            elif source == "R":
                # Infinite Duress explicitly heals for 100% of all
                # post-mitigation damage dealt to its target.
                _heal_from_damage(
                    healing, event, float(event.get("damage", 0.0)), "Infinite Duress"
                )

    elif name == "Dr. Mundo":
        # Maximum Dosage is an actor-wide regeneration stream, independent of
        # which enemy pair produced the current damage result.  The timeline
        # layer deduplicates this receipt across multiple defenders.
        r = _ability(champion_data, "R")
        r_rank = _rank(ability_damages, "R")
        per_tick = extract_named(
            r, "Health Regenerated per 0.5 Seconds", r_rank, champion_stats, {}
        )
        duration = max(0.0, float(fight_duration_seconds or 0.0))
        if per_tick > 0.0 and duration > 0.0:
            for cast in cast_timeline or []:
                if cast.get("slot") != "R":
                    continue
                start = float(cast.get("time", 0.0)) + 0.5
                end = min(duration, start - 0.5 + 10.0)
                tick = start
                while tick <= end + 1e-9:
                    healing.append(
                        {
                            "time": tick,
                            "amount": float(per_tick),
                            "source": "Maximum Dosage",
                            "kind": "champion_ability",
                            "actor_wide": True,
                        }
                    )
                    tick += 0.5

    elif name == "Irelia":
        ability = _ability(champion_data, "Q")
        rank = _rank(ability_damages, "Q")
        amount = extract_named(ability, "Heal", rank, champion_stats, {})
        for event in damage_events:
            if _event_source(event) == "Q":
                _heal_from_damage(healing, event, amount, "Bladesurge")

    elif name == "Renekton":
        ability = _ability(champion_data, "Q")
        rank = _rank(ability_damages, "Q")
        amount = extract_named(ability, "Champion Healing", rank, champion_stats, {})
        for event in damage_events:
            if _event_source(event) == "Q":
                _heal_from_damage(healing, event, amount, "Cull the Meek")

    elif name == "Soraka":
        ability = _ability(champion_data, "Q")
        rank = _rank(ability_damages, "Q")
        per_tick = extract_named(ability, "Heal per Tick", rank, champion_stats, {})
        total = extract_named(ability, "Total Heal", rank, champion_stats, {})
        tick_count = (
            max(1, min(100, int(round(total / per_tick))))
            if per_tick > 0.0 and total > 0.0
            else 0
        )
        for event in damage_events:
            if _event_source(event) != "Q" or tick_count <= 0:
                continue
            trigger = _trigger_fields(event)
            for index in range(1, tick_count + 1):
                healing.append(
                    {
                        "time": float(event.get("time", 0.0)) + index * 0.2,
                        "amount": float(per_tick),
                        "source": "Starcall · Rejuvenation",
                        "kind": "champion_ability",
                        **trigger,
                    }
                )

    elif name == "Briar":
        ability = _ability(champion_data, "E")
        rank = _rank(ability_damages, "E")
        per_tick = extract_named(ability, "Heal Per Tick", rank, champion_stats, {})
        maximum = extract_named(ability, "Maximum Heal", rank, champion_stats, {})
        if per_tick > 0.0 and maximum > 0.0:
            for event in damage_events:
                if _event_source(event) != "E":
                    continue
                ticks = max(1, min(4, int(math.ceil(maximum / per_tick))))
                for index in range(1, ticks + 1):
                    healing.append(
                        {
                            "time": float(event.get("time", 0.0)) + index * 0.25,
                            "amount": min(
                                float(per_tick),
                                max(0.0, maximum - per_tick * (index - 1)),
                            ),
                            "source": "Chilling Scream",
                            "kind": "champion_ability",
                            **_trigger_fields(event),
                        }
                    )

    elif name == "Rakan":
        # Gleaming Quill marks a radius around Rakan on a champion hit;
        # after 3 seconds (or when an ally enters it) he heals himself and
        # nearby allies for a flat per-level amount + AP (wiki: "Heal: 40 :
        # 230 (based on level) (+ 55% AP)").  The heal is once per Q cast,
        # so the pair copies are deduplicated as an actor-wide receipt.
        level = max(1, int(champion_stats.get("level", 18) or 18))
        heal = extract_named(
            _ability(champion_data, "Q"), "Heal", level, champion_stats
        )
        if heal > 0.0:
            for event in _attributed_events(
                damage_events, lambda source, _event: source == "Q"
            ):
                healing.append(
                    {
                        "time": float(event.get("time", 0.0)) + 3.0,
                        "amount": heal,
                        "source": "Gleaming Quill",
                        "kind": "champion_ability",
                        "actor_wide": True,
                    }
                )

    elif name == "Sona":
        # Aria of Perseverance heals Sona herself on every W cast (wiki:
        # "Heal: 30 / 45 / 60 / 75 / 90 (+ 30% AP)"); the tone's ally half
        # is authored by the support layer.  W has no enemy damage, so the
        # cast timeline is the sourced trigger.
        w_rank = _rank(ability_damages, "W")
        heal = extract_named(
            _ability(champion_data, "W"), "Heal", w_rank, champion_stats
        )
        if heal > 0.0:
            for cast in cast_timeline or []:
                if cast.get("slot") != "W":
                    continue
                healing.append(
                    {
                        "time": float(cast.get("time", 0.0)),
                        "amount": heal,
                        "source": "Aria of Perseverance",
                        "kind": "champion_ability",
                        "actor_wide": True,
                    }
                )

    elif name == "Janna":
        # Monsoon channels for up to 3 seconds, healing Janna herself and
        # nearby allies every 0.25 seconds (wiki: "Heal Per Tick: 25 / 37.5
        # / 50 (+ 12.5% AP)"; "Total Heal: 300 / 450 / 600 (+ 150% AP)").
        # The tick count is sourced from the total/per-tick ratio so the
        # authored sum stays exact at every rank.
        r_rank = _rank(ability_damages, "R")
        ability = _ability(champion_data, "R")
        per_tick = extract_named(ability, "Heal Per Tick", r_rank, champion_stats)
        total = extract_named(ability, "Total Heal", r_rank, champion_stats)
        tick_count = (
            max(1, min(100, int(round(total / per_tick))))
            if per_tick > 0.0 and total > 0.0
            else 12
        )
        if per_tick > 0.0:
            for cast in cast_timeline or []:
                if cast.get("slot") != "R":
                    continue
                start = float(cast.get("time", 0.0))
                for index in range(1, tick_count + 1):
                    healing.append(
                        {
                            "time": start + index * 0.25,
                            "amount": float(per_tick),
                            "source": "Monsoon",
                            "kind": "champion_ability",
                            "actor_wide": True,
                        }
                    )

    elif name == "Milio":
        # Breath of Life heals Milio himself and nearby allied champions
        # on cast (wiki: "Heal: 150 / 250 / 350 (+ 50% AP)").  R deals no
        # enemy damage, so the R cast timeline is the sourced trigger.
        r_rank = _rank(ability_damages, "R")
        heal = extract_named(
            _ability(champion_data, "R"), "Heal", r_rank, champion_stats
        )
        if heal > 0.0:
            for cast in cast_timeline or []:
                if cast.get("slot") != "R":
                    continue
                healing.append(
                    {
                        "time": float(cast.get("time", 0.0)),
                        "amount": heal,
                        "source": "Breath of Life",
                        "kind": "champion_ability",
                        "actor_wide": True,
                    }
                )

    elif name == "Taric":
        # Starlight's Touch heals Taric himself and nearby allies per
        # charge, capped at the maximum charge heal (wiki prose: "heals
        # himself and nearby allied champions for 25 (+ 15% AP) (+ 1% of
        # his maximum health) per charge" and "up to a maximum of 125
        # (+ 75% AP) (+ 5% of his maximum health) at 5 charges").  The
        # stock is the rank-scaled "Maximum Charges" leveling attribute.
        q = _ability(champion_data, "Q")
        q_rank = _rank(ability_damages, "Q")
        charges = extract_named(q, "Maximum Charges", q_rank, champion_stats)
        descriptions = [
            effect.get("description", "") for effect in q.get("effects", [])
        ]
        per_charge_match = re.search(
            r"for\s+(\d+(?:\.\d+)?)\s*\(\+\s*(\d+(?:\.\d+)?)%\s*AP\)"
            r"\s*\(\+\s*(\d+(?:\.\d+)?)%\s*of his maximum health\)\s*per charge",
            " ".join(descriptions),
            flags=re.IGNORECASE,
        )
        maximum_match = re.search(
            r"maximum of\s+(\d+(?:\.\d+)?)\s*\(\+\s*(\d+(?:\.\d+)?)%\s*AP\)"
            r"\s*\(\+\s*(\d+(?:\.\d+)?)%\s*of his maximum health\)",
            " ".join(descriptions),
            flags=re.IGNORECASE,
        )
        if per_charge_match is not None and charges > 0.0:
            maximum_health = float(champion_stats.get("health", 0.0) or 0.0)
            ability_power = float(champion_stats.get("ability_power", 0.0) or 0.0)

            def _charge_heal(
                flat: float, ap_percent: float, hp_percent: float
            ) -> float:
                return (
                    flat
                    + ability_power * ap_percent / 100.0
                    + maximum_health * hp_percent / 100.0
                )

            per_charge = _charge_heal(
                float(per_charge_match.group(1)),
                float(per_charge_match.group(2)),
                float(per_charge_match.group(3)),
            )
            heal = charges * per_charge
            if maximum_match is not None:
                heal = min(
                    heal,
                    _charge_heal(
                        float(maximum_match.group(1)),
                        float(maximum_match.group(2)),
                        float(maximum_match.group(3)),
                    ),
                )
            if heal > 0.0:
                for cast in cast_timeline or []:
                    if cast.get("slot") != "Q":
                        continue
                    healing.append(
                        {
                            "time": float(cast.get("time", 0.0)),
                            "amount": heal,
                            "source": "Starlight's Touch",
                            "kind": "champion_ability",
                            "actor_wide": True,
                        }
                    )

    if name == "Vladimir":
        # Transfusion (Q): flat heal per cast, rank-scaled, + AP ratio
        # (wiki: "Heal: 20 / 25 / 30 / 35 / 40 (+ 35% AP)").
        q_rank = _rank(ability_damages, "Q")
        q_heal = extract_named(
            _ability(champion_data, "Q"), "Heal", q_rank, champion_stats
        )
        for event in _attributed_events(
            damage_events, lambda source, _event: source == "Q"
        ):
            _heal_from_damage(
                healing, event, q_heal, "Transfusion", link_to_damage=False
            )
        # Sanguine Pool (W): heals for 30% of pre-mitigation damage dealt
        # (patch 12.13: "Healing increased to 30% of damage dealt from 15%";
        # 18% against minions — champion targets assumed here).
        for event in _attributed_events(
            damage_events, lambda source, _event: source == "W"
        ):
            # Pre-mitigation damage per the wiki ("30% of the pre-mitigation
            # damage dealt"); the engine exposes it as event["raw_damage"].
            dealt = float(event.get("raw_damage", event.get("damage", 0.0)) or 0.0)
            _heal_from_damage(healing, event, 0.30 * dealt, "Sanguine Pool")
        # Hemoplague (R): flat heal per infected champion, reduced for later
        # targets (wiki: "Heal: 150 / 250 / 350 (+ 70% AP)" and
        # "Reduced Heal: 60 / 100 / 140 (+ 28% AP)").  Each pair fight sees
        # only its own R packet, so every copy is authored at the full value
        # with the reduced amount attached as an explicit receipt; the
        # coupled participant ledger re-prices later roster targets so the
        # first infected champion pays the full heal and each additional
        # champion pays the reduced heal.
        r_rank = _rank(ability_damages, "R")
        r_heal = extract_named(
            _ability(champion_data, "R"), "Heal", r_rank, champion_stats
        )
        r_reduced = extract_named(
            _ability(champion_data, "R"), "Reduced Heal", r_rank, champion_stats
        )
        for event in _attributed_events(
            damage_events, lambda source, _event: source == "R"
        ):
            _heal_from_damage(
                healing,
                event,
                r_heal,
                "Hemoplague",
                later_target_amount=r_reduced,
                link_to_damage=False,
            )

    return sorted(healing, key=lambda event: (event["time"], event["source"]))
