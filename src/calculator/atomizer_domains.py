"""Domain extractors for the unified Atomizer.

Each domain maps one cached data family to Atom records:
- items: per-effect fragments (branches + sentences) classified independently,
  with values extracted from the fragment text — the correct replacement for
  the buggy first-passive-absorbs-everything item atomizer.
- abilities: champion ability slots -> effects -> leveling modifiers.
- runes: keystone numerical values.
- economics: per-item sell/combine rows (already structured records).
- stats: champion/item stat blocks.
- champions: delegates to the specialist champion atomizer (extract_atoms).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from .atom_spelling import _snake, _stat_unit
from .atomizer import Atomizer, number_and_unit, split_effect_fragments

# keyword -> (atom_id, behavior)
# Coverage classes: damage, heal, shield, crowd-control
# mobility, on-hit, burn, stats — plus summon/stack/vision/economy for the
# real corpus. Matching is a lowered substring check against each effect's
# own fragment text; evidence receipts name the exact keyword that fired.
_ITEM_KEYWORDS: tuple[tuple[str, str, str], ...] = (
    # --- damage ---
    ("true damage", "damage.true", "damage"),
    ("magic damage", "damage.magic", "damage"),
    ("physical damage", "damage.physical", "damage"),
    ("bonus damage", "damage.bonus", "damage"),
    ("increased damage", "damage.bonus", "damage"),
    ("ability damage", "damage.ability", "damage"),
    ("pet damage", "damage.pet", "damage"),
    ("basic attack", "damage.basic_attack", "damage"),
    ("incoming", "damage.reduction", "damage"),
    ("damage taken", "damage.reduction", "damage"),
    ("burn", "damage.burn", "damage"),
    # --- heal / shield ---
    ("heal", "heal.flat", "heal"),
    ("healing", "heal.flat", "heal"),
    ("shield", "shield.flat", "shield"),
    # --- crowd control / mobility ---
    ("dash", "control.dash", "control"),
    ("slow", "control.slow", "control"),
    ("stun", "control.stun", "control"),
    ("root", "control.root", "control"),
    ("knock up", "control.knockup", "control"),
    ("knockup", "control.knockup", "control"),
    ("knock back", "control.knockback", "control"),
    ("knockback", "control.knockback", "control"),
    ("blind", "control.blind", "control"),
    ("taunt", "control.taunt", "control"),
    ("fear", "control.fear", "control"),
    ("charm", "control.charm", "control"),
    ("immobilize", "control.immobilize", "control"),
    ("stasis", "control.stasis", "control"),
    ("curse", "control.curse", "control"),
    ("tether", "control.tether", "control"),
    ("movement speed", "control.movement_speed", "control"),
    ("move speed", "control.movement_speed", "control"),
    ("ghost", "control.ghosted", "control"),
    # --- on-hit ---
    ("on-hit", "damage.on_hit", "damage"),
    ("on hit", "damage.on_hit", "damage"),
    ("energize", "damage.on_hit", "damage"),
    # --- stats ---
    ("attack damage", "stat.attack_damage", "stat"),
    ("ability power", "stat.ability_power", "stat"),
    ("health", "stat.health", "stat"),
    ("health regen", "stat.health_regen", "stat"),
    ("health regeneration", "stat.health_regen", "stat"),
    ("mana", "stat.mana", "stat"),
    ("mana regen", "stat.mana_regen", "stat"),
    ("mana regeneration", "stat.mana_regen", "stat"),
    ("armor", "stat.armor", "stat"),
    ("armor penetration", "stat.armor_penetration", "stat"),
    ("armor pen", "stat.armor_penetration", "stat"),
    ("magic resistance", "stat.magic_resistance", "stat"),
    ("magic penetration", "stat.magic_penetration", "stat"),
    ("magic pen", "stat.magic_penetration", "stat"),
    ("attack speed", "stat.attack_speed", "stat"),
    ("ability haste", "stat.haste", "stat"),
    ("summoner spell haste", "stat.haste", "stat"),
    ("critical strike chance", "stat.crit", "stat"),
    ("critical strike", "stat.crit", "stat"),
    ("lethality", "stat.lethality", "stat"),
    ("life steal", "stat.lifesteal", "stat"),
    ("omnivamp", "stat.omnivamp", "stat"),
    ("tenacity", "stat.tenacity", "stat"),
    ("adaptive force", "stat.adaptive_force", "stat"),
    ("attack range", "stat.attack_range", "stat"),
    # --- timing ---
    ("cooldown", "timing.cooldown", "timing"),
    # --- summon / stack / vision / economy ---
    ("companion", "summon.companion", "summon"),
    ("smite", "summon.companion", "summon"),
    ("stack", "stack.gain", "stack"),
    ("stealth ward", "vision.ward", "vision"),
    ("sight", "vision.sight", "vision"),
    ("gold", "economy.gold", "economy"),
    ("kill", "economy.gold", "economy"),
)


def atomize_item(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Atomize one item: stats + shop + every passive/active fragment.

    Fragments are classified per-effect (never against a whole-item blob),
    and dedup happens at emission by (atom_id, behavior) with evidence
    receipts naming the exact effect + keyword.
    """
    a = Atomizer("items", source_ref=item.get("name", "?"))
    name = str(item.get("name", "Unknown"))
    # stats block
    for stat_name, stat in (item.get("stats") or {}).items():
        if isinstance(stat, dict):
            flat = stat.get("flat")
            if isinstance(flat, (int, float)) and flat:
                a.add(
                    f"stat.{_snake(stat_name)}",
                    "stat",
                    f"{name}.stats.{stat_name}",
                    stat_name,
                    values=[float(flat)],
                    units=["flat"],
                    evidence=[f"stats.{stat_name}.flat"],
                )
    prices = (item.get("shop") or {}).get("prices") or {}
    if isinstance(prices.get("total"), (int, float)):
        a.add(
            "economy.total",
            "economy",
            f"{name}.shop.prices.total",
            "total",
            values=[float(prices["total"])],
            units=["gold"],
            evidence=["shop.prices.total"],
        )
    # passives and actives as per-effect fragments
    for effect_kind, effects in (
        ("passive", item.get("passives")),
        ("active", item.get("active")),
    ):
        if not effects:
            continue
        effect_rows = [effects] if isinstance(effects, dict) else effects
        for index, effect in enumerate(effect_rows):
            effect_name = str(
                effect.get("name") or f"{effect_kind.capitalize()} {index + 1}"
            )
            for fragment_path, fragment_text in split_effect_fragments(
                effect, prefix=f"{name}.{effect_kind}s", index=index
            ):
                values, units = number_and_unit(fragment_text)
                lowered = fragment_text.lower()
                lockout_match = re.search(
                    r"same target once every\s+\{\{fd\|"
                    r"(\d+(?:\.\d+)?)\}\}\s+seconds\s+"
                    r"from the same cast instance",
                    fragment_text,
                    re.IGNORECASE,
                )
                if lockout_match:
                    a.add(
                        "timing.same_target_cast_lockout",
                        "timing",
                        fragment_path,
                        effect_name,
                        values=[float(lockout_match.group(1))],
                        units=["seconds"],
                        evidence=[f"{effect_kind}:{effect_name}@kw:ability damage"],
                    )
                for keyword, atom_id, behavior in _ITEM_KEYWORDS:
                    if keyword in lowered:
                        evidence = f"{effect_kind}:{effect_name}@kw:{keyword}"
                        a.add(
                            atom_id,
                            behavior,
                            fragment_path,
                            effect_name,
                            values=values,
                            units=units,
                            evidence=[evidence],
                        )
    return a.emit()


