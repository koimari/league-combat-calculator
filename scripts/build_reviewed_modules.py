#!/usr/bin/env python3
"""Generate reviewed champion packet evidence from pinned local sources.

The generated evidence is deliberately explicit: every cached ability slot is
represented either by a numeric Wiki/Axword packet or by a sourced no-damage
entry. Runtime modules consume or supersede this evidence; this script never
writes executable champion modules.

Source supply contract (issue #134): the Wiki index and the Axword Meraki kit
source resolve repo-relative by default (``data/wiki/league-wiki.sqlite3`` and
the sibling ``lol-strength-analysis`` checkout) and are overridable per run
with ``--wiki-db`` / ``LCC_WIKI_DB`` and ``--axword-source`` /
``LCC_AXWORD_SOURCE``.  A missing source aborts with one actionable error, and
a champion is only labeled ``reviewed_packet`` when the Wiki index carries a
current revision receipt for its page — revision-less packets are labeled
``generated_packet`` and a zero-receipt run aborts entirely.
"""

from __future__ import annotations

import argparse
import json
import os
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

try:
    from source_receipt import source_receipt
except ImportError:  # imported as scripts.build_reviewed_modules in tests
    from scripts.source_receipt import source_receipt

from src.calculator.cast_dependency import BASE_CAST_SLOTS  # noqa: E402

SLOTS = BASE_CAST_SLOTS

REPO_ROOT = Path(__file__).resolve().parents[1]

# Source supply contract (issue #134): every external dependency resolves
# repo-relative by default and is overridable per-run via CLI flag or
# environment variable.  No developer-home paths are hardcoded anywhere, so
# the generator behaves identically on any machine that supplies the files.
DEFAULT_WIKI_DB = REPO_ROOT / "data" / "wiki" / "league-wiki.sqlite3"
DEFAULT_AXWORD_SOURCE = (
    REPO_ROOT.parent
    / "lol-strength-analysis"
    / "src"
    / "data"
    / "generated"
    / "merakiAbilityKits.ts"
)


def resolve_wiki_db(cli_value: str | Path | None = None) -> Path:
    """Resolve the Local League Wiki cache: --wiki-db > LCC_WIKI_DB > repo default."""
    raw = cli_value or os.environ.get("LCC_WIKI_DB")
    return Path(raw).expanduser() if raw else DEFAULT_WIKI_DB


def resolve_axword_source(cli_value: str | Path | None = None) -> Path:
    """Resolve the Axword Meraki kit source: flag > LCC_AXWORD_SOURCE > sibling repo."""
    raw = cli_value or os.environ.get("LCC_AXWORD_SOURCE")
    return Path(raw).expanduser() if raw else DEFAULT_AXWORD_SOURCE


