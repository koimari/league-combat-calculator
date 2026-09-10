"""How patch ingestion folds the Wiki item table and Riot's description into one cached entry."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

# Wiki effect keys are ``pass``/``pass2``/``aura``/``act``; lolstaticdata reads
# the same prefixes when it builds the cached passive and active lists.
_PASSIVE_KEY_MARKERS = ("pass", "aura")


_ACTIVE_KEY_PREFIX = "act"


def _resolve_inherited(
    wiki_table: Mapping[str, Any],
    item_name: str,
    field: str,
) -> Any:
    """Follow ``=>Parent`` redirects for one Wiki field."""
    seen: set[str] = set()
    name = item_name
    while name not in seen:
        seen.add(name)
        value = (wiki_table.get(name) or {}).get(field)
        if not (isinstance(value, str) and value.startswith("=>")):
            return value
        name = value[2:]
    return None


def _resolve_effect_entry(
    wiki_table: Mapping[str, Any],
    item_name: str,
    key: str,
    value: Any,
) -> Any:
    """Follow ``=>Parent`` redirects for one Wiki effect sub-entry."""
    seen: set[str] = set()
    name = item_name
    while isinstance(value, str) and value.startswith("=>") and name not in seen:
        seen.add(name)
        name = value[2:]
        value = (_resolve_inherited(wiki_table, name, "effects") or {}).get(key)
    return value


def _wiki_effect_kind(key: str) -> str | None:
    """Classify a Wiki effect key the way lolstaticdata's item parser does."""
    if any(marker in key for marker in _PASSIVE_KEY_MARKERS):
        return "passive"
    if key.startswith(_ACTIVE_KEY_PREFIX):
        return "active"
    return None


