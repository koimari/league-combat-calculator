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


def _missing_health_scaled_heal(minimum: float, maximum: float):
    """Build a live missing-health interpolation between two sourced bounds.

    Wiki "0% : 100% (based on missing health)" means the heal pays the
    minimum at full health and the maximum at 0 health, interpolated
    linearly by the recipient's missing-health ratio at the moment the heal
    lands.  The survival walk evaluates the returned callable with the
    recipient's live (current, maximum) health.
    """
    minimum = max(0.0, float(minimum))
    maximum = max(minimum, float(maximum))

    def amount_formula(current_health: float, maximum_health: float) -> float:
        if maximum_health <= 0.0:
            return minimum
        missing_ratio = max(0.0, maximum_health - current_health) / maximum_health
        return minimum + (maximum - minimum) * missing_ratio

    return amount_formula


def _cast_slot_times(
    cast_timeline: list[dict[str, Any]] | None, slot: str
) -> list[float]:
    """Ordered cast times for one slot from the engine's cast timeline."""
    return sorted(
        float(cast.get("time", 0.0))
        for cast in (cast_timeline or [])
        if cast.get("slot") == slot
    )


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
        "Kayle",
        "Kha'Zix",
        "Kindred",
        "Lissandra",
        "Nidalee",
        "Senna",
        "Smolder",
        "Sylas",
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

    elif name == "Kayle":
        # Celestial Blessing (W): flat self-heal per cast (wiki: "Heal:
        # 55 / 80 / 105 / 130 / 155 (+ 25% AP)").  W deals no damage, so the
        # cast timeline is the only trigger receipt; the heal pays once per
        # cast regardless of which enemy pair produced the damage result, so
        # it is authored actor-wide.
        w = _ability(champion_data, "W")
        w_rank = _rank(ability_damages, "W")
        w_heal = extract_named(w, "Heal", w_rank, champion_stats)
        for cast_time in _cast_slot_times(cast_timeline, "W"):
            healing.append(
                {
                    "time": cast_time,
                    "amount": w_heal,
                    "source": "Celestial Blessing",
                    "kind": "champion_ability",
                    "actor_wide": True,
                }
            )

    elif name == "Kha'Zix":
        # Void Spike (W): heals Kha'Zix for a flat amount per cast when he
        # is within the explosion (wiki/data: "Heal: 55 / 75 / 95 / 115 /
        # 135 (+ 50% AP)").  The explosion happens whether or not the spike
        # damage is blocked, so the flat heal is not linked to damage.
        w = _ability(champion_data, "W")
        w_rank = _rank(ability_damages, "W")
        w_heal = extract_named(w, "Heal", w_rank, champion_stats)
        for event in _attributed_events(
            damage_events, lambda source, _event: source == "W"
        ):
            _heal_from_damage(
                healing, event, w_heal, "Void Spike", link_to_damage=False
            )

    elif name == "Kindred":
        # Lamb's Respite (R): every unit inside the zone is healed when the
        # blessing ends, 4 seconds after the cast (wiki: "Heal: 225 / 300 /
        # 375").  R deals no damage, so the cast timeline is the trigger;
        # the heal is actor-wide because one cast pays one heal regardless
        # of roster size.
        r = _ability(champion_data, "R")
        r_rank = _rank(ability_damages, "R")
        r_heal = extract_named(r, "Heal", r_rank, champion_stats)
        duration = max(0.0, float(fight_duration_seconds or 0.0))
        for cast_time in _cast_slot_times(cast_timeline, "R"):
            heal_time = cast_time + 4.0
            if heal_time > duration + 1e-9:
                continue
            healing.append(
                {
                    "time": heal_time,
                    "amount": r_heal,
                    "source": "Lamb's Respite",
                    "kind": "champion_ability",
                    "actor_wide": True,
                }
            )

    elif name == "Lissandra":
        # Frozen Tomb self-cast (R): heals every 0.25 seconds for the 2.5
        # second stasis, scaled from minimum to maximum per tick by her
        # missing health (wiki: "Minimum Heal per Tick" / "Maximum Heal per
        # Tick"; 10 ticks of 0.25s reconcile the total attributes).  The
        # engine's R damage row anchors the cast time; the heal amount is a
        # live missing-health formula.
        r = _ability(champion_data, "R")
        r_rank = _rank(ability_damages, "R")
        min_tick = extract_named(r, "Minimum Heal per Tick", r_rank, champion_stats)
        max_tick = extract_named(r, "Maximum Heal per Tick", r_rank, champion_stats)
        for event in _attributed_events(
            damage_events, lambda source, _event: source == "R"
        ):
            trigger = _trigger_fields(event)
            for index in range(1, 11):
                healing.append(
                    {
                        "time": float(event.get("time", 0.0)) + index * 0.25,
                        "amount": 0.0,
                        "amount_formula": _missing_health_scaled_heal(
                            min_tick, max_tick
                        ),
                        "source": "Frozen Tomb",
                        "kind": "champion_ability",
                        **trigger,
                    }
                )

    elif name == "Nidalee":
        # Primal Surge (E): self/ally heal scaled by the target's missing
        # health (wiki: "Minimum Heal" / "Maximum Heal").  The engine's E
        # damage row anchors the cast; the heal triggers on cast whether or
        # not the paired damage landed, so it is not linked to damage.
        e = _ability(champion_data, "E")
        e_rank = _rank(ability_damages, "E")
        min_heal = extract_named(e, "Minimum Heal", e_rank, champion_stats)
        max_heal = extract_named(e, "Maximum Heal", e_rank, champion_stats)
        for event in _attributed_events(
            damage_events, lambda source, _event: source == "E"
        ):
            healing.append(
                {
                    "time": float(event.get("time", 0.0)),
                    "amount": 0.0,
                    "amount_formula": _missing_health_scaled_heal(min_heal, max_heal),
                    "source": "Primal Surge",
                    "kind": "champion_ability",
                    **_trigger_fields(event),
                }
            )

    elif name == "Senna":
        # Piercing Darkness (Q): the light ray heals Senna and allied
        # champions hit (wiki: "Healing: 40 / 60 / 80 / 100 / 120
        # (+ 40% bonus AD) (+ 35% AP)").  Flat heal per cast, unlinked from
        # the damage row.
        q = _ability(champion_data, "Q")
        q_rank = _rank(ability_damages, "Q")
        q_heal = extract_named(q, "Healing", q_rank, champion_stats)
        for event in _attributed_events(
            damage_events, lambda source, _event: source == "Q"
        ):
            _heal_from_damage(
                healing, event, q_heal, "Piercing Darkness", link_to_damage=False
            )

    elif name == "Smolder":
        # MMOOOMMMM! (R): the fire wave heals Smolder (wiki: "Self Heal:
        # 100 / 135 / 170 (+ 50% bonus AD) (+ 75% AP)").  Flat heal per
        # cast, unlinked from the damage row.
        r = _ability(champion_data, "R")
        r_rank = _rank(ability_damages, "R")
        r_heal = extract_named(r, "Self Heal", r_rank, champion_stats)
        for event in _attributed_events(
            damage_events, lambda source, _event: source == "R"
        ):
            _heal_from_damage(
                healing, event, r_heal, "MMOOOMMMM!", link_to_damage=False
            )

    elif name == "Sylas":
        # Kingslayer (W): if the strike damages a champion, Sylas is healed
        # for an amount scaled by his missing health (wiki: "Minimum Heal" /
        # "Maximum Heal", doubled at 0 health).  The heal is conditional on
        # the W damage landing, so it stays linked to the damage row.
        w = _ability(champion_data, "W")
        w_rank = _rank(ability_damages, "W")
        min_heal = extract_named(w, "Minimum Heal", w_rank, champion_stats)
        max_heal = extract_named(w, "Maximum Heal", w_rank, champion_stats)
        for event in _attributed_events(
            damage_events, lambda source, _event: source == "W"
        ):
            if float(event.get("damage", 0.0)) <= 0.0:
                continue
            healing.append(
                {
                    "time": float(event.get("time", 0.0)),
                    "amount": 0.0,
                    "amount_formula": _missing_health_scaled_heal(min_heal, max_heal),
                    "source": "Kingslayer",
                    "kind": "champion_ability",
                    **_trigger_fields(event),
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
