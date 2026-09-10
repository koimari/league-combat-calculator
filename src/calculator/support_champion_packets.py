"""The sourced per-champion metadata and follow-up packets an ally receives."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .ability_atoms import (
    AbilityAtomQuery,
    atom_receipt,
    ranked_ability_atom_value,
    required_ability_atom,
    required_ranked_attribute_atom,
)
from .champions.slot_extract import ability_name, extract_named
from .support_row_metadata import _shield_duration_metadata


def _morgana_black_shield_metadata(
    champion_data: dict[str, Any],
    ability: dict[str, Any],
    rank: int,
    stats: Mapping[str, float],
) -> dict[str, Any]:
    """Return Black Shield's typed pool, duration, and source receipts."""
    champion_name = str(champion_data.get("name", ""))
    strength_source = "Morgana.E[0].effects[0].leveling[0].modifiers[0]"
    strength_atom = required_ability_atom(
        champion_name,
        champion_data,
        "E",
        query=AbilityAtomQuery(
            source=strength_source,
            behavior="ability",
            evidence_prefix="Magic Shield Strength@",
        ),
    )
    strength_base = ranked_ability_atom_value(
        strength_atom, rank, source=strength_source
    )
    base_stats = dict(stats)
    base_stats["ability_power"] = 0.0
    parsed_base = extract_named(ability, "Magic Shield Strength", rank, base_stats, {})
    if abs(parsed_base - strength_base) > 1e-9:
        raise ValueError(
            "Morgana E Magic Shield Strength atom disagrees with cached ability data"
        )

    duration_metadata = _shield_duration_metadata(champion_data, "E")
    return {
        **duration_metadata,
        "shield_pool": "magic",
        "crowd_control_immunity_while_shield": True,
        "crowd_control_immunity_source": ability_name(ability),
        "source_atom": atom_receipt(strength_atom),
    }


def _target_max_health_shield_metadata(
    champion_data: dict[str, Any],
    ability: Mapping[str, Any],
    slot: str,
    attribute: str,
    *,
    rank: int,
) -> dict[str, Any]:
    """Return a typed target-health formula when the source names one."""
    champion_name = str(champion_data.get("name", ""))
    for effect_index, effect in enumerate(ability.get("effects", [])):
        for leveling_index, leveling in enumerate(effect.get("leveling", [])):
            if leveling.get("attribute") != attribute:
                continue
            for modifier_index, modifier in enumerate(leveling.get("modifiers", [])):
                units = [
                    str(unit).strip().lower() for unit in modifier.get("units", [])
                ]
                if not units or any(
                    unit != "% of target's maximum health" for unit in units
                ):
                    continue
                source = (
                    f"{champion_name}.{slot}[0].effects[{effect_index}]"
                    f".leveling[{leveling_index}].modifiers[{modifier_index}]"
                )
                atom = required_ability_atom(
                    champion_name,
                    champion_data,
                    slot,
                    query=AbilityAtomQuery(
                        source=source,
                        behavior="ability",
                        evidence_prefix=f"{attribute}@",
                    ),
                )
                ratio = ranked_ability_atom_value(atom, rank, source=source) / 100.0

                def amount_formula(
                    _current_health: float,
                    maximum_health: float,
                    ratio: float = ratio,
                ) -> float:
                    return max(0.0, maximum_health) * ratio

                return {
                    "amount": 0.0,
                    "amount_formula": amount_formula,
                    "amount_formula_atom": atom_receipt(atom),
                }
    return {}


def _target_missing_health_heal_metadata(
    champion_data: dict[str, Any],
    slot: str,
    attribute: str,
    rank: int,
) -> dict[str, Any]:
    """Return a typed live missing-health formula when the source names it."""
    champion_name = str(champion_data.get("name", ""))
    value, atom = required_ranked_attribute_atom(
        champion_name,
        champion_data,
        slot,
        attribute,
        rank,
    )
    units = [str(unit).strip().lower() for unit in atom.get("units", [])]
    if not units or any(unit != "% of target's missing health" for unit in units):
        raise ValueError(
            f"{champion_name} {slot} {attribute} atom must use target missing health"
        )
    ratio = value / 100.0

    def amount_formula(
        current_health: float,
        maximum_health: float,
        ratio: float = ratio,
    ) -> float:
        return max(0.0, maximum_health - current_health) * ratio

    return {
        "amount": 0.0,
        "amount_formula": amount_formula,
        "amount_formula_atom": atom_receipt(atom),
    }


