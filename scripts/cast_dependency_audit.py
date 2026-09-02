"""Audit the declared-vs-inferred cast-dependency surface (Phase 5).

Two surfaces make ordering claims about a champion's kit: the module
*declares* prerequisites (``CAST_DEPENDENCIES``) and the rotation resolver
*infers* them from the markers it parses.  Every claim either surface makes
must resolve against something real, and this is the gate that says so.  It
walks every cached champion across the certified option matrix and emits
five ledgers:

``inferred_kind_coverage``
    Which champions produce each member of ``INFERRED_EDGE_KINDS``.  A kind
    no champion produces is a branch the derivation can never take — a
    silently dead interpreter branch — so an empty kind fails, unless it is
    named on the dated acknowledged-gap list carried in the committed
    receipt.
``declared_dependency_activation``
    Every declaration, with the number of option states it was active in
    and the surfaces it is load-bearing on (``load_bearing_routes``,
    measured by deleting it and asking what notices).  A declaration
    active in no certified state constrains nothing, and one on no route
    is a sentence nobody can falsify; both fail.  This is where a
    declaration's disposition lives — in the committed receipt beside
    every other declaration-level ledger, not in a table inside a suite.
``suppression_ledger``
    Every nested suppression, and whether it matched an inferred edge or
    stood latent with its ``latent_reason``.
``conflict_ledger``
    Every opposition between the two surfaces.  A *covered* row cites the
    suppression that reviewed it; an *uncovered* one is a modelling
    disagreement and fails (D-82).
``authored_marker_reach``
    The interpreter→author half of reachability.
    ``engine._validate_cc_event_contract`` proves an authored marker
    reaches its interpreter for one marker; this ledger proves every
    marker the interpreter *reads* is authored by somebody, and that each
    one carries a negative test that withholds or mutates it.  The marker
    surface is **derived** from the apply-atom keys
    ``detect_setup_consume_edges`` actually reads — never hand-listed,
    because a hand list is exactly the prose-outruns-code shape this
    campaign exists to kill.

Two further resolutions ride the declaration ledger.  Every
``CastDependency.source`` is resolved against the committed full-entry wiki
audit: the leaf checks the ``"<url>@<revision>"`` *shape* at import with no
filesystem access, and this is where the revision is proved to be one the
repository actually reviewed.  And every ``cc_enabler`` is resolved against
an authored ``cc_kind`` on the slot whose CC it enables — the declaration's
own ``slot``, since an enabler exists because *that* slot's crowd control is
conditional (Syndra's E stuns only through a sphere Q placed).  An enabler
naming a marker that does not exist is a declaration with no referent, so
the marker is re-checked through ``engine._validate_cc_event_contract``,
the same gate the author side runs at parse time — re-run here so the
*enabler's* claim is checked and not merely the parse's.

Usage::

    python scripts/cast_dependency_audit.py
    python scripts/cast_dependency_audit.py --json
    python scripts/cast_dependency_audit.py --output docs/cast-dependency-audit.json
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from gate_receipt import build_receipt
except ImportError:  # imported as scripts.cast_dependency_audit in tests
    from scripts.gate_receipt import build_receipt

from src.calculator.cast_dependency import (
    INFERRED_EDGE_KINDS,
    CastDependency,
    CastDependencyError,
    ConflictingInferenceError,
    CustomOrderViolatesDependencyError,
    ResolvedCycleError,
    check_order_satisfies_dependencies,
    expand_user_order,
    orderable_slots,
)
from src.calculator.champions import (
    get_champion_cast_dependencies,
    get_champion_cast_order,
    get_champion_option_rotation,
    get_champion_options_meta,
    parse_champion_abilities,
)
from src.calculator.champions.engine import _validate_cc_event_contract
from src.calculator.data_fetcher import fetch_champion_data, fetch_item_data
from src.calculator.pipeline import cast_slot_surface
from src.calculator.rotation_resolver import (
    CAST_ORDER_OVERRIDES,
    ORDER_OVERRIDE_REASONS,
    derive_champion_rule,
    resolved_edges,
)
from src.calculator.stats import calculate_total_stats

RESOLVER_SOURCE = ROOT / "src" / "calculator" / "rotation_resolver.py"
NEGATIVE_TEST_SOURCE = ROOT / "tests" / "test_cast_dependency_audit.py"
WIKI_AUDIT_PATH = ROOT / "docs" / "wiki-full-entry-audit.json"
RECEIPT_PATH = ROOT / "docs" / "cast-dependency-audit.json"

# The name of the marker → test-function mapping the negative-test suite
# declares.  The audit reads it out of the suite's source rather than
# importing the suite: a gate that imports its own evidence can be
# satisfied by the evidence.
NEGATIVE_TEST_MAPPING = "MARKER_NEGATIVE_TESTS"

# The level × build reference matrix, mirroring the rotation suites.  The
# option matrix below is the axis the phase names; these two are the axes
# D-88's "no producer anywhere" verification was measured on, and a
# coverage claim measured on a narrower matrix than the claim it carries
# is the same prose-outruns-code failure in miniature.
MATRIX_LEVELS: tuple[int, ...] = (11, 18)
MATRIX_BUILDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("no_items", ()),
    ("magic", ("Luden's Echo", "Shadowflame", "Rabadon's Deathcap")),
    ("physical", ("Kraken Slayer", "Infinity Edge", "Lord Dominik's Regards")),
    ("spellblade", ("Trinity Force", "Infinity Edge", "Berserker's Greaves")),
)
MATRIX_TARGET_STATS = {
    "target_max_health": 2000.0,
    "target_current_health": 2000.0,
    "target_missing_health": 0.0,
}

# The ledgers an acknowledged gap may excuse a member of.
GAP_LEDGERS = ("inferred_kind_coverage", "authored_marker_reach")

# The closed set of surfaces a declaration can be load-bearing on.  A
# declaration on none of them is prose in a dataclass: deleting it changes
# nothing anybody can observe, so nothing would catch it drifting into
# plausible sentences with every other check still green.
#
# ``derived_order``           deleting it changes the order the derivation
#                             returns, or makes the derivation refuse to
#                             return one, in at least one certified state
# ``confirmed_by_inference``  the detector independently derived the same
#                             edge and the merge receipt says so
# ``custom_order_refusal``    deleting it makes a request order the engine
#                             currently refuses legal again (D-86) — the
#                             route a head-only declaration takes when its
#                             champion's hand seed still decides the order
DECLARATION_ROUTES: tuple[str, ...] = (
    "derived_order",
    "confirmed_by_inference",
    "custom_order_refusal",
)


class AuditDerivationError(RuntimeError):
    """The audit could not derive a surface it is required to derive.

    Raised rather than reported, because a derivation that silently
    returned nothing would publish an empty ledger as a clean bill of
    health — this gate's own failure shape.
    """


# ─────────────────────────────────────────────────────────────────────
# Derived surfaces — read out of source, never typed here
# ─────────────────────────────────────────────────────────────────────


def apply_marker_keys(source: str | None = None) -> tuple[str, ...]:
    """The parsed-entry keys the resolver's apply-atom loop reads, sorted.

    This is the marker surface ``authored_marker_reach`` is measured over.
    It is derived from ``detect_setup_consume_edges``'s own body: the loop
    filling ``apply_atoms`` is located by its assignment target, and every
    string key it reads off a parsed entry is a marker.  A read added to
    that loop grows this set on the commit that adds it, which is what makes
    "a newly read key with no negative test fails the audit" enforceable.
    """
    text = source if source is not None else RESOLVER_SOURCE.read_text(encoding="utf-8")
    loop = _apply_atom_loop(ast.parse(text))
    if loop is None:
        raise AuditDerivationError(
            "the apply-atom loop in detect_setup_consume_edges could not be "
            "located: the audit derives the marker surface from the "
            "assignment to apply_atoms[...] and will not fall back to a "
            "hand-written list"
        )
    keys: set[str] = set()
    for node in ast.walk(loop):
        keys.update(_entry_key_reads(node))
    if not keys:
        raise AuditDerivationError(
            "the apply-atom loop reads no parsed-entry key, which cannot be "
            "true of a working detector"
        )
    return tuple(sorted(keys))


def _apply_atom_loop(tree: ast.AST) -> ast.For | None:
    """The ``for`` statement whose body assigns ``apply_atoms[...]``."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name != "detect_setup_consume_edges":
            continue
        for statement in ast.walk(node):
            if isinstance(statement, ast.For) and any(
                _assigns_apply_atoms(inner) for inner in statement.body
            ):
                return statement
    return None