def _derive_patch(champions_source: Path) -> str:
    """Derive the patch string from the cache's pinned ddragon icon URLs.

    Replaces the old hardcoded ``"patch": "16.15"`` so the emitted value
    always matches the cache the packets were built from.
    """
    try:
        raw = json.loads(champions_source.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return "unknown"
    for entry in raw.values():
        if not isinstance(entry, dict):
            continue
        match = re.search(
            r"cdn/([0-9]+\.[0-9]+)\.[0-9]+/img/champion/",
            str(entry.get("icon") or ""),
        )
        if match:
            return match.group(1)
    return "unknown"


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


def _wiki_revisions(wiki_db: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Read revision receipts from the local read-only Wiki index.

    Fail closed (issue #134): a missing or unreadable cache raises one
    actionable error instead of silently returning ``{}`` — an empty receipt
    set used to let ``build()`` label every champion ``reviewed_packet``
    against no evidence at all.
    """
    db = Path(wiki_db).expanduser() if wiki_db else resolve_wiki_db()
    if not db.is_file():
        raise RuntimeError(
            f"Local League Wiki cache not found: {db}\n"
            "Supply it with --wiki-db or the LCC_WIKI_DB environment "
            "variable (repo convention: data/wiki/league-wiki.sqlite3)."
        )
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as connection:
            rows = connection.execute(
                "SELECT title, revision_id, revision_timestamp "
                "FROM pages WHERE namespace = 0"
            ).fetchall()
    except (OSError, sqlite3.Error) as exc:
        raise RuntimeError(
            f"Local League Wiki cache is unreadable ({db}): {exc}\n"
            "Supply a readable copy with --wiki-db or LCC_WIKI_DB."
        ) from exc
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
    return (
        {
            "MAGIC_DAMAGE": "magic",
            "PHYSICAL_DAMAGE": "physical",
            "TRUE_DAMAGE": "true",
        }.get(field)
        or infer_damage_type_from_attribute(attribute)
        or "magic"
    )


def _wiki_cooldown(ability: dict[str, Any]) -> float:
    """The rank-1 cooldown, recorded as evidence of the row's shape.

    A packet's ``cooldown`` is a scalar and a cooldown is a rank array, so
    this field can only ever be the array's first entry.  It is no longer
    served: ``packet_module._packet_cooldown`` reads the cached row at the
    rank being cast, which is the cooldown's one home.  The field stays for
    the receipt (and pins the packet digests already accepted by named
    modules); a regeneration is free to drop it.
    """
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
        (
            len(modifier.get("values", []))
            for leveling in levelings
            for modifier in leveling.get("modifiers", [])
        ),
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
                " ".join(
                    str(effect.get("description", ""))
                    for effect in ability.get("effects", [])
                ),
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
                if (
                    slot == "P"
                    and "damage" not in str(ability.get("blurb", "")).lower()
                ):
                    continue
                # Some Wiki effect groups attach a percentage state modifier
                # to an effect that also mentions damage (notably Irelia W's
                # incoming-damage reduction).  Do not mistake that modifier
                # for the spell's outgoing damage packet.
                if (
                    "reduces incoming" in effect_description
                    or "damage reduction" in effect_description
                ):
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
                if any(
                    term in attr_lower
                    for term in (
                        "max health damage",
                        "current health damage",
                        "missing health damage",
                    )
                ):
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
            specs.append(
                packet
                or {
                    "kind": "wiki_attribute",
                    "attribute": selected_attribute,
                    "damage_type": _damage_kind(ability, selected_attribute),
                    "ranks": "level" if slot == "P" else "rank",
                    "source": [slot, ability_index],
                    "name": str(ability.get("name", slot)),
                }
            )
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
                    selected_attribute = str(
                        leveling.get("attribute", "Per-Level Scaling")
                    )
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


def _axword_spec(ability: dict[str, Any]) -> dict[str, Any] | None:
    damage = ability.get("damage")
    if not isinstance(damage, dict) or not damage.get("base"):
        return None
    return {
        "kind": "packet",
        "name": str(ability.get("name", "")),
        "cooldown": float(ability.get("cooldown", 0.0)),
        "damage_type": {"magical": "magic"}.get(
            str(damage.get("type")), str(damage.get("type", "magic"))
        ),
        "base": [float(value) for value in damage.get("base", [])],
        "ratios": [
            {
                "stat": str(ratio.get("stat", "")),
                "values": [float(value) for value in ratio.get("values", [])],
            }
            for ratio in damage.get("ratios", [])
        ],
    }


def build(
    source: Path,
    axword_source: Path,
    output: Path,
    wiki_db: str | Path | None = None,
) -> dict[str, Any]:
    """Generate the reviewed-packet evidence asset.

    Fail closed (issue #134): every source is pre-flighted before any output
    is written, and a champion is only ever labeled ``reviewed_packet`` when
    the current Wiki index carries a revision receipt for its page.  A run
    without any receipts aborts entirely.
    """
    if not source.is_file():
        raise RuntimeError(
            f"Champion cache not found: {source}\n"
            "Supply it with --source (repo convention: data/champions.json)."
        )
    if not axword_source.is_file():
        raise RuntimeError(
            f"Axword Meraki kit source not found: {axword_source}\n"
            "Supply it with --axword-source or the LCC_AXWORD_SOURCE "
            "environment variable (repo convention: the sibling "
            "lol-strength-analysis checkout)."
        )
    raw = json.loads(source.read_text(encoding="utf-8"))
    axword = _axword_by_name(_load_axword(axword_source))
    revisions = _wiki_revisions(wiki_db)
    if not revisions:
        raise RuntimeError(
            "The Wiki index returned zero revision receipts — no champion can "
            "be labeled reviewed_packet against no evidence. Check --wiki-db / "
            "LCC_WIKI_DB and rebuild the index before generating packets."
        )
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
                "damage" in str(ability.get("blurb", "")).lower() for ability in entries
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
        source_url = "https://wiki.leagueoflegends.com/en-us/" + quote(
            name.replace(" ", "_")
        )
        receipt = revisions.get(name, {})
        # A champion whose page has no revision receipt in the current index
        # is generated, never reviewed: the packet may embed stale numbers
        # and nothing proves what was read.
        review_status = "reviewed_packet" if receipt else "generated_packet"
        champions[name] = {
            "review_status": review_status,
            "review_manifest": {
                "module_kind": "dedicated_champion_module",
                "formula_slots": sorted(
                    slot
                    for slot, value in slots.items()
                    if value.get("kind") in {"packet", "variants", "wiki_attribute"}
                ),
                "no_damage_slots": sorted(
                    slot
                    for slot, value in slots.items()
                    if value.get("kind") == "no_damage"
                ),
                "event_model": "typed_packet_order",
            },
            "slots": slots,
            "assumptions": [
                "Every slot is an explicit packet or sourced no-damage entry from the pinned local Wiki cache; no runtime archetype inference is used.",
                "Numeric packets preserve rank/level arrays, typed scaling, target-health terms, and explicit variant selectors where the source lists them.",
            ],
            "sources": [
                {"label": "Local League Wiki cache", "url": source_url, **receipt}
            ],
        }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "patch": _derive_patch(source),
                "source": "League Wiki cache + Axword Meraki ability kits",
                "champion_count": len(champions),
                "source_receipts": {
                    "champions.json": source_receipt(source, kind="tracked wiki cache"),
                    "axword_source": source_receipt(
                        axword_source, kind="Axword Meraki ability kits"
                    ),
                },
                "champions": champions,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "champion_count": len(champions),
        "output": str(output),
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Source supply (issue #134, no developer-home defaults):\n"
            "  --wiki-db / LCC_WIKI_DB      -> data/wiki/league-wiki.sqlite3\n"
            "  --axword-source / LCC_AXWORD_SOURCE\n"
            "                                -> sibling lol-strength-analysis checkout\n"
            "  --source                     -> data/champions.json"
        ),
    )
    parser.add_argument("--source", type=Path, default=root / "data" / "champions.json")
    parser.add_argument(
        "--axword-source",
        type=Path,
        default=None,
        help="Axword Meraki ability kits source (env LCC_AXWORD_SOURCE)",
    )
    parser.add_argument(
        "--wiki-db",
        type=Path,
        default=None,
        help="Local League Wiki sqlite index (env LCC_WIKI_DB)",
    )
    parser.add_argument(
        "--output", type=Path, default=root / "static" / "reviewed-packets.json"
    )
    args = parser.parse_args()
    try:
        result = build(
            args.source.resolve(),
            resolve_axword_source(args.axword_source).resolve(),
            args.output.resolve(),
            wiki_db=resolve_wiki_db(args.wiki_db).resolve(),
        )
    except RuntimeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
