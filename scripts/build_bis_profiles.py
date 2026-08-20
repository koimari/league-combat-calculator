#!/usr/bin/env python3
"""Build compact Wiki-derived champion profiles for roster BIS previews.

The production fight engine remains fail-closed around its reviewed champion
modules.  Roster BIS needs a useful, explicitly approximate fallback for all
173 champions, though, so this asset preserves the cached Wiki damage
levelings, attack/utility signals, and champion role ratings in a small
browser-readable graph.  It is never presented as a reviewed event timeline.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_ability_catalog import catalogue_champions, rank_count
from scripts.source_receipt import cache_patch, source_receipt, source_sha256
from src.calculator.cast_dependency import BASE_CAST_SLOTS

_DAMAGE_ATTRIBUTE = re.compile(
    r"(?i)(damage|strike|hit|burst|bleed|burn|detonat|poison|explos|rocket|"
    r"bolt|shot|slash|snip|needle|wave|orb|passive magic|active magic|physical|true)"
)
_NON_DAMAGE_ATTRIBUTE = re.compile(
    r"(?i)(reduction|damage taken|damage increase|damage stored|damage mitigated|"
    r"health cost|transmission|attack damage|bonus attack damage|bonus damage per stack)"
)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _values(modifier: dict[str, Any]) -> list[float]:
    raw = modifier.get("values", [])
    if not isinstance(raw, list):
        return []
    return [value for value in (_number(item) for item in raw) if value is not None]


def _ratio_components(unit: str, attribute: str) -> dict[str, float]:
    text = " ".join(str(unit or "").lower().split())
    attr = str(attribute or "").lower()
    if not text:
        return {"base": 1.0}
    result: dict[str, float] = {}
    if "% ap" in text and "per 100 ap" not in text:
        result["ap"] = 1.0 / 100.0
    if "% bonus ad" in text and "per 100 bonus ad" not in text:
        result["bonusAd"] = 1.0 / 100.0
    elif ("% ad" in text or text.endswith(" ad")) and "per 100 ad" not in text:
        result["ad"] = 1.0 / 100.0
    if (
        "target" in text
        and "maximum health" in text
        or "target" in text
        and "max health" in text
    ):
        result["targetMaxHp"] = 1.0 / 100.0
    elif "target" in text and "current health" in text:
        result["targetCurrentHp"] = 1.0 / 100.0
    elif "target" in text and "missing health" in text:
        result["targetMissingHp"] = 1.0 / 100.0
    elif "maximum health" in text or "max health" in text:
        result["selfMaxHp"] = 1.0 / 100.0
    if "bonus ad" in text:
        result["bonusAd"] = 1.0 / 100.0
    elif "total ad" in text or text.endswith(" ad") or "% ad" in text:
        result["ad"] = 1.0 / 100.0
    if "bonus health" in text:
        result["bonusHp"] = 1.0 / 100.0
    if "bonus armor" in text:
        result["bonusArmor"] = 1.0 / 100.0
    elif "total armor" in text or text.endswith(" armor"):
        result["armor"] = 1.0 / 100.0
    if "bonus magic resistance" in text or "bonus mr" in text:
        result["bonusMr"] = 1.0 / 100.0
    elif "total magic resistance" in text or text.endswith(" magic resistance"):
        result["mr"] = 1.0 / 100.0
    # Wiki strings such as "% (+ 3% per 100 AP) of target's maximum health"
    # carry a second ratio in the units text. Preserve that signal alongside
    # the primary health ratio rather than dropping one of the terms.
    for key, pattern in (
        ("ap", r"([0-9.]+)%\s*per\s*100\s*ap"),
        ("bonusAd", r"([0-9.]+)%\s*per\s*100\s*bonus\s*ad"),
        ("bonusHp", r"([0-9.]+)%\s*per\s*100\s*bonus\s*health"),
        ("bonusArmor", r"([0-9.]+)%\s*per\s*100\s*bonus\s*armor"),
        ("bonusMr", r"([0-9.]+)%\s*per\s*100\s*bonus\s*magic\s*resistance"),
    ):
        match = re.search(pattern, text)
        if match:
            result[key] = float(match.group(1)) / 10000.0
    if result:
        return result
    if text == "%" or "percent" in text:
        if "health" in attr:
            return {"selfMaxHp": 1.0 / 100.0}
        return {}
    return {}


def _cooldown_values(ability: dict[str, Any]) -> list[float]:
    cooldown = ability.get("cooldown")
    if not isinstance(cooldown, dict):
        return []
    for modifier in cooldown.get("modifiers", []):
        values = _values(modifier)
        if values:
            return values[:5]
    return []


def _damage_packet(attribute: str, leveling: dict[str, Any]) -> dict[str, Any] | None:
    if not _DAMAGE_ATTRIBUTE.search(attribute) or _NON_DAMAGE_ATTRIBUTE.search(
        attribute
    ):
        return None
    base: list[float] = []
    ratios: dict[str, list[float]] = {}
    for modifier in leveling.get("modifiers", []):
        values = _values(modifier)
        if not values:
            continue
        units = modifier.get("units", [])
        unit = str(units[0] if units else "")
        components = _ratio_components(unit, attribute)
        if components.get("base"):
            base = values
        else:
            for key, factor in components.items():
                ratios[key] = [value * factor for value in values]
    if not base and not ratios:
        return None
    lower = attribute.lower()
    priority = 0
    if "total" in lower:
        priority += 4
    if "maximum" in lower or "enhanced" in lower:
        priority += 3
    if "per hit" in lower or "per tick" in lower:
        priority += 1
    if "minimum" in lower:
        priority -= 2
    return {
        "attribute": attribute,
        "base": base,
        "ratios": ratios,
        "priority": priority,
    }


def _utility_packet(attribute: str, leveling: dict[str, Any]) -> dict[str, Any] | None:
    """Extract shield/heal values without treating them as damage packets."""
    lower = attribute.lower()
    if not re.search(r"shield|barrier|\bheal(?:ing)?\b", lower):
        return None
    base: list[float] = []
    ratios: dict[str, list[float]] = {}
    for modifier in leveling.get("modifiers", []):
        values = _values(modifier)
        if not values:
            continue
        units = modifier.get("units", [])
        unit = str(units[0] if units else "")
        components = _ratio_components(unit, attribute)
        if components.get("base"):
            base = values
        else:
            for key, factor in components.items():
                ratios[key] = [value * factor for value in values]
    if not base and not ratios:
        return None
    return {"attribute": attribute, "base": base, "ratios": ratios, "priority": 0}


def _form_profile(slot: str, ability: dict[str, Any]) -> dict[str, Any]:
    descriptions = [
        str(effect.get("description", "")).strip()
        for effect in ability.get("effects", [])
        if str(effect.get("description", "")).strip()
    ]
    description = " ".join(dict.fromkeys(descriptions))
    packets: list[dict[str, Any]] = []
    shields: list[dict[str, Any]] = []
    heals: list[dict[str, Any]] = []
    for effect in ability.get("effects", []):
        for leveling in effect.get("leveling", []):
            packet = _damage_packet(str(leveling.get("attribute", "")), leveling)
            if packet:
                packets.append(packet)
            utility = _utility_packet(str(leveling.get("attribute", "")), leveling)
            if utility:
                if (
                    "shield" in str(leveling.get("attribute", "")).lower()
                    or "barrier" in str(leveling.get("attribute", "")).lower()
                ):
                    shields.append(utility)
                else:
                    heals.append(utility)
    # Multiple Wiki levelings commonly expose min/max/total variants for the
    # same cast. Keep the strongest declared variant per damage family rather
    # than summing mutually exclusive tooltip rows.
    chosen: list[dict[str, Any]] = []
    families: dict[str, dict[str, Any]] = {}
    for packet in packets:
        family = re.sub(
            r"(?i)minimum|maximum|total|enhanced|per tick|per hit",
            "",
            packet["attribute"],
        )
        current = families.get(family)
        if current is None or packet["priority"] > current["priority"]:
            families[family] = packet
    chosen.extend(families.values())
    for packet in chosen:
        packet["damageType"] = ability.get("damageType")

    def choose_utility(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        families: dict[str, dict[str, Any]] = {}
        for packet in entries:
            family = re.sub(
                r"(?i)minimum|maximum|total|per tick|per hit", "", packet["attribute"]
            )
            current = families.get(family)
            if current is None or packet["priority"] > current["priority"]:
                families[family] = packet
        return list(families.values())

    text = (description + " " + str(ability.get("blurb") or "")).lower()
    return {
        "name": ability.get("name") or slot,
        "slot": slot,
        "maxRank": rank_count(ability, slot),
        "cooldown": _cooldown_values(ability),
        "damageType": ability.get("damageType"),
        "targeting": ability.get("targeting"),
        "affects": ability.get("affects"),
        "packets": chosen,
        "shields": choose_utility(shields),
        "heals": choose_utility(heals),
        "signals": {
            "attack": bool(
                re.search(
                    r"basic attack|on-hit|on hit|next attack|empowered attack|per attack",
                    text,
                )
            ),
            "heal": bool(
                re.search(r"\bheal(?:ing)?\b|lifesteal|omnivamp|regenerat", text)
            ),
            "shield": "shield" in text,
            "control": bool(
                re.search(
                    r"stun|root|slow|knock|silence|immobil|suppress|charm|polymorph",
                    text,
                )
            ),
            "persistent": bool(
                re.search(
                    r"per tick|per second|damage over time|recast|bounce|detonat|each hit",
                    text,
                )
            ),
            "hasDamage": bool(chosen),
        },
    }


def _load_meraki_kits(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    marker = "MERAKI_ABILITY_KITS"
    start = text.index("= ", text.index(marker)) + 2
    return json.loads(text[start : text.rfind("}") + 1])


def _merge_auxiliary_damage(champions: dict[str, Any], kits: dict[str, Any]) -> int:
    merged = 0
    by_name = {
        str(kit.get("name")): kit for kit in kits.values() if isinstance(kit, dict)
    }
    for name, champion in champions.items():
        kit = by_name.get(name)
        if not kit:
            continue
        for ability in kit.get("abilities", []):
            damage = ability.get("damage")
            if not damage:
                continue
            forms = champion["abilities"].get(ability.get("slot"), [])
            target = next((form for form in forms if not form.get("packets")), None)
            if not target:
                continue
            ratios = {
                ratio.get("stat"): ratio.get("values", [])
                for ratio in damage.get("ratios", [])
                if ratio.get("stat")
                in {"ap", "ad", "bonusAd", "targetMaxHp", "targetMissingHp"}
            }
            target["packets"] = [
                {
                    "attribute": "Auxiliary generated damage packet",
                    "base": damage.get("base", []),
                    "ratios": ratios,
                    "priority": -1,
                    "damageType": str(damage.get("type", "")).upper() + "_DAMAGE",
                    "source": "Axword Meraki generated kit",
                }
            ]
            target["damageType"] = str(damage.get("type", "")).upper() + "_DAMAGE"
            target["signals"]["hasDamage"] = True
            merged += 1
    return merged


def build_profiles(
    source: Path, patch: str, auxiliary_source: Path | None = None
) -> dict[str, Any]:
    raw = json.loads(source.read_text(encoding="utf-8"))
    champions: dict[str, Any] = {}
    for champion in catalogue_champions(raw):
        abilities = champion.get("abilities", {})
        forms: dict[str, list[dict[str, Any]]] = {}
        for slot in BASE_CAST_SLOTS:
            forms[slot] = [
                _form_profile(slot, ability)
                for ability in abilities.get(slot, [])
                if isinstance(ability, dict)
            ]
        champions[champion.get("name", "")] = {
            "name": champion.get("name", ""),
            "key": champion.get("key", ""),
            "roles": champion.get("roles", []),
            "positions": champion.get("positions", []),
            "ratings": champion.get("attributeRatings", {}),
            "abilities": forms,
        }
    auxiliary_kits = _load_meraki_kits(auxiliary_source)
    auxiliary_merged = _merge_auxiliary_damage(champions, auxiliary_kits)
    result = {
        "schema_version": 1,
        "patch": patch,
        "champion_count": len(champions),
        "source": source_receipt(source),
        "champions": champions,
    }
    if auxiliary_source and auxiliary_kits:
        result["auxiliary_source"] = {
            "kind": "Axword local Meraki generated kit reference",
            "path": "local sibling: lol-strength-analysis/src/data/generated/merakiAbilityKits.ts",
            "sha256": source_sha256(auxiliary_source),
            "merged_damage_packets": auxiliary_merged,
        }
    return result


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=root / "data" / "champions.json")
    parser.add_argument(
        "--output", type=Path, default=root / "static" / "bis-profiles.json"
    )
    parser.add_argument(
        "--auxiliary-source",
        type=Path,
        default=root.parent
        / "lol-strength-analysis"
        / "src"
        / "data"
        / "generated"
        / "merakiAbilityKits.ts",
    )
    # Default derived from the cache, so a rebuild cannot stamp a stale patch.
    parser.add_argument("--patch", default=None)
    args = parser.parse_args()
    profiles = build_profiles(
        args.source.resolve(),
        args.patch or cache_patch(),
        args.auxiliary_source.resolve() if args.auxiliary_source.exists() else None,
    )
    if not profiles["champions"]:
        raise SystemExit(
            "No champions in the cached source — refusing to write an empty "
            "BIS profiles asset"
        )
    args.output.write_text(
        json.dumps(profiles, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.output} ({profiles['champion_count']} champions)")


if __name__ == "__main__":
    main()
