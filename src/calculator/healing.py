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

from .champions.slotlib import extract_named, find_named_leveling, sum_modifiers


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


def _leveling_modifier(
    ability: dict[str, Any], attribute: str, rank: int, modifier_index: int = 0
) -> float:
    """Read one sourced leveling modifier at rank without scaling resolution.

    ``extract_named`` sums every modifier and resolves stat-scaling units,
    but a missing-health percentage (e.g. Tahm Kench's ``"% of missing
    health"``) is not a stat the scaling layer knows, so it resolves to 0.0.
    This helper reads the raw percentage value for those formula components;
    the caller folds it into an amount formula evaluated against the
    fighter's live health.
    """
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            if leveling.get("attribute") != attribute:
                continue
            modifiers = leveling.get("modifiers", [])
            if modifier_index >= len(modifiers):
                return 0.0
            values = modifiers[modifier_index].get("values", [])
            if not values:
                return 0.0
            return float(values[min(max(rank, 1) - 1, len(values) - 1)])
    return 0.0


def _ability(
    champion_data: dict[str, Any], slot: str, index: int = 0
) -> dict[str, Any]:
    entries = champion_data.get("abilities", {}).get(slot, [])
    if index >= len(entries):
        return {}
    return entries[index] if isinstance(entries[index], dict) else {}


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
        "Ahri",
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
        "Illaoi",
        "Irelia",
        "Karma",
        "Nami",
        "Nilah",
        "Renekton",
        "Soraka",
        "Briar",
        "Vladimir",
        "Kayle",
        "Kha'Zix",
        "Kindred",
        "Lissandra",
        "Master Yi",
        "Nidalee",
        "Naafiri",
        "Senna",
        "Smolder",
        "Sylas",
        "Tahm Kench",
        "Tryndamere",
        "Volibear",
        "Zac",
        "Rakan",
        "Sona",
        "Janna",
        "Milio",
        "Taric",
        "Zaahen",
        "Aphelios",
        "Camille",
        "Fiddlesticks",
        "Hecarim",
        "Swain",
        "Trundle",
        "Xin Zhao",
        "Yorick",
        "Udyr",
        "Yuumi",
        "Morgana",
        "Talon",
        "Nunu & Willump",
        "Shyvana",
        "Nasus",
    }
)

