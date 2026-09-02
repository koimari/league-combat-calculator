"""Data-ownership registry: who may write under data/, and the only
runtime-cache write API.

The three tracked runtime caches (champions.json, items.json,
runes.json) have a single writer, data_updater, and reach disk only
through write_runtime_cache().  tests/test_data_writer_inventory.py
enforces that boundary with an AST scan, and holds every writer under
data/ to a repo-anchored path so an import from a foreign cwd cannot
write somewhere else.

data_version() is the other half of that ownership statement, read from
the consumer's side: one monotonic counter naming *which* runtime cache a
derived value was computed from, so a memo can tell "still current" from
"computed before the last refresh".
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import MutableMapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .data_fetcher import _item_name_index, _read_json_version
from .patch_identity import PatchIdentityError, canonical_patch

CACHE_FILES = frozenset({"champions.json", "items.json", "runes.json"})

# How many times this process has replaced a runtime cache.  Starts at zero
# and only ever grows, so "same version" is a sound reason to reuse a value
# derived from data/ and a bump is the one signal that invalidates every
# such memo at once.
_DATA_VERSION = 0


def data_version() -> int:
    """The current runtime-cache generation, monotonic and process-local."""
    return _DATA_VERSION


def store_for_generation(
    memo: MutableMapping[tuple[int, Any], Any],
    key: tuple[int, Any],
    value: Any,
) -> None:
    """Write one memo entry, dropping any superseded generation first.

    A generation-prefixed key makes a stale entry unreachable but not freed.
    Eviction sits on the write path because a read has already matched the
    live generation, and these are the optimizer's inner loops."""
    for existing in memo:
        if existing[0] != key[0]:
            memo.clear()
        break
    memo[key] = value


class Invalidator(Enum):
    """What can make a cached answer wrong: the tree's one vocabulary.

    Two registries answer "what stales this cache": the memo tables below,
    and ``program/caches.CACHES``.  The enum lives here, in the module that
    owns ``data_version`` and imports nothing, and ``program/caches``
    imports it: one vocabulary, two populations, and a gate that can read
    both.

    ``DATA_VERSION`` is the member most caches carry and the one
    ``program/caches`` requires of every declaration it holds, because a
    derived number that survives a patch refresh is the stale literal
    CLAUDE.md rule 5 bans, one layer up.  The last three members exist so a
    cache the counter *cannot* govern says so in the same language rather
    than by being filed somewhere else.
    """

    DATA_VERSION = "data_version"
    ROSTER = "roster"
    ACTOR_STATS = "actor_stats"
    PARAMS = "params"
    PROJECTION = "projection"
    HAND_AUTHORED_ARTIFACT = "hand_authored_artifact"
    """A ``data/`` file no script writes, so the runtime-cache counter can
    never move for it."""

    REFRESH_CLEAR = "refresh_clear"
    """Emptied wholesale by the function that rebuilds what it derives from,
    so the counter has nothing to add."""

    IMPORTED_MODULE = "imported_module"
    """A Python module object, which cannot change inside a process — so no
    `data/` refresh can stale it and the counter would be noise in its key.
    Distinct from :attr:`HAND_AUTHORED_ARTIFACT`, which is a `data/` file
    nothing writes: this is not a `data/` file at all."""

    OBJECT_IDENTITY = "object_identity"
    """An address is part of what selects the entry — the honest spelling of
    a memo the counter alone does not determine.  Declared *alongside*
    ``DATA_VERSION`` where a memo carries both (``_CAST_ORDER_PARAMS_MEMO``
    keys on ``(data_version(), id(params), order)``), and alone where the
    address is the whole key.  Every member alone is a row on the deferred
    table with an issue reference; every member paired with ``DATA_VERSION``
    is outside migration frontier counter 7's scanned trees and names its
    owning lane.  Either way this reads as the gap it is rather than as a
    design, which is the reason not to let the counter member stand for the
    whole key."""