def _assigns_apply_atoms(node: ast.stmt) -> bool:
    """Whether *node* is the ``apply_atoms[slot] = atoms`` assignment."""
    if not isinstance(node, ast.Assign) or len(node.targets) != 1:
        return False
    target = node.targets[0]
    return (
        isinstance(target, ast.Subscript)
        and isinstance(target.value, ast.Name)
        and target.value.id == "apply_atoms"
    )


def _entry_key_reads(node: ast.AST) -> set[str]:
    """Every parsed-entry key *node* reads, as literal strings."""
    if isinstance(node, ast.Call):
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "get"
            and isinstance(func.value, ast.Name)
            and func.value.id == "info"
        ):
            return _literal_arg(node.args, 0)
        if isinstance(func, ast.Name) and func.id == "getattr":
            return _literal_arg(node.args, 1)
    if (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "info"
    ):
        return _literal_arg([node.slice], 0)
    return set()


def _literal_arg(args: Sequence[ast.AST], index: int) -> set[str]:
    """The string literal at *index*, or nothing when it is not one."""
    if len(args) > index:
        argument = args[index]
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            return {argument.value}
    return set()


def declared_negative_tests(source: str | None = None) -> dict[str, str]:
    """The marker → test-function map the negative-test suite declares.

    Read out of the suite's source so the audit cannot be satisfied by a
    mapping the suite does not actually carry.  The suite's own test
    asserts every named function exists.

    Raises:
        AuditDerivationError: The mapping is absent or is not a literal
            dict of strings.
    """
    if source is None and not NEGATIVE_TEST_SOURCE.exists():
        raise AuditDerivationError(
            f"{NEGATIVE_TEST_SOURCE.name} does not exist, so no marker carries "
            "the negative test the audit requires"
        )
    text = (
        source
        if source is not None
        else NEGATIVE_TEST_SOURCE.read_text(encoding="utf-8")
    )
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.Assign):
            continue
        if NEGATIVE_TEST_MAPPING not in [
            target.id for target in node.targets if isinstance(target, ast.Name)
        ]:
            continue
        mapping = _literal_string_dict(node.value)
        if mapping is not None:
            return mapping
        break
    raise AuditDerivationError(
        f"{NEGATIVE_TEST_SOURCE.name} declares no literal {NEGATIVE_TEST_MAPPING} "
        "mapping; the audit reads negative-test coverage from the suite and "
        "refuses to assume it"
    )