# Nami W (Ebb and Flow) bounce prose — cached
# ``Nami.W[0].effects[1].description``: "each bounce modifying the
# effectiveness of the next by -20% (+ 15% per 100 AP)".  The reduction is
# per-bounce off the ORIGINAL first-target value: the sourced "Minimum
# Heal" row is exactly 60% of the "Heal" row at every rank (93 = 0.6 x 155
# at rank 5), so the second bounce keeps 1 - 2 x 0.20 = 60% at 0 AP — the
# sourced Minimum Heal row is the documented floor, exactly as the E1 rule
# floors the first bounce.
_NAMI_BOUNCE_REDUCTION_PER_BOUNCE = 0.20


_NAMI_BOUNCE_AP_RELIEF_PER_100 = 0.15


# Yuumi R (Final Chapter) Best Friend bonus — cached
# ``Yuumi.R[0].effects[4].description``: "Final Chapter's heal to the Best
# Friend is increased by 30% : 60% (based on level)" with the sourced
# per-level row (30 / 35 / 40 / 45 / 50 / 55 / 60%).  The deterministic
# roster model treats the selected teammate as the anchor and Best Friend
# (the same teammate Yuumi E already targets), so the bonus rides the
# base heal packet of the same cast.
_YUUMI_R_BEST_FRIEND_QUERY = AbilityAtomQuery(
    source="Yuumi.R[0].effects[4].leveling[0].modifiers[0]",
    behavior="ability",
    evidence_prefix="Per-Level Scaling@",
)


# The conversion shield lifetime is "1.5 seconds plus the remaining
# channel duration" (cached ``Yuumi.R[0].effects[1].description``); the
# scanner lumps the sourced Total Heal at the cast, so the remaining
# channel is the full sourced 3.5s channel (``effects[0]``).
_YUUMI_R_SHIELD_DURATION_QUERY = AbilityAtomQuery(
    source="Yuumi.R[0].effects[1].description",
    behavior="timing",
    evidence_prefix="shield duration@",
)


_YUUMI_R_CHANNEL_QUERY = AbilityAtomQuery(
    source="Yuumi.R[0].effects[0].description",
    behavior="timing",
    evidence_prefix="active duration@",
)


def _clamped_per_level_fraction(atom: Mapping[str, Any], level: int) -> float:
    """Read a per-level atom row at the repo's clamped level index.

    Rows with one value per level index directly (20 values); shorter
    per-level rows (Yuumi R's 7-value Best Friend row) clamp at the last
    value — the same convention ``slotlib._modifier_value`` and the
    Renata P Leverage rule use.  The wiki bracket levels are not present
    in the cache, so the endpoints (30% at level 1, 60% at level 18) are
    exact and intermediate levels follow the established clamp.
    """
    values = atom.get("values", ())
    if not values:
        raise ValueError(f"per-level atom {atom.get('source', '')!r} has no values")
    index = min(max(level, 1) - 1, len(values) - 1)
    value = values[index]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"per-level atom {atom.get('source', '')!r} "
            f"level {level} is not numeric"
        )
    return float(value) / 100.0


def _nami_return_bounce_packet(
    champion_data: dict[str, Any],
    ability: dict[str, Any],
    slot: str,
    rank: int,
    *,
    stats: Mapping[str, float],
    base_amount: float,
    cast_time: float,
    cast_index: int,
) -> dict[str, Any]:
    """Ebb and Flow's return bounce heals the selected teammate again.

    Cast on the selected teammate, the stream bounces to the enemy and
    back; the second bounce keeps 60% + 30% per 100 AP of the original
    heal, never below the sourced "Minimum Heal" row (which is exactly the
    60% floor at every rank).  The packet has its own selection key so the
    roster UI can choose the return-bounce recipient explicitly.
    """
    _, heal_atom = required_ranked_attribute_atom(
        "Nami", champion_data, slot, "Heal", rank
    )
    _, floor_atom = required_ranked_attribute_atom(
        "Nami", champion_data, slot, "Minimum Heal", rank
    )
    floor = extract_named(ability, "Minimum Heal", rank, stats, {})
    ap = float(stats.get("ability_power", 0.0) or 0.0)
    factor = 1.0 - 2.0 * (
        _NAMI_BOUNCE_REDUCTION_PER_BOUNCE - _NAMI_BOUNCE_AP_RELIEF_PER_100 * ap / 100.0
    )
    amount = max(floor, base_amount * factor)
    return {
        "time": cast_time,
        "kind": "heal",
        "amount": amount,
        "source": "Ebb and Flow · Return Bounce",
        "slot": slot,
        "target_self": False,
        "target_scope": "one_teammate",
        "rank": rank,
        "target_selection_key": f"heal:{slot}:{cast_index}:bounce",
        "source_atoms": [atom_receipt(heal_atom), atom_receipt(floor_atom)],
    }


