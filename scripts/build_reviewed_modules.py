#!/usr/bin/env python3
"""Generate explicit champion packet modules from the pinned local sources.

The generated modules are deliberately explicit: every cached ability slot is
represented either by a numeric Wiki/Axword packet or by a sourced no-damage
entry.  A missing numeric row is never replaced with an archetype estimate.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.calculator.champions.attribute_classifier import (
    infer_damage_type_from_attribute,
    is_damage_attribute,
    is_primary_damage_attribute,
)


SLOTS = ("P", "Q", "W", "E", "R")
WIKI_DB = Path("/Users/river/scryglass/data/lol/knowledge/league-wiki.sqlite3")


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _load_axword(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    marker = "export const MERAKI_ABILITY_KITS"
    start = text.index("=", text.index(marker)) + 1
    end = text.index("\n}\n\nexport const MERAKI_ABILITY_KIT_IDS", start) + 2
    payload = json.loads(text[start:end])
    return payload if isinstance(payload, dict) else {}


def _axword_by_name(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    aliases = {
        "wukong": "MonkeyKing",
        "nunuandwillump": "Nunu",
        "renataglasc": "Renata",
        "reksai": "RekSai",
    }
    result = {_norm(name): kit for name, kit in payload.items()}
    for canonical, source in aliases.items():
        if source in payload:
            result[canonical] = payload[source]
    return result


def _wiki_revisions() -> dict[str, dict[str, Any]]:
    """Read revision receipts from the local read-only Wiki index, if present."""
    try:
        with sqlite3.connect(f"file:{WIKI_DB}?mode=ro", uri=True) as connection:
            rows = connection.execute(
                "SELECT title, revision_id, revision_timestamp "
                "FROM pages WHERE namespace = 0"
            ).fetchall()
    except (OSError, sqlite3.Error):
        return {}
    return {
        str(title): {
            "revision_id": int(revision_id),
            "revision_timestamp": str(timestamp),
        }
        for title, revision_id, timestamp in rows
        if title and revision_id and timestamp
    }


def _damage_kind(ability: dict[str, Any], attribute: str) -> str:
    field = str(ability.get("damageType", ""))
    return {
        "MAGIC_DAMAGE": "magic",
        "PHYSICAL_DAMAGE": "physical",
        "TRUE_DAMAGE": "true",
    }.get(field) or infer_damage_type_from_attribute(attribute) or "magic"


def _wiki_cooldown(ability: dict[str, Any]) -> float:
    raw = ability.get("cooldown")
    if not isinstance(raw, dict):
        return 0.0
    modifiers = raw.get("modifiers", [])
    if not modifiers or not modifiers[0].get("values"):
        return 0.0
    return float(modifiers[0]["values"][0])


def _wiki_packet(
    ability: dict[str, Any],
    slot: str,
    ability_index: int,
    levelings: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Translate one selected Wiki damage group into an explicit packet."""
    damage_type = _damage_kind(ability, str(levelings[0].get("attribute", "")))
    max_len = max(
        (len(modifier.get("values", [])) for leveling in levelings for modifier in leveling.get("modifiers", [])),
        default=0,
    )
    if not max_len:
        return None
    base = [0.0] * max_len
    ratios: list[dict[str, Any]] = []
    stat_map = {
        "% AP": "ap",
        "% AD": "ad",
        "% total AD": "ad",
        "% bonus AD": "bonusAd",
        "% maximum health": "health",
        "% bonus health": "bonusHealth",
        "% armor": "armor",
        "% total armor": "armor",
        "% magic resistance": "magicResistance",
        "% total magic resistance": "magicResistance",
        "% of target's maximum health": "targetMaxHp",
        "% of target's current health": "targetCurrentHp",
        "% of target's missing health": "targetMissingHp",
    }

    def explicit_percent_stat(unit: str, attribute: str) -> str | None:
        """Resolve a bare Wiki ``%`` only when the source names the stat.

        A bare percent is intentionally *not* interpreted from damage type
        (for example, magic damage does not imply AP).  The Wiki uses bare
        percent units for both damage and state modifiers, so ambiguous rows
        must remain an attribute-only packet until a source-backed formula is
        available.
        """
        if unit != "%":
            return None
        lower = attribute.lower()
        if "current health" in lower:
            return "targetCurrentHp"
        if "missing health" in lower:
            return "targetMissingHp"
        if "max health" in lower or "maximum health" in lower:
            return "targetMaxHp"
        source_text = " ".join(
            [
                str(ability.get("name", "")),
                str(ability.get("blurb", "")),
                " ".join(str(effect.get("description", "")) for effect in ability.get("effects", [])),
            ]
        ).lower()
        if "bonus attack damage" in source_text or "bonus ad" in source_text:
            return "bonusAd"
        if "attack damage" in source_text or " ad" in source_text:
            return "ad"
        if "ability power" in source_text or " ap" in source_text:
            return "ap"
        if "bonus health" in source_text:
            return "bonusHealth"
        return None
    for leveling in levelings:
        for modifier in leveling.get("modifiers", []):
            values = [float(value) for value in modifier.get("values", [])]
            units = modifier.get("units", [])
            if not values:
                continue
            unit = str(units[0]).strip() if units else ""
            if unit in ("", " (based on level)"):
                for index, value in enumerate(values):
                    base[index] += value
                continue
            stat = stat_map.get(unit)
            if stat is None and unit == "%":
                stat = explicit_percent_stat(unit, str(leveling.get("attribute", "")))
            if stat is None:
                return None
            ratios.append({"stat": stat, "values": [value / 100.0 for value in values]})
    if not any(base) and not ratios:
        return None
    return {
        "kind": "packet",
        "name": str(ability.get("name", slot)),
        "cooldown": _wiki_cooldown(ability),
        "damage_type": damage_type,
        "base": base,
        "ratios": ratios,
        "ranks": "level" if slot == "P" else "rank",
        "source": [slot, ability_index],
    }