def _literal_string_dict(node: ast.AST) -> dict[str, str] | None:
    """*node* as a ``dict[str, str]`` of literals, or ``None``."""
    if not isinstance(node, ast.Dict):
        return None
    mapping: dict[str, str] = {}
    for key, value in zip(node.keys, node.values, strict=False):
        if not isinstance(key, ast.Constant) or not isinstance(value, ast.Constant):
            return None
        mapping[str(key.value)] = str(value.value)
    return mapping


# ─────────────────────────────────────────────────────────────────────
# The certified option matrix
# ─────────────────────────────────────────────────────────────────────


def option_states(champion_name: str) -> tuple[tuple[str, dict[str, Any]], ...]:
    """The certified option states for one champion.

    The defaults, plus each declared option driven to each of its declared
    extremes — ``min`` and ``max`` for a number, both values for a
    boolean, every choice for a select.  A select's declared values are a
    closed set, and taking two of five would silently skip the very states
    that gate a slot (Kayn's forms, Aphelios' weapons).

    Returns:
        ``(label, options)`` pairs, deduplicated, defaults first.
    """
    meta = get_champion_options_meta(champion_name) or {}
    options = meta.get("options", []) or []
    defaults = {
        str(option["key"]): option["default"]
        for option in options
        if option.get("key") and "default" in option
    }
    states: list[tuple[str, dict[str, Any]]] = [("defaults", dict(defaults))]
    seen = {_state_key(defaults)}
    for option in options:
        key = str(option.get("key", ""))
        for value in _declared_extremes(option):
            state = dict(defaults)
            state[key] = value
            signature = _state_key(state)
            if signature in seen:
                continue
            seen.add(signature)
            states.append((f"{key}={value}", state))
    return tuple(states)


def _declared_extremes(option: Mapping[str, Any]) -> tuple[Any, ...]:
    """The declared boundary values of one option."""
    kind = option.get("type")
    if kind in ("int", "float"):
        return tuple(
            value
            for value in (option.get("min"), option.get("max"))
            if value is not None
        )
    if kind == "bool":
        return (False, True)
    if kind == "select":
        return tuple(
            choice.get("value")
            for choice in option.get("choices") or ()
            if isinstance(choice, Mapping) and choice.get("value") is not None
        )
    return ()


def _state_key(state: Mapping[str, Any]) -> str:
    """A stable signature for one option state."""
    return json.dumps(state, sort_keys=True, default=str)


def slot_option_keys(champion_name: str) -> dict[str, list[str]]:
    """``slot -> option keys``, as ``detect_setup_consume_edges`` reads it."""
    meta = get_champion_options_meta(champion_name) or {}
    rotations = get_champion_option_rotation(champion_name)
    slot_options: dict[str, list[str]] = {}
    for option in meta.get("options", []) or []:
        key = str(option.get("key", ""))
        declaration = rotations.get(key)
        if not declaration or declaration.get("role") not in (
            "setup",
            "consume",
            "execute",
        ):
            continue
        slot_options.setdefault(str(declaration.get("slot") or "__all__"), []).append(
            key
        )
    return slot_options


# ─────────────────────────────────────────────────────────────────────
# The walk
# ─────────────────────────────────────────────────────────────────────


def _marker_authored(entry: Mapping[str, Any], marker: str) -> bool:
    """Whether one parsed entry authors *marker*.

    ``cc_kind`` lives on a damage part rather than on the entry, which is
    why the detector reads it through ``parts``; every other marker is an
    entry key.
    """
    if marker == "cc_kind":
        return any(
            getattr(part, "cc_kind", None) not in (None, "none")
            for part in entry.get("parts", ()) or ()
        )
    return bool(entry.get(marker))


