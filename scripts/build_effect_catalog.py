#!/usr/bin/env python3
"""Compile Wiki item effects into a compact, ordered event catalogue.

This is intentionally a signal catalogue, not a claim that every effect is
safe for the reviewed fight engine. It keeps the original Wiki text, detected
mathematical phrases, and an explicit trigger -> resolution order for the
roster BIS preview to reason about conditional value.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

NUMBER_RE = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?%?")


def _text(item: dict[str, Any]) -> str:
    parts = [str(item.get("simpleDescription") or ""), str(item.get("active") or "")]
    parts.extend(
        str(effect.get("effects") or "")
        for effect in item.get("passives", [])
        if isinstance(effect, dict)
    )
    return " ".join(parts).replace("\n", " ").strip()


def _effect(item: dict[str, Any]) -> dict[str, Any]:
    raw = _text(item)
    text = raw.lower()
    # Categories come from the compact patch snapshot; derive them from the
    # effect wording here so the asset is independent of the frontend shape.
    tags: list[str] = []
    checks = (
        ("healing_reduction", "wounds" in text or "grievous" in text),
        (
            "damage_over_time",
            any(
                token in text
                for token in ("burn", "per second", "per tick", "over 3 seconds")
            ),
        ),
        (
            "damage_amp",
            any(
                token in text
                for token in ("bonus damage", "more damage", "damage taken")
            ),
        ),
        ("on_hit", "on-hit" in text or "on hit" in text),
        ("basic_attack", "basic attack" in text or "attacks" in text),
        ("ability_hit", "ability" in text or "spell" in text),
        ("shield", "shield" in text),
        (
            "healing",
            bool(re.search(r"\bheal(?:ing)?\b|lifesteal|omnivamp|regenerat", text)),
        ),
        ("armor_penetration", "armor penetration" in text or "lethality" in text),
        ("magic_penetration", "magic penetration" in text or "magic resist" in text),
        ("active", bool(item.get("active"))),
    )
    tags.extend(name for name, enabled in checks if enabled)
    order: list[str] = []
    if any(
        token in text
        for token in (
            "damaging ability",
            "ability hits",
            "dealing damage",
            "attacks deal",
        )
    ):
        order.append("trigger damage resolves")
    if "wounds" in text or "grievous" in text:
        order.append("apply healing reduction after the triggering damage")
    if "burn" in text or "per second" in text or "per tick" in text:
        order.append("apply periodic damage after the hit, then tick over its duration")
    if "after" in text or "within" in text or "for 3 seconds" in text:
        order.append("respect the stated delay, duration, and cooldown")
    if "shield" in text or re.search(
        r"\bheal(?:ing)?\b|lifesteal|omnivamp|regenerat", text
    ):
        order.append("resolve healing/shield modification with the recipient event")
    if "when hit" in text or "being hit" in text:
        order.insert(0, "incoming damage resolves")
        order.append("retaliation resolves after the incoming hit")
    if not order:
        order.append("static stats apply before the combat window")
    formulas = sorted(set(NUMBER_RE.findall(raw)))
    return {
        "name": item.get("name") or "",
        "id": int(item.get("id") or 0),
        "tier": item.get("tier"),
        "tags": tags,
        "formulas": formulas,
        "eventOrder": order,
        "passives": [
            {"name": effect.get("name") or "", "text": effect.get("effects") or ""}
            for effect in item.get("passives", [])
            if isinstance(effect, dict)
            and (effect.get("name") or effect.get("effects"))
        ],
        "active": item.get("active") or None,
    }


def build_catalog(source: Path, patch: str) -> dict[str, Any]:
    raw = json.loads(source.read_text(encoding="utf-8"))
    items = {
        _effect(item)["id"]: _effect(item)
        for item in raw.values()
        if isinstance(item, dict) and not item.get("removed")
    }
    return {
        "schema_version": 1,
        "patch": patch,
        "item_count": len(items),
        "source": {
            "kind": "local Wiki cache",
            # as_posix() so a Windows rebuild matches a macOS/Linux one.
            "path": source.relative_to(source.parents[1]).as_posix(),
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        },
        "items": {str(item_id): effect for item_id, effect in sorted(items.items())},
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=root / "data" / "items.json")
    parser.add_argument(
        "--output", type=Path, default=root / "static" / "effect-catalog.json"
    )
    parser.add_argument("--patch", default="26.15")
    args = parser.parse_args()
    catalog = build_catalog(args.source.resolve(), args.patch)
    args.output.write_text(
        json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.output} ({catalog['item_count']} items)")


if __name__ == "__main__":
    main()
