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
from typing import Any

from .atomizer import Atomizer, number_and_unit, split_effect_fragments
from .champions.slotlib import (
    extract_description_control_durations,
    extract_description_damage_reduction,
    extract_description_damage_reduction_cap,
    extract_description_duration,
    extract_description_invulnerability_timing,
    extract_description_shield_duration,
)

# keyword -> (atom_id, behavior)
# Coverage classes (issue #140): damage, heal, shield, crowd-control
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


def atomize_item(item: dict[str, Any]) -> list[dict[str, Any]]:
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
                    [float(flat)],
                    ["flat"],
                    [f"stats.{stat_name}.flat"],
                )
    # shop prices
    prices = (item.get("shop") or {}).get("prices") or {}
    if isinstance(prices.get("total"), (int, float)):
        a.add(
            "economy.total",
            "economy",
            f"{name}.shop.prices.total",
            "total",
            [float(prices["total"])],
            ["gold"],
            ["shop.prices.total"],
        )
    # passives and actives as per-effect fragments
    for effect_kind, effects in (
        ("passive", item.get("passives")),
        ("active", item.get("active")),
    ):
        if not effects:
            continue
        if isinstance(effects, dict):
            effects = [effects]
        for index, effect in enumerate(effects):
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
                        [float(lockout_match.group(1))],
                        ["seconds"],
                        [f"{effect_kind}:{effect_name}@kw:ability damage"],
                    )
                for keyword, atom_id, behavior in _ITEM_KEYWORDS:
                    if keyword in lowered:
                        evidence = f"{effect_kind}:{effect_name}@kw:{keyword}"
                        a.add(
                            atom_id,
                            behavior,
                            fragment_path,
                            effect_name,
                            values,
                            units,
                            [evidence],
                        )
    return a.emit()