def _walk_roster(markers: Sequence[str]) -> dict[str, Any]:
    """Run every champion through every certified state and collect observations.

    Returns:
        The raw observations the ledgers are projected from: which
        champions produced each inferred kind, which states each
        declaration was active in, what the suppressions did, every
        conflict, which champions author each marker, and any state whose
        merge raised.
    """
    champions = {
        str(data.get("name")): data
        for data in fetch_champion_data().values()
        if data.get("name")
    }
    items_by_name = {
        str(item["name"]): item
        for item in fetch_item_data().values()
        if item.get("name")
    }

    kind_producers: dict[str, set[str]] = {kind: set() for kind in INFERRED_EDGE_KINDS}
    marker_authors: dict[str, set[str]] = {marker: set() for marker in markers}
    activation: dict[tuple[str, str, str], set[str]] = {}
    matched: dict[tuple[str, str, str, str], set[str]] = {}
    latent: dict[tuple[str, str, str, str], set[str]] = {}
    conflicts: list[dict[str, str]] = []
    uncovered: list[dict[str, str]] = []
    walk_errors: list[dict[str, str]] = []
    cc_markers: dict[tuple[str, str], set[str]] = {}
    cc_contract: dict[tuple[str, str], str] = {}
    routes: dict[tuple[str, str, str], set[str]] = {}
    states_walked = 0

    for name in sorted(champions):
        data = champions[name]
        declarations = get_champion_cast_dependencies(name)
        option_keys = slot_option_keys(name)
        for label, options in option_states(name):
            for level in MATRIX_LEVELS:
                for build_label, build in MATRIX_BUILDS:
                    state = f"{label}|L{level}|{build_label}"
                    states_walked += 1
                    parsed = _parse(data, level, build, items_by_name, options)
                    _record_markers(
                        name, parsed, markers, marker_authors, cc_markers, cc_contract
                    )
                    try:
                        edges, receipt = resolved_edges(name, parsed, data, option_keys)
                    except ConflictingInferenceError as error:
                        uncovered.append(
                            {"champion": name, "state": state, "detail": str(error)}
                        )
                        continue
                    except CastDependencyError as error:
                        walk_errors.append(
                            {
                                "champion": name,
                                "state": state,
                                "error": type(error).__name__,
                                "detail": str(error),
                            }
                        )
                        continue
                    for edge in edges:
                        if edge.origin == "inferred":
                            kind_producers.setdefault(edge.kind, set()).add(name)
                    _record_merge(
                        name,
                        state,
                        declarations,
                        receipt,
                        activation,
                        matched,
                        latent,
                        conflicts,
                    )
                    _record_routes(
                        name, data, parsed, options, declarations, receipt, routes
                    )

    return {
        "champions": sorted(champions),
        "kind_producers": kind_producers,
        "marker_authors": marker_authors,
        "activation": activation,
        "suppression_matched": matched,
        "suppression_latent": latent,
        "conflicts": conflicts,
        "uncovered": uncovered,
        "walk_errors": walk_errors,
        "cc_markers": cc_markers,
        "cc_contract": cc_contract,
        "routes": routes,
        "states_walked": states_walked,
    }


def _parse(
    champion_data: Mapping[str, Any],
    level: int,
    build: Sequence[str],
    items_by_name: Mapping[str, Any],
    options: Mapping[str, Any],
) -> dict[str, Any]:
    """One champion's parsed ability package for one matrix cell."""
    items = [items_by_name[name] for name in build if name in items_by_name]
    stats = calculate_total_stats(champion_data, level, items)
    return parse_champion_abilities(
        champion_data,
        level,
        stats["ability_power"],
        ability_ranks=None,
        champion_stats=stats,
        target_stats=dict(MATRIX_TARGET_STATS),
        champion_options=dict(options) or None,
    )


def _record_markers(
    name: str,
    parsed: Mapping[str, Any],
    markers: Sequence[str],
    marker_authors: dict[str, set[str]],
    cc_markers: dict[tuple[str, str], set[str]],
    cc_contract: dict[tuple[str, str], str],
) -> None:
    """Record who authors each marker, and re-run the CC contract on CC slots."""
    for slot, entry in parsed.items():
        if not isinstance(entry, Mapping):
            continue
        for marker in markers:
            if _marker_authored(entry, marker):
                marker_authors[marker].add(name)
        kinds = {
            str(part.cc_kind)
            for part in entry.get("parts", ()) or ()
            if getattr(part, "cc_kind", None) not in (None, "none")
        }
        if not kinds:
            continue
        cc_markers.setdefault((name, slot), set()).update(kinds)
        try:
            _validate_cc_event_contract(name, slot, dict(entry))
        except ValueError as error:  # pragma: no cover - a red gate
            cc_contract[(name, slot)] = str(error)


def _record_merge(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    name: str,
    state: str,
    declarations: Sequence[CastDependency],
    receipt: Any,
    activation: dict[tuple[str, str, str], set[str]],
    matched: dict[tuple[str, str, str, str], set[str]],
    latent: dict[tuple[str, str, str, str], set[str]],
    conflicts: list[dict[str, str]],
) -> None:
    """Fold one state's merge receipt into the declaration ledgers.

    The receipt's rows are display strings, and each ledger's rows open
    with the pair they are about — ``"E requires Q ..."``,
    ``"E -> Q (cc_setup) ..."``.  That prefix is the join key, pinned by
    the audit's own suite: if the resolver's wording drifts, every
    declaration reads as active in zero states and the audit goes red,
    rather than a ledger quietly emptying.
    """
    for dependency in declarations:
        key = (name, dependency.slot, dependency.requires)
        activation.setdefault(key, set())
        if _has_prefix(
            receipt.active, f"{dependency.slot} requires {dependency.requires}"
        ):
            activation[key].add(state)
        for suppression in dependency.suppresses:
            prefix = (
                f"{suppression.setup} -> {suppression.consume} ({suppression.kind})"
            )
            suppression_key = (
                name,
                suppression.setup,
                suppression.consume,
                suppression.kind,
            )
            matched.setdefault(suppression_key, set())
            latent.setdefault(suppression_key, set())
            if _has_prefix(receipt.suppressed, prefix):
                matched[suppression_key].add(state)
            if _has_prefix(receipt.latent, prefix):
                latent[suppression_key].add(state)
    conflicts.extend(
        {"champion": name, "state": state, "row": row} for row in receipt.conflicts
    )


