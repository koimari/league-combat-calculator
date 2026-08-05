"""The ingested-source view of a cached item.

Patch ingestion records what the League Wiki item table and Riot's
CommunityDragon description say about every item.  This module owns that
cache schema and the three questions the calculator asks of it:

* **What effect branches does the item have?**  The Wiki stores a passive or
  active as ``description``, ``description2``, ... — separate branches of one
  effect.  Only the first ever reached the cache, which is how Cull lost its
  completion payout and Muramana lost its whole ability-triggered Shock
  branch.  :func:`merge_item_sources` stores every branch; :func:`effect_text`
  is what parsers read.
* **Is it an ordinary Summoner's Rift purchase?**  Decided from the cached
  ``modes`` table, champion restriction, and acquisition note — never from a
  hand-maintained name list.  An item whose sources are missing is withheld,
  not assumed available.
* **Is every source-declared effect accounted for?**  :func:`source_audit`
  compares Riot's declared passives and actives against the Wiki branches we
  cached.  A divergence is either explained
  (:data:`ACKNOWLEDGED_SOURCE_CONFLICTS`), a known-open review item
  (:data:`OPEN_SOURCE_CONFLICTS`), or it fails the gate.  Neither source is
  silently preferred: an unsettled effect is withheld, not guessed at.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

# The Wiki item table's key for ordinary 5v5 Summoner's Rift availability.
SR_MODE_KEY = "classic sr 5v5"

# Wiki effect keys are ``pass``/``pass2``/``aura``/``act``; lolstaticdata reads
# the same prefixes when it builds the cached passive and active lists.
_PASSIVE_KEY_MARKERS = ("pass", "aura")
_ACTIVE_KEY_PREFIX = "act"

_BRANCH_SEPARATOR = "\n"

# Riot's rich description marks each effect with a ``<passive>``/``<active>``
# tag.  Names arrive decorated: ``Reap``, ``Undaunted:``, ``Soul Anchor's``,
# ``UNIQUE Active - Hunter's Sight:``.
_RIOT_EFFECT_TAG = re.compile(
    r"<(passive|active)>(.*?)</\1>", re.IGNORECASE | re.DOTALL
)
_RIOT_INNER_TAG = re.compile(r"<[^>]+>")
_RIOT_LABEL_PREFIX = re.compile(
    r"^(?:unique\s+)?(?:active|passive|consume)\s*-\s*", re.IGNORECASE
)
_RIOT_POSSESSIVE = re.compile(r"['’]s$")
# Bare tag labels that head an effect block without naming it.
_RIOT_BARE_LABELS = frozenset({"active", "passive", "consume", "unique"})


# Effect branches Riot really did remove, keyed by the ``item / kind name``
# label :func:`branch_inventory` builds.  Patch day stops on any other branch
# that disappears, because a vanishing branch is far more often an ingestion
# break than a deleted mechanic.  Each entry names the patch and how the
# removal was confirmed.
APPROVED_BRANCH_REMOVALS: dict[str, str] = {}


# Divergences between Riot's description and the Wiki item table that have
# been chased down and explained.  They stay listed so patch day re-reads them
# instead of rediscovering them, and the tests fail when one stops being true.
ACKNOWLEDGED_SOURCE_CONFLICTS: dict[str, dict[str, str]] = {
    "Arcane Sweeper (Trinket)": {
        "Hunter's Sight": (
            "The Wiki records this active without a name, so its branch cannot "
            "be matched to Riot's. Both describe the same 5-second sweeper "
            "mist; the trinket never enters a loadout."
        ),
    },
    "Crimson Lucidity": {
        "Ionian Insight": (
            "Naming divergence only: Riot calls the summoner-haste passive "
            "Ionian Insight, the Wiki calls it Ionian Lucidity. Both give 20 "
            "summoner spell haste."
        ),
    },
    "Echoes of Helia": {
        "Soul Charges": (
            "Display-markup artifact: Riot reuses the passive tag as an inline "
            "keyword for Soul Siphon's charge counter. The Wiki has the whole "
            "effect under Soul Siphon."
        ),
    },
    "Guardian's Horn": {
        "Recovery": (
            "The Wiki records Recovery as the flat health-regeneration stat "
            "(20 per 5 seconds) rather than a passive branch. Both sources "
            "agree on the value."
        ),
    },
    "Shattered Armguard": {
        "Shattered Time": (
            "Shop metadata, not a combat effect: Riot's text explains that a "
            "broken Armguard can still be upgraded. The Wiki records no "
            "effect because there is none to model."
        ),
    },
    "Wooglet's Witchcap": {
        "Time Stop": (
            "Naming divergence only: Riot calls the active Time Stop, the "
            "Wiki calls it Stasis. Both are the same 2.5-second stasis."
        ),
    },
    "Gunmetal Greaves": {
        "Noxian Gait": (
            "The Riot-only branch is retained as an explicit source conflict: "
            "its movement-speed magnitude is absent from the current Wiki entry "
            "and the supported fight model has no sourced movement/spacing input "
            "that could price the on-hit utility. The boot remains fail-closed in "
            "attacker coverage rather than silently dropping the branch."
        ),
    },
    "Radiant Virtue": {
        "Judgement": (
            "Radiant Virtue is a DISTRIBUTED Arena record, not an ordinary "
            "Summoner's Rift purchase. Riot's 30 ultimate-haste label is retained "
            "as an out-of-scope source note; it cannot enter the supported SR "
            "loadout or objective paths."
        ),
    },
}


# There are no unresolved source conflicts in the current patch inventory.
# Conflicts whose scope is understood remain in
# ``ACKNOWLEDGED_SOURCE_CONFLICTS`` so the full-entry and patch gates keep the
# discrepancy visible without presenting an unreviewed effect as modeled.
OPEN_SOURCE_CONFLICTS: dict[str, dict[str, str]] = {}


# ---------------------------------------------------------------------------
# Effect-branch schema
# ---------------------------------------------------------------------------


def branches(entry: Mapping[str, Any]) -> tuple[str, ...]:
    """Return every stored branch of one passive or active."""
    return tuple(str(branch) for branch in entry.get("branches") or ())


def effect_text(entry: Mapping[str, Any]) -> str:
    """Return one passive's or active's complete text, all branches included."""
    return _BRANCH_SEPARATOR.join(branches(entry))


def effect_entries(
    item: Mapping[str, Any],
) -> tuple[tuple[str, Mapping[str, Any]], ...]:
    """Pair each of an item's passives and actives with its kind."""
    passives = tuple(("passive", entry) for entry in item.get("passives") or ())
    actives = tuple(("active", entry) for entry in item.get("active") or ())
    return passives + actives