@dataclass(frozen=True, slots=True)
class MemoGovernance:
    """One memo's ``invalidated_by``, and why that is the right set.

    The reason is not decoration: the four tables below are four different
    *claims* — "keys on the counter", "another lane keys it", "the counter
    cannot govern it", "it should be keyed and is not this phase's to edit"
    — and a set of invalidators alone cannot tell the third from the fourth.
    """

    invalidated_by: frozenset[Invalidator]
    why: str

    def __post_init__(self) -> None:
        """A declaration with no invalidator and no reason is not one."""
        if not self.invalidated_by:
            raise ValueError(
                "a memo governance declaring no invalidator says nothing; use "
                "Invalidator.OBJECT_IDENTITY if the honest answer is 'nothing "
                "stales it', which is a gap and reads like one"
            )
        if not self.why.strip():
            raise ValueError("a memo governance with no reason is undeclared")


def _governed(*invalidators: Invalidator):
    """A governance builder, so a table row reads as name -> reason."""

    def declare(why: str) -> MemoGovernance:
        return MemoGovernance(invalidated_by=frozenset(invalidators), why=why)

    return declare


_version_keyed = _governed(Invalidator.DATA_VERSION)

# The generation *and* an address, which is three memos: they key on
# ``(data_version(), id(x), ...)`` behind a strong-reference guard.  Spelled
# as its own builder so the pairing is a declaration a reader can grep for
# rather than a detail inside a reason string — a memo whose key is half an
# address and which declares only the counter reads as value-keyed, and
# migration frontier counter 7 does not scan any of the three.
_keyed_on_an_address_too = _governed(
    Invalidator.DATA_VERSION, Invalidator.OBJECT_IDENTITY
)


# ── who keys on the counter ──────────────────────────────────────────────
#
# The population is machine-derived, not judged, and it is derived two ways
# because either one alone has a blind spot.  A memo is *either* a
# module-level mapping under src/calculator/ whose name ends in ``_MEMO`` or
# ``_CACHE``, *or* a module-level empty dict that some function in its module
# fills, clears or pops — which is what a lazily filled cache looks like
# whatever it is called.  tests/test_data_version_memos.py scans for both and
# asserts the five tables below partition the union exactly, so a new one
# cannot join the codebase without landing in one of them, which is the whole
# point of a counter over a convention (D-49).
#
# The second detector is S10's repair: until it existed the population was
# the name rule alone, and ``item_effects._RESOLVED_DAMAGE_EFFECTS`` — a memo
# this file already governed, in REFRESH_CLEARED_MEMOS — sat outside it
# because of how it is spelled.  "The population is closed" that is closed
# over a naming convention is a claim about the convention.
#
# Splitting the population five ways rather than two is deliberate: "keys on
# it", "another lane keys it", "cannot be governed by it", "the refresh
# empties it" and "should be keyed and is not this phase's to edit" are five
# different claims, and collapsing the last two would hide a real gap behind
# a reasoned exemption.

DATA_VERSION_KEYED_MEMOS: dict[str, MemoGovernance] = {
    "calculator.item_behavior_catalog._BEHAVIOR_RULES_MEMO": _version_keyed(
        "one owner's compiled BehaviorRules; every number in them is read out "
        "of a registry the cache generation counts, and the entry objects are "
        "held beside the key so a refresh that rebuilds them without writing "
        "a file misses too"
    ),
    "calculator.economy._ITEM_BY_ID_MEMO": _version_keyed(
        "the id-keyed view of the item cache the optimizer prices plans through"
    ),
    "calculator.interpreters.threshold_defense._THRESHOLD_HEALTH_OWNER_MEMO": _version_keyed(
        "which item declares the temporary-health Lifeline, derived from the "
        "catalog the cache generation counts; read inside two fight loops, so "
        "the derivation is memoized rather than re-scanned per candidate"
    ),
    "calculator.interpreters.threshold_defense._THRESHOLD_HEALTH_TICK_MEMO": _version_keyed(
        "the cadence that Lifeline's heal is delivered on, read off the same "
        "declaration and through the same registry the cache generation "
        "counts; asked once per armed Lifeline inside the ordered damage walk"
    ),
    "calculator.pipeline._CAST_ORDER_PARAMS_MEMO": _keyed_on_an_address_too(
        "derived cast-order params; the order was resolved from cached ability "
        "data — and the key is (data_version(), id(params), order) with a "
        "strong-reference guard, so the address is half of it. Declared rather "
        "than implied: pipeline.py is outside migration frontier counter 7's "
        "scanned trees ({survival,program} and stats.py) and outside this "
        "lane's edit scope, so counter 7 reading 0 says nothing about it"
    ),
    "calculator.ability_atoms._ABILITY_ATOMS_MEMO": _version_keyed(
        "one cached champion's atomized ability rows, keyed "
        "(data_version(), champion_name); the fight path builds a fresh "
        "champion mapping per request, so an identity key would re-atomize "
        "every champion per request and retain the rows forever"
    ),
    "calculator.stats._ITEM_STATS_MEMO": _version_keyed(
        "one cached item's extracted stat block"
    ),
    "calculator.stats._ITEM_STATS_VALIDATION_MEMO": _version_keyed(
        "the schema verdict on one cached item's stat map"
    ),
    "calculator.support_effects._SUPPORT_ATTRS_MEMO": _keyed_on_an_address_too(
        "whether a cached champion carries any support attribute; keyed "
        "(data_version(), id(champion_data)) with a strong-reference guard"
    ),
    "calculator.support_effects._SUPPORT_PROFILE_MEMO": _keyed_on_an_address_too(
        "one cached ability's shield/heal attribute names and target scope; "
        "keyed (data_version(), id(ability)) with a strong-reference guard"
    ),
    "calculator.survival.receipt_state._STATE_PROTO_MEMO": _version_keyed(
        "a participant's survival prototype, derived from cached item stats"
    ),
}