def _has_prefix(rows: Iterable[str], prefix: str) -> bool:
    """Whether any receipt row opens with *prefix*."""
    return any(row.startswith(prefix) for row in rows)


def _record_routes(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    name: str,
    champion_data: Mapping[str, Any],
    parsed: Mapping[str, Any],
    options: Mapping[str, Any],
    declarations: Sequence[CastDependency],
    receipt: Any,
    routes: dict[tuple[str, str, str], set[str]],
) -> None:
    """Fold one state's load-bearing measurement into the route ledger.

    Every declaration is deleted in turn and the state is asked what
    notices.  A declaration that survives its own deletion unnoticed on all
    three surfaces is unfalsifiable prose.
    """
    if not declarations:
        return
    certified = get_champion_cast_order(name)
    full_order = _derived_order(
        name, parsed, champion_data, certified, options, declarations
    )
    for dependency in declarations:
        key = (name, dependency.slot, dependency.requires)
        routes.setdefault(key, set())
        rest = tuple(other for other in declarations if other is not dependency)
        if (
            _derived_order(name, parsed, champion_data, certified, options, rest)
            != full_order
        ):
            routes[key].add("derived_order")
        if _has_prefix(
            receipt.confirmed_by_inference,
            f"{dependency.slot} requires {dependency.requires}",
        ):
            routes[key].add("confirmed_by_inference")
        if _frees_a_refused_order(dependency, declarations, rest, parsed):
            routes[key].add("custom_order_refusal")


def _derived_order(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    name: str,
    parsed: Mapping[str, Any],
    champion_data: Mapping[str, Any],
    certified: list[str] | None,
    options: Mapping[str, Any],
    declarations: Sequence[CastDependency],
) -> tuple[str, ...] | None:
    """The order the derivation returns against *declarations*.

    ``None`` means the derivation refused to return one — a declared cycle
    is a module/interpreter disagreement, and "the answer changed from an
    order to a refusal" is a change like any other.
    """
    try:
        rule = derive_champion_rule(
            name,
            parsed,
            champion_data,
            certified,
            dict(options) or None,
            declarations=declarations,
        )
    except ResolvedCycleError:
        return None
    return tuple(rule.order)


def _frees_a_refused_order(
    dependency: CastDependency,
    declarations: Sequence[CastDependency],
    rest: Sequence[CastDependency],
    parsed: Mapping[str, Any],
) -> bool:
    """Does deleting *dependency* make a refused request order legal?

    The probe is a real request, built the way the request boundary builds
    one: a permutation of ``orderable_slots`` — what a payload may name —
    run through ``expand_user_order`` so live recasts ride their parents,
    then checked.  A two-slot fragment would answer a different and easier
    question: Syndra's ``E requires Q`` frees nothing on its own, because
    ``E requires Q2`` refuses the same order, and only a whole order can
    see that.
    """
    surface = cast_slot_surface(parsed)
    live = set(surface)
    if not {dependency.slot, dependency.requires} <= live:
        return False
    nameable = orderable_slots(surface)
    if dependency.slot not in nameable:
        return False
    head = [dependency.slot] + [
        slot for slot in (dependency.requires,) if slot in nameable
    ]
    inverted = expand_user_order(
        head + [slot for slot in nameable if slot not in head], surface
    )
    try:
        check_order_satisfies_dependencies(inverted, declarations, live)
    except CustomOrderViolatesDependencyError:
        pass
    else:
        return False
    try:
        check_order_satisfies_dependencies(inverted, rest, live)
    except CustomOrderViolatesDependencyError:
        return False
    return True


# ─────────────────────────────────────────────────────────────────────
# Source resolution
# ─────────────────────────────────────────────────────────────────────


def wiki_revisions() -> dict[str, int]:
    """``source_url -> revision_id`` from the committed full-entry audit."""
    audit = json.loads(WIKI_AUDIT_PATH.read_text(encoding="utf-8"))
    revisions: dict[str, int] = {}
    for entry in audit.get("entries", []) or []:
        url = entry.get("source_url")
        revision = entry.get("revision_id")
        if isinstance(url, str) and isinstance(revision, int):
            revisions[url] = revision
    if not revisions:
        raise AuditDerivationError(
            f"{WIKI_AUDIT_PATH.name} carries no reviewed revision, so no "
            "declaration source could ever resolve"
        )
    return revisions


def resolve_source(source: str, revisions: Mapping[str, int]) -> dict[str, Any]:
    """Resolve one ``"<url>@<revision>"`` against the committed wiki audit.

    Three outcomes, and only two of them are defects.  A page the audit
    never reviewed, or a revision *newer* than the one it reviewed, is a
    citation to something this repository has never read — that fails.  A
    revision *older* than the reviewed one is a declaration that honestly
    pins what its author read and is reported ``stale`` rather than
    failed, the same reading ``full_entry_audit`` already gives a module
    whose pinned source receipt has been overtaken by a newer pull.
    """
    url, _, revision = source.rpartition("@")
    reviewed = revisions.get(url)
    cited = int(revision) if revision.isdigit() else None
    known_page = reviewed is not None and cited is not None
    return {
        "source": source,
        "url": url,
        "revision_id": cited,
        "reviewed_revision_id": reviewed,
        "resolved": known_page and cited <= reviewed,
        "current": known_page and cited == reviewed,
        "stale": known_page and cited < reviewed,
    }


