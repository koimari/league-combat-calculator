"""Strict access to typed ability atoms from the cached champion data."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .atomizer_domains import atomize_abilities

_ABILITY_ATOMS_MEMO: dict[
    int, tuple[Mapping[str, Any], dict[str, tuple[dict, ...]]]
] = {}


@dataclass(frozen=True)
class AbilityAtomQuery:
    """Exact source receipt used to select one typed ability atom."""

    source: str
    behavior: str
    evidence_prefix: str


def _ability_atoms(
    champion_name: str, champion_data: Mapping[str, Any]
) -> dict[str, tuple[dict, ...]]:
    """Return atomized ability rows for one cached champion object.

    The cache keeps a strong reference to the source object. A refreshed
    champion cache therefore cannot reuse rows from an older object with the
    same Python identity.
    """
    # The memo key is (object identity, champion_name): the SAME cached
    # object can be atomized under the data key ("KSante") by a typed
    # lookup and under the display name ("K'Sante") by the fight path —
    # their source paths differ, so an id-only key would return the wrong
    # champion's rows (P3 package 3J).
    key = (id(champion_data), champion_name)
    memo = _ABILITY_ATOMS_MEMO.get(key)
    if memo is not None and memo[0] is champion_data:
        return memo[1]
    rows = {
        slot: tuple(atoms)
        for slot, atoms in atomize_abilities(champion_name, dict(champion_data)).items()
    }
    _ABILITY_ATOMS_MEMO[key] = (champion_data, rows)
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


__all__ = [
    "AbilityAtomQuery",
    "ranked_ability_atom_value",
    "required_ranked_attribute_atom",
    "required_ability_atom",
]