def _yuumi_best_friend_packet(
    champion_data: dict[str, Any],
    slot: str,
    level: int,
    rank: int,
    *,
    base_amount: float,
    cast_time: float,
    cast_index: int,
) -> dict[str, Any]:
    """Final Chapter's Best Friend bonus heal on the selected teammate.

    The anchor (the selected teammate) is healed for the sourced per-level
    bonus (30% : 60% based on level) of the sourced Total Heal, emitted as
    its own packet with an explicit selection key so the base and bonus
    heals stay independently targetable.
    """
    _, total_atom = required_ranked_attribute_atom(
        "Yuumi", champion_data, slot, "Total Heal", rank
    )
    bonus_atom = required_ability_atom(
        "Yuumi",
        champion_data,
        slot,
        query=_YUUMI_R_BEST_FRIEND_QUERY,
    )
    fraction = _clamped_per_level_fraction(bonus_atom, level)
    return {
        "time": cast_time,
        "kind": "heal",
        "amount": base_amount * fraction,
        "source": "Final Chapter · Best Friend Bonus",
        "slot": slot,
        "target_self": False,
        "target_scope": "one_teammate",
        "rank": rank,
        "target_selection_key": f"heal:{slot}:{cast_index}:best_friend",
        "source_atoms": [atom_receipt(total_atom), atom_receipt(bonus_atom)],
    }


def _yuumi_conversion_shield_packet(
    champion_data: dict[str, Any],
    heal_event: Mapping[str, Any],
    slot: str,
) -> dict[str, Any]:
    """Final Chapter's overheal-to-shield conversion for one heal packet.

    Cached ``Yuumi.R[0].effects[1].description``: "each heal instance
    beyond maximum health being converted into a shield that lasts for
    1.5 seconds plus the remaining channel duration instead".  The live
    excess ``max(0, heal - missing)`` is a shield formula the survival
    kernel evaluates against the target's current health at the packet's
    timestamp (same amount_formula path as Taric W), so the shield pool
    and expiry follow the shared shield ledger.
    """
    shield_duration_atom = required_ability_atom(
        "Yuumi",
        champion_data,
        slot,
        query=_YUUMI_R_SHIELD_DURATION_QUERY,
    )
    channel_atom = required_ability_atom(
        "Yuumi",
        champion_data,
        slot,
        query=_YUUMI_R_CHANNEL_QUERY,
    )
    duration = float(shield_duration_atom["values"][0]) + float(
        channel_atom["values"][0]
    )
    heal_amount = float(heal_event.get("amount", 0.0))

    def amount_formula(
        current_health: float,
        maximum_health: float,
        heal: float = heal_amount,
    ) -> float:
        return max(0.0, heal - max(0.0, maximum_health - current_health))

    return {
        "time": float(heal_event.get("time", 0.0)),
        "kind": "shield",
        "amount": 0.0,
        "amount_formula": amount_formula,
        "source": "Final Chapter · Overheal Conversion",
        "slot": slot,
        "target_self": False,
        "target_scope": "one_teammate",
        "rank": int(heal_event.get("rank", 0)),
        # The conversion rides the heal it converts: it shares the parent
        # heal's selection key so the roster's chosen recipient for that
        # heal packet also receives its shield (in-game the conversion
        # lands on the ally who was healed, not an independent target).
        "target_selection_key": str(heal_event.get("target_selection_key", "")),
        "duration": duration,
        "duration_atom": atom_receipt(shield_duration_atom),
        "source_atoms": [
            atom_receipt(shield_duration_atom),
            atom_receipt(channel_atom),
        ],
    }