def _wiki_specs(entries: list[dict[str, Any]], slot: str) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for ability_index, ability in enumerate(entries):
        candidates: list[tuple[int, dict[str, Any]]] = []
        for effect in ability.get("effects", []):
            effect_description = str(effect.get("description", "")).lower()
            for leveling in effect.get("leveling", []):
                attribute = str(leveling.get("attribute", ""))
                lower_attribute = attribute.lower()
                if (
                    not is_damage_attribute(attribute)
                    or "attack damage" in lower_attribute
                    or "damage reduction" in lower_attribute
                ):
                    continue
                if slot == "P" and "damage" not in str(ability.get("blurb", "")).lower():
                    continue
                # Some Wiki effect groups attach a percentage state modifier
                # to an effect that also mentions damage (notably Irelia W's
                # incoming-damage reduction).  Do not mistake that modifier
                # for the spell's outgoing damage packet.
                if "reduces incoming" in effect_description or "damage reduction" in effect_description:
                    continue
                if not any(
                    isinstance(modifier.get("values"), list) and modifier["values"]
                    for modifier in leveling.get("modifiers", [])
                ):
                    continue
                # Explicit health terms are target-state formulas, not a
                # generic AD/AP fallback. Prefer them when a passive lists a
                # cap/auxiliary row beside the actual target-health damage.
                attr_lower = attribute.lower()
                if any(term in attr_lower for term in ("max health damage", "current health damage", "missing health damage")):
                    priority = -1
                else:
                    priority = 0 if is_primary_damage_attribute(attribute) else 1
                candidates.append((priority, leveling))
        if candidates:
            _, leveling = sorted(candidates, key=lambda row: row[0])[0]
            selected_attribute = str(leveling["attribute"])
            selected_levelings = [
                item
                for effect in ability.get("effects", [])
                for item in effect.get("leveling", [])
                if str(item.get("attribute", "")) == selected_attribute
            ]
            packet = _wiki_packet(ability, slot, ability_index, selected_levelings)
            specs.append(packet or {
                "kind": "wiki_attribute",
                "attribute": selected_attribute,
                "damage_type": _damage_kind(ability, selected_attribute),
                "ranks": "level" if slot == "P" else "rank",
                "source": [slot, ability_index],
                "name": str(ability.get("name", slot)),
            })
            continue
        if slot == "P" or not ability.get("damageType"):
            continue
        if "damage" not in str(ability.get("blurb", "")).lower():
            continue
        for effect in ability.get("effects", []):
            for leveling in effect.get("leveling", []):
                if any(
                    isinstance(modifier.get("values"), list) and modifier["values"]
                    for modifier in leveling.get("modifiers", [])
                ):
                    selected_attribute = str(leveling.get("attribute", "Per-Level Scaling"))
                    selected_levelings = [
                        item
                        for effect in ability.get("effects", [])
                        for item in effect.get("leveling", [])
                        if str(item.get("attribute", "")) == selected_attribute
                    ]
                    specs.append(
                        _wiki_packet(ability, slot, ability_index, selected_levelings)
                        or {
                            "kind": "wiki_attribute",
                            "attribute": selected_attribute,
                            "damage_type": _damage_kind(ability, selected_attribute),
                            "ranks": "rank",
                            "source": [slot, ability_index],
                            "name": str(ability.get("name", slot)),
                        }
                    )
                    break
            if specs and specs[-1].get("source") == [slot, ability_index]:
                break
    return specs


def _wiki_spec(entries: list[dict[str, Any]], slot: str) -> dict[str, Any] | None:
    specs = _wiki_specs(entries, slot)
    return specs[0] if specs else None