def atomize_item_catalogue(
    items: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    return {str(key): atomize_item(item) for key, item in sorted(items.items())}


# P1 Slice 11: Ashe Q — effects[0] is the Focus stack window (4s,
# mislabeled "active duration" before), effects[1] is the real 6s active
# window ("Active: For 6 seconds...").  An explicit map, NOT a keyword
# rule (61 genuine actives mention stacks) — every other champion's
# atoms stay byte-identical.
_FOCUS_WINDOW_EFFECTS = frozenset({("Ashe", "Q", 0)})
_FOCUS_WINDOW_ACTIVE_EFFECTS = {"Ashe": {"Q": 1}}


def atomize_abilities(
    champion_name: str,
    champion: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Atomize one champion's ability slots -> effects -> leveling modifiers."""
    out: dict[str, list[dict[str, Any]]] = {}
    for slot, entries in (champion.get("abilities") or {}).items():
        a = Atomizer("abilities", source_ref=f"{champion_name}.{slot}")
        for entry_index, entry in enumerate(entries or []):
            ability_name = str(entry.get("name") or f"{slot}{entry_index}")
            # cooldown / cost
            cooldown = entry.get("cooldown")
            if isinstance(cooldown, dict):
                for mod_index, mod in enumerate(cooldown.get("modifiers") or []):
                    values = [
                        float(v)
                        for v in mod.get("values", [])
                        if isinstance(v, (int, float))
                    ]
                    if values:
                        a.add(
                            "timing.cooldown",
                            "timing",
                            f"{champion_name}.{slot}[{entry_index}].cooldown",
                            ability_name,
                            values,
                            ["s"] * len(values),
                            [f"cooldown.modifiers[{mod_index}]"],
                        )
            # P1 Slice 11: the effect-0-only scan mislabels multi-effect
            # entries whose effects[0] is a passive — the explicit map
            # (below) relabels Ashe Q's Focus window + extracts the real
            # 6s active duration.
            # The scalar timing.control_duration is emitted from the FIRST
            # control-bearing effect of each entry only (P3 package 3J): a
            # later effect's scalar would merge into the same (atom_id,
            # behavior) row by first-wins values + evidence union, making
            # one scalar claim durations from effects whose values were
            # dropped (the K'Sante R/Q over-claim).  Every control duration
            # is still preserved by the per-effect sequence rows.
            control_scalar_emitted = False
            for effect_index, effect in enumerate(entry.get("effects") or []):
                if not isinstance(effect, dict):
                    continue
                prose_duration = (
                    extract_description_duration(entry, effect_index)
                    if effect_index == 0
                    else None
                )
                # P1 Slice 11: the effect-0-only scan mislabels multi-effect
                # entries whose effects[0] is a PASSIVE (Ashe Q: the 4s Focus
                # stack window was claimed as the Q's active duration).  The
                # explicit map relabels Ashe Q's effects[0] to the Focus
                # window atom AND extracts the real 6s active duration from
                # effects[1].  An explicit map (NOT a keyword rule — 61
                # genuine actives mention stacks) keeps every other
                # champion's atoms byte-identical.
                focus_window_effect = (
                    champion_name,
                    slot,
                    entry_index,
                ) in _FOCUS_WINDOW_EFFECTS and effect_index == 0
                if prose_duration is not None and focus_window_effect:
                    a.add(
                        "timing.stack_duration",
                        "timing",
                        f"{champion_name}.{slot}[{entry_index}].effects[{effect_index}]"
                        ".description",
                        ability_name,
                        [prose_duration],
                        ["s"],
                        [f"stack duration@effects[{effect_index}].description"],
                    )
                elif prose_duration is not None:
                    a.add(
                        "timing.active_duration",
                        "timing",
                        f"{champion_name}.{slot}[{entry_index}].effects[{effect_index}]"
                        ".description",
                        ability_name,
                        [prose_duration],
                        ["s"],
                        [f"active duration@effects[{effect_index}].description"],
                    )
                if (
                    champion_name in _FOCUS_WINDOW_ACTIVE_EFFECTS
                    and slot in _FOCUS_WINDOW_ACTIVE_EFFECTS[champion_name]
                    and effect_index
                    == _FOCUS_WINDOW_ACTIVE_EFFECTS[champion_name][slot]
                ):
                    active_duration = extract_description_duration(entry, effect_index)
                    if active_duration is not None:
                        a.add(
                            "timing.active_duration",
                            "timing",
                            f"{champion_name}.{slot}[{entry_index}].effects"
                            f"[{effect_index}].description",
                            ability_name,
                            [active_duration],
                            ["s"],
                            [f"active duration@effects[{effect_index}].description"],
                        )
                shield_duration = extract_description_shield_duration(
                    entry, effect_index
                )
                if shield_duration is not None:
                    a.add(
                        "timing.shield_duration",
                        "timing",
                        f"{champion_name}.{slot}[{entry_index}].effects[{effect_index}]"
                        ".description",
                        ability_name,
                        [shield_duration],
                        ["s"],
                        [f"shield duration@effects[{effect_index}].description"],
                    )
                control_durations = extract_description_control_durations(
                    entry, effect_index
                )
                control_duration = control_durations[0] if control_durations else None
                if control_duration is not None and not control_scalar_emitted:
                    control_scalar_emitted = True
                    a.add(
                        "timing.control_duration",
                        "timing",
                        f"{champion_name}.{slot}[{entry_index}].effects[{effect_index}]"
                        ".description",
                        ability_name,
                        [control_duration],
                        ["s"],
                        [f"control duration@effects[{effect_index}].description"],
                    )
                if len(control_durations) > 1:
                    a.add(
                        "timing.control_duration_sequence",
                        "timing",
                        f"{champion_name}.{slot}[{entry_index}].effects[{effect_index}]"
                        ".description",
                        ability_name,
                        control_durations,
                        ["s"] * len(control_durations),
                        [
                            f"control duration sequence@effects[{effect_index}]"
                            ".description"
                        ],
                    )
                damage_reduction = extract_description_damage_reduction(
                    entry, effect_index
                )
                if damage_reduction is not None:
                    a.add(
                        "ability.damage_reduction",
                        "ability",
                        f"{champion_name}.{slot}[{entry_index}].effects[{effect_index}]"
                        ".description",
                        ability_name,
                        [damage_reduction],
                        ["%"],
                        [f"damage reduction@effects[{effect_index}].description"],
                    )
                damage_reduction_cap = extract_description_damage_reduction_cap(
                    entry, effect_index
                )
                if damage_reduction_cap is not None:
                    a.add(
                        "ability.damage_reduction_cap",
                        "ability",
                        f"{champion_name}.{slot}[{entry_index}].effects[{effect_index}]"
                        ".description",
                        ability_name,
                        [damage_reduction_cap],
                        ["%"],
                        [f"damage reduction cap@effects[{effect_index}].description"],
                    )
                invulnerability_delay, invulnerability_duration = (
                    extract_description_invulnerability_timing(entry, effect_index)
                )
                source = (
                    f"{champion_name}.{slot}[{entry_index}].effects[{effect_index}]"
                    ".description"
                )
                if invulnerability_delay is not None:
                    a.add(
                        "timing.invulnerability_delay",
                        "timing",
                        source,
                        ability_name,
                        [invulnerability_delay],
                        ["s"],
                        [f"invulnerability delay@effects[{effect_index}].description"],
                    )
                if invulnerability_duration is not None:
                    a.add(
                        "timing.invulnerability_duration",
                        "timing",
                        source,
                        ability_name,
                        [invulnerability_duration],
                        ["s"],
                        [
                            f"invulnerability duration@effects[{effect_index}].description"
                        ],
                    )
                for leveling_index, leveling in enumerate(effect.get("leveling") or []):
                    if not isinstance(leveling, dict):
                        continue
                    attribute = str(leveling.get("attribute") or "Unnamed")
                    for mod_index, modifier in enumerate(
                        leveling.get("modifiers") or []
                    ):
                        values = [
                            float(v)
                            for v in modifier.get("values", [])
                            if isinstance(v, (int, float))
                        ]
                        units = [str(u) for u in modifier.get("units", [])]
                        if not values:
                            continue
                        atom_id = f"ability.{_snake(attribute)}"
                        # A leveling row can contain separate numeric pieces
                        # of one formula, such as a flat base and a bonus-AD
                        # ratio. Keep those pieces as separate typed atoms so
                        # a runtime accessor cannot read the first modifier
                        # and silently lose the rest.
                        if len(leveling.get("modifiers") or []) > 1:
                            atom_id = f"{atom_id}.modifier_{mod_index}"
                        a.add(
                            atom_id,
                            "ability",
                            f"{champion_name}.{slot}[{entry_index}].effects[{effect_index}]"
                            f".leveling[{leveling_index}].modifiers[{mod_index}]",
                            ability_name,
                            values,
                            units,
                            [f"{attribute}@effects[{effect_index}]"],
                        )
        out[slot] = a.emit()
    return out


def atomize_rune_catalogue(runes: Any) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    if isinstance(runes, dict):
        runes = list(runes.values())
    for rune in runes or []:
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

        def visit(value: Any, path: str) -> None:
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
                values,
                [unit_for(path)] * len(values),
                [f"{path}={value}"],
            )

        for key, value in rune.items():
            if key in {"name", "path", "icon", "implemented", "description"}:
                continue
            visit(value, key)
        out[name] = a.emit()
    return out


def atomize_economics(economics: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
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
                [float(row["total"])],
                ["gold"],
                ["per_item_sell.total"],
            )
        if isinstance(row.get("ddragon_sell"), (int, float)):
            a.add(
                "economy.sell",
                "economy",
                f"{name}.sell",
                name,
                [float(row["ddragon_sell"])],
                ["gold"],
                ["per_item_sell.ddragon_sell"],
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
                [float(row["derived_combine"])],
                ["gold"],
                ["combine_costs.derived_combine"],
            )
        out.setdefault(name, []).extend(a.emit())
    return out


def atomize_stats(champion: dict[str, Any]) -> list[dict[str, Any]]:
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
                    [float(value)],
                    [_stat_unit(field)],
                    [f"stats.{stat_name}.{field}"],
                )
    return a.emit()


def _stat_unit(field: str) -> str:
    """Map the cached stat field to the unit used by the atom contract."""
    return {
        "flat": "flat",
        "perLevel": "per_level",
        "percent": "percent",
        "percentPerLevel": "percent_per_level",
    }.get(field, "flat")


def _snake(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()