# ---------------------------------------------------------------------------
# Ingestion: merging the source tables into the cache
# ---------------------------------------------------------------------------


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
    for champion in (wiki_entry or {}).get("champion") or ():
        restriction.append(str(champion))
    for key in ("requiredChampion", "requiredAlly"):
        value = str(item.get(key) or "")
        if value and value not in restriction:
            restriction.append(value)
    return restriction


def _merge_effect_branches(
    entry: dict[str, Any],
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
        for cached, match in zip(cached_entries, chosen):
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
        for index in unclaimed:
            warnings.append(
                f"{name}: Wiki {kind} '{wiki_entries[index].get('name')}' is "
                "absent from the cache"
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
        for dropped in unclassified:
            warnings.append(
                f"{name}: Wiki effect '{dropped}' is not a passive or active "
                "and is not represented in the cache"
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


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Availability:
    """Why an item is, or is not, an ordinary Summoner's Rift purchase."""

    on_summoners_rift: bool
    acquisition: str
    selectable: bool
    reason: str


def sr_availability(item: Mapping[str, Any]) -> Availability:
    """Classify one cached item for the ordinary Summoner's Rift shop."""
    name = str(item.get("name") or "unknown item")
    modes = item.get("modes") or {}
    if not modes:
        return Availability(
            on_summoners_rift=False,
            acquisition="unknown_source",
            selectable=False,
            reason=(
                f"{name} has no cached mode availability, so it is withheld "
                "until ingestion records one."
            ),
        )

    on_rift = bool(modes.get(SR_MODE_KEY, False))
    restriction = [str(champion) for champion in item.get("championRestriction") or ()]
    shop = item.get("shop") or {}
    purchasable = bool(shop.get("purchasable", False))
    price = (shop.get("prices") or {}).get("total")
    ranks = {str(rank).upper() for rank in item.get("rank") or ()}
    acquisition_note = str(item.get("acquisitionNote") or "")

    if restriction:
        acquisition = "champion_granted"
        acquisition_reason = (
            f"{name} is granted to {', '.join(restriction)} rather than bought."
        )
    elif ranks & {"TURRET", "TRINKET", "DISTRIBUTED"}:
        # The cached rank is Riot's map/system classification.  These records
        # can advertise SR in the mode table while still being granted by the
        # map, a turret, or an event rather than appearing in a player shop.
        acquisition = "map_or_system"
        acquisition_reason = (
            f"{name} is a {', '.join(sorted(ranks & {'TURRET', 'TRINKET', 'DISTRIBUTED'}))} "
            "record, not a player shop purchase."
        )
    elif not purchasable and acquisition_note:
        acquisition = "quest_transform"
        acquisition_reason = (
            f"{name} is not sold; it transforms from another item on a quest."
        )
    elif not purchasable and price in (0, 0.0, None):
        acquisition = "map_or_system"
        acquisition_reason = (
            f"{name} has no shop price or purchase flag, so it is withheld "
            "as a map/system item until ingestion supplies an acquisition."
        )
    else:
        acquisition = "shop"
        acquisition_reason = f"{name} is an ordinary Summoner's Rift purchase."

    if not on_rift:
        reason = f"{name} is not available on Summoner's Rift."
    else:
        reason = acquisition_reason

    return Availability(
        on_summoners_rift=on_rift,
        acquisition=acquisition,
        selectable=on_rift and acquisition == "shop",
        reason=reason,
    )


def is_ordinary_sr_item(item: Mapping[str, Any]) -> bool:
    """Return whether an item belongs in ordinary Summoner's Rift builds."""
    return sr_availability(item).selectable


# ---------------------------------------------------------------------------
# Source audit
# ---------------------------------------------------------------------------


def _normalize_effect_name(raw: str) -> str:
    """Reduce a Riot effect label to its bare name."""
    name = _RIOT_INNER_TAG.sub("", raw).strip()
    name = _RIOT_LABEL_PREFIX.sub("", name).strip()
    name = name.rstrip(":").strip()
    return _RIOT_POSSESSIVE.sub("", name).strip()


def riot_declared_effects(item: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the passive and active names Riot's description declares."""
    declared: list[str] = []
    for _, raw in _RIOT_EFFECT_TAG.findall(str(item.get("riotDescription") or "")):
        name = _normalize_effect_name(raw)
        if not name or name.casefold() in _RIOT_BARE_LABELS:
            continue
        if name not in declared:
            declared.append(name)
    return tuple(declared)


def _comparable(name: str) -> str:
    """Fold an effect name to letters and digits for cross-source matching."""
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def _conflict_status(item_name: str, effect: str) -> tuple[str, str]:
    """Classify one Riot/Wiki divergence: ``explained``, ``open``, or new."""
    for status, table in (
        ("explained", ACKNOWLEDGED_SOURCE_CONFLICTS),
        ("open", OPEN_SOURCE_CONFLICTS),
    ):
        note = table.get(item_name, {}).get(effect)
        if note is not None:
            return status, note
    return (
        "unreviewed",
        "Riot declares this effect and the Wiki item table does not; review "
        "which source is stale before trusting either.",
    )


def item_source_audit(item: Mapping[str, Any]) -> dict[str, Any]:
    """Account for every effect Riot declares on one cached item."""
    name = str(item.get("name") or "")
    cached_names = {
        _comparable(str(entry.get("name") or "")) for _, entry in effect_entries(item)
    }

    parsed: list[str] = []
    conflicts: list[dict[str, Any]] = []
    for declared in riot_declared_effects(item):
        if _comparable(declared) in cached_names:
            parsed.append(declared)
            continue
        status, note = _conflict_status(name, declared)
        conflicts.append(
            {
                "item": name,
                "effect": declared,
                "status": status,
                "acknowledged": status != "unreviewed",
                "note": note,
            }
        )

    return {
        "item": name,
        "parsed": parsed,
        "conflicts": conflicts,
        "warnings": list(item.get("sourceWarnings") or ()),
    }


def source_audit(items: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarise source completeness across the whole cache."""
    audits = [item_source_audit(item) for item in items]
    conflicts = [conflict for audit in audits for conflict in audit["conflicts"]]
    unreviewed = [conflict for conflict in conflicts if not conflict["acknowledged"]]
    return {
        "items": audits,
        "conflicts": conflicts,
        "unreviewed_conflicts": unreviewed,
        "open_conflicts": [c for c in conflicts if c["status"] == "open"],
        "warnings": [warning for audit in audits for warning in audit["warnings"]],
        "complete": not unreviewed,
    }


def branch_inventory(items: Mapping[str, Any]) -> dict[str, dict[str, list[str]]]:
    """Map item name to each effect's branch texts, for cross-patch comparison."""
    return {
        str(item.get("name") or ""): {
            f"{kind} {entry.get('name') or '(unnamed)'}": list(branches(entry))
            for kind, entry in effect_entries(item)
        }
        for item in items.values()
    }


def branch_losses(
    previous_items: Mapping[str, Any],
    current_items: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Effect branches the new cache no longer carries.

    A branch vanishing usually means ingestion broke, not that Riot deleted a
    mechanic, so patch day stops on it.  Once the loss is verified against the
    sources it is recorded in :data:`APPROVED_BRANCH_REMOVALS` and stops
    failing.  Items that left the shop entirely are the shop delta's business,
    not this check's.
    """
    before = branch_inventory(previous_items)
    after = branch_inventory(current_items)

    losses: list[dict[str, Any]] = []
    for item_name, effects in before.items():
        if item_name not in after:
            continue
        for effect, texts in effects.items():
            kept = after[item_name].get(effect)
            if kept is None:
                detail = "the whole effect is gone from the cache"
            elif len(kept) < len(texts):
                detail = f"{len(texts)} branches became {len(kept)}"
            else:
                continue
            label = f"{item_name} / {effect}"
            losses.append(
                {
                    "effect": label,
                    "detail": detail,
                    "approved": label in APPROVED_BRANCH_REMOVALS,
                    "explanation": APPROVED_BRANCH_REMOVALS.get(label, ""),
                }
            )
    return losses


__all__ = [
    "ACKNOWLEDGED_SOURCE_CONFLICTS",
    "APPROVED_BRANCH_REMOVALS",
    "OPEN_SOURCE_CONFLICTS",
    "Availability",
    "SR_MODE_KEY",
    "branch_inventory",
    "branch_losses",
    "branches",
    "effect_entries",
    "effect_text",
    "is_ordinary_sr_item",
    "item_source_audit",
    "merge_item_sources",
    "riot_declared_effects",
    "source_audit",
    "sr_availability",
]
