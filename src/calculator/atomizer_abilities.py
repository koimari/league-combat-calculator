"""The ability domain: champion slot to effect to leveling modifier, plus a row's prose values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .ability_prose import (
    extract_description_control_durations,
    extract_description_damage_reduction,
    extract_description_damage_reduction_cap,
    extract_description_duration,
    extract_description_invulnerability_timing,
    extract_description_shield_duration,
)
from .atom_spelling import _snake
from .atomizer import Atomizer

# P1 Slice 11: Ashe Q — effects[0] is the Focus stack window (4s,
# mislabeled "active duration" before), effects[1] is the real 6s active
# window ("Active: For 6 seconds...").  An explicit map, NOT a keyword
# rule (61 genuine actives mention stacks) — every other champion's
# atoms stay byte-identical.
_FOCUS_WINDOW_EFFECTS = frozenset({("Ashe", "Q", 0)})


_FOCUS_WINDOW_ACTIVE_EFFECTS = {"Ashe": {"Q": 1}}


def atomize_abilities(
    champion_name: str,
    champion: Mapping[str, Any],
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
                            values=values,
                            units=["s"] * len(values),
                            evidence=[f"cooldown.modifiers[{mod_index}]"],
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
                        values=[prose_duration],
                        units=["s"],
                        evidence=[
                            f"stack duration@effects[{effect_index}].description"
                        ],
                    )
                elif prose_duration is not None:
                    a.add(
                        "timing.active_duration",
                        "timing",
                        f"{champion_name}.{slot}[{entry_index}].effects[{effect_index}]"
                        ".description",
                        ability_name,
                        values=[prose_duration],
                        units=["s"],
                        evidence=[
                            f"active duration@effects[{effect_index}].description"
                        ],
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
                            values=[active_duration],
                            units=["s"],
                            evidence=[
                                f"active duration@effects[{effect_index}].description"
                            ],
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
                        values=[shield_duration],
                        units=["s"],
                        evidence=[
                            f"shield duration@effects[{effect_index}].description"
                        ],
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
                        values=[control_duration],
                        units=["s"],
                        evidence=[
                            f"control duration@effects[{effect_index}].description"
                        ],
                    )
                if len(control_durations) > 1:
                    a.add(
                        "timing.control_duration_sequence",
                        "timing",
                        f"{champion_name}.{slot}[{entry_index}].effects[{effect_index}]"
                        ".description",
                        ability_name,
                        values=control_durations,
                        units=["s"] * len(control_durations),
                        evidence=[
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
                        values=[damage_reduction],
                        units=["%"],
                        evidence=[
                            f"damage reduction@effects[{effect_index}].description"
                        ],
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
                        values=[damage_reduction_cap],
                        units=["%"],
                        evidence=[
                            f"damage reduction cap@effects[{effect_index}].description"
                        ],
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
                        values=[invulnerability_delay],
                        units=["s"],
                        evidence=[
                            f"invulnerability delay@effects[{effect_index}].description"
                        ],
                    )
                if invulnerability_duration is not None:
                    a.add(
                        "timing.invulnerability_duration",
                        "timing",
                        source,
                        ability_name,
                        values=[invulnerability_duration],
                        units=["s"],
                        evidence=[
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
                            values=values,
                            units=units,
                            evidence=[f"{attribute}@effects[{effect_index}]"],
                        )
        out[slot] = a.emit()
    return out