# ─────────────────────────────────────────────────────────────────────
# The audit
# ─────────────────────────────────────────────────────────────────────


def committed_acknowledged_gaps() -> tuple[dict[str, Any], ...]:
    """The acknowledged-gap list carried in the committed receipt.

    The exclusion list lives in the receipt, never inside this tool
    (D-40): a counter whose exclusions live in the measuring script can be
    driven to zero by editing the script, and nobody reading the number
    would see it happen.  With no committed receipt there are no
    exclusions and the audit fails closed.
    """
    if not RECEIPT_PATH.exists():
        return ()
    receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    return tuple(
        dict(gap)
        for gap in receipt.get("acknowledged_gaps") or []
        if isinstance(gap, Mapping)
    )


def run_audit(
    *, acknowledged_gaps: Iterable[Mapping[str, Any]] | None = None
) -> dict[str, Any]:
    """Return the deterministic cast-dependency audit receipt.

    Args:
        acknowledged_gaps: The dated gap list to honour; read from the
            committed receipt when omitted.  Passing ``()`` is how the
            gate's own negative test reproduces a red on demand (R-05).

    Returns:
        The gate-receipt envelope carrying the five ledgers.
    """
    gaps = tuple(
        dict(gap)
        for gap in (
            committed_acknowledged_gaps()
            if acknowledged_gaps is None
            else acknowledged_gaps
        )
    )
    markers = apply_marker_keys()
    negative_tests = declared_negative_tests()
    revisions = wiki_revisions()
    observed = _walk_roster(markers)

    kind_coverage = {
        kind: sorted(observed["kind_producers"].get(kind, ()))
        for kind in sorted(INFERRED_EDGE_KINDS)
    }
    activation_ledger, activation_failures = _activation_ledger(observed, revisions)
    suppression_ledger, suppression_failures = _suppression_ledger(observed)
    conflict_ledger, conflict_failures = _conflict_ledger(observed)
    marker_ledger, marker_failures = _marker_ledger(markers, observed, negative_tests)

    unfilled = [
        ("inferred_kind_coverage", kind)
        for kind, producers in kind_coverage.items()
        if not producers
    ] + [
        ("authored_marker_reach", marker)
        for marker, row in marker_ledger.items()
        if not row["authors"]
    ]
    failures = (
        activation_failures
        + suppression_failures
        + conflict_failures
        + marker_failures
        + _gap_failures(gaps, unfilled)
        + [
            {
                "item": f"walk:{error['champion']}",
                "reason": f"{error['state']}: {error['error']}: {error['detail']}",
            }
            for error in observed["walk_errors"]
        ]
    )

    units = (
        {f"inferred_kind_coverage:{kind}" for kind in kind_coverage}
        | {_declaration_item(row) for row in activation_ledger}
        | {_suppression_item(row) for row in suppression_ledger}
        | {f"authored_marker_reach:{marker}" for marker in marker_ledger}
        | {_gap_item(gap) for gap in gaps}
    )
    failing = {failure["item"] for failure in failures}
    total = len(units | failing)
    return build_receipt(
        matrix="cast_dependency_declarations",
        passed=not failing,
        passed_count=total - len(failing),
        failed_count=len(failing),
        total_count=total,
        withheld_count=0,
        failures=sorted(failures, key=lambda row: (row["item"], row["reason"])),
        extra={
            "audit": "cast_dependency_declarations",
            "acknowledged_gaps": list(gaps),
            "option_matrix": {
                "champions": len(observed["champions"]),
                "states_walked": observed["states_walked"],
                "levels": list(MATRIX_LEVELS),
                "builds": [label for label, _ in MATRIX_BUILDS],
            },
            "inferred_kind_coverage": kind_coverage,
            "declared_dependency_activation": activation_ledger,
            "suppression_ledger": suppression_ledger,
            "conflict_ledger": conflict_ledger,
            "authored_marker_reach": marker_ledger,
            "order_override_frontier": _override_frontier(),
        },
    )


def _declaration_item(row: Mapping[str, Any]) -> str:
    """The gate-unit id of one declaration row."""
    return f"declaration:{row['champion']}:{row['slot']}->{row['requires']}"


def _suppression_item(row: Mapping[str, Any]) -> str:
    """The gate-unit id of one suppression row."""
    return (
        f"suppression:{row['champion']}:{row['setup']}->{row['consume']}:{row['kind']}"
    )


def _gap_item(gap: Mapping[str, Any]) -> str:
    """The gate-unit id of one acknowledged gap."""
    return f"acknowledged_gap:{gap.get('ledger')}:{gap.get('member')}"