# Grey-health champions whose self-heals are sourced from damage TAKEN
# (post-mitigation) stored as a grey pool, then paid back when the
# champion's active consumes it (Pyke P out-of-vision, Rengar W, Tahm
# Kench E out-of-combat, Mordekaiser W recast).  The 1v1 heal derivation
# below only sees the main's OUTGOING events, so these receipts are
# authored by the participant timeline against its incoming ledger (the
# enemy -> main pair events) rather than here; the set is shared so the
# timeline and this module stay in one source of truth.  Kled's Skaarl
# pool is a revive-boundary pattern (dismount/remount) and is documented
# in the Kled module, not authored as a heal.
GREY_HEALTH_RULE_CHAMPIONS = frozenset(
    {"Pyke", "Rengar", "Tahm Kench", "Mordekaiser", "Locke"}
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

    if name == "Ahri":
        # Essence Theft (P): at 9 Essence Fragments the passive heals Ahri
        # for 35 : 95 (based on level) (+ 20% AP) and consumes the stacks
        # (cached P "Heal" leveling row; the fragment count is player state
        # the module exposes as ``p_essence_fragments``).  The module emits
        # the P receipt only when the user has 9+ fragments, and the fight
        # does not simulate fragment generation mid-duel, so one completed
        # 9-stack cycle heals once — on the first ability that hits the
        # enemy champion (the "next ability" that consumes them).
        if "passive" in ability_damages:
            # The module emits the P receipt only at 9+ fragments.
            level = int(champion_stats.get("level", 0) or 0)
            heal = extract_named(
                _ability(champion_data, "P"), "Heal", level, champion_stats
            )
            for event in damage_events:
                source = _event_source(event)
                if source not in {"Q", "W", "E", "R"}:
                    continue
                _heal_from_damage(
                    healing,
                    event,
                    heal,
                    "Essence Theft",
                    link_to_damage=False,
                )
                break

    elif name == "Aatrox":
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

    elif name == "Illaoi":
        # Prophet of an Elder God: "Each Tentacle also heals Illaoi for 5%
        # of her missing health if it hits at least one enemy champion"
        # (cached P description prose).  Every tentacle champion hit — the
        # module's P proc events, whose source key is ``passive`` — is one
        # heal of 5% of the missing health at the hit's timestamp, priced
        # by the participant ledger with the fighter's live health (the
        # Decimate missing-health pattern).
        tentacle_hits = _attributed_events(
            damage_events, lambda source, _event: source == "passive"
        )
        for event in tentacle_hits:
            healing.append(
                {
                    "time": float(event.get("time", 0.0)),
                    "amount": 0.0,
                    "amount_formula": lambda current_health, maximum_health: (
                        max(0.0, maximum_health - current_health) * 0.05
                    ),
                    "source": "Prophet of an Elder God",
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
        # P (Crimson Curse) bleed self-heal: "The bleed always heals Briar
        # for 25% of the pre-mitigation damage dealt" (cached passive prose).
        # The bleed's own per-stack heal rows (2.5 : 12.5 + 12.5% bonus AD
        # per stack, +25% per extra-stack share) are exactly 25% of the
        # pre-mitigation bleed damage at every stack level, so one sourced
        # rule prices the whole stream.  The wiki's missing-health healing
        # amplifier (0% : 40%) is a live-state boundary, not priced here.
        for event in _attributed_events(
            damage_events,
            lambda source, _event: source.startswith("stacking_dot_"),
        ):
            dealt = float(event.get("raw_damage", event.get("damage", 0.0)) or 0.0)
            amount = 0.25 * dealt
            if amount > 0.0:
                healing.append(
                    {
                        "time": float(event.get("time", 0.0)),
                        "amount": amount,
                        "source": "Crimson Curse",
                        "kind": "champion_passive",
                        **_trigger_fields(event),
                    }
                )
        # W[1] (Snack Attack): "healing her for 5% of her maximum health
        # plus a percentage of the post-mitigation damage dealt" — the
        # percentage is the sourced "Heal Percentage" row (24 / 28 / 32 /
        # 36 / 40% by rank).  The heal pays at the bite's hit event.
        w_rank = _rank(ability_damages, "W")
        heal_percent = extract_named(
            _ability(champion_data, "W", 1),
            "Heal Percentage",
            w_rank,
            champion_stats,
            {},
        )
        max_health = float(champion_stats.get("health", 0.0) or 0.0)
        for event in _attributed_events(
            damage_events, lambda source, _event: source == "W"
        ):
            snack_heal = (
                0.05 * max_health
                + float(event.get("damage", 0.0) or 0.0) * heal_percent / 100.0
            )
            _heal_from_damage(healing, event, snack_heal, "Snack Attack")
        # R (Certain Death) grants life steal (10 / 15 / 20% by rank) while
        # Hematomania lasts; life steal heals for the sourced percentage of
        # the post-mitigation damage dealt by basic attacks.
        r_rank = _rank(ability_damages, "R")
        life_steal = extract_named(
            _ability(champion_data, "R"), "Life Steal", r_rank, champion_stats, {}
        )
        if life_steal > 0.0:
            for event in _attributed_events(
                damage_events, lambda source, _event: source == "auto_attacks"
            ):
                _heal_from_damage(
                    healing,
                    event,
                    float(event.get("damage", 0.0) or 0.0) * life_steal / 100.0,
                    "Certain Death",
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
        # W passive Hunter's Vigor: at 100 stacks the next basic attack
        # heals Kindred for 0% : 100% (based on her missing health) of the
        # sourced per-level heal (47 : 81, data/champions.json W "Heal"
        # per-level row).  The module emits the W_vigor receipt only at
        # 100 stacks; the heal pays on the first basic-attack damage event
        # (the deterministic next auto) and is naturally zero at full
        # health (the wiki says it is not triggered there).
        if "W_vigor" in ability_damages:
            level = int(champion_stats.get("level", 18) or 18)
            heal = extract_named(
                _ability(champion_data, "W"), "Heal", level, champion_stats, {}
            )
            for event in _attributed_events(
                damage_events, lambda source, _event: source == "auto_attacks"
            ):
                healing.append(
                    {
                        "time": float(event.get("time", 0.0)),
                        "amount": 0.0,
                        "amount_formula": _missing_health_scaled_heal(0.0, heal),
                        "source": "Hunter's Vigor",
                        "kind": "champion_passive",
                        **_trigger_fields(event),
                    }
                )
                break

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

    elif name == "Naafiri":
        # Darkin Daggers (Q) recast: "If that target is also a champion or
        # large monster, Naafiri heals herself" (cached Q description).
        # The heal is the cached "Heal" row (45 : 105 by rank + 40% bonus
        # AD) and fires once per Q cast — the recast hits the already-
        # bleeding champion the module prices as the Q entry's second stage.
        # The scanner is excluded from this slot (support_effects
        # ``_MODULE_AUTHORED_HEAL_SLOTS``) so the champion-owned ledger is
        # the single receipt.
        q_rank = _rank(ability_damages, "Q")
        q_heal = extract_named(
            _ability(champion_data, "Q"), "Heal", q_rank, champion_stats
        )
        # One heal per Q cast: the module emits the initial hit at the
        # cast boundary, then the bleed ticks and the recast share later
        # timestamps, so the heal anchors to the cast's initial-hit event
        # (the recast hits an already-bleeding champion the same cast).
        q_events = _attributed_events(
            damage_events, lambda source, _event: source == "Q"
        )
        q_event_by_time: dict[float, dict[str, Any]] = {}
        for event in q_events:
            q_event_by_time.setdefault(round(float(event.get("time", 0.0)), 6), event)
        for cast_time in _cast_slot_times(cast_timeline, "Q"):
            anchor = q_event_by_time.get(round(cast_time, 6))
            if anchor is None:
                continue
            _heal_from_damage(
                healing,
                anchor,
                q_heal,
                "Darkin Daggers",
                link_to_damage=False,
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

    elif name == "Tahm Kench":
        # Tongue Lash heals Tahm Kench for a flat amount plus a percentage
        # of his missing health whenever it hits an enemy champion (wiki:
        # "Heal: 10 / 15 / 20 / 25 / 30 (+ 5% / 5.5% / 6% / 6.5% / 7% of
        # missing health)").  The missing-health percentage is not a stat
        # scaling, so ``extract_named`` resolves only the flat part; the
        # percentage is read as the second modifier and folded into a
        # missing-health formula the participant ledger materializes with
        # the fighter's live health (Decimate pattern).
        q = _ability(champion_data, "Q")
        q_rank = _rank(ability_damages, "Q")
        q_flat = extract_named(q, "Heal", q_rank, champion_stats, {})
        q_missing_pct = _leveling_modifier(q, "Heal", q_rank, 1)

        def tongue_lash_heal(
            current_health: float,
            maximum_health: float,
            flat: float = q_flat,
            missing_pct: float = q_missing_pct,
        ) -> float:
            return (
                flat + max(0.0, maximum_health - current_health) * missing_pct / 100.0
            )

        for event in _attributed_events(
            damage_events, lambda source, _event: source == "Q"
        ):
            healing.append(
                {
                    "time": float(event.get("time", 0.0)),
                    "amount": 0.0,
                    "amount_formula": tongue_lash_heal,
                    "source": "Tongue Lash",
                    "kind": "champion_ability",
                    **_trigger_fields(event),
                }
            )

    elif name == "Tryndamere":
        # Bloodlust consumes all Fury to heal.  The fight model does not
        # track Fury, so the sourced receipt is the 0-Fury minimum the wiki
        # publishes as its own leveling value: "Minimum Heal: 30 / 40 /
        # 50 / 60 / 70 (+ 30% AP)".  E5-1 removed the spurious Q
        # magic-damage row (Bloodlust is a pure heal), so the heal now
        # anchors to the Q cast timeline — the same trigger receipt Kayle W
        # and Kindred R use for no-damage abilities — instead of a Q damage
        # event that no longer exists.
        q_rank = _rank(ability_damages, "Q")
        amount = extract_named(
            _ability(champion_data, "Q"), "Minimum Heal", q_rank, champion_stats
        )
        for cast_time in _cast_slot_times(cast_timeline, "Q"):
            healing.append(
                {
                    "time": cast_time,
                    "amount": amount,
                    "source": "Bloodlust",
                    "kind": "champion_ability",
                    "actor_wide": True,
                }
            )

    elif name == "Volibear":
        # Frenzied Maul's Wounded bonus: biting an already-Wounded target
        # heals Volibear for a flat amount plus a percentage of his missing
        # health (wiki: "Heal: 20 / 35 / 50 / 65 / 80 (+ 8% / 11% / 14% /
        # 17% / 20% of his missing health)").  The first W applies the
        # Wound; the heal lands on every later W.  Each pair fight is one
        # defender, so counting W events in this ledger is per-target.
        w = _ability(champion_data, "W")
        w_rank = _rank(ability_damages, "W")
        w_flat = extract_named(w, "Heal", w_rank, champion_stats, {})
        w_missing_pct = _leveling_modifier(w, "Heal", w_rank, 1)

        def frenzied_maul_heal(
            current_health: float,
            maximum_health: float,
            flat: float = w_flat,
            missing_pct: float = w_missing_pct,
        ) -> float:
            return (
                flat + max(0.0, maximum_health - current_health) * missing_pct / 100.0
            )

        w_hits = 0
        for event in _attributed_events(
            damage_events, lambda source, _event: source == "W"
        ):
            w_hits += 1
            if w_hits < 2:
                continue
            healing.append(
                {
                    "time": float(event.get("time", 0.0)),
                    "amount": 0.0,
                    "amount_formula": frenzied_maul_heal,
                    "source": "Frenzied Maul",
                    "kind": "champion_ability",
                    **_trigger_fields(event),
                }
            )

    elif name == "Zac":
        # Cell Division: each ability hit sheds a Goo chunk that Zac
        # consumes to heal for 4% : 8.47% (based on level) of his maximum
        # health (passive leveling attribute "Max Health Damage", one value
        # per champion level).  In a 1v1 every Q/W/E/R damage event is one
        # collected chunk; R's per-bounce chunks collapse to one receipt
        # per cast, the sourced minimum.
        p = _ability(champion_data, "P")
        level = int(champion_stats.get("level", 18) or 18)
        chunk_pct = extract_named(p, "Max Health Damage", level, champion_stats, {})

        def cell_division_heal(
            _current_health: float,
            maximum_health: float,
            pct: float = chunk_pct,
        ) -> float:
            return maximum_health * pct / 100.0

        for event in _attributed_events(
            damage_events, lambda source, _event: source in {"Q", "W", "E", "R"}
        ):
            healing.append(
                {
                    "time": float(event.get("time", 0.0)),
                    "amount": 0.0,
                    "amount_formula": cell_division_heal,
                    "source": "Cell Division",
                    "kind": "champion_passive",
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

    elif name == "Karma":
        # Renewal (Mantra-empowered W): "Karma heals for 17% (+ 1% per 100
        # AP) of her missing health once on-cast, and again once the tether
        # lasts its full duration or the target dies while tethered."  The
        # tether lasts 2 seconds (the packet module prices the completion
        # hit at +2.0s).  The heal is a missing-health formula priced by
        # the coupled timeline at each heal's timestamp (Darius pattern);
        # the Mantra variant only exists when the parse picked it (its
        # parsed name is "Renewal").  Flat trigger: the heal lands on-cast
        # even if the paired W packet was fully blocked.
        if str(ability_damages.get("W", {}).get("name", "")) == "Renewal":
            ap = float(champion_stats.get("ability_power", 0.0) or 0.0)
            ratio = 0.17 + ap / 10000.0

            def _renewal_heal(current_health: float, maximum_health: float) -> float:
                return max(0.0, maximum_health - current_health) * ratio

            for cast in cast_timeline or []:
                if cast.get("slot") != "W":
                    continue
                cast_time = float(cast.get("time", 0.0))
                for offset in (0.0, 2.0):
                    healing.append(
                        {
                            "time": cast_time + offset,
                            "amount": 0.0,
                            "amount_formula": _renewal_heal,
                            "source": "Renewal",
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
        # Cozy Campfire (W): the fuemigo heals Milio himself — "Milio counts
        # as an allied champion for this ability" — every tick over its
        # 6-second duration (wiki: "Heal per Tick: 2.8 / 3.6 / 4.4 / 5.2 / 6
        # (+ 0.6% AP)"; "Total Heal: 70 / 90 / 110 / 130 / 150 (+ 15% AP)").
        # The tick count is sourced from the Total/PerTick ratio (25) and
        # spread across the 6s duration -> 0.24s intervals.  The 0.264s
        # cadence in the description does not reconcile to the sourced 25
        # ticks, so the ratio-derived count wins, exactly as Janna's Monsoon
        # is handled.  W deals no enemy damage, so the W cast timeline is
        # the sourced trigger.
        w_rank = _rank(ability_damages, "W")
        w_ability = _ability(champion_data, "W")
        w_per_tick = extract_named(w_ability, "Heal per Tick", w_rank, champion_stats)
        w_total = extract_named(w_ability, "Total Heal", w_rank, champion_stats)
        w_tick_count = (
            max(1, min(100, int(round(w_total / w_per_tick))))
            if w_per_tick > 0.0 and w_total > 0.0
            else 25
        )
        if w_per_tick > 0.0:
            for cast in cast_timeline or []:
                if cast.get("slot") != "W":
                    continue
                start = float(cast.get("time", 0.0))
                for index in range(1, w_tick_count + 1):
                    healing.append(
                        {
                            "time": start + index * 0.24,
                            "amount": float(w_per_tick),
                            "source": "Cozy Campfire",
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
    elif name == "Nami":
        # Ebb and Flow (W): cast on the enemy, the stream bounces to Nami
        # next, so her self-heal is the first bounce — "each bounce
        # modifying the effectiveness of the next by -20% (+ 15% per 100
        # AP)" of the original, never below the sourced Minimum Heal.
        # Flat per cast: the heal lands even if the paired W damage packet
        # was fully blocked.
        w_rank = _rank(ability_damages, "W")
        w_ability = _ability(champion_data, "W")
        base = extract_named(w_ability, "Heal", w_rank, champion_stats, {})
        floor = extract_named(w_ability, "Minimum Heal", w_rank, champion_stats, {})
        ap = float(champion_stats.get("ability_power", 0.0) or 0.0)
        amount = max(floor, base * (0.80 + 0.15 * ap / 100.0))
        for event in _attributed_events(
            damage_events, lambda source, _event: source == "W"
        ):
            _heal_from_damage(
                healing, event, amount, "Ebb and Flow", link_to_damage=False
            )

    elif name == "Nilah":
        # Q passive: basic attacks and Formless Blade heal her for
        # 0%-20% (based on critical strike chance) of the post-mitigation
        # damage dealt to champions.  Apotheosis (R): heals her for
        # 20%-50% (based on critical strike chance) of the post-mitigation
        # damage dealt to champions.  Both scale linearly with crit.
        crit = max(
            0.0,
            min(
                100.0,
                float(champion_stats.get("critical_strike_chance", 0.0) or 0.0),
            ),
        )
        q_ratio = 0.20 * crit / 100.0
        r_ratio = 0.20 + 0.30 * crit / 100.0
        for event in damage_events:
            source = _event_source(event)
            if source in ("Q", "auto_attacks") and q_ratio > 0.0:
                _heal_from_damage(
                    healing,
                    event,
                    float(event.get("damage", 0.0)) * q_ratio,
                    "Formless Blade",
                )
            elif source == "R" and r_ratio > 0.0:
                _heal_from_damage(
                    healing,
                    event,
                    float(event.get("damage", 0.0)) * r_ratio,
                    "Apotheosis",
                )

    elif name == "Zaahen":
        # The Darkin Glaive (Q): the empowered attack heals him for
        # "Champion Healing" — 5 / 6 / 7 / 8 / 9% of his maximum health
        # (halved against minions/monsters; champion targets assumed).  The
        # wiki unit ("% of his maximum health") is not a slotlib-recognised
        # unit, so the percent is read raw and priced against the sourced
        # max health.  Flat trigger: the heal lands on-attack even if the
        # paired strike packet was fully blocked.
        q_rank = _rank(ability_damages, "Q")
        q_heal_pct = _leveling_value(
            _ability(champion_data, "Q"), "Champion Healing", q_rank
        )
        q_heal = q_heal_pct / 100.0 * float(champion_stats.get("health", 0.0))
        for event in _attributed_events(
            damage_events, lambda source, _event: source == "Q"
        ):
            _heal_from_damage(
                healing, event, q_heal, "The Darkin Glaive", link_to_damage=False
            )
        # Grim Deliverance (R): flat heal per champion hit
        # ("Healing per Champion hit": 82.5 / 132 / 181.5 (+ 66% bonus
        # AD)); the 1v1 pair fight sees exactly one hit per R cast.
        r_rank = _rank(ability_damages, "R")
        r_heal = extract_named(
            _ability(champion_data, "R"),
            "Healing per Champion hit",
            r_rank,
            champion_stats,
            {},
        )
        for event in _attributed_events(
            damage_events, lambda source, _event: source == "R"
        ):
            _heal_from_damage(
                healing, event, r_heal, "Grim Deliverance", link_to_damage=False
            )

    elif name == "Aphelios":
        # Severum (main-weapon passive): its attacks heal for a per-level
        # percent of the POST-mitigation damage dealt (wiki P[2] Severum:
        # "2% : 7.1% (based on level) of the post-mitigation damage dealt,
        # increased to 5% : 17.75% (based on level) for attacks from
        # abilities").  The parser stamps the chosen main weapon on Moonlight
        # Vigil's entry detail, so the rule is gated on that receipt rather
        # than assuming a weapon.  The R follow-up's flat Severum heal
        # (250/350/450) belongs to attacks the engine does not emit as
        # events, so only the on-hit passive is modeled.
        r_detail = str(ability_damages.get("R", {}).get("detail", ""))
        if "Severum" in r_detail:
            severum = next(
                (
                    entry
                    for entry in champion_data.get("abilities", {}).get("P", [])
                    if isinstance(entry, dict) and entry.get("name") == "Severum"
                ),
                {},
            )
            level = int(champion_stats.get("level", 18))
            basic_scaling = find_named_leveling(severum, "Per-Level Scaling", 0)
            ability_scaling = find_named_leveling(severum, "Per-Level Scaling", 1)
            basic_ratio = (
                sum_modifiers(basic_scaling, level, champion_stats, {}) / 100.0
                if basic_scaling is not None
                else 0.0
            )
            ability_ratio = (
                sum_modifiers(ability_scaling, level, champion_stats, {}) / 100.0
                if ability_scaling is not None
                else 0.0
            )
            # Severum's wiki passive converts excess healing into a shield
            # capped at the per-level "Heal" row (10 : 160 by level + 6%
            # maximum health), lingering for up to 30 seconds.  In the
            # fight's deterministic state the conversion is driven by the
            # survival walk: each heal event carries the sourced cap and
            # duration, and the participant timeline converts the excess
            # (heal in excess of the fighter's maximum health, i.e. all of
            # it while at full health) into a timed shield (the
            # ``_apply_overheal_shield`` receipt).
            heal_leveling = find_named_leveling(severum, "Heal")
            shield_cap = (
                sum_modifiers(heal_leveling, level, champion_stats, {})
                if heal_leveling is not None
                else 0.0
            )
            # The module stamps the option state on Moonlight Vigil's
            # detail (the Shyvana dragon-form convention): "overheal shield
            # on" when the user enabled the conversion (default on).
            overheal_shield = "overheal shield on" in r_detail
            for event in damage_events:
                source = _event_source(event)
                if source == "auto_attacks":
                    ratio = basic_ratio
                elif source == "Q":
                    # With Severum equipped the Q row is Onslaught, whose
                    # attacks count as ability attacks for the heal.
                    ratio = ability_ratio
                else:
                    continue
                amount = max(0.0, float(event.get("damage", 0.0))) * ratio
                _heal_from_damage(healing, event, amount, "Severum")
                if overheal_shield and amount > 0.0 and shield_cap > 0.0:
                    healing[-1]["overheal_to_shield"] = True
                    healing[-1]["overheal_shield_cap"] = shield_cap
                    healing[-1]["overheal_shield_duration"] = 30.0

    elif name == "Camille":
        # Tactical Sweep's outer half deals bonus damage and heals Camille
        # for 100% of that additional damage post-mitigation (wiki W
        # effect[1]).  The engine prices the W row as the sourced base
        # physical damage plus the outer-cone sweet spot, so the outer
        # portion is the raw surplus over that base; both parts share the
        # same armor mitigation, so the post-mit outer amount is the surplus
        # scaled by damage/raw.  With the outer cone option off the surplus
        # is zero and nothing heals.
        w_ability = _ability(champion_data, "W")
        w_rank = _rank(ability_damages, "W")
        base_raw = extract_named(
            w_ability, "Physical Damage", w_rank, champion_stats, {}
        )
        for event in _attributed_events(
            damage_events, lambda source, _event: source == "W"
        ):
            raw = float(event.get("raw_damage", event.get("damage", 0.0)) or 0.0)
            post = float(event.get("damage", 0.0) or 0.0)
            outer_raw = max(0.0, raw - base_raw)
            amount = outer_raw * (post / raw) if raw > 0.0 else 0.0
            _heal_from_damage(healing, event, amount, "Tactical Sweep")

    elif name == "Fiddlesticks":
        # Bountiful Harvest drains its tether and "heals itself for a
        # portion of the pre-mitigation damage dealt" per tick (wiki W
        # effect[2]); the Champion Heal Portion is 25%-55% by rank.  Each
        # drain tick the engine emits is one W damage event, so every W
        # event heals that portion of its pre-mitigation damage.
        w_ability = _ability(champion_data, "W")
        w_rank = _rank(ability_damages, "W")
        portion = (
            extract_named(
                w_ability, "Champion Heal Portion", w_rank, champion_stats, {}
            )
            / 100.0
        )
        for event in _attributed_events(
            damage_events, lambda source, _event: source == "W"
        ):
            dealt = float(event.get("raw_damage", event.get("damage", 0.0)) or 0.0)
            _heal_from_damage(healing, event, portion * dealt, "Bountiful Harvest")

    elif name == "Hecarim":
        # Spirit of Dread: while active (4 seconds per W cast) Hecarim is
        # healed for 25% of the post-mitigation damage dealt to enemies in
        # the area from all sources (wiki W effect[1]).  The sourced cap
        # applies only to minions and monsters, so a champion duel uses the
        # uncapped 25%.  Window membership comes from the engine's own cast
        # timeline, and every damaging event inside the window (including
        # the W ticks themselves) is a valid trigger.
        w_casts = [
            float(cast.get("time", 0.0))
            for cast in (cast_timeline or [])
            if cast.get("slot") == "W"
        ]
        if w_casts:
            for event in damage_events:
                event_time = float(event.get("time", 0.0))
                if not any(
                    cast_time <= event_time <= cast_time + 4.0 for cast_time in w_casts
                ):
                    continue
                amount = 0.25 * max(0.0, float(event.get("damage", 0.0)))
                _heal_from_damage(healing, event, amount, "Spirit of Dread")

    elif name == "Swain":
        # Demonic Ascension drains nearby enemies, healing a flat amount per
        # 0.5-second tick per target affected (wiki R effect[1]: Heal per
        # Tick 7.5/15/22.5 + 2.5% AP + 0.75% of his bonus health).  The
        # Reduced Heal per Tick entry is the 90%-reduced minion/monster
        # variant, so a champion duel pays the full amount.  The engine's R
        # packet prices one drain tick per cast, so each R event heals one
        # tick's flat value.  The "% of his bonus health" unit is not a
        # generic scaling unit, so it is resolved with an explicit override
        # rather than silently dropped.
        r_ability = _ability(champion_data, "R")
        r_rank = _rank(ability_damages, "R")
        heal_leveling = find_named_leveling(r_ability, "Heal per Tick")

        def swain_bonus_health(unit: str, value: float) -> float | None:
            if unit == "% of his bonus health":
                return value / 100.0 * float(champion_stats.get("bonus_health", 0.0))
            return None

        heal_per_tick = (
            sum_modifiers(
                heal_leveling,
                r_rank,
                champion_stats,
                {},
                modifier_override=swain_bonus_health,
            )
            if heal_leveling is not None
            else 0.0
        )
        for event in _attributed_events(
            damage_events, lambda source, _event: source == "R"
        ):
            _heal_from_damage(
                healing,
                event,
                heal_per_tick,
                "Demonic Ascension",
                link_to_damage=False,
            )

    elif name == "Trundle":
        # Subjugate drains the target, "dealing magic damage and healing
        # himself for the same amount" (wiki R effect[0]); Total Healing and
        # Total Magic Damage share the same % of the target's maximum health
        # leveling values.  The engine's R event carries the drain's
        # pre-mitigation damage, which is exactly the heal amount — the heal
        # does not pass through magic resistance.
        for event in _attributed_events(
            damage_events, lambda source, _event: source == "R"
        ):
            dealt = float(event.get("raw_damage", event.get("damage", 0.0)) or 0.0)
            _heal_from_damage(healing, event, dealt, "Subjugate", link_to_damage=False)

    elif name == "Xin Zhao":
        # Wind Becomes Lightning's damage "heals Xin Zhao for 33.3% of his
        # life steal" (wiki W effect[1]): the W damage applies his lifesteal
        # at 33.3% effectiveness.  With no lifesteal source the heal is
        # zero, so the rule only emits when the build actually carries
        # lifesteal.
        lifesteal = float(champion_stats.get("lifesteal_percent", 0.0) or 0.0)
        if lifesteal > 0.0:
            for event in _attributed_events(
                damage_events, lambda source, _event: source == "W"
            ):
                amount = (
                    0.333
                    * max(0.0, float(event.get("damage", 0.0)))
                    * lifesteal
                    / 100.0
                )
                _heal_from_damage(healing, event, amount, "Wind Becomes Lightning")

    if name == "Nasus":
        # Soul Eater (P): innate lifesteal — "Nasus gains 12% / 18% / 24%
        # (based on level) life steal" (cached P description).  The exact
        # breakpoints are the game-file LifestealTooltip (12% at level 1,
        # +6% at level 7, +6% at level 13 — verified in the game files via
        # Community Dragon NasusPassive, NOT the wiki, whose page omits
        # the levels).  Lifesteal heals the sourced % of post-mitigation
        # physical basic-attack and on-hit damage dealt, mirroring the
        # engine's lifesteal eligibility for items (auto_attacks and
        # on_hit_* rows, physical only) so the passive behaves like the
        # stat it replaces.
        nasus_level = max(1, int(champion_stats.get("level", 18) or 18))
        soul_eater_ratio = (
            0.24 if nasus_level >= 13 else (0.18 if nasus_level >= 7 else 0.12)
        )
        for event in damage_events:
            source = _event_source(event)
            if source != "auto_attacks" and not source.startswith("on_hit_"):
                continue
            if event.get("damage_type") != "physical":
                continue
            amount = max(0.0, float(event.get("damage", 0.0))) * soul_eater_ratio
            _heal_from_damage(healing, event, amount, "Soul Eater")

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

    elif name == "Master Yi":
        # Meditate channels for up to 4 seconds, healing Master Yi every
        # 0.5 seconds, increased by 0% : 100% (based on missing health)
        # between the sourced Minimum Heal Per Tick and Maximum Heal Per
        # Tick rows (8 ticks; Minimum/Maximum Total Heal == 8 x per-tick at
        # every rank).  W deals no enemy damage, so the W cast timeline is
        # the sourced trigger (Kayle W / Kindred R pattern).
        w_rank = _rank(ability_damages, "W")
        w_ability = _ability(champion_data, "W")
        min_tick = extract_named(
            w_ability, "Minimum Heal Per Tick", w_rank, champion_stats
        )
        max_tick = extract_named(
            w_ability, "Maximum Heal Per Tick", w_rank, champion_stats
        )
        if min_tick > 0.0:
            for cast_time in _cast_slot_times(cast_timeline, "W"):
                start = float(cast_time)
                for index in range(1, 9):
                    healing.append(
                        {
                            "time": start + index * 0.5,
                            "amount": 0.0,
                            "amount_formula": _missing_health_scaled_heal(
                                min_tick, max_tick
                            ),
                            "source": "Meditate",
                            "kind": "champion_ability",
                            "actor_wide": True,
                        }
                    )

    elif name == "Udyr":
        # Iron Mantle (W): the shield stance heals every 0.25 s over 4 s
        # (wiki: "Heal per Tick" x16 == "Total Healing", e2-dot-3 sourced).
        w_rank = _rank(ability_damages, "W")
        per_tick = extract_named(
            _ability(champion_data, "W"), "Heal per Tick", w_rank, champion_stats
        )
        if per_tick > 0.0:
            for cast in cast_timeline or []:
                if cast.get("slot") != "W":
                    continue
                start = float(cast.get("time", 0.0))
                for index in range(1, 17):
                    healing.append(
                        {
                            "time": start + index * 0.25,
                            "amount": float(per_tick),
                            "source": "Iron Mantle",
                            "kind": "champion_ability",
                            "actor_wide": True,
                        }
                    )

    elif name == "Yuumi":
        # Final Chapter (R): each of the 5 waves heals (wiki: "Heal per
        # Hit" x5 == "Total Heal", e2-dot-3 sourced); waves at 0.7 s.
        r_rank = _rank(ability_damages, "R")
        per_wave = extract_named(
            _ability(champion_data, "R"), "Heal per Hit", r_rank, champion_stats
        )
        if per_wave > 0.0:
            for cast in cast_timeline or []:
                if cast.get("slot") != "R":
                    continue
                start = float(cast.get("time", 0.0))
                for index in range(5):
                    healing.append(
                        {
                            "time": start + index * 0.7,
                            "amount": float(per_wave),
                            "source": "Final Chapter",
                            "kind": "champion_ability",
                            "actor_wide": True,
                        }
                    )

    elif name == "Morgana":
        # Soul Siphon: "heals herself for 18% of the post-mitigation
        # damage dealt by her abilities against champions, large
        # minions, and medium and large monsters" (wiki P).  In a
        # champion duel every Q/W/R damage event is ability damage
        # against the champion target (W's storm ticks included); E is
        # a shield and deals no damage.
        for event in damage_events:
            if _event_source(event) not in {"Q", "W", "R"}:
                continue
            _heal_from_damage(
                healing,
                event,
                0.18 * max(0.0, float(event.get("damage", 0.0))),
                "Soul Siphon",
            )

    elif name == "Talon":
        # Noxian Diplomacy: "If Noxian Diplomacy kills the target, Talon
        # heals for 9 : 60.41 (based on level) and the ability's
        # cooldown is reduced by 50%" (wiki Q effect[1]).  The heal is
        # a per-LEVEL flat (20 values, independent of Q rank); the kill
        # condition is state the outgoing ledger cannot identify (no
        # killing-blow marker), so the sourced flat heal is priced once
        # per Q cast — exact for a 1v1 that ends on a Q cast, an
        # overstatement of at most one heal per extra Q cast otherwise.
        # The 50% cooldown refund is a cooldown-state rider not modeled.
        level = max(1, int(champion_stats.get("level", 18) or 18))
        heal = _leveling_value(_ability(champion_data, "Q"), "Heal", level)
        for event in _attributed_events(
            damage_events, lambda source, _event: source == "Q"
        ):
            _heal_from_damage(healing, event, heal, "Noxian Diplomacy")

    elif name == "Nunu & Willump":
        # Consume against a champion heals for the Base Champion Heal
        # (39-111 + 54% AP + 6% bonus health), increased by 50% while
        # Willump is below 50% maximum health (the wiki's Empowered
        # Champion Heal row is exactly 1.5x the base row at every
        # rank).  The empowerment is a live health-ratio formula
        # re-priced by the participant ledger at the heal timestamp
        # (the Darius missing-health pattern).
        q = _ability(champion_data, "Q")
        q_rank = _rank(ability_damages, "Q")
        base = extract_named(q, "Base Champion Heal", q_rank, champion_stats, {})

        def consume_heal(
            current_health: float,
            maximum_health: float,
            base_amount: float = base,
        ) -> float:
            if maximum_health > 0.0 and current_health < maximum_health * 0.5:
                return base_amount * 1.5
            return base_amount

        for event in _attributed_events(
            damage_events, lambda source, _event: source == "Q"
        ):
            healing.append(
                {
                    "time": float(event.get("time", 0.0)),
                    "amount": 0.0,
                    "amount_formula": consume_heal,
                    "source": "Consume",
                    "kind": "champion_ability",
                    **_trigger_fields(event),
                }
            )
    elif name == "Shyvana":
        # Inferno Aegis (W) recast, Dragon Form: "If the explosion hits an
        # enemy champion, Shyvana heals herself for 60 : 104.71 (based on
        # level) (+ 4% : 8.47% (based on level) missing health)".  The W
        # module emits the recast explosion as W damage events (gated on
        # the w_recast option and stamped "dragon form" in the W row when
        # the dragon_form option is set), so each damaging W event is one
        # champion-hit explosion.  The flat is the level-indexed "Heal"
        # row (60 at level 1 .. 104.71 at level 18); the missing-health
        # percentage is the level-indexed "Missing Health Damage" row
        # (4% .. 8.47%) — the "Heal" row's own second modifier carries the
        # percentage only as prose ("% : 8.47% (based on level"), so the
        # leveled array is the source.  A live missing-health formula
        # (Volibear W pattern) prices the heal at the fighter's health at
        # the explosion timestamp; the zero-damage shield-grant event the
        # module emits at the cast is not an explosion and heals nothing.
        w_row = ability_damages.get("W", {})
        if "dragon form" in str(w_row.get("detail", "")).lower():
            level = max(1, int(champion_stats.get("level", 18) or 18))
            w = _ability(champion_data, "W")
            flat = extract_named(w, "Heal", level, champion_stats, {})
            missing_pct = _leveling_modifier(w, "Missing Health Damage", level, 0)

            def inferno_aegis_heal(
                current_health: float,
                maximum_health: float,
                flat: float = flat,
                missing_pct: float = missing_pct,
            ) -> float:
                return (
                    flat
                    + max(0.0, maximum_health - current_health) * missing_pct / 100.0
                )

            for event in _attributed_events(
                damage_events, lambda source, _event: source == "W"
            ):
                if float(event.get("damage", 0.0)) <= 0.0:
                    continue
                healing.append(
                    {
                        "time": float(event.get("time", 0.0)),
                        "amount": 0.0,
                        "amount_formula": inferno_aegis_heal,
                        "source": "Inferno Aegis",
                        "kind": "champion_ability",
                        **_trigger_fields(event),
                    }
                )

    return sorted(healing, key=lambda event: (event["time"], event["source"]))
