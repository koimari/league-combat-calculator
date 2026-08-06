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


def _leveling_ratio(
    ability: dict[str, Any], attribute: str, unit_substring: str, rank: int
) -> float:
    """Read one sourced modifier whose unit contains a substring at rank.

    Some heal attributes mix modifiers with different unit vocabularies
    (flat-per-level, "% AP", "% of his missing health"); ``extract_named``
    resolves the stat-scaling ones but drops units it does not recognize,
    so the missing-health term needs its own targeted read.
    """
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") != attribute:
                continue
            for modifier in leveling.get("modifiers", []):
                units = modifier.get("units", [])
                values = modifier.get("values", [])
                if not units or not values:
                    continue
                if unit_substring.lower() not in str(units[0]).lower():
                    continue
                return float(values[min(max(rank, 1) - 1, len(values) - 1)])
    return 0.0


def _leveling_flat_at_level(
    ability: dict[str, Any], attribute: str, level: int
) -> float:
    """Read the flat (unit-less) modifier of one attribute at champion level."""
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") != attribute:
                continue
            for modifier in leveling.get("modifiers", []):
                values = modifier.get("values", [])
                units = modifier.get("units", [])
                if not values:
                    continue
                if units and str(units[0]).strip():
                    continue
                return float(values[min(max(level, 1) - 1, len(values) - 1)])
    return 0.0


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
        "Alistar",
        "Ambessa",
        "Darius",
        "Warwick",
        "Dr. Mundo",
        "Ekko",
        "Fiora",
        "Gangplank",
        "Garen",
        "Gragas",
        "Gwen",
        "Irelia",
        "Renekton",
        "Soraka",
        "Briar",
        "Vladimir",
        "Yorick",
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

    elif name == "Alistar":
        # Triumphant Roar: Q (stun + knockup) and W (knockback) each
        # generate one Triumph stack per enemy champion hit; at 7 stacks
        # the passive heals Alistar for 5% of his maximum health and
        # consumes the stacks.  Both numbers are read from the cached
        # Wiki text ("At 7 stacks, Alistar consumes them all to heal
        # himself for 5% of his maximum health").  A nearby enemy
        # champion death would grant all 7 stacks at once, but a 1v1
        # kill ends the fight before any heal receipt can apply.
        p_text = " ".join(
            effect.get("description", "")
            for effect in _ability(champion_data, "P").get("effects", [])
        )
        stack_match = re.search(r"At\s+(\d+)\s+stacks", p_text, flags=re.IGNORECASE)
        stack_cap = int(stack_match.group(1)) if stack_match else 0
        self_match = re.search(
            r"heal(?:s|ing)? himself for\s+(\d+(?:\.\d+)?)%\s+of his "
            r"maximum health",
            p_text,
            flags=re.IGNORECASE,
        )
        self_ratio = float(self_match.group(1)) / 100.0 if self_match else 0.0
        qw_seen = 0
        for event in damage_events:
            if _event_source(event) not in {"Q", "W"}:
                continue
            if stack_cap <= 0:
                break
            qw_seen += 1
            if qw_seen % stack_cap == 0:
                healing.append(
                    {
                        "time": float(event.get("time", 0.0)),
                        "amount": self_ratio * float(champion_stats.get("health", 0.0)),
                        "source": "Triumphant Roar",
                        "kind": "champion_passive",
                        **_trigger_fields(event),
                    }
                )

    elif name == "Ekko":
        # Chronobreak: flat heal at detonation, rank-scaled Minimum Heal
        # (wiki: "Heal: 100 / 150 / 200 (+ 60% AP)", increased by 0% :
        # 300% based on health lost in the last 4 seconds).  The 4-second
        # health-loss rider needs incoming-damage history the outgoing
        # ledger does not carry, so the sourced Minimum Heal is the
        # conservative floor.  Triggers at detonation even if the paired
        # R packet was fully blocked: link_to_damage=False.
        r_rank = _rank(ability_damages, "R")
        r_heal = extract_named(
            _ability(champion_data, "R"), "Minimum Heal", r_rank, champion_stats
        )
        for event in _attributed_events(
            damage_events, lambda source, _event: source == "R"
        ):
            _heal_from_damage(
                healing, event, r_heal, "Chronobreak", link_to_damage=False
            )

    elif name == "Fiora":
        # Duelist's Dance: each Vital proc heals Fiora for 35 : 100
        # (based on level) — the same sourced per-level array the module
        # prices the proc damage from ("Bonus Damage", 35 at level 1,
        # 100 at level 18).
        p_level = int(champion_stats.get("level", 0) or 0)
        p_heal = extract_named(
            _ability(champion_data, "P"), "Bonus Damage", p_level, champion_stats
        )
        for event in _attributed_events(
            damage_events, lambda source, _event: source == "passive"
        ):
            _heal_from_damage(healing, event, p_heal, "Duelist's Dance")

    elif name == "Gangplank":
        # Remove Scurvy: flat rank heal + 90% AP + 13% missing health at
        # cast (wiki: "Heal: 45 / 70 / 95 / 120 / 145 (+ 90% AP)
        # (+ 13% missing health)").  W is a heal/cleanse with no damage
        # event, so the cast timeline is the trigger; the missing-health
        # term is a live amount_formula the survival ledger re-prices
        # from the current health at cast time.  One cast pays one
        # self-heal no matter how many defenders the pair ledger walks.
        w = _ability(champion_data, "W")
        w_rank = _rank(ability_damages, "W")
        w_flat = extract_named(w, "Heal", w_rank, champion_stats)
        w_missing_ratio = _leveling_ratio(w, "Heal", "missing health", w_rank) / 100.0

        def remove_scurvy_heal(
            current_health: float,
            maximum_health: float,
            flat: float = w_flat,
            missing_ratio: float = w_missing_ratio,
        ) -> float:
            return flat + max(0.0, maximum_health - current_health) * missing_ratio

        for cast in cast_timeline or []:
            if cast.get("slot") != "W":
                continue
            healing.append(
                {
                    "time": float(cast.get("time", 0.0)),
                    "amount": 0.0,
                    "amount_formula": remove_scurvy_heal,
                    "source": "Remove Scurvy",
                    "kind": "champion_ability",
                    "actor_wide": True,
                }
            )

    elif name == "Garen":
        # Perseverance: regenerates 0.15% : 1.01% (based on level) of
        # maximum health every 0.5 seconds, but is lost for 8 seconds
        # whenever Garen takes champion damage (refreshing on subsequent
        # damage).  The ticks are authored with the timeline's combat
        # gate (same receipt as Warmog's Heart), so a 1v1 fight — which
        # is continuous champion damage — suppresses every tick with an
        # explicit skipped receipt instead of silently emitting the
        # out-of-combat regen.  The per-0.5s array is the second "Max
        # Health Damage" leveling entry; the Wiki lists the per-5s
        # phrasing first (10x the same rate).
        p = _ability(champion_data, "P")
        p_level = int(champion_stats.get("level", 0) or 0)
        per_tick = 0.0
        for effect in p.get("effects", []):
            for leveling in effect.get("leveling", []):
                if leveling.get("attribute") != "Max Health Damage":
                    continue
                modifiers = leveling.get("modifiers", [])
                if not modifiers:
                    continue
                values = modifiers[0].get("values", [])
                if not values:
                    continue
                per_tick = (
                    float(values[min(max(p_level, 1) - 1, len(values) - 1)]) / 100.0
                )
        duration = max(0.0, float(fight_duration_seconds or 0.0))
        if per_tick > 0.0 and duration > 0.0:
            tick = 0.5
            sequence = 0
            while tick <= duration + 1e-9:
                healing.append(
                    {
                        "time": tick,
                        "amount": 0.0,
                        "amount_formula": (
                            lambda _current_health, maximum_health, ratio=per_tick: (
                                maximum_health * ratio
                            )
                        ),
                        "source": "Perseverance",
                        "kind": "regen",
                        "actor_wide": True,
                        "requires_damage_free_seconds": 8.0,
                        "sequence": sequence,
                    }
                )
                sequence += 1
                tick += 0.5

    elif name == "Gragas":
        # Happy Hour: heals for 5.5% of maximum health after each ability
        # cast (cached Wiki text: "Periodically, after casting an
        # ability, Gragas heals himself for 5.5% of his maximum
        # health").  The heal triggers on the cast, not on damage
        # landing, so the cast timeline is the source; one cast pays one
        # self-heal per fight (actor-wide receipt).
        p_text = " ".join(
            effect.get("description", "")
            for effect in _ability(champion_data, "P").get("effects", [])
        )
        ratio_match = re.search(
            r"heals himself for\s+(\d+(?:\.\d+)?)%\s+of his maximum health",
            p_text,
            flags=re.IGNORECASE,
        )
        ratio = float(ratio_match.group(1)) / 100.0 if ratio_match else 0.0
        per_cast = ratio * float(champion_stats.get("health", 0.0))
        if per_cast > 0.0:
            for cast in cast_timeline or []:
                slot = cast.get("slot")
                if slot not in {"Q", "W", "E", "R"}:
                    continue
                healing.append(
                    {
                        "time": float(cast.get("time", 0.0)),
                        "amount": per_cast,
                        "source": f"Happy Hour · {slot}",
                        "kind": "champion_passive",
                        "actor_wide": True,
                    }
                )

    elif name == "Gwen":
        # A Thousand Cuts: heals for 50% of the passive instance's
        # post-mitigation damage dealt against champions, capped per
        # instance at 10 : 25 (based on level) (+ 6.5% AP) (cached Wiki
        # text is explicit about the post-mitigation basis, the same
        # qualification Aatrox's Deathbringer Stance carries — the
        # engine's post-mitigation event value is the sourced basis
        # here, unlike lifesteal-style heals whose Wiki text does not
        # qualify the basis).  The module emits the passive as
        # auto-attack on-hit instances ("on_hit_ability_passive"); Q
        # center / Needlework rider instances are folded into their
        # ability totals and are not separately receipted.
        p_level = int(champion_stats.get("level", 0) or 0)
        per_instance_cap = extract_named(
            _ability(champion_data, "P"), "Bonus Damage", p_level, champion_stats
        )
        for event in _attributed_events(
            damage_events,
            lambda source, _event: source == "on_hit_ability_passive",
        ):
            dealt = float(event.get("damage", 0.0))
            _heal_from_damage(
                healing,
                event,
                min(0.50 * dealt, per_instance_cap),
                "A Thousand Cuts",
            )

    elif name == "Yorick":
        # Last Rites: the empowered attack heals Yorick for 10 : 78
        # (based on level) + 6% : 10% (based on rank) of his missing
        # health against champions (reduced 50% against non-champions;
        # the 1v1 model only prices the champion branch).  The flat term
        # is per-LEVEL while the missing-health term is per-RANK, so the
        # two modifiers are read independently; the missing-health term
        # is a live amount_formula the survival ledger re-prices from
        # the current health at the empowered hit.
        q = _ability(champion_data, "Q")
        q_rank = _rank(ability_damages, "Q")
        q_level = int(champion_stats.get("level", 0) or 0)
        q_flat = _leveling_flat_at_level(q, "Heal", q_level)
        q_missing_ratio = _leveling_ratio(q, "Heal", "missing health", q_rank) / 100.0

        def last_rites_heal(
            current_health: float,
            maximum_health: float,
            flat: float = q_flat,
            missing_ratio: float = q_missing_ratio,
        ) -> float:
            return flat + max(0.0, maximum_health - current_health) * missing_ratio

        for event in _attributed_events(
            damage_events, lambda source, _event: source == "Q"
        ):
            healing.append(
                {
                    "time": float(event.get("time", 0.0)),
                    "amount": 0.0,
                    "amount_formula": last_rites_heal,
                    "source": "Last Rites",
                    "kind": "champion_ability",
                    **_trigger_fields(event),
                }
            )

    return sorted(healing, key=lambda event: (event["time"], event["source"]))