def atomize_item_catalogue(
    items: Mapping[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    return {str(key): atomize_item(item) for key, item in sorted(items.items())}


def atomize_rune_catalogue(
    runes: Mapping[str, Mapping[str, Any]] | Iterable[Mapping[str, Any]] | None,
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    records = runes.values() if isinstance(runes, Mapping) else runes or ()
    for rune in records:
        a = Atomizer("runes", source_ref=str(rune.get("name", "?")))
        name = str(rune.get("name", "?"))

        def numeric_values(value: Any) -> list[float]:
            if isinstance(value, bool):
                return []
            if isinstance(value, (int, float)):
                return [float(value)]
            if isinstance(value, list):
                values: list[float] = []
                for item in value:
                    values.extend(numeric_values(item))
                return values
            return []

        def unit_for(path: str) -> str:
            lowered = path.lower()
            path_parts = lowered.replace(".", "_").split("_")
            if "attack_speed_percent" in lowered:
                return "percent"
            if "bonus_move_speed" in lowered:
                return "percent"
            if "adaptive_force" in lowered:
                return "adaptive_force"
            if any(
                token in path_parts
                for token in (
                    "ratio",
                    "ratios",
                    "percent",
                    "percentage",
                    "effectiveness",
                )
            ):
                return "ratio"
            if any(token in lowered for token in ("heal", "shield")):
                return "health"
            if any(token in lowered for token in ("cooldown", "duration", "seconds")):
                return "s"
            if any(
                token in lowered for token in ("radius", "width", "distance", "units")
            ):
                return "units"
            if any(
                token in lowered
                for token in ("stack", "stacks", "charge", "charges", "count")
            ):
                return "count"
            return "flat"

        def visit(value: Any, path: str, *, a=a, name=name) -> None:
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    visit(sub_value, f"{path}.{sub_key}" if path else sub_key)
                return
            values = numeric_values(value)
            if not values or not path:
                return
            a.add(
                f"rune.{_snake(path)}",
                "rune",
                f"{name}.{path}",
                name,
                values=values,
                units=[unit_for(path)] * len(values),
                evidence=[f"{path}={value}"],
            )

        for key, value in rune.items():
            if key in {"name", "path", "icon", "implemented", "description"}:
                continue
            visit(value, key)
        out[name] = a.emit()
    return out


def atomize_economics(economics: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Atomize the sourced sell/combine tables."""
    out: dict[str, list[dict[str, Any]]] = {}
    for row in economics.get("per_item_sell", []):
        a = Atomizer("economics", source_ref=str(row.get("name", "?")))
        name = str(row.get("name", "?"))
        if isinstance(row.get("total"), (int, float)):
            a.add(
                "economy.total",
                "economy",
                f"{name}.total",
                name,
                values=[float(row["total"])],
                units=["gold"],
                evidence=["per_item_sell.total"],
            )
        if isinstance(row.get("ddragon_sell"), (int, float)):
            a.add(
                "economy.sell",
                "economy",
                f"{name}.sell",
                name,
                values=[float(row["ddragon_sell"])],
                units=["gold"],
                evidence=["per_item_sell.ddragon_sell"],
            )
        out[name] = a.emit()
    for row in economics.get("combine_costs", []):
        a = Atomizer("economics", source_ref=str(row.get("name", "?")))
        name = str(row.get("name", "?"))
        if isinstance(row.get("derived_combine"), (int, float)):
            a.add(
                "economy.combine",
                "economy",
                f"{name}.combine",
                name,
                values=[float(row["derived_combine"])],
                units=["gold"],
                evidence=["combine_costs.derived_combine"],
            )
        out.setdefault(name, []).extend(a.emit())
    return out


def atomize_stats(champion: Mapping[str, Any]) -> list[dict[str, Any]]:
    a = Atomizer("stats", source_ref=str(champion.get("name", "?")))
    name = str(champion.get("name", "?"))
    for stat_name, stat in (champion.get("stats") or {}).items():
        if not isinstance(stat, dict):
            continue
        for field, value in stat.items():
            if isinstance(value, (int, float)) and value:
                a.add(
                    f"stat.{_snake(stat_name)}.{_snake(field)}",
                    "stat",
                    f"{name}.stats.{stat_name}.{field}",
                    stat_name,
                    values=[float(value)],
                    units=[_stat_unit(field)],
                    evidence=[f"stats.{stat_name}.{field}"],
                )
    return a.emit()
