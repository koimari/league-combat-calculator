"""Strict access to typed ability atoms from the cached champion data."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .atomizer_domains import atomize_abilities
from .data_registry import data_version, store_for_generation

_ABILITY_ATOMS_MEMO: dict[tuple[int, str], dict[str, tuple[dict, ...]]] = {}


@dataclass(frozen=True)
class AbilityAtomQuery:
    """Exact source receipt used to select one typed ability atom."""

    source: str
    behavior: str
    evidence_prefix: str


def _ability_atoms(
    champion_name: str, champion_data: Mapping[str, Any]
) -> dict[str, tuple[dict, ...]]:
    """Return atomized ability rows for one cached champion's abilities.

    A refreshed champion cache cannot serve rows atomized from the old one:
    :func:`data_version` moves on every reload, so the reloaded data is a
    miss under a key the stale rows can never occupy — and
    :func:`store_for_generation` then drops them, because unreachable is not
    gone while each row set still pins the ability dicts it came from.
    """
    # The memo key is (data version, champion_name), the convention
    # ``survival.receipt_state`` keys its state prototypes on.  The name is
    # part of the key because the SAME cached object is atomized under the
    # data key ("KSante") by a typed lookup and under the display name
    # ("K'Sante") by the fight path — their source paths differ, so a
    # version-only key would return the wrong champion's rows (P3 package
    # 3J).  Keying on ``id(champion_data)`` instead cannot hit at all: the
    # fight path builds a fresh mapping per request, so every request
    # re-atomized every champion and left the rows in the memo forever.
    key = (data_version(), champion_name)
    memo = _ABILITY_ATOMS_MEMO.get(key)
    if memo is not None:
        return memo
    rows = {
        slot: tuple(atoms)
        for slot, atoms in atomize_abilities(champion_name, dict(champion_data)).items()
    }
    store_for_generation(_ABILITY_ATOMS_MEMO, key, rows)
    return rows


def _valid_atom_hash(atom: Mapping[str, Any]) -> bool:
    """Check the hash emitted by :class:`src.calculator.atomizer.Atom`."""
    record = {
        key: atom.get(key)
        for key in (
            "atom_id",
            "behavior",
            "source",
            "name",
            "values",
            "units",
            "evidence",
        )
    }
    expected = hashlib.sha256(
        json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    return str(atom.get("hash", "")) == expected


def required_ability_atom(
    champion_name: str,
    champion_data: Mapping[str, Any],
    slot: str,
    *,
    query: AbilityAtomQuery,
) -> dict[str, Any]:
    """Return one exact atom or raise with the source path.

    A missing row, stale hash, or malformed numeric payload is a data error.
    Callers must fail closed instead of supplying a local numeric fallback.
    """
    candidates = [
        atom
        for atom in _ability_atoms(champion_name, champion_data).get(slot, ())
        if atom.get("source") == query.source
        and atom.get("behavior") == query.behavior
        and any(
            str(receipt).startswith(query.evidence_prefix)
            for receipt in atom.get("evidence", ())
        )
    ]
    if len(candidates) != 1:
        raise KeyError(
            f"ability atom {champion_name}.{slot} {query.source!r} "
            f"{query.evidence_prefix!r} "
            f"resolved {len(candidates)} rows"
        )
    atom = candidates[0]
    values = atom.get("values")
    units = atom.get("units")
    if not isinstance(values, list) or not values:
        raise ValueError(f"ability atom {query.source!r} has no numeric values")
    if not isinstance(units, list) or len(units) != len(values):
        raise ValueError(
            f"ability atom {query.source!r} has mismatched values and units"
        )
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for value in values
    ):
        raise TypeError(f"ability atom {query.source!r} has a non-numeric value")
    if not atom.get("evidence") or not _valid_atom_hash(atom):
        raise ValueError(f"ability atom {query.source!r} has invalid provenance")
    return dict(atom)


def ranked_ability_atom_value(
    atom: Mapping[str, Any], rank: int, *, source: str
) -> float:
    """Read one 1-indexed rank from a validated ability atom."""
    if isinstance(rank, bool) or rank < 1:
        raise ValueError(f"ability atom {source!r} needs a positive rank")
    values = atom.get("values", ())
    if rank > len(values):
        raise ValueError(
            f"ability atom {source!r} has {len(values)} ranks, requested {rank}"
        )
    value = values[rank - 1]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"ability atom {source!r} rank {rank} is not numeric")
    return float(value)


def required_ranked_attribute_atom(
    champion_name: str,
    champion_data: Mapping[str, Any],
    slot: str,
    attribute: str,
    rank: int,
    *,
    entry_index: int = 0,
    occurrence: int = 0,
    modifier_index: int = 0,
) -> tuple[float, dict[str, Any]]:
    """Read one exact ranked attribute atom and return its receipt.

    The raw ability walk finds the exact effect, leveling row, and modifier.
    The atom catalog then validates the same source path, hash, values, and
    evidence before the caller receives a number.
    """
    entries = champion_data.get("abilities", {}).get(slot, [])
    if not isinstance(entries, list) or entry_index < 0 or entry_index >= len(entries):
        raise KeyError(f"ability atom {champion_name}.{slot}[{entry_index}] is missing")
    ability = entries[entry_index]
    if not isinstance(ability, Mapping):
        raise TypeError(
            f"ability atom {champion_name}.{slot}[{entry_index}] is not an object"
        )
    seen = 0
    for effect_index, effect in enumerate(ability.get("effects", [])):
        if not isinstance(effect, Mapping):
            continue
        for leveling_index, leveling in enumerate(effect.get("leveling", [])):
            if not isinstance(leveling, Mapping):
                continue
            if str(leveling.get("attribute", "")) != attribute:
                continue
            if seen != occurrence:
                seen += 1
                continue
            modifiers = leveling.get("modifiers", [])
            if (
                not isinstance(modifiers, list)
                or modifier_index < 0
                or modifier_index >= len(modifiers)
            ):
                raise KeyError(
                    f"ability atom {champion_name}.{slot}[{entry_index}]"
                    f" attribute {attribute!r} modifier {modifier_index} is missing"
                )
            source = (
                f"{champion_name}.{slot}[{entry_index}].effects[{effect_index}]"
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
            return ranked_ability_atom_value(atom, rank, source=source), atom
    raise KeyError(
        f"ability atom {champion_name}.{slot}[{entry_index}] attribute "
        f"{attribute!r} occurrence {occurrence} is missing"
    )


# ── The ability payload schema ────────────────────────────────────────────
#
# A champion module authors ``ability_damages[slot]`` and its sub-payloads
# from wiki atoms; the fight engine reads named fields off them.  This table
# is the one home for what an absent field means: REQUIRED says the payload
# is malformed without it, and anything else is the value an unauthored field
# prices at.  No engine call site restates a default (CLAUDE.md rule 5).
REQUIRED = object()

EMPTY_PAYLOAD: Mapping[str, Any] = MappingProxyType({})

ABILITY_PAYLOAD_SCHEMA: Mapping[str, Mapping[str, Any]] = MappingProxyType(
    {
        # ``ability_damages[slot]`` itself.
        "ability": MappingProxyType(
            {
                "auto_attack_override": EMPTY_PAYLOAD,
                "auto_stack_every": 1,
                "basic_attack_true_ratio": 0.0,
                "cast_instances": 1,
                "cast_time": 0.0,
                "control_events": (),
                "control_source_atoms": (),
                "cooldown": 0.0,
                "deathfire_category": "",
                "detail": "",
                "dot_duration": 0.0,
                "dot_stack_count": 0,
                "dot_tick_interval": 0.0,
                "event_phase": "effect",
                "execute_threshold_ratio": 0.0,
                "name": REQUIRED,
                "on_hit": EMPTY_PAYLOAD,
                "parts": (),
                "proc_count": 0,
                "rank": 0,
                "resource_cost": 0.0,
                "resource_maximum_bonus": 0.0,
                "resource_maximum_bonus_duration": 0.0,
                "resource_restore": 0.0,
                "resource_restore_per_proc": 0.0,
                "resource_type": "NONE",
                "short_fuse_cooldown": 0.0,
                "short_fuse_refund": 0.0,
                "spellblade_bonus_true_ratio": 0.0,
                "spellblade_true_ratio": 0.0,
            }
        ),
        "on_hit": MappingProxyType(
            {
                # Slots that feed this counter, ``{slot: stacks per landed
                # hit}``, for a counter only part of the kit generates (Xin
                # Zhao's W).  ``count_ability_hits`` is the kit-wide
                # alternative.
                "ability_stack_slots": None,
                # >0 — the row is affected by critical strike modifiers at
                # this effectiveness, the crit PROBABILITY scale
                # ``DamagePart.crit_effectiveness`` names on an ability part.
                "crit_effectiveness": 0.0,
                "damage_per_hit": 0.0,
                # Two engine paths read this key and disagreed on what an
                # unauthored one meant — physical on the current-health proc,
                # magic on the flat one — so no payload may leave it out.
                "damage_type": REQUIRED,
                "hits": 1,
                # ``None`` is "no cap"; a module caps by authoring a count.
                "max_procs": None,
                "min_damage": 0.0,
                # >0 — every application is amplified by this fraction of
                # the target's MISSING health (1.0 doubles at full missing
                # health), read against the live target per proc.
                "missing_health_amp": 0.0,
                "stacks_required": 0,
                "triggers": ("on_hit",),
            }
        ),
        "target_debuff": MappingProxyType(
            {
                "armor_reduction_flat": 0.0,
                "armor_reduction_percent": 0.0,
                "duration": 0.0,
                "mr_reduction_flat": 0.0,
                "mr_reduction_percent": 0.0,
                "stacks": 0,
                "threshold_hits": 0,
            }
        ),
        "post_hit_proc": MappingProxyType({"name": "Post-hit proc", "parts": ()}),
        "stacking_dot": MappingProxyType(
            {
                "applied_by_autos": True,
                "damage_type": "physical",
                "single_stack_bonus_ad_ratio": 0.0,
                "starting_stacks": 0,
                "tick_interval": 0.0,
            }
        ),
        "stack_triggered_buff": MappingProxyType({"name": REQUIRED}),
        "crit_modifier": MappingProxyType(
            {
                "crit_chance_multiplier": 1.0,
                "crit_damage_multiplier_factor": 1.0,
                "excess_crit_bonus_ad_per_percent": 0.0,
            }
        ),
        "auto_attack_override": MappingProxyType(
            {
                "ad_ratio": 1.0,
                "crit_as_bonus": False,
                "damage_ratio": 1.0,
                "damage_type": "physical",
                "on_hit_effectiveness": 1.0,
            }
        ),
        "conversion": MappingProxyType(
            {
                "bonus_raw": 0.0,
                "count": 0,
                "damage_type": "magic",
                "name": "Modified attacks",
            }
        ),
        "double_shot": MappingProxyType({"ad_ratio": 0.5, "name": "Double Shot"}),
        "empower": MappingProxyType({"attack_speed": 0.0, "hits": 1}),
        "empower_timing": MappingProxyType(
            {"attack_interval": 0.0, "first_attack_delay": 0.0}
        ),
        "proc_restore": MappingProxyType({"proc_count": 0}),
        "resource_declaration": MappingProxyType({"atoms": ()}),
        "stored_damage": MappingProxyType(
            {
                "duration": 0.0,
                "include_auto_attacks": False,
                "ratio": 0.0,
                "source_slots": (),
            }
        ),
        "temporary_buff": MappingProxyType(
            {"applied_to_triggering_event": False, "applies_before_event": False}
        ),
    }
)

_MISSING = object()


def ability_field(
    payload: Mapping[str, Any], key: str, *, form: str = "ability"
) -> Any:
    """One field of an authored ability payload, through its declared schema.

    The payload identifies itself by the ability ``name`` its module authored,
    which is what a reader needs to find the champion and slot at fault.
    """
    value = payload.get(key, _MISSING)
    # An authored ``None`` is the unauthored field: a module that writes one
    # has declared the absence, not a value the engine can price.
    if value is not _MISSING and value is not None:
        return value
    declared = ABILITY_PAYLOAD_SCHEMA.get(form, EMPTY_PAYLOAD).get(key, _MISSING)
    if declared is _MISSING:
        raise KeyError(f"ability payload form {form!r} declares no field {key!r}")
    if declared is REQUIRED:
        raise KeyError(
            f"ability payload {payload.get('name') or form!r} is missing "
            f"required field {key!r}"
        )
    return declared


def ability_payload(ability_damages: Mapping[str, Any], slot: str) -> Mapping[str, Any]:
    """One slot's authored payload, or the empty one when the kit has none."""
    payload = ability_damages.get(slot)
    return payload if isinstance(payload, Mapping) else EMPTY_PAYLOAD


def ability_sub_payload(
    payload: Mapping[str, Any], key: str, *, form: str = "ability"
) -> Mapping[str, Any]:
    """One named sub-payload, or the empty one when it is not authored."""
    nested = ability_field(payload, key, form=form)
    return nested if isinstance(nested, Mapping) else EMPTY_PAYLOAD


__all__ = [
    "ABILITY_PAYLOAD_SCHEMA",
    "AbilityAtomQuery",
    "EMPTY_PAYLOAD",
    "REQUIRED",
    "ability_field",
    "ability_payload",
    "ability_sub_payload",
    "ranked_ability_atom_value",
    "required_ranked_attribute_atom",
    "required_ability_atom",
]