# Keyed by their own lane rather than here: Phase 5 owns the two rotation
# memos and keyed them with the cast-dependency work (D-49's split).
ROTATION_MEMOS: dict[str, MemoGovernance] = {
    "calculator.rotation_resolver._DERIVED_RULE_CACHE": _version_keyed(
        "a champion's derived rotation rule, keyed with the cast-dependency work"
    ),
    "calculator.rotation_resolver._MATRIX_DPS_CACHE": _version_keyed(
        "the per-signature DPS matrix behind that rule, keyed the same way"
    ),
}

# Not governable by this counter: the counter counts write_runtime_cache
# calls, and a memo over something write_runtime_cache never writes would
# key on a number that can never move for it.
UNGOVERNED_MEMOS: dict[str, MemoGovernance] = {
    "calculator.certainty._AUDIT_CACHE": _governed(Invalidator.HAND_AUTHORED_ARTIFACT)(
        "derived from data/wiki-full-entry-audit.json, a HAND_AUTHORED "
        "artifact rather than a runtime cache"
    ),
    "calculator.champions.__init__._MODULE_CONTRACTS": _governed(
        Invalidator.IMPORTED_MODULE
    )(
        "the validated contract of an imported champion module, re-verified "
        "against the registered module name on every hit; a module object "
        "cannot change inside a process, so no data/ refresh reaches it"
    ),
    "calculator.survival.actions._CLASS_SETS": _governed(Invalidator.IMPORTED_MODULE)(
        "an interning table, not a derivation: it maps a frozenset of enum "
        "members to itself so packets declaring the same classes share one "
        "object.  Both key and value are members of a module-level enum "
        "vocabulary, so nothing in data/ appears in it and a refresh cannot "
        "make an entry wrong.  Bounded by the vocabulary at 2**N entries"
    ),
}

# The same shape as the seven above, over champions.json instead of
# items.json, and keyed by the same argument — but the champion tree is
# ruled out of this phase's sweep (D-24: no champion sweep is implied), so
# these five are named here with their issue rather than silently left out
# of the population.  This is a gap on the record, not an exemption.
_CHAMPION_MEMO_DEFERRAL = (
    "champions/ is outside this phase's edit scope (D-24); identity-keyed "
    "with a strong reference and re-verified on every hit, so the residual "
    "hazard is an in-place mutation of a cached ability dict — issue #212"
)

# Emptied wholesale when the registry they derive from is rebuilt, so the
# counter has nothing to add.  Named here anyway, with the test that asserts
# the clear still happens: a memo whose safety is one line in somebody
# else's function is exactly the claim this campaign stopped taking on
# trust.  Their names do not match the ``_MEMO``/``_CACHE`` shape, which is
# why the scan grew its second detector rather than this table staying
# outside the partition.
REFRESH_CLEARED_MEMOS: dict[str, MemoGovernance] = {
    "calculator.item_effects._RESOLVED_DAMAGE_EFFECTS": _governed(
        Invalidator.REFRESH_CLEAR
    )(
        "refresh_item_effects() clears it in the same call that rebuilds "
        "ITEM_EFFECTS"
    ),
}

