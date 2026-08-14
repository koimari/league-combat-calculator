"""Data-ownership registry: who may write under data/, and the only
runtime-cache write API.

Categories:
  RUNTIME_CACHE    — tracked inputs the calculator reads at runtime
                     (champions.json, items.json, runes.json).  Only
                     data_updater may write these, only via
                     write_runtime_cache().
  EXTERNAL_EVIDENCE— downloaded game/wiki files (gitignored or sample
                     tracked): gamefiles/, bin/, wiki/, wiki-raw/.
  DERIVED_ARTIFACT — regenerable outputs computed from cache/evidence:
                     economics-sourced.json, staleness.json, atoms/.
  HAND_AUTHORED    — worklists, audits, receipts: never written by scripts.

WRITERS maps every data/ subtree (or file) to the module(s) allowed to
write it.  tests/test_data_writer_inventory.py enforces the map with an
AST scan so a new downloader cannot silently join the boundary.

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

CACHE_FILES = frozenset({"champions.json", "items.json", "runes.json"})

WRITERS: dict[str, tuple[str, ...]] = {
    "champions.json|items.json|runes.json": ("src/calculator/data_updater.py",),
    "staleness.json": ("scripts/patch_regression.py",),
    "economics-sourced.json": ("scripts/refresh_economics_data.py",),
    "onhit-matrix.json": ("scripts/build_onhit_matrix.py",),
    "gamefiles": ("scripts/patch_regression.py",),
    "bin": ("scripts/decompose_binaries.py",),
    "wiki": ("scripts/decompose_wiki.py",),
    "wiki-raw": ("scripts/decompose_wiki.py",),
    "atoms": ("scripts/extract_atoms.py",),
    "practice-corpus": (),  # hand-authored only
}

# How many times this process has replaced a runtime cache.  Starts at zero
# and only ever grows, so "same version" is a sound reason to reuse a value
# derived from data/ and a bump is the one signal that invalidates every
# such memo at once.
_DATA_VERSION = 0


def data_version() -> int:
    """The current runtime-cache generation — monotonic, process-local.

    Every memo over data/-derived values keys on this number: two reads
    that see the same version saw the same cache, and write_runtime_cache
    bumping it is what makes a mid-process refresh recompute rather than
    serve a value derived from the cache it replaced.

    Who reads it is :data:`DATA_VERSION_KEYED_MEMOS`, below, and the three
    tables beside it say why every other memo in the tree does not — each
    row carrying its ``invalidated_by`` in :class:`Invalidator`, the one
    vocabulary ``program/caches`` also declares in.  It is
    declared here, in the module that owns the write it counts, because the
    two lanes that key on it are live at once and a counter either of them
    declared would be a counter the other could not use.
    """
    return _DATA_VERSION


def store_for_generation(
    memo: MutableMapping[tuple[int, Any], Any],
    key: tuple[int, Any],
    value: Any,
) -> None:
    """Write one memo entry, dropping any superseded generation first.

    Prefixing a memo key with the cache generation makes a stale entry
    unreachable, which is correctness — but unreachable is not gone.  An
    unbounded memo keyed that way keeps every superseded generation, and
    each entry holds a strong reference to the cached dict it was derived
    from, so a process that refreshes twice retains three copies of
    everything it ever memoized.  Before ``id()`` was prefixed, a recycled
    address at least overwrote its predecessor.

    The eviction lives on the **write** path, and deliberately: a read that
    hits has already matched the live generation in its key, so it needs no
    check at all, and these are the optimizer's inner loops.  Every entry
    shares one generation because this function is what puts keys there, so
    the check is one comparison against the first key rather than a scan.
    """
    for existing in memo:
        if existing[0] != key[0]:
            memo.clear()
        break
    memo[key] = value


class Invalidator(Enum):
    """What can make a cached answer wrong — the campaign's one vocabulary.

    Two registries in this tree answer "what stales this cache": the memo
    tables below, and ``program/caches.CACHES``.  Until S10 they answered it
    in two languages — a table membership here, an ``invalidated_by`` field
    there — so "every cache declares ``invalidated_by``" was true of one of
    them and unaskable of the other.  The enum lives here, in the module
    that owns ``data_version`` and imports nothing, and ``program/caches``
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

    OBJECT_IDENTITY = "object_identity"
    """Nothing but the identity guard in front of the key — the honest
    spelling of a memo that is not invalidated at all.  Every member is a
    row on the deferred table with an issue reference, so this reads as the
    gap it is rather than as a design."""


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


# ── who keys on the counter ──────────────────────────────────────────────
#
# The population is machine-derived, not judged: *every module-level binding
# under src/calculator/ whose name ends in ``_MEMO`` or ``_CACHE`` and whose
# value is a mapping*.  tests/test_data_version_memos.py scans the tree for
# that shape — fifteen of them today — and asserts the four tables below
# partition it exactly, so a sixteenth cannot join the codebase without
# landing in one of them, which is the whole point of a counter over a
# convention (D-49).
#
# Splitting the population four ways rather than two is deliberate: "keys on
# it", "another lane keys it", "cannot be governed by it" and "should be
# keyed and is not this phase's to edit" are four different claims, and
# collapsing the last two would hide a real gap behind a reasoned exemption.

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
    "calculator.pipeline._CAST_ORDER_PARAMS_MEMO": _version_keyed(
        "derived cast-order params; the order was resolved from cached ability data"
    ),
    "calculator.stats._ITEM_STATS_MEMO": _version_keyed(
        "one cached item's extracted stat block"
    ),
    "calculator.stats._ITEM_STATS_VALIDATION_MEMO": _version_keyed(
        "the schema verdict on one cached item's stat map"
    ),
    "calculator.support_effects._SUPPORT_ATTRS_MEMO": _version_keyed(
        "whether a cached champion carries any support attribute"
    ),
    "calculator.support_effects._SUPPORT_PROFILE_MEMO": _version_keyed(
        "one cached ability's shield/heal attribute names and target scope"
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
# trust.  Their names do not match the ``_MEMO``/``_CACHE`` shape the scan
# looks for, which is why they are listed rather than partitioned.
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
) -> None:
    """Atomically write one tracked runtime-cache file with provenance meta.

    Refuses filenames outside CACHE_FILES: the three tracked caches have a
    single writer (data_updater) and every other data/ path has its own
    documented owner in WRITERS.
    """
    if filename not in CACHE_FILES:
        raise ValueError(
            f"{filename} is not a runtime-cache file; runtime cache is "
            f"limited to {sorted(CACHE_FILES)} (see data_registry.WRITERS)"
        )
    data_directory.mkdir(parents=True, exist_ok=True)
    data_path = data_directory / filename
    tmp_path = data_directory / f".{filename}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, data_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    from .data_fetcher import _read_json_version  # local: no import cycle

    # The file on disk has changed, so the parsed-JSON cache is stale and so
    # is everything derived from it.  Both are invalidated here, before the
    # provenance metadata is written: a reader that sees the new version has
    # a live parse behind it.  ``global`` is the honest spelling of a
    # module-level counter; hiding it in a container would not make the
    # state any less module-level.
    _read_json_version.cache_clear()
    global _DATA_VERSION  # pylint: disable=global-statement
    _DATA_VERSION += 1

    metadata: dict[str, Any] = {
        "fetched_at": time.time(),
        "filename": filename,
        "source_url": source_url,
        "source_version": source_version,
        "source_hash": source_hash,
    }
    meta_path = data_directory / f".{filename}.meta"
    with open(meta_path, "w", encoding="utf-8") as meta_file:
        json.dump(metadata, meta_file, indent=2)
