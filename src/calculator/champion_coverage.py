"""Fail-closed attacker certification reasons derived from cached kit data."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Collection
from typing import Any

from .champions.attribute_classifier import is_damage_attribute
from .champions.scaling import is_supported_scaling_unit


def _damage_levelings(ability: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        leveling
        for effect in ability.get("effects", [])
        for leveling in effect.get("leveling", [])
        if is_damage_attribute(str(leveling.get("attribute", "")))
    ]


def _all_levelings(ability: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        leveling
        for effect in ability.get("effects", [])
        for leveling in effect.get("leveling", [])
    ]


def _ability_units(levelings: list[dict[str, Any]]) -> set[str]:
    return {
        str(unit).strip()
        for leveling in levelings
        for modifier in leveling.get("modifiers", [])
        for unit in modifier.get("units", [])
        if str(unit).strip()
    }


def _ability_label(slot: str, ability: dict[str, Any]) -> str:
    return f"{slot} · {ability.get('name', 'unnamed ability')}"


def _blocker(code: str, label: str, abilities: Collection[str]) -> dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "abilities": sorted(set(abilities)),
    }


def attacker_availability(
    champion: dict[str, Any], verified_champions: Collection[str]
) -> dict[str, Any]:
    """Return public attacker readiness and every detected review blocker.

    A reviewed module is authoritative. An unregistered kit is never promoted
    by this scanner: detected mechanics explain why it remains unavailable,
    while a review-pending blocker covers apparently simple kits whose event
    sequence still lacks champion-specific tests.
    """
    name = str(champion.get("name", ""))
    if name in verified_champions:
        return {
            "ready": True,
            "verification": "reviewed_module",
            "blockers": [],
        }

    matches: dict[str, list[str]] = defaultdict(list)
    unsupported_units: dict[str, list[str]] = defaultdict(list)
    for slot, abilities in champion.get("abilities", {}).items():
        if len(abilities) > 1:
            matches["alternate_forms"].extend(
                _ability_label(slot, ability) for ability in abilities
            )
        for ability in abilities:
            label = _ability_label(slot, ability)
            all_levelings = _all_levelings(ability)
            levelings = _damage_levelings(ability)
            damage_units = _ability_units(levelings)
            blurb = str(ability.get("blurb") or "").lower()
            attributes = " ".join(
                str(leveling.get("attribute", "")).lower() for leveling in all_levelings
            )
            has_damage = bool(levelings or ability.get("damageType"))
            attack_attribute = any(
                phrase in str(leveling.get("attribute", "")).lower()
                for leveling in levelings
                for phrase in ("on-hit", "on hit", "per attack", "per hit")
            )
            auto_attack_bonus = (
                str(ability.get("targeting", "")).lower() == "auto"
                and "bonus" in attributes
                and "attack" in blurb
            )

            if has_damage and (
                slot == "P"
                or str(ability.get("targeting", "")).lower() == "passive"
                or attack_attribute
                or auto_attack_bonus
                or "empowered attack" in blurb
                or "next basic attack" in blurb
            ):
                matches["attack_events"].append(label)

            if has_damage and (
                any(
                    phrase in blurb
                    for phrase in (
                        "damage over time",
                        "per tick",
                        "each second",
                        "multiple damage instances",
                        "detonat",
                        "recast",
                        "subsequent damage",
                        "bounces",
                    )
                )
                or any(
                    phrase in attributes
                    for phrase in (
                        "per tick",
                        "total damage",
                        "total magic damage",
                        "total physical damage",
                        "subsequent",
                        "maximum damage",
                        "minimum damage",
                    )
                )
            ):
                matches["timed_stages"].append(label)

            if has_damage and (
                any(
                    "target" in unit.lower() and "health" in unit.lower()
                    for unit in damage_units
                )
                or any(
                    phrase in blurb
                    for phrase in (
                        "missing health",
                        "current health",
                        "health threshold",
                        "execute",
                    )
                )
            ):
                matches["changing_health"].append(label)

            if ability.get("rechargeRate") or (
                has_damage
                and (
                    "maximum charges" in attributes
                    or re.search(r"\b(ammo|stores? (?:a|up to) charge)\b", blurb)
                )
            ):
                matches["charges"].append(label)

            if (
                has_damage
                and re.search(
                    r"\b(stacks?|marks?|resets?|forms?|stances?|transforms?)\b", blurb
                )
                or (
                    has_damage
                    and re.search(r"\b(stacks?|marks?|recasts?)\b", attributes)
                )
            ):
                matches["stateful"].append(label)

            if has_damage and re.search(
                r"\b(pets?|turrets?|soldiers?|summons?|clones?)\b", blurb
            ):
                matches["summons"].append(label)

            if any(
                phrase in attributes
                for phrase in (
                    "bonus attack speed",
                    "bonus attack damage",
                    "bonus armor",
                    "bonus magic resistance",
                    "critical strike chance",
                )
            ):
                matches["stat_steroids"].append(label)

            for unit in damage_units:
                if not is_supported_scaling_unit(unit):
                    unsupported_units[unit].append(label)

    blockers = []
    if matches["alternate_forms"]:
        blockers.append(
            _blocker(
                "alternate_forms",
                "Alternate forms or sub-spells need explicit state selection.",
                matches["alternate_forms"],
            )
        )
    if unsupported_units:
        unsupported = _blocker(
            "unsupported_scaling",
            "Cached damage scaling needs a champion-specific formula.",
            {
                ability
                for abilities in unsupported_units.values()
                for ability in abilities
            },
        )
        unsupported["units"] = sorted(unsupported_units)
        blockers.append(unsupported)
    for code, label in (
        ("attack_events", "Passive or attack-triggered damage needs event modelling."),
        ("timed_stages", "Persistent or multi-stage damage needs hit timing."),
        (
            "changing_health",
            "Target-health or execute scaling needs a changing-health timeline.",
        ),
        ("charges", "Charges or ammo need explicit starting-state controls."),
        (
            "stat_steroids",
            "Offensive stat steroids need explicit activation timing and ordering.",
        ),
        ("stateful", "Stacks, marks, resets, or forms need explicit state controls."),
        ("summons", "Pets or summoned attacks need their own event timeline."),
    ):
        if matches[code]:
            blockers.append(_blocker(code, label, matches[code]))

    if not blockers:
        blockers.append(
            _blocker(
                "review_pending",
                "This kit's cast sequence and passive interactions still need review.",
                (),
            )
        )

    return {
        "ready": False,
        "verification": "blocked",
        "blockers": blockers,
    }
