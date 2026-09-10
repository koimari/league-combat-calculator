"""The ranked atom and prose duration readers every champion to champion interaction prices from."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .ability_atoms import (
    AbilityAtomQuery,
    atom_receipt,
    ranked_ability_atom_value,
    required_ability_atom,
)
from .champions.skill_orders import get_ability_rank
from .delivery_facts import ChampionFacts, RequestFacts


def rank_for(champion: str, level: int, request: RequestFacts | None, slot: str) -> int:
    requested = getattr(request, "ability_ranks", None)
    if isinstance(requested, Mapping) and slot in requested:
        return int(requested[slot])
    return int(get_ability_rank(slot, level, champion))


def cached_ability(
    champion_data: Mapping[str, Any], slot: str
) -> Mapping[str, Any] | None:
    entries = champion_data.get("abilities", {}).get(slot, [])
    if not isinstance(entries, list) or not entries:
        return None
    ability = entries[0]
    return ability if isinstance(ability, Mapping) else None


def source_selection(options: Mapping[str, Any], key: str) -> tuple[str, ...]:
    selected = options.get(key, [])
    if not isinstance(selected, list):
        return ()
    return tuple(str(value).strip() for value in selected if str(value).strip())


def requested_window(
    options: Mapping[str, Any],
    start_key: str,
    duration_key: str,
    source_duration: float,
) -> tuple[float, float]:
    start = max(0.0, float(options.get(start_key, 0.0) or 0.0))
    requested = max(0.0, float(options.get(duration_key, 0.0) or 0.0))
    duration = source_duration if requested <= 0.0 else min(source_duration, requested)
    return start, duration


_PROSE_DURATION_QUERIES: dict[tuple[str, str], AbilityAtomQuery] = {
    ("Yasuo", "W"): AbilityAtomQuery(
        source="Yasuo.W[0].effects[0].description",
        behavior="timing",
        evidence_prefix="active duration@",
    ),
    ("Samira", "W"): AbilityAtomQuery(
        source="Samira.W[0].effects[0].description",
        behavior="timing",
        evidence_prefix="active duration@",
    ),
    ("Gwen", "W"): AbilityAtomQuery(
        source="Gwen.W[0].effects[0].description",
        behavior="timing",
        evidence_prefix="active duration@",
    ),
    ("Fiora", "W"): AbilityAtomQuery(
        source="Fiora.W[0].effects[0].description",
        behavior="timing",
        evidence_prefix="active duration@",
    ),
    ("Pantheon", "E"): AbilityAtomQuery(
        source="Pantheon.E[0].effects[0].description",
        behavior="timing",
        evidence_prefix="active duration@",
    ),
    ("Jax", "E"): AbilityAtomQuery(
        source="Jax.E[0].effects[0].description",
        behavior="timing",
        evidence_prefix="active duration@",
    ),
}


# The prose-duration windows: slot, then the ProjectileDefense fields, where a
# ``blocked_sources`` / ``blocked_event_ids`` entry names the option holding
# the selection.
PROSE_DURATION_WINDOWS: dict[str, tuple[str, dict[str, Any]]] = {
    "Yasuo": (
        "W",
        {
            "kind": "yasuo_wind_wall",
            "source": "Yasuo W · Wind Wall",
            "blocked_sources": "w_blocked_skillshots",
            "blocked_event_ids": "w_blocked_event_ids",
            "destroy_projectiles": True,
        },
    ),
    "Samira": (
        "W",
        {
            "kind": "samira_blade_whirl",
            "source": "Samira W · Blade Whirl",
            "blocked_sources": "w_blocked_skillshots",
            "destroy_projectiles": True,
        },
    ),
    "Gwen": (
        "W",
        {
            "kind": "gwen_hallowed_mist",
            "source": "Gwen W · Hallowed Mist",
            "blocked_sources": "w_blocked_skillshots",
            "destroy_projectiles": True,
        },
    ),
    "Fiora": (
        "W",
        {
            "kind": "fiora_riposte",
            "source": "Fiora W · Riposte",
            "blocked_sources": "w_blocked_sources",
            "full_block_all": True,
            "requires_skillshot": False,
        },
    ),
    "Pantheon": (
        "E",
        {
            "kind": "pantheon_aegis_assault",
            "source": "Pantheon E · Aegis Assault",
            "blocked_sources": "e_blocked_skillshots",
            "full_block_all": True,
        },
    ),
    "Jax": (
        "E",
        {
            "kind": "jax_counter_strike",
            "source": "Jax E · Counter Strike",
            "full_block_all": True,
            "blocks_basic_attacks": True,
            "area_damage_reduction": 0.25,
            "requires_skillshot": False,
        },
    ),
}


BRAUM_DURATION_QUERY = AbilityAtomQuery(
    source="Braum.E[0].effects[0].leveling[1].modifiers[0]",
    behavior="ability",
    evidence_prefix="Barrier Duration@",
)


BRAUM_REDUCTION_QUERY = AbilityAtomQuery(
    source="Braum.E[0].effects[0].leveling[0].modifiers[0]",
    behavior="ability",
    evidence_prefix="Damage reduction@",
)


AMUMU_REDUCTION_CAP_QUERY = AbilityAtomQuery(
    source="Amumu.E[0].effects[0].description",
    behavior="ability",
    evidence_prefix="damage reduction cap@",
)


def ranked_atom_value(
    atom: Mapping[str, Any], rank: int, *, source: str, unit: str
) -> float:
    """Read one ranked atom value and validate its source unit."""
    units = atom.get("units")
    if not isinstance(units, list) or rank < 1 or rank > len(units):
        raise ValueError(f"ability atom {source!r} has no unit for rank {rank}")
    if str(units[rank - 1]).strip().lower() != unit:
        raise ValueError(
            f"ability atom {source!r} must use {unit!r}, got {units[rank - 1]!r}"
        )
    return ranked_ability_atom_value(atom, rank, source=source)


def combatant_level(combatant: ChampionFacts) -> int:
    """Read a level from either a timeline combatant or resolved loadout."""
    level = getattr(combatant, "level", None)
    if level is None:
        level = getattr(getattr(combatant, "request", None), "level", 0)
    return int(level)


def prose_duration_atom(
    champion: str, champion_data: Mapping[str, Any], slot: str
) -> tuple[float, dict[str, Any]]:
    """Return one validated prose duration atom for a defense window."""
    query = _PROSE_DURATION_QUERIES[(champion, slot)]
    atom = required_ability_atom(champion, champion_data, slot, query=query)
    if atom.get("units") != ["s"]:
        raise ValueError(f"{champion} {slot} defense duration atom must use seconds")
    return ranked_ability_atom_value(atom, 1, source=query.source), atom_receipt(atom)