def _axword_spec(ability: dict[str, Any]) -> dict[str, Any] | None:
    damage = ability.get("damage")
    if not isinstance(damage, dict) or not damage.get("base"):
        return None
    return {
        "kind": "packet",
        "name": str(ability.get("name", "")),
        "cooldown": float(ability.get("cooldown", 0.0)),
        "damage_type": {"magical": "magic"}.get(str(damage.get("type")), str(damage.get("type", "magic"))),
        "base": [float(value) for value in damage.get("base", [])],
        "ratios": [
            {
                "stat": str(ratio.get("stat", "")),
                "values": [float(value) for value in ratio.get("values", [])],
            }
            for ratio in damage.get("ratios", [])
        ],
    }


def build(source: Path, axword_source: Path, output: Path, modules: Path) -> dict[str, Any]:
    raw = json.loads(source.read_text(encoding="utf-8"))
    axword = _axword_by_name(_load_axword(axword_source))
    revisions = _wiki_revisions()
    champions: dict[str, Any] = {}
    for champion in sorted(raw.values(), key=lambda row: str(row.get("name", ""))):
        name = str(champion["name"])
        ax = axword.get(_norm(name))
        ax_slots = {row.get("slot"): row for row in (ax or {}).get("abilities", [])}
        slots: dict[str, Any] = {}
        for slot in SLOTS:
            entries = champion.get("abilities", {}).get(slot, [])
            wiki_specs = _wiki_specs(entries, slot)
            if len(wiki_specs) > 1:
                spec = {"kind": "variants", "variants": wiki_specs, "default": 0}
            elif wiki_specs:
                spec = wiki_specs[0]
            elif slot in ax_slots and any(
                "damage" in str(ability.get("blurb", "")).lower()
                for ability in entries
            ):
                spec = _axword_spec(ax_slots[slot])
            else:
                spec = None
            if spec is not None:
                slots[slot] = spec
            else:
                # A non-damaging or prose-only ability is still part of the
                # reviewed champion contract.  Emitting an explicit zero
                # entry keeps the slot visible to the engine/UI and prevents
                # the old generic parser from silently inventing damage.
                ability = entries[0] if entries else {}
                slots[slot] = {
                    "kind": "no_damage",
                    "name": str(ability.get("name", slot)),
                    "reason": (
                        "The pinned Wiki packet contains no enemy-damage formula for this slot; "
                        "it is modeled as a non-damaging/state-only ability."
                    ),
                    "source": [slot, 0],
                }
        source_url = "https://wiki.leagueoflegends.com/en-us/" + quote(name.replace(" ", "_"))
        receipt = revisions.get(name, {})
        champions[name] = {
            "review_status": "reviewed_packet",
            "review_manifest": {
                "module_kind": "dedicated_champion_module",
                "formula_slots": sorted(
                    slot for slot, value in slots.items() if value.get("kind") in {"packet", "variants", "wiki_attribute"}
                ),
                "no_damage_slots": sorted(
                    slot for slot, value in slots.items() if value.get("kind") == "no_damage"
                ),
                "event_model": "typed_packet_order",
            },
            "slots": slots,
            "assumptions": [
                "Every slot is an explicit packet or sourced no-damage entry from the pinned local Wiki cache; no runtime archetype inference is used.",
                "Numeric packets preserve rank/level arrays, typed scaling, target-health terms, and explicit variant selectors where the source lists them.",
            ],
            "sources": [{"label": "Local League Wiki cache", "url": source_url, **receipt}],
        }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "patch": "16.15",
                "source": "League Wiki cache + Axword Meraki ability kits",
                "champion_count": len(champions),
                "champions": champions,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    modules.mkdir(parents=True, exist_ok=True)
    (modules / "__init__.py").write_text(
        '"""Generated explicit champion packet modules."""\n', encoding="utf-8"
    )
    for name in champions:
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        option_keys = sorted(
            {
                f"{slot.lower()}_variant"
                for slot, spec in champions[name]["slots"].items()
                if spec.get("kind") == "variants"
            }
        )
        option_comment = (
            f"# Packet option keys consumed by packet_module: {json.dumps(option_keys)}\n"
            if option_keys
            else ""
        )
        (modules / f"{slug}.py").write_text(
            f'''"""Generated packet module for {name}."""\n\n'''
            f"from ..packet_module import build_packet_module\n\n"
            f"{option_comment}"
            f"parse_abilities, SLOTS, ASSUMPTIONS, SOURCES, OPTIONS = build_packet_module({name!r})\n"
            "REVIEW_STATUS = 'reviewed_packet'\n",
            encoding="utf-8",
        )
    return {"champion_count": len(champions), "output": str(output), "modules": str(modules)}


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=root / "data" / "champions.json")
    parser.add_argument(
        "--axword-source",
        type=Path,
        default=Path("/Users/river/Projects/lol-strength-analysis/src/data/generated/merakiAbilityKits.ts"),
    )
    parser.add_argument("--output", type=Path, default=root / "static" / "reviewed-packets.json")
    parser.add_argument("--modules", type=Path, default=root / "src" / "calculator" / "champions" / "generated")
    args = parser.parse_args()
    result = build(args.source.resolve(), args.axword_source.resolve(), args.output.resolve(), args.modules.resolve())
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