_deferred = _governed(Invalidator.OBJECT_IDENTITY)

DEFERRED_MEMOS: dict[str, MemoGovernance] = {
    "calculator.champions.engine._CAST_TIME_MEMO": _deferred(_CHAMPION_MEMO_DEFERRAL),
    "calculator.champions.engine._RESOURCE_COST_MEMO": _deferred(
        _CHAMPION_MEMO_DEFERRAL
    ),
    "calculator.champions.slotlib._MODIFIER_PAIRS_MEMO": _deferred(
        _CHAMPION_MEMO_DEFERRAL
    ),
    "calculator.champions.slotlib._NAMED_LEVELING_MEMO": _deferred(
        _CHAMPION_MEMO_DEFERRAL
    ),
    "calculator.champions.slotlib._PRIMARY_LEVELING_MEMO": _deferred(
        _CHAMPION_MEMO_DEFERRAL
    ),
}


#: Every memo this module governs, in one mapping — the half of "what stales
#: a cache" that lives here.  ``program/caches.every_declaration`` unions it
#: with the program layer's own declarations so the question has one answer
#: and not two.
GOVERNED_MEMOS: dict[str, MemoGovernance] = {
    **DATA_VERSION_KEYED_MEMOS,
    **ROTATION_MEMOS,
    **UNGOVERNED_MEMOS,
    **REFRESH_CLEARED_MEMOS,
    **DEFERRED_MEMOS,
}


def write_runtime_cache(
    data_directory: Path,
    filename: str,
    payload: dict[str, Any],
    *,
    source_url: str | None = None,
    source_version: str | None = None,
    source_hash: str | None = None,
    fetched_at: float | None = None,
) -> None:
    """Atomically write one tracked runtime-cache file with provenance meta.

    ``fetched_at`` defaults to now; an offline re-parse of a cache passes the
    stamp of the fetch it re-reads, so the published freshness stays the
    fetch's and not the re-parse's.

    Refuses filenames outside CACHE_FILES: the three tracked caches have a
    single writer, data_updater, and no other data/ path reaches disk
    through this API.
    """
    if filename not in CACHE_FILES:
        raise ValueError(
            f"{filename} is not a runtime-cache file; runtime cache is "
            f"limited to {sorted(CACHE_FILES)}"
        )
    data_directory.mkdir(parents=True, exist_ok=True)
    data_path = data_directory / filename
    tmp_path = data_directory / f".{filename}.tmp"
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.replace(data_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    # local: no import cycle

    # The file on disk has changed, so the parsed-JSON cache is stale and so
    # is everything derived from it.  Both are invalidated here, before the
    # provenance metadata is written: a reader that sees the new version has
    # a live parse behind it.  ``global`` is the honest spelling of a
    # module-level counter; hiding it in a container would not make the
    # state any less module-level.
    _read_json_version.cache_clear()
    _item_name_index.cache_clear()
    global _DATA_VERSION  # pylint: disable=global-statement
    _DATA_VERSION += 1

    metadata: dict[str, Any] = {
        "fetched_at": time.time() if fetched_at is None else fetched_at,
        "filename": filename,
        "source_url": source_url,
        "source_version": source_version,
        "source_hash": source_hash,
    }
    if source_version:
        try:
            identity = canonical_patch(source_version)
        except PatchIdentityError:
            # Keep the source receipt. A non-Riot source version must not be
            # relabelled as a guessed public patch.
            pass
        else:
            metadata["public_patch"] = identity.public_patch
            metadata["client_patch"] = identity.client_patch
            metadata["patch_namespace"] = {
                "public_patch": identity.public_patch,
                "client_patch": identity.client_patch,
                "source_version": source_version,
            }
    meta_path = data_directory / f".{filename}.meta"
    with meta_path.open("w", encoding="utf-8") as meta_file:
        json.dump(metadata, meta_file, indent=2)
