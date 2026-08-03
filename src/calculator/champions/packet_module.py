"""Shared runtime for generated, explicit Wiki/Axword champion packets.

The generated champion modules each select their own packet specification at
build time.  This helper only evaluates those already-selected formulas; it
does not inspect attributes or choose an archetype at runtime.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..ability_spec import DamagePart
from .engine import SlotCtx, build_parser
from .slotlib import damage_entry, simple_damage

_ROOT = Path(__file__).resolve().parents[3]
_PACKET_PATH = _ROOT / "static" / "reviewed-packets.json"


@lru_cache(maxsize=1)
def _packet_specs() -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(_PACKET_PATH.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Reviewed packet asset is unavailable: {_PACKET_PATH}"
        ) from exc
    champions = payload.get("champions") if isinstance(payload, dict) else None
    if not isinstance(champions, dict):
        raise RuntimeError("Reviewed packet asset has no champion map")
    return champions


def _ranked(values: list[float], rank: int) -> float:
    if not values:
        return 0.0
    return float(values[min(max(rank, 1) - 1, len(values) - 1)])


def _packet_parser(spec: dict[str, Any], slot: str):
    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None
        rank = ctx.level if spec.get("ranks") == "level" else ctx.rank_for()
        if rank < 1:
            return None

        base = _ranked(spec.get("base", []), rank)
        static = base
        target_terms: list[tuple[str, float]] = []
        for ratio in spec.get("ratios", []):
            stat = str(ratio.get("stat", ""))
            value = _ranked(ratio.get("values", []), rank)
            if stat in {"targetMaxHp", "targetCurrentHp", "targetMissingHp"}:
                target_terms.append((stat, value))
                continue
            stat_key = {
                "ap": "ability_power",
                "ad": "attack_damage",
                "bonusAd": "bonus_attack_damage",
                "health": "health",
                "bonusHealth": "bonus_health",
                "armor": "armor",
                "magicResistance": "magic_resistance",
            }.get(stat)
            if stat_key:
                static += value * float(ctx.stats.get(stat_key, 0.0))

        damage_type = str(spec.get("damage_type", "magic"))
        if target_terms:
            target_max = float(ctx.target.get("target_max_health", 0.0))

            def hp_scaled(missing_ratio: float) -> float:
                current_ratio = max(0.0, 1.0 - missing_ratio)
                total = static
                for kind, value in target_terms:
                    if kind == "targetMaxHp":
                        total += value * target_max
                    elif kind == "targetCurrentHp":
                        total += value * target_max * current_ratio
                    else:
                        total += value * target_max * missing_ratio
                return total

            parts = (DamagePart(damage_type, hp_scaled_damage=hp_scaled),)
            total_raw = static
        else:
            parts = (DamagePart(damage_type, amount=static),)
            total_raw = static

        entry = damage_entry(
            ability.get("name", spec.get("name", f"Ability {slot}")),
            rank,
            float(spec.get("cooldown", 0.0)),
            total_raw,
            damage_type,
        )
        entry["parts"] = parts
        entry["total_raw"] = total_raw
        if spec.get("cast_time") is not None:
            entry["cast_time"] = float(spec["cast_time"])
        if spec.get("count", 1) != 1:
            entry["parts"] = tuple(
                DamagePart(
                    part.damage_type,
                    amount=part.amount,
                    count=int(spec["count"]),
                    hp_scaled_damage=part.hp_scaled_damage,
                )
                for part in parts
            )
        return entry

    parse.phase = "damage"
    return parse


def _no_formula_parser(
    slot: str, *, reason: str = "No enemy damage is listed for this ability."
):
    def parse(ctx: SlotCtx) -> dict[str, Any] | None:
        ability = ctx.ability()
        if ability is None:
            return None
        return {
            "name": ability.get("name", f"Ability {slot}"),
            "rank": ctx.rank_for(),
            "cooldown": 0.0,
            "damage_type": "magic",
            "total_raw": 0.0,
            "parts": (),
            "detail": reason,
        }

    parse.phase = "damage"
    return parse


def build_packet_module(champion_name: str):
    """Return the explicit parser and metadata for one generated champion."""
    champion = _packet_specs().get(champion_name)
    if champion is None:
        raise KeyError(f"No reviewed packet specification for {champion_name!r}")
    slots = {}
    options: list[dict[str, Any]] = []
    for slot in ("Q", "W", "E", "R", "P"):
        spec = champion.get("slots", {}).get(slot)
        if not spec:
            continue
        variants = spec.get("variants") if spec.get("kind") == "variants" else None
        if variants:
            variant_parsers = []
            for variant in variants:
                if variant.get("kind") == "wiki_attribute":
                    variant_parsers.append(
                        simple_damage(
                            attr=str(variant["attribute"]),
                            dmg_type=str(variant.get("damage_type", "auto")),
                            ranks=str(variant.get("ranks", "rank")),
                            source=(
                                tuple(variant["source"])
                                if variant.get("source")
                                else None
                            ),
                        )
                    )
                elif variant.get("kind") == "packet":
                    variant_parsers.append(_packet_parser(variant, slot))
                else:
                    variant_parsers.append(
                        _no_formula_parser(
                            slot,
                            reason=str(
                                variant.get(
                                    "reason",
                                    "No enemy damage is listed for this variant.",
                                )
                            ),
                        )
                    )
            option_key = f"{slot.lower()}_variant"

            def select_variant(
                ctx: SlotCtx,
                parsers=variant_parsers,
                key=option_key,
                default=spec.get("default", 0),
            ):
                try:
                    index = int(ctx.options.get(key, default))
                except (TypeError, ValueError):
                    index = int(default)
                index = max(0, min(index, len(parsers) - 1))
                return parsers[index](ctx)

            select_variant.phase = getattr(variant_parsers[0], "phase", "damage")
            slots[slot] = select_variant
            options.append(
                {
                    "key": option_key,
                    "type": "int",
                    "default": int(spec.get("default", 0)),
                    "label": f"{slot} packet variant",
                    "min": 0,
                    "max": len(variants) - 1,
                }
            )
        elif spec.get("kind") == "wiki_attribute":
            slots[slot] = simple_damage(
                attr=str(spec["attribute"]),
                dmg_type=str(spec.get("damage_type", "auto")),
                ranks=str(spec.get("ranks", "rank")),
                source=tuple(spec["source"]) if spec.get("source") else None,
            )
        elif spec.get("kind") == "packet":
            slots[slot] = _packet_parser(spec, slot)
        elif spec.get("kind") == "no_damage":
            slots[slot] = _no_formula_parser(
                slot,
                reason=str(
                    spec.get("reason", "No enemy damage is listed for this ability.")
                ),
            )
        else:
            slots[slot] = _no_formula_parser(slot)
    parser = build_parser(slots, champion_name)

    def parse_abilities(*args, **kwargs):
        result = parser(*args, **kwargs)
        for entry in result.values():
            if "parts" in entry:
                continue
            entry["parts"] = ()
            entry.setdefault("total_raw", 0.0)
            on_hit = entry.get("on_hit") or {}
            entry.setdefault("damage_type", on_hit.get("damage_type", "physical"))
        return result

    assumptions = list(champion.get("assumptions", []))
    sources = list(champion.get("sources", []))
    return parse_abilities, slots, assumptions, sources, options