def _wiki_effects_by_kind(
    wiki_table: Mapping[str, Any],
    item_name: str,
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Group one Wiki item's effect entries by kind, naming what was dropped."""
    grouped: dict[str, list[dict[str, Any]]] = {"passive": [], "active": []}
    unclassified: list[str] = []
    effects = _resolve_inherited(wiki_table, item_name, "effects")
    if not isinstance(effects, Mapping):
        return grouped, unclassified
    for key, value in effects.items():
        resolved = _resolve_effect_entry(wiki_table, item_name, key, value)
        if not isinstance(resolved, Mapping):
            continue
        kind = _wiki_effect_kind(key)
        if kind is None:
            unclassified.append(key)
            continue
        grouped[kind].append(dict(resolved))
    return grouped, unclassified


def _branch_texts(wiki_entry: Mapping[str, Any]) -> list[str]:
    """Return ``description``, ``description2``, ... in source order."""
    keys = sorted(
        (key for key in wiki_entry if key.startswith("description")),
        key=lambda key: int(key[len("description") :] or 1),
    )
    return [str(wiki_entry[key]) for key in keys if wiki_entry[key]]


def _effect_name(entry: Mapping[str, Any]) -> str:
    """Return one effect entry's comparable name, blank when it has none."""
    return str(entry.get("name") or "").casefold()


def _align_effects(
    cached_entries: Sequence[Mapping[str, Any]],
    wiki_entries: Sequence[Mapping[str, Any]],
) -> tuple[list[int | None], list[int]]:
    """Pair each cached passive or active with the Wiki entry it came from.

    Source order is the common case — lolstaticdata builds the cached list by
    walking the same table — so a name-agreeing position wins first.  Name
    matching only rescues a reordered list, and each Wiki entry is consumed
    once so repeated names (Umbral Glaive splits one Blackout across two
    keys) stay distinct.

    Returns the Wiki index chosen for each cached entry, plus the Wiki
    indices nothing claimed.
    """
    unclaimed = list(range(len(wiki_entries)))
    chosen: list[int | None] = []
    for index, cached in enumerate(cached_entries):
        name = _effect_name(cached)
        if index in unclaimed and _effect_name(wiki_entries[index]) == name:
            match: int | None = index
        else:
            match = next(
                (
                    candidate
                    for candidate in unclaimed
                    if _effect_name(wiki_entries[candidate]) == name
                ),
                None,
            )
        if match is not None:
            unclaimed.remove(match)
        chosen.append(match)
    return chosen, unclaimed


def _champion_restriction(
    item: Mapping[str, Any],
    wiki_entry: Mapping[str, Any] | None,
) -> list[str]:
    """Union the Wiki's champion list with Riot's required champion or ally."""
    restriction: list[str] = []
    restriction.extend(
        str(champion) for champion in (wiki_entry or {}).get("champion") or ()
    )
    for key in ("requiredChampion", "requiredAlly"):
        value = str(item.get(key) or "")
        if value and value not in restriction:
            restriction.append(value)
    return restriction


def _merge_effect_branches(
    entry: Mapping[str, Any],
    grouped: Mapping[str, list[dict[str, Any]]],
    warnings: list[str],
) -> None:
    """Replace each cached passive/active text with its full branch list.

    A cached effect with no Wiki source keeps whatever text it already had —
    losing it silently is the failure this whole module exists to stop — and
    says so in *warnings*.
    """
    name = entry.get("name")
    for kind, cached_key in (("passive", "passives"), ("active", "active")):
        cached_entries = entry.get(cached_key) or []
        wiki_entries = grouped[kind]
        chosen, unclaimed = _align_effects(cached_entries, wiki_entries)
        for cached, match in zip(cached_entries, chosen, strict=False):
            texts = _branch_texts(wiki_entries[match]) if match is not None else []
            if not texts:
                previous = list(cached.get("branches") or ()) or [
                    str(cached.get("effects") or "")
                ]
                texts = [text for text in previous if text]
                warnings.append(
                    f"{name}: {kind} '{cached.get('name')}' has no Wiki source "
                    "branch; only its previously cached text is available"
                )
            cached.pop("effects", None)
            cached["branches"] = texts
        warnings.extend(
            f"{name}: Wiki {kind} '{wiki_entries[index].get('name')}' is "
            "absent from the cache"
            for index in unclaimed
        )


def _merge_one_item(
    item: Mapping[str, Any],
    wiki_table: Mapping[str, Any],
    wiki_name: str | None,
    riot_description: str,
) -> dict[str, Any]:
    """Record one item's source facts, naming whatever could not be matched."""
    entry = deepcopy(dict(item))
    warnings: list[str] = []
    name = str(entry.get("name") or "")
    grouped: dict[str, list[dict[str, Any]]] = {"passive": [], "active": []}

    if wiki_name is None:
        warnings.append(f"{name}: no Wiki item-table entry; sources unmerged")
    else:
        grouped, unclassified = _wiki_effects_by_kind(wiki_table, wiki_name)
        warnings.extend(
            f"{name}: Wiki effect '{dropped}' is not a passive or active "
            "and is not represented in the cache"
            for dropped in unclassified
        )

    wiki_stats = _resolve_inherited(wiki_table, wiki_name, "stats")
    entry["modes"] = dict(_resolve_inherited(wiki_table, wiki_name, "modes") or {})
    if wiki_name is not None and not entry["modes"]:
        warnings.append(f"{name}: Wiki item-table entry has no mode availability")
    entry["championRestriction"] = _champion_restriction(
        entry, wiki_table.get(wiki_name) or {}
    )
    entry["acquisitionNote"] = str(
        _resolve_inherited(wiki_table, wiki_name, "req") or ""
    )
    entry["specialStats"] = str(
        wiki_stats.get("spec") or "" if isinstance(wiki_stats, Mapping) else ""
    )
    entry["riotDescription"] = riot_description

    _merge_effect_branches(entry, grouped, warnings)
    entry["sourceWarnings"] = warnings
    return entry


def merge_item_sources(
    items: Mapping[str, Any],
    wiki_table: Mapping[str, Any],
    riot_descriptions: Mapping[int, str],
) -> dict[str, Any]:
    """Record every source fact the calculator needs on each cached item.

    Args:
        items: The generated item cache, keyed by item id.
        wiki_table: The decoded ``Module:ItemData/data`` table, keyed by name.
        riot_descriptions: CommunityDragon descriptions, keyed by item id.

    Returns:
        A new cache whose entries carry mode availability, champion
        restriction, acquisition note, special stat line, Riot description,
        and the complete branch list of every passive and active.  Anything
        that could not be matched is named in ``sourceWarnings`` rather than
        dropped.
    """
    wiki_by_id = {
        entry["id"]: name
        for name, entry in wiki_table.items()
        if isinstance(entry, Mapping) and "id" in entry
    }

    def wiki_name_for(item: Mapping[str, Any], key: str) -> str | None:
        name = str(item.get("name") or key)
        return wiki_by_id.get(item.get("id")) or (name if name in wiki_table else None)

    return {
        key: _merge_one_item(
            item,
            wiki_table,
            wiki_name_for(item, key),
            str(riot_descriptions.get(item.get("id"), "")),
        )
        for key, item in items.items()
    }