def _activation_ledger(
    observed: Mapping[str, Any], revisions: Mapping[str, int]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Every declaration with its activation, source and enabler resolution."""
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for name in observed["champions"]:
        for dependency in get_champion_cast_dependencies(name):
            states = sorted(
                observed["activation"].get(
                    (name, dependency.slot, dependency.requires), ()
                )
            )
            source = resolve_source(dependency.source, revisions)
            row: dict[str, Any] = {
                "champion": name,
                "slot": dependency.slot,
                "requires": dependency.requires,
                "kind": dependency.kind,
                "active_states": len(states),
                "sample_active_state": states[0] if states else None,
                "source_resolution": source,
                "load_bearing_routes": sorted(
                    observed["routes"].get(
                        (name, dependency.slot, dependency.requires), ()
                    ),
                    key=DECLARATION_ROUTES.index,
                ),
            }
            if dependency.kind == "cc_enabler":
                row["cc_enabler_resolution"] = _resolve_cc_enabler(
                    name, dependency, observed
                )
            rows.append(row)
            failures.extend(_declaration_failures(row, dependency))
    return rows, failures


def _resolve_cc_enabler(
    champion_name: str, dependency: CastDependency, observed: Mapping[str, Any]
) -> dict[str, Any]:
    """Resolve one ``cc_enabler`` against the marker it claims to enable.

    The marker sits on the declaration's own ``slot``: an enabler exists
    because *that* slot's crowd control is conditional on ``requires``
    running first, so it is that slot's ``cc_kind`` the declaration is
    about.  ``engine._validate_cc_event_contract`` decides whether the
    marker reaches the event ledger, which is what makes it a marker
    rather than a decoration.
    """
    kinds = sorted(observed["cc_markers"].get((champion_name, dependency.slot), set()))
    contract_error = observed["cc_contract"].get((champion_name, dependency.slot), "")
    return {
        "marker_slot": dependency.slot,
        "cc_kinds": kinds,
        "resolved": bool(kinds),
        "reaches_event_ledger": bool(kinds) and not contract_error,
        "contract_error": contract_error or None,
    }


def _declaration_failures(
    row: Mapping[str, Any], dependency: CastDependency
) -> list[dict[str, str]]:
    """Everything one declaration failed to resolve."""
    item = _declaration_item(row)
    source = row["source_resolution"]
    failures: list[dict[str, str]] = []
    if not row["active_states"]:
        failures.append(
            {
                "item": item,
                "reason": (
                    "the declaration is active in no certified option state, so "
                    "it constrains nothing and no test can falsify it"
                ),
            }
        )
    if not row["load_bearing_routes"]:
        failures.append(
            {
                "item": item,
                "reason": (
                    "the declaration is load-bearing on nothing: deleting it "
                    "changes no derived order in any certified state, frees no "
                    "refused request order, and no inference confirms it — a "
                    "sentence in a dataclass that nothing can falsify"
                ),
            }
        )
    if not source["resolved"]:
        failures.append(
            {
                "item": item,
                "reason": (
                    f"source {dependency.source!r} resolves against nothing the "
                    "committed wiki audit reviewed: the page is uncached, the "
                    "revision is unreadable, or it is newer than the reviewed "
                    f"revision {source['reviewed_revision_id']}"
                ),
            }
        )
    enabler = row.get("cc_enabler_resolution")
    if enabler and not enabler["resolved"]:
        failures.append(
            {
                "item": item,
                "reason": (
                    f"cc_enabler names no marker: {dependency.slot} authors no "
                    "cc_kind in any certified state, so the declaration enables "
                    "nothing"
                ),
            }
        )
    elif enabler and not enabler["reaches_event_ledger"]:
        failures.append(
            {
                "item": item,
                "reason": (
                    "the enabled cc_kind never reaches the event ledger: "
                    f"{enabler['contract_error']}"
                ),
            }
        )
    return failures


def _suppression_ledger(
    observed: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Every nested suppression, matched or latent, with its reason."""
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for name in observed["champions"]:
        for dependency in get_champion_cast_dependencies(name):
            for suppression in dependency.suppresses:
                key = (name, suppression.setup, suppression.consume, suppression.kind)
                matched = observed["suppression_matched"].get(key, ())
                latent = observed["suppression_latent"].get(key, ())
                row = {
                    "champion": name,
                    "parent": f"{dependency.slot} requires {dependency.requires}",
                    "setup": suppression.setup,
                    "consume": suppression.consume,
                    "kind": suppression.kind,
                    "matched_states": len(matched),
                    "latent_states": len(latent),
                    "reason": suppression.reason,
                    "latent_reason": suppression.latent_reason,
                }
                rows.append(row)
                item = _suppression_item(row)
                if latent and not suppression.latent_reason:
                    failures.append(
                        {
                            "item": item,
                            "reason": (
                                "the suppression stood latent with no "
                                "latent_reason — a claim about an inference "
                                "nobody can see"
                            ),
                        }
                    )
                if not matched and not latent:
                    failures.append(
                        {
                            "item": item,
                            "reason": (
                                "the suppression neither matched an inference nor "
                                "stood latent in any certified state"
                            ),
                        }
                    )
    return rows, failures


def _conflict_ledger(
    observed: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Covered oppositions as rows; uncovered ones as rows *and* failures."""
    covered: dict[tuple[str, str], set[str]] = {}
    for row in observed["conflicts"]:
        covered.setdefault((row["champion"], row["row"]), set()).add(row["state"])
    rows: list[dict[str, Any]] = [
        {"champion": champion, "row": text, "covered": True, "states": len(states)}
        for (champion, text), states in sorted(covered.items())
    ]
    failures: list[dict[str, str]] = []
    for row in observed["uncovered"]:
        rows.append(
            {
                "champion": row["champion"],
                "row": row["detail"],
                "covered": False,
                "states": 1,
            }
        )
        failures.append(
            {
                "item": f"conflict:{row['champion']}",
                "reason": (
                    f"{row['state']}: an inference opposes a declaration with no "
                    f"suppression covering it: {row['detail']}"
                ),
            }
        )
    return rows, failures


def _marker_ledger(
    markers: Sequence[str],
    observed: Mapping[str, Any],
    negative_tests: Mapping[str, str],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """The derived marker surface, its authors and its negative tests."""
    ledger: dict[str, Any] = {}
    failures: list[dict[str, str]] = []
    for marker in markers:
        authors = sorted(observed["marker_authors"].get(marker, ()))
        ledger[marker] = {
            "authors": len(authors),
            "sample_author": authors[0] if authors else None,
            "negative_test": negative_tests.get(marker),
        }
        if marker not in negative_tests:
            failures.append(
                {
                    "item": f"authored_marker_reach:{marker}",
                    "reason": (
                        "the interpreter reads this marker and no negative test "
                        "withholds or mutates it, so nothing proves the read is "
                        "load-bearing"
                    ),
                }
            )
    failures.extend(
        {
            "item": f"authored_marker_reach:{marker}",
            "reason": (
                "a negative test claims a marker the interpreter no longer "
                "reads; the test is stale"
            ),
        }
        for marker in sorted(set(negative_tests) - set(markers))
    )
    return ledger, failures


def _gap_failures(
    gaps: Sequence[Mapping[str, Any]], unfilled: Sequence[tuple[str, str]]
) -> list[dict[str, str]]:
    """Unexcused empty members, stale gap entries, and malformed ones.

    A gap that excuses nothing is deleted rather than kept: a stale
    exclusion is how an empty ledger stays excused after the hole it named
    was filled.
    """
    excused = {(str(gap.get("ledger")), str(gap.get("member"))): gap for gap in gaps}
    holes = set(unfilled)
    failures: list[dict[str, str]] = []
    for ledger, member in unfilled:
        if (ledger, member) in excused:
            continue
        failures.append(
            {
                "item": f"{ledger}:{member}",
                "reason": (
                    f"{member!r} is unfilled in {ledger} and is not on the "
                    "acknowledged-gap list, so the branch reading it is dead"
                ),
            }
        )
    for (ledger, member), gap in sorted(excused.items()):
        if (ledger, member) in holes:
            continue
        failures.append(
            {
                "item": _gap_item(gap),
                "reason": (
                    f"the gap dated {gap.get('dated')} excuses nothing: "
                    f"{member!r} is not an unfilled member of {ledger}, so the "
                    "entry is stale and must be deleted"
                ),
            }
        )
    for gap in gaps:
        missing = [
            field
            for field in ("ledger", "member", "dated", "decision", "reason")
            if not str(gap.get(field, "")).strip()
        ]
        if missing or str(gap.get("ledger")) not in GAP_LEDGERS:
            failures.append(
                {
                    "item": _gap_item(gap),
                    "reason": (
                        f"the gap entry is missing {sorted(missing)} or names a "
                        f"ledger outside {list(GAP_LEDGERS)}"
                    ),
                }
            )
    return failures


def _override_frontier() -> dict[str, Any]:
    """The remaining hand-held cast orders and why each is still held.

    The retirement frontier is a count this audit publishes rather than a
    claim a document makes: every surviving entry of
    ``CAST_ORDER_OVERRIDES`` carries a reason from the closed set, and the
    histogram is what a later slice drives down.

    ``head_only`` is the second half of that frontier and is derived, not
    listed: a seed whose champion also declares a ``CastDependency`` is
    D-89's head-only disposition — the declaration decides the head of the
    order and the hand seed still decides the tail — where a seed whose
    champion declares nothing is hand-held end to end.  After the four
    retirements all seven survivors carry the same ``dps_tiebreak``
    reason, so without this the histogram cannot tell Zed and Brand apart
    from a pure Tier 3 seed and the distinction D-89 ruled lives only in
    ``declared_dependency_activation``.
    """
    histogram = dict.fromkeys(sorted(ORDER_OVERRIDE_REASONS), 0)
    unclassified: list[str] = []
    for name, rule in sorted(CAST_ORDER_OVERRIDES.items()):
        if rule.override_reason in histogram:
            histogram[rule.override_reason] += 1
        else:
            unclassified.append(name)
    return {
        "entries": len(CAST_ORDER_OVERRIDES),
        "champions": sorted(CAST_ORDER_OVERRIDES),
        "reasons": histogram,
        "unclassified": unclassified,
        "head_only": [
            name
            for name in sorted(CAST_ORDER_OVERRIDES)
            if get_champion_cast_dependencies(name)
        ],
    }


def main() -> int:
    """Run the audit and return a shell-friendly status code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit the full receipt")
    parser.add_argument("--output", type=Path, help="write the full receipt to a file")
    args = parser.parse_args()
    receipt = run_audit()
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    if args.json:
        print(encoded, end="")
    else:
        print(json.dumps({"passed": receipt["passed"], "counts": receipt["counts"]}))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
