"""The resolution tier — where an evidence string becomes an object.

``coverage_evidence`` is the *load* tier: it refuses a claim whose **shape**
cannot be backed by anything.  This module is the tier that asks the harder
question — does the thing a claim's evidence names actually exist in *this*
tree — and it answers it on **every** ``pytest`` run, including under ``-k``
and inside a ``git bisect``, because the drift window this campaign closes is
one commit wide (D-21).

Four properties of this file are ruled, and every one of them is load-bearing.

*It is not collected.*  ``coverage_resolver.py`` matches none of pytest's
``python_files`` patterns, so nothing here is a test and nothing here can be
filtered away by a ``-k`` expression aimed at something else.  It is a helper
the collected suites call.

*It imports exactly one production module.*  ``coverage_evidence`` and no
other, at module scope or anywhere else.  Production code must not import
pytest, so the resolution tier lives on the test side; and a resolver that
imported the modules it resolves against would resolve them at its own import
time, before any seam could be replaced.

*Every read goes through a seam.*  :class:`ResolverContext` carries the three
— ``importer`` (a module by dotted path), ``read_source`` (a repository file
by relative path) and ``nodes`` (the set pytest collected).  Those three are
the entire mutation harness: M1–M9 prove the resolver notices a broken
evidence member by handing it a context whose seams describe a tree the repo
does not have, and a read that reached past them would be a branch no
mutation test could reach.

*Nothing here is memoized.*  A module-level cache would answer the second
mutation with the first mutation's tree, which turns the mutation suite green
by construction.  The one module-level name this file rebinds is
``_SESSION_CONFIG``, the handle to the running pytest session; the collected
node set itself has exactly one home, ``config.stash``, and
:func:`live_context` reads it fresh on every call.

The tier below this one is the *full session*: exact node ids, marker facts
and duplicate-nodeid detection, which only a complete collection can see.
A filtered session does not *skip* those checks — ``pytest.skip`` prints
green, and a decorative tier launders absence as success — it never collects
them, and this module proves the weaker fact by source scan instead
(:func:`test_ref_verdict` takes ``full_session`` and says which tier answered).
"""

import ast
import contextlib
import importlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pytest

from src.calculator.coverage_evidence import (
    Absence,
    Claim,
    EffectKey,
    EffectTag,
    OptionSchema,
    PacketSource,
    PairedSides,
    SourceRef,
    Symbol,
    TestRef,
    claim_name,
)

ROOT = Path(__file__).resolve().parents[1]

Tier = Literal["full_session", "resolution"]

# The marker the full-session tier carries.  Its name is here rather than in
# ``conftest`` so the tier's gate and the tier's checks name one string.
FULL_SESSION_MARKER = "full_session"

# ``config.stash`` is the collected node set's one home; these are the keys.
COLLECTED_NODES: pytest.StashKey[Mapping[str, "CollectedNode"]] = pytest.StashKey()
FULL_SESSION: pytest.StashKey[bool] = pytest.StashKey()

# Rule 4's vocabulary.  ``pytest.skip`` and ``pytest.importorskip`` are the
# two calls that turn a test into a green non-result from inside its own body.
_SKIP_CALLS: frozenset[str] = frozenset({"skip", "importorskip"})
_SKIP_MARKS: frozenset[str] = frozenset({"skip", "skipif"})
_XFAIL_MARKS: frozenset[str] = frozenset({"xfail"})

# Fixtures pytest itself supplies.  They have no visible definition in the
# repository, so the closure scan names them and moves on rather than
# reporting a gap it cannot close.
_BUILTIN_FIXTURES: frozenset[str] = frozenset(
    {
        "cache",
        "capfd",
        "capfdbinary",
        "caplog",
        "capsys",
        "capsysbinary",
        "doctest_namespace",
        "monkeypatch",
        "pytestconfig",
        "pytester",
        "record_property",
        "record_testsuite_property",
        "record_xml_attribute",
        "recwarn",
        "request",
        "tmp_path",
        "tmp_path_factory",
        "tmpdir",
        "tmpdir_factory",
    }
)

# Relevance (rule 5) ignores tokens this short.  A three-character fragment
# of a packet source matches half the repository, and a rule that always
# passes is the prose this phase deletes.
_MIN_RELEVANCE_TOKEN = 4


class EvidenceUnresolved(Exception):
    """One evidence member naming something this tree does not have.

    It is raised by the resolvers and collected by ``resolve_table``, so it
    carries the claim and the member as fields rather than only in its
    message: one run names every broken member, not the first.
    """

    def __init__(self, *, claim: str, evidence: object, detail: str) -> None:
        super().__init__(f"{claim}: {type(evidence).__name__} {detail}")
        self.claim = claim
        self.evidence = evidence
        self.detail = detail


@dataclass(frozen=True, slots=True)
class CollectedNode:
    """One node pytest collected, reduced to the facts a ``TestRef`` is judged on.

    Attributes:
        node_id: the id as pytest reports it, parametrization included.
        module_path: the repository-relative posix path of the defining file.
        parents: the class parts between the file and the function.
        function_name: the function's own name, without the parametrization.
        parametrization: the ``[...]`` suffix, empty when there is none.
        markers: every marker in force, including class and module
            ``pytestmark`` — ``iter_markers`` already walks the chain, which
            is why a skip hidden at module level cannot pass this record.
        fixtures: the node's fixture closure, by name.
        occurrences: how many collected items carried this id.  It is a
            field rather than a boolean because "resolves to exactly one
            node" is rule 1, and a duplicate id is the interesting failure.
    """

    node_id: str
    module_path: str
    parents: tuple[str, ...]
    function_name: str
    parametrization: str
    markers: frozenset[str]
    fixtures: frozenset[str]
    occurrences: int

    @classmethod
    def from_node_id(
        cls,
        node_id: str,
        *,
        markers: Iterable[str] = (),
        fixtures: Iterable[str] = (),
        occurrences: int = 1,
    ) -> "CollectedNode":
        """Build the record from an id plus the facts only collection knows."""
        module_path, parents, function_name, parametrization = split_node_id(node_id)
        return cls(
            node_id=node_id,
            module_path=module_path,
            parents=parents,
            function_name=function_name,
            parametrization=parametrization,
            markers=frozenset(markers),
            fixtures=frozenset(fixtures),
            occurrences=occurrences,
        )


@dataclass(frozen=True, slots=True)
class TestRefVerdict:
    """What the four skip/xfail rules found, and which tier found it.

    Attributes:
        node_id: the id that was judged.
        tier: ``full_session`` when the collected node set answered,
            ``resolution`` when the weaker source scan did.
        failures: one line per broken rule; empty means the ref passes.
        unscanned_fixtures: closure members whose definition this tier could
            not read — a factory-built fixture, or one a plugin supplies.
            Reported rather than failed, because an unreadable definition is
            not evidence of a skip; naming them is what keeps the gap from
            being silent.
    """

    # pytest collects any imported class whose name starts with ``Test``.
    __test__ = False

    node_id: str
    tier: Tier
    failures: tuple[str, ...]
    unscanned_fixtures: frozenset[str]

    @property
    def resolved(self) -> bool:
        """Whether every rule this tier could check passed."""
        return not self.failures


@dataclass(frozen=True, slots=True)
class ResolverContext:
    """The three seams. No module-level caching — a memo defeats every mutation.

    Attributes:
        importer: a dotted path to a module object, ``importlib`` in life.
        read_source: a repository-relative posix path to that file's text.
            It raises ``OSError`` for a path the tree does not have, which is
            how "this evidence names no file" reaches a verdict.
        nodes: the collected node set, keyed by node id.  Empty is legal and
            means the full-session tier has nothing to answer with.
    """

    importer: Callable[[str], object]
    read_source: Callable[[str], str]
    nodes: Mapping[str, CollectedNode]


# ── the live session ──────────────────────────────────────────────────────

# The handle to the running session, set once by ``conftest``'s collection
# hook.  It is a session handle and not a cache: the node set lives in
# ``config.stash`` and is read through it on every call.
_SESSION_CONFIG: pytest.Config | None = None


def record_session(config: pytest.Config) -> None:
    """Hand the resolver the session whose stash holds the collected nodes."""
    global _SESSION_CONFIG  # pylint: disable=global-statement
    _SESSION_CONFIG = config


def _session() -> pytest.Config:
    """The recorded session, or a failure that says who was supposed to set it."""
    if _SESSION_CONFIG is None:
        raise RuntimeError(
            "no pytest session recorded; tests/conftest.py's "
            "pytest_collection_modifyitems calls record_session"
        )
    return _SESSION_CONFIG


def collected_nodes() -> Mapping[str, CollectedNode]:
    """The node set this session collected, read from its one home."""
    return _session().stash[COLLECTED_NODES]


def full_session() -> bool:
    """Whether this session collected everything, per ``conftest``'s answer."""
    return _session().stash[FULL_SESSION]


def read_repo_file(path: str) -> str:
    """The ``read_source`` seam in life: one repository-relative posix path."""
    return (ROOT / path).read_text(encoding="utf-8")


def live_context() -> ResolverContext:
    """The production seams — real importlib, real file reads, the stashed nodes.

    The only zero-argument constructor; every mutation test builds its own.
    A fresh record every call, so nothing here can answer one mutation with
    another mutation's tree.
    """
    return ResolverContext(
        importer=importlib.import_module,
        read_source=read_repo_file,
        nodes=collected_nodes(),
    )


def node_facts(items: Iterable[object]) -> dict[str, CollectedNode]:
    """The only place a pytest ``Item`` becomes a :class:`CollectedNode`.

    ``iter_markers`` walks the function, its class and its module, so a
    ``pytestmark`` skip declared three levels up is already in ``markers``.
    Duplicate ids are counted rather than collapsed, because the count is
    what rule 1 asks about.
    """
    facts: dict[str, CollectedNode] = {}
    for item in items:
        node_id = getattr(item, "nodeid", "")
        if not node_id:
            continue
        markers = {
            marker.name for marker in getattr(item, "iter_markers", lambda: ())()
        }
        fixtures = set(getattr(item, "fixturenames", ()))
        seen = facts.get(node_id)
        facts[node_id] = CollectedNode.from_node_id(
            node_id,
            markers=markers,
            fixtures=fixtures,
            occurrences=1 if seen is None else seen.occurrences + 1,
        )
    return facts


# ── node ids and the syntax underneath them ───────────────────────────────


def split_node_id(node_id: str) -> tuple[str, tuple[str, ...], str, str]:
    """A node id as ``(module path, class parts, function, parametrization)``."""
    module_path, _, remainder = node_id.partition("::")
    parts = [part for part in remainder.split("::") if part] if remainder else []
    last = parts[-1] if parts else ""
    name, bracket, argument = last.partition("[")
    return (
        module_path,
        tuple(parts[:-1]),
        name,
        f"[{argument}" if bracket else "",
    )


def _mark_name(node: ast.AST) -> str | None:
    """The mark a decorator expression names, or ``None`` if it names none."""
    if isinstance(node, ast.Call):
        return _mark_name(node.func)
    if isinstance(node, ast.Attribute):
        owner = node.value
        if isinstance(owner, ast.Attribute) and owner.attr == "mark":
            return node.attr
        if isinstance(owner, ast.Name) and owner.id == "mark":
            return node.attr
    return None


def _mark_names(node: ast.AST) -> frozenset[str]:
    """Every mark an expression names, unwrapping a list or tuple of them."""
    if isinstance(node, (ast.List, ast.Tuple)):
        found: set[str] = set()
        for element in node.elts:
            found |= _mark_names(element)
        return frozenset(found)
    name = _mark_name(node)
    return frozenset({name}) if name else frozenset()


def _pytestmark_marks(body: Iterable[ast.stmt]) -> frozenset[str]:
    """The marks a ``pytestmark`` assignment in this body declares."""
    found: set[str] = set()
    for statement in body:
        targets: list[ast.expr] = []
        if isinstance(statement, ast.Assign):
            targets = list(statement.targets)
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
        names = {target.id for target in targets if isinstance(target, ast.Name)}
        if "pytestmark" in names and statement.value is not None:
            found |= _mark_names(statement.value)
    return frozenset(found)


def _locate_function(
    tree: ast.Module, parents: tuple[str, ...], name: str
) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef | None, frozenset[str]]:
    """The function a node id names, plus every mark in force above it."""
    marks = set(_pytestmark_marks(tree.body))
    body: list[ast.stmt] = list(tree.body)
    for parent in parents:
        found = next(
            (
                statement
                for statement in body
                if isinstance(statement, ast.ClassDef) and statement.name == parent
            ),
            None,
        )
        if found is None:
            return None, frozenset(marks)
        for decorator in found.decorator_list:
            marks |= _mark_names(decorator)
        marks |= _pytestmark_marks(found.body)
        body = list(found.body)
    function = next(
        (
            statement
            for statement in body
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
            and statement.name == name
        ),
        None,
    )
    if function is not None:
        for decorator in function.decorator_list:
            marks |= _mark_names(decorator)
    return function, frozenset(marks)


def _is_fixture_decorator(node: ast.AST) -> bool:
    """Whether a decorator expression is ``pytest.fixture`` in any spelling."""
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute):
        return target.attr == "fixture"
    return isinstance(target, ast.Name) and target.id == "fixture"


def _fixture_defs(
    tree: ast.Module,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every ``@pytest.fixture`` in a module, keyed by the name it registers."""
    found: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        registered: str | None = None
        for decorator in node.decorator_list:
            if not _is_fixture_decorator(decorator):
                continue
            registered = node.name
            if isinstance(decorator, ast.Call):
                for keyword in decorator.keywords:
                    if keyword.arg == "name" and isinstance(
                        keyword.value, ast.Constant
                    ):
                        registered = str(keyword.value.value)
        if registered is not None:
            found[registered] = node
    return found


def _skip_calls_in(function: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    """The ``pytest.skip`` / ``pytest.importorskip`` calls inside one body."""
    found: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Attribute) and target.attr in _SKIP_CALLS:
            found.add(f"pytest.{target.attr}")
        elif isinstance(target, ast.Name) and target.id in _SKIP_CALLS:
            found.add(target.id)
    return frozenset(found)


def _conftest_candidates(module_path: str) -> tuple[str, ...]:
    """Where a module's ``conftest.py`` files would be, root-most first.

    Candidates, never a directory listing: whether one exists is a question
    for the ``read_source`` seam, and a ``Path.is_file`` here would be a read
    the mutation harness could not replace.
    """
    directory = Path(module_path).parent
    directories = [directory, *directory.parents]
    return tuple(
        (candidate / "conftest.py").as_posix().removeprefix("./")
        for candidate in reversed(directories)
    )


def _fixture_sources(
    ctx: ResolverContext, module_path: str
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Fixture definitions visible to a test module: its conftests, then its own."""
    visible: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for path in (*_conftest_candidates(module_path), module_path):
        try:
            text = ctx.read_source(path)
        except OSError:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        visible.update(_fixture_defs(tree))
    return visible


def _declared_closure(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    visible: Mapping[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> frozenset[str]:
    """The fixture closure a filtered session can derive from source alone.

    Collection computes the real closure; without it the parameter names of
    the test and, transitively, of every fixture it reaches are the weaker
    fact that stands in for it.
    """
    pending = [argument.arg for argument in function.args.args]
    closure: set[str] = set()
    while pending:
        name = pending.pop()
        if name in closure:
            continue
        closure.add(name)
        fixture = visible.get(name)
        if fixture is not None:
            pending.extend(argument.arg for argument in fixture.args.args)
    return frozenset(closure)


def _closure_skip_report(
    closure: Iterable[str],
    visible: Mapping[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> tuple[tuple[str, ...], frozenset[str]]:
    """Rule 4 over a fixture closure: its failures and what it could not read."""
    failures: list[str] = []
    unscanned: set[str] = set()
    for name in sorted(closure):
        if name in _BUILTIN_FIXTURES:
            continue
        fixture = visible.get(name)
        if fixture is None:
            unscanned.add(name)
            continue
        calls = _skip_calls_in(fixture)
        if calls:
            failures.append(
                f"fixture {name!r} in its closure calls {sorted(calls)}; the "
                "node can report green without executing its assertions"
            )
    return tuple(failures), frozenset(unscanned)


@dataclass(frozen=True, slots=True)
class _SourceScan:
    """What a node's own source says about it, whichever tier asked.

    ``found`` is false when the file or the function is missing, and then
    ``failures`` holds the one line saying which; the marks and the closure
    report are meaningless in that case and are empty.
    """

    found: bool
    marks: frozenset[str]
    failures: tuple[str, ...]
    unscanned: frozenset[str]


def _scan_source(
    ctx: ResolverContext,
    module_path: str,
    parents: tuple[str, ...],
    name: str,
    *,
    closure: frozenset[str] | None,
) -> _SourceScan:
    """Read one node out of the tree: its marks, its skips, its unread fixtures.

    ``closure`` is the set collection computed, or ``None`` when nothing
    collected this node and the parameter names in the source have to stand
    in for it.  Both tiers share this pass, so a skip call cannot be caught
    by one of them and missed by the other.
    """
    try:
        text = ctx.read_source(module_path)
    except OSError:
        return _SourceScan(
            found=False,
            marks=frozenset(),
            failures=(f"names {module_path!r}, which this tree does not have",),
            unscanned=frozenset(),
        )
    function, marks = _locate_function(ast.parse(text), parents, name)
    if function is None:
        located = "::".join((*parents, name))
        return _SourceScan(
            found=False,
            marks=frozenset(),
            failures=(f"names {located!r}, which {module_path} does not define",),
            unscanned=frozenset(),
        )
    failures: list[str] = []
    calls = _skip_calls_in(function)
    if calls:
        failures.append(
            f"its body calls {sorted(calls)}; the node can report green "
            "without executing its assertions"
        )
    visible = _fixture_sources(ctx, module_path)
    resolved_closure = (
        _declared_closure(function, visible) if closure is None else frozenset(closure)
    )
    closure_failures, unscanned = _closure_skip_report(resolved_closure, visible)
    return _SourceScan(
        found=True,
        marks=marks,
        failures=(*failures, *closure_failures),
        unscanned=unscanned,
    )


# ── the five TestRef rules ────────────────────────────────────────────────


def _marker_failures(marks: frozenset[str]) -> tuple[str, ...]:
    """Rules 2 and 3: no skip or skipif at any level, no xfail in any form."""
    failures: list[str] = []
    skipping = sorted(marks & _SKIP_MARKS)
    if skipping:
        failures.append(f"carries the {skipping} marker; a skipped node backs no claim")
    if marks & _XFAIL_MARKS:
        failures.append(
            "carries the xfail marker, strict or not; a node expected to fail "
            "cannot be evidence that something works"
        )
    return tuple(failures)


def _full_session_verdict(ref: TestRef, ctx: ResolverContext) -> TestRefVerdict:
    """The four rules answered by the collected node set.

    Rule 1 is at its full strength only here: exactly one collected node,
    duplicates counted rather than collapsed.  Rules 2 and 3 read the markers
    pytest resolved, so a ``pytestmark`` three levels up is already in them.
    """
    node = ctx.nodes.get(ref.node_id)
    if node is None:
        return TestRefVerdict(
            node_id=ref.node_id,
            tier="full_session",
            failures=("names no collected node",),
            unscanned_fixtures=frozenset(),
        )
    failures: list[str] = []
    if node.occurrences != 1:
        failures.append(
            f"resolves to {node.occurrences} collected nodes; a duplicated id "
            "backs whichever of them ran"
        )
    failures.extend(_marker_failures(node.markers))
    scan = _scan_source(
        ctx,
        node.module_path,
        node.parents,
        node.function_name,
        closure=node.fixtures,
    )
    failures.extend(scan.failures)
    return TestRefVerdict(
        node_id=ref.node_id,
        tier="full_session",
        failures=tuple(failures),
        unscanned_fixtures=scan.unscanned,
    )


def _resolution_verdict(ref: TestRef, ctx: ResolverContext) -> TestRefVerdict:
    """The same rules, proved by source scan when collection was filtered.

    It is weaker in exactly one way and says so: with no collected set it
    cannot know how many nodes an id resolves to, so duplicate detection is
    the full-session tier's alone.  Everything else — the file, the function,
    every marker in force, and every skip call in the body or in the fixture
    closure the parameter names describe — is in the source, which a ``-k``
    expression cannot change.  A dangling ``TestRef`` therefore still fails
    under a filter, which is the whole point of not skipping.
    """
    module_path, parents, name, _ = split_node_id(ref.node_id)
    scan = _scan_source(ctx, module_path, parents, name, closure=None)
    failures = (
        list(scan.failures)
        if not scan.found
        else [*_marker_failures(scan.marks), *scan.failures]
    )
    return TestRefVerdict(
        node_id=ref.node_id,
        tier="resolution",
        failures=tuple(failures),
        unscanned_fixtures=scan.unscanned,
    )


def test_ref_verdict(
    ref: TestRef, ctx: ResolverContext, *, full_session: bool
) -> TestRefVerdict:
    """The four skip/xfail rules; downgrades to a source-defined check when filtered."""
    if full_session:
        return _full_session_verdict(ref, ctx)
    return _resolution_verdict(ref, ctx)


def relevance_tokens(claim: Claim) -> tuple[str, ...]:
    """The strings a ``TestRef`` must mention for rule 5 — the claim's own.

    The subject, every ``Symbol`` path and its final segment, every literal
    fragment of a ``PacketSource`` between its ``{}`` slots, and both halves
    of an ``EffectKey``.  Tokens shorter than four characters are dropped:
    a claim whose only strings are that short cannot establish relevance,
    and a rule that always passes backs everything.
    """
    tokens: set[str] = {claim.subject}
    for member in claim.evidence:
        if isinstance(member, Symbol):
            tokens.add(member.path)
            tokens.add(member.path.rsplit(".", 1)[-1])
        elif isinstance(member, PacketSource):
            tokens.update(member.source.split("{}"))
        elif isinstance(member, EffectKey):
            tokens.update((member.item, member.key))
    return tuple(
        sorted(
            token.strip()
            for token in tokens
            if len(token.strip()) >= _MIN_RELEVANCE_TOKEN
        )
    )


def relevance_failure(ref: TestRef, claim: Claim, ctx: ResolverContext) -> str | None:
    """Rule 5: the node has to be *about* the claim, or it backs everything.

    ``tests/test_smoke.py::test_imports`` resolves, is unskipped and is
    unxfailed, and would otherwise discharge every claim in the table.  The
    node is about the claim when its module text or its parametrization id
    carries one of the claim's own strings.
    """
    tokens = relevance_tokens(claim)
    if not tokens:
        return (
            "carries no string long enough to establish relevance; the claim "
            "names nothing a test could mention"
        )
    module_path, _, _, parametrization = split_node_id(ref.node_id)
    node = ctx.nodes.get(ref.node_id)
    if node is not None:
        parametrization = node.parametrization
    haystacks = [parametrization.lower()]
    with contextlib.suppress(OSError):
        haystacks.append(ctx.read_source(module_path).lower())
    if any(token.lower() in haystack for token in tokens for haystack in haystacks):
        return None
    return (
        f"mentions none of the claim's strings {list(tokens)} in its module "
        "text or its parametrization id; a node that is not about the claim "
        "backs every claim"
    )


def resolve_test_ref(
    ref: TestRef, claim: Claim, ctx: ResolverContext, *, full_session: bool
) -> None:
    """All five ``TestRef`` rules, raising :class:`EvidenceUnresolved` on any.

    The fifth rule needs the whole claim rather than only its name, which is
    why this door takes a :class:`Claim`: relevance is a comparison against
    the claim's own subject and evidence strings, and a message parameter
    could not carry them.
    """
    verdict = test_ref_verdict(ref, ctx, full_session=full_session)
    failures = list(verdict.failures)
    irrelevant = relevance_failure(ref, claim, ctx)
    if irrelevant is not None:
        failures.append(irrelevant)
    if failures:
        raise EvidenceUnresolved(
            claim=claim_name(claim),
            evidence=ref,
            detail=f"{ref.node_id} " + "; ".join(failures),
        )


# ── the package, read through the seams ───────────────────────────────────

# Every ``Symbol`` path, every registry and every handler qualname a claim
# names is written relative to the package: ``damage._apply_command_amp``,
# not ``src.calculator.damage._apply_command_amp``.  The prefix is spelled
# once here rather than in nine evidence members' worth of strings.
PACKAGE = "src.calculator"
PACKAGE_ROOT = "src/calculator"

# The committed full-entry audit a ``SourceRef`` cites.  It is a repository
# path read through the ``read_source`` seam, never an import: the receipt is
# evidence about what was reviewed, and a test that reached it any other way
# could not be handed a different one.
FULL_ENTRY_AUDIT = "docs/wiki-full-entry-audit.json"

# Which module owns each registry an ``EffectKey`` may name.  Three of the
# four live together and the runes one does not, which is exactly why the
# member carries the registry name rather than a dotted path — a claim says
# *which* registry holds the number, and this table is the only place that
# turns the answer into a module (D-46's three plus ``ITEM_INPUT_OPTIONS``).
REGISTRY_MODULES: Mapping[str, str] = {
    "ITEM_EFFECTS": "item_effects",
    "ALLY_ITEM_EFFECTS": "item_effects",
    "ITEM_INPUT_OPTIONS": "item_effects",
    "RUNE_EFFECTS": "rune_effects",
}

# A bounded ``ITEM_INPUT_OPTIONS`` control declares all four: a type, a
# default, and the two ends it may not leave.  "Bounded" is the whole content
# of the claim ``modeled_state`` makes about a control, so an option missing
# an end is an unbounded input wearing a schema.
_OPTION_BOUNDS: frozenset[str] = frozenset({"type", "default", "min", "max"})
_OPTION_TYPES: frozenset[str] = frozenset({"int", "float"})


def module_path_of(dotted: str) -> str:
    """The repository path of a package-relative module name."""
    return f"{PACKAGE_ROOT}/{dotted.replace('.', '/')}.py"


def import_symbol(path: str, ctx: ResolverContext) -> tuple[str, object]:
    """Resolve a package-relative dotted path to its module and its object.

    The split between module and attribute is not knowable from the string —
    ``survival.transitions.trigger_defy`` is a two-segment module and one
    attribute, ``damage._apply_command_amp`` is one and one — so the longest
    importable prefix wins and the remainder is walked as attributes.

    Returns the module's package-relative name beside the object, because
    every caller that resolves a symbol also needs to know which file to read
    next: a packet source is proved against the module that builds it, and an
    effect tag against the module that dispatches on it.
    """
    segments = path.split(".")
    for cut in range(len(segments) - 1, 0, -1):
        name = ".".join(segments[:cut])
        try:
            module = ctx.importer(f"{PACKAGE}.{name}")
        except ImportError:
            continue
        found: object = module
        for attribute in segments[cut:]:
            try:
                found = getattr(found, attribute)
            except AttributeError as missing:
                raise LookupError(
                    f"{path!r} names no {attribute!r} in {PACKAGE}.{name}"
                ) from missing
        return name, found
    raise LookupError(f"{path!r} names no importable module under {PACKAGE}")


@dataclass(frozen=True, slots=True)
class PacketSite:
    """One call carrying ``source=``, reduced to what a claim is judged on.

    Attributes:
        source: the rendered ``source=`` argument; an f-string's interpolated
            parts collapse to bare ``{}`` slots.
        keywords: every keyword name the call passes.  ``owner`` is the one
            the campaign turns on — a dual-sided packet that stops declaring
            it is the incident's second failure layer — so the set is carried
            rather than a boolean about one of them.
    """

    source: str
    keywords: frozenset[str]


def render_source_argument(node: ast.AST) -> str | None:
    """Render one ``source=`` argument; f-strings collapse to ``{}`` slots.

    A constant renders verbatim.  A joined string renders its literal parts
    with a bare ``{}`` wherever a value is interpolated, which is the shape a
    ``PacketSource`` member is authored in — a member spelling ``{item}``
    could never match, so the load tier rejects it on sight.  Anything else
    renders ``None``: a source built by a call or a name is not a literal any
    declaration can quote.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        rendered: list[str] = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                rendered.append(part.value)
            elif isinstance(part, ast.FormattedValue):
                rendered.append("{}")
            else:
                return None
        return "".join(rendered)
    return None


def packet_sites(module_text: str) -> tuple[PacketSite, ...]:
    """Every call carrying ``source=``, with its keyword-name set.

    Measured 29 in ``item_support_effects.py``; the measurement, not a pinned
    integer, is the contract, and Phase 3's producer count is derived from it
    (the length of the distinct ``source`` set).  A call whose source is not a
    literal is skipped rather than reported: it is unquotable evidence, not a
    broken site.
    """
    sites: list[PacketSite] = []
    for node in ast.walk(ast.parse(module_text)):
        if not isinstance(node, ast.Call):
            continue
        keywords = {keyword.arg for keyword in node.keywords if keyword.arg}
        if "source" not in keywords:
            continue
        argument = next(
            (keyword.value for keyword in node.keywords if keyword.arg == "source"),
            None,
        )
        rendered = render_source_argument(argument) if argument is not None else None
        if rendered is not None:
            sites.append(PacketSite(source=rendered, keywords=frozenset(keywords)))
    return tuple(sites)


# The separator every ``_packet`` source is built with.  A literal is spelled
# ``"<Holder> — <Effect>"``, which is what lets a holder's frontier key stand
# for the packets that holder emits without a second hand list saying so.
PACKET_SOURCE_SEPARATOR = " — "


def unquoted_packet_sources(
    claims: Mapping[Any, Claim], frontier: Mapping[str, str], module_text: str
) -> tuple[str, ...]:
    """Every walk-packet literal the corpus neither quotes nor withholds.

    :class:`PacketSource` proves one direction — that the builder a claim
    names really emits the packet the claim quotes.  Nothing proved the
    other: a packet the builder emits that *no* claim quotes owed no
    evidence at all, so a second packet added to an already-claimed item
    would enter the walk with nobody noticing.  That is this phase's own
    failure shape, surviving inside its own evidence union, and this is the
    direction that closes it.

    A literal is accounted for in exactly two ways.  **Quoted**: some claim
    carries it as a ``PacketSource``.  **Withheld**: ``FRONTIER`` names it,
    either through its own ``packet:<source>`` key or through the
    ``item:<holder>@support_packet`` key of the holder whose packet it is —
    a holder with no claim at all cannot be asked to quote one, and
    :data:`PACKET_SOURCE_SEPARATOR` is what makes "whose packet it is" a
    derivation rather than a second hand list.  A source whose holder
    collapses to an f-string ``{}`` slot names no holder and is therefore
    only ever quotable, which is why ``World Atlas`` quotes both of its.

    Reported literals are sorted and the empty tuple is the pass condition.
    """
    quoted = {
        evidence.source
        for claim in claims.values()
        for evidence in claim.evidence
        if isinstance(evidence, PacketSource)
    }
    withheld_holders = tuple(
        key.removeprefix("item:").removesuffix("@support_packet")
        for key in frontier
        if key.startswith("item:") and key.endswith("@support_packet")
    )
    unquoted = set()
    for source in {site.source for site in packet_sites(module_text)}:
        if source in quoted or f"packet:{source}" in frontier:
            continue
        prefixes = (f"{holder}{PACKET_SOURCE_SEPARATOR}" for holder in withheld_holders)
        if not any(source.startswith(prefix) for prefix in prefixes):
            unquoted.add(source)
    return tuple(sorted(unquoted))


def tag_dispatch_branches(module_text: str, qualname: str) -> frozenset[str]:
    """The effect tags a handler actually branches on — ``EffectTag``'s oracle.

    ``qualname`` is package-relative and its last segment names the function;
    every string constant inside that function's body is a candidate branch,
    which is what the live dispatch ladder is made of.  Reading the constants
    rather than the ``==`` comparisons is deliberate: the ladder mixes
    equality tests with set membership, and a rule that understood only one
    spelling would report a live tag as dead.
    """
    wanted = qualname.rsplit(".", 1)[-1]
    tree = ast.parse(module_text)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != wanted:
            continue
        return frozenset(
            inner.value
            for inner in ast.walk(node)
            if isinstance(inner, ast.Constant) and isinstance(inner.value, str)
        )
    return frozenset()


def audit_entries(ctx: ResolverContext) -> tuple[Mapping[str, Any], ...]:
    """The committed full-entry audit's item entries, read through the seam.

    Built fresh on every call.  ``resolve_table`` builds it once and hands it
    down, because one table resolves a hundred ``SourceRef`` members against
    one three-megabyte receipt; a module-level memo would do the same job and
    would also answer the next mutation with this tree.
    """
    try:
        text = ctx.read_source(FULL_ENTRY_AUDIT)
    except OSError:
        return ()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ()
    return tuple(
        entry
        for entry in payload.get("entries", ())
        if isinstance(entry, Mapping) and entry.get("kind") == "item"
    )


# ── the eight remaining evidence kinds ────────────────────────────────────


def _unresolved(claim: Claim, evidence: object, detail: str) -> EvidenceUnresolved:
    """One failure, naming the claim and the member that produced it."""
    return EvidenceUnresolved(claim=claim_name(claim), evidence=evidence, detail=detail)


def resolve_symbol(symbol: Symbol, claim: Claim, ctx: ResolverContext) -> None:
    """The dotted path names something this tree actually defines.

    This is M1's and M2's tripwire: renaming the pair-engine effect accessor
    or deleting the pair-side pricer leaves a claim naming a path that no
    longer resolves, and the evidence fails rather than the prose surviving.
    """
    try:
        import_symbol(symbol.path, ctx)
    except LookupError as missing:
        raise _unresolved(claim, symbol, str(missing)) from missing


def _builder_modules(claim: Claim, ctx: ResolverContext) -> tuple[str, ...]:
    """The modules a claim's packet-building Symbols name."""
    modules: list[str] = []
    for member in claim.evidence:
        if not isinstance(member, Symbol) or member.role != "walk_packet_builder":
            continue
        try:
            module, _ = import_symbol(member.path, ctx)
        except LookupError:
            continue
        if module not in modules:
            modules.append(module)
    return tuple(modules)


def resolve_packet_source(
    packet: PacketSource, claim: Claim, ctx: ResolverContext
) -> None:
    """The ``source=`` literal is built by the module the claim names.

    A packet source is proved against the builder the same claim points at,
    never against a repository-wide scan: "this string exists somewhere in
    ``src/``" is satisfied by a comment, and the member is supposed to say
    that *this* producer emits *this* receipt.  So a claim carrying a
    ``PacketSource`` and no ``walk_packet_builder`` Symbol is unresolved for
    that reason alone — M3's shape, where the packet literal is removed and
    nothing else changes.
    """
    modules = _builder_modules(claim, ctx)
    if not modules:
        raise _unresolved(
            claim,
            packet,
            f"{packet.source!r} names no builder; a packet source is proved "
            "against the walk_packet_builder Symbol on its own claim",
        )
    for module in modules:
        try:
            text = ctx.read_source(module_path_of(module))
        except OSError:
            continue
        if any(site.source == packet.source for site in packet_sites(text)):
            return
    raise _unresolved(
        claim,
        packet,
        f"{packet.source!r} is not a source= argument in "
        f"{', '.join(module_path_of(module) for module in modules)}",
    )


def _owner_declaring_sites(
    claim: Claim, ctx: ResolverContext, source: str
) -> tuple[bool, bool]:
    """Whether the named packet exists, and whether it declares ``owner=``."""
    found = declares_owner = False
    for module in _builder_modules(claim, ctx):
        try:
            text = ctx.read_source(module_path_of(module))
        except OSError:
            continue
        for site in packet_sites(text):
            if site.source != source:
                continue
            found = True
            declares_owner = declares_owner or "owner" in site.keywords
    return found, declares_owner


# The two authorities that describe a mechanic with two declared halves.
# ``SPLIT`` says the halves are disjoint and the walk skips the holder;
# ``COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW`` says the walk owns the number
# and the pair half is a preview of it.  ``COUPLED_ONLY`` is deliberately not
# here: it names a second engine that has no pricer at all, so there is no
# second half for a dual-sided claim to point at.
_DUAL_SIDED_AUTHORITIES = frozenset(
    {"SPLIT", "COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW"}
)


def resolve_paired_sides(
    sides: PairedSides, claim: Claim, ctx: ResolverContext
) -> None:
    """Both engine halves exist, pair back, and the handshake is declared.

    The incident shipped with one half present and a hand list that agreed
    with it, so nothing here reads a name list: the capability registry is the
    authority, ``pair_of`` has to name a capability on the *other* engine
    owned by the same holder, and exactly one walk half may claim that pair
    half — the back edge, which the pair half cannot carry itself because
    ``pair_of`` is required only where ``pairing is PAIRED``.

    Two authorities describe a mechanic with two declared halves, and both
    are accepted here: ``SPLIT``, where the halves are disjoint and the walk
    skips the holder, and ``COUPLED_AUTHORITATIVE_WITH_PAIR_PREVIEW``, where
    the walk owns the number and the pair half survives as a declared
    preview.  Which of the two a claim describes is not free — the
    ``owner_policy`` below is checked against the packet's own ``owner=``,
    so a claim that named the wrong shape still fails.
    """
    capabilities = _capabilities(sides, claim, ctx)
    walk = capabilities.get(sides.mechanic)
    if walk is None:
        raise _unresolved(
            claim, sides, f"{sides.mechanic!r} is not a declared capability"
        )
    if walk.authority.name not in _DUAL_SIDED_AUTHORITIES:
        raise _unresolved(
            claim,
            sides,
            f"{sides.mechanic} declares authority {walk.authority.name}, which "
            "names no second engine; a dual-sided claim may not describe a "
            "single-engine mechanic",
        )
    if walk.pair_of is None:
        raise _unresolved(
            claim, sides, f"{sides.mechanic} declares no pair_of; one half is missing"
        )
    pair = capabilities.get(walk.pair_of)
    if pair is None:
        raise _unresolved(
            claim, sides, f"{walk.pair_of!r} is not a declared capability"
        )
    _resolve_pair_half(sides, claim, walk, pair, capabilities)
    for half in (walk, pair):
        try:
            import_symbol(half.impl, ctx)
        except LookupError as missing:
            raise _unresolved(
                claim, sides, f"{half.mechanic} implements {missing}"
            ) from missing
    _resolve_owner_policy(sides, claim, ctx, walk)


def _capabilities(
    sides: PairedSides, claim: Claim, ctx: ResolverContext
) -> Mapping[str, Any]:
    """Phase 2's capability registry, through the importer seam."""
    try:
        trigger_stream = ctx.importer(f"{PACKAGE}.trigger_stream")
    except ImportError as missing:
        raise _unresolved(claim, sides, "trigger_stream does not import") from missing
    return getattr(trigger_stream, "CAPABILITIES", {})


def _resolve_pair_half(
    sides: PairedSides,
    claim: Claim,
    walk: Any,
    pair: Any,
    capabilities: Mapping[str, Any],
) -> None:
    """The pair half is the other engine's, the same holder's, and only ours."""
    if pair.authority.name not in _DUAL_SIDED_AUTHORITIES:
        raise _unresolved(
            claim,
            sides,
            f"{walk.pair_of} declares authority {pair.authority.name}, which "
            "names no second engine",
        )
    if pair.authority.name != walk.authority.name:
        raise _unresolved(
            claim,
            sides,
            f"{sides.mechanic} declares {walk.authority.name} and "
            f"{walk.pair_of} declares {pair.authority.name}; one mechanic has "
            "one authority, and two halves disagreeing about it is the "
            "divergence this campaign retired",
        )
    if pair.engine is walk.engine:
        raise _unresolved(
            claim,
            sides,
            f"{sides.mechanic} and {walk.pair_of} are both on "
            f"{walk.engine.name}; a split mechanic has one half per engine",
        )
    if pair.owner != walk.owner:
        raise _unresolved(
            claim,
            sides,
            f"{sides.mechanic} is owned by {walk.owner} and {walk.pair_of} by "
            f"{pair.owner}; the two halves price one holder's mechanic",
        )
    back = sorted(
        key
        for key, capability in capabilities.items()
        if capability.pair_of == walk.pair_of
    )
    if back != [sides.mechanic]:
        raise _unresolved(
            claim,
            sides,
            f"{walk.pair_of} is paired back by {back}, not by "
            f"{sides.mechanic} alone",
        )


def _resolve_owner_policy(
    sides: PairedSides, claim: Claim, ctx: ResolverContext, walk: Any
) -> None:
    """The declared handshake against the packet the walk half emits.

    ``owner_skips_holder`` is the only policy that shows up in the source as
    something a reader can point at: the walk packet carries ``owner=``, and
    the walk skips that participant because the holder's own engine prices it.
    The other two policies say the opposite — no owner keyword — so the check
    is one comparison, and M4, dropping ``owner=`` from a dual-sided packet,
    fails it.
    """
    if walk.packet_source is None:
        raise _unresolved(
            claim,
            sides,
            f"{sides.mechanic} declares no packet_source; the walk half of a "
            "split mechanic emits the packet the owner policy is about",
        )
    found, declares_owner = _owner_declaring_sites(claim, ctx, walk.packet_source)
    if not found:
        raise _unresolved(
            claim,
            sides,
            f"{walk.packet_source!r} is emitted by no site in the claim's "
            "builder module",
        )
    wanted = sides.owner_policy == "owner_skips_holder"
    if declares_owner is not wanted:
        raise _unresolved(
            claim,
            sides,
            f"policy {sides.owner_policy!r} expects the {walk.packet_source!r} "
            f"packet {'to' if wanted else 'not to'} declare owner=, and it "
            f"{'does not' if wanted else 'does'}",
        )


def resolve_effect_key(key: EffectKey, claim: Claim, ctx: ResolverContext) -> None:
    """The registry holds this holder, and the holder holds this key.

    The number itself is never quoted (CLAUDE.md rule 5), so the resolution is
    exactly membership: the key exists, and the value it names is left to the
    accessor that reads it.
    """
    module = REGISTRY_MODULES[key.registry]
    try:
        registry = getattr(ctx.importer(f"{PACKAGE}.{module}"), key.registry)
    except (ImportError, AttributeError) as missing:
        raise _unresolved(
            claim, key, f"{module}.{key.registry} does not resolve"
        ) from missing
    entry = registry.get(key.item)
    if entry is None:
        raise _unresolved(claim, key, f"{key.registry} has no {key.item!r} entry")
    if key.key not in entry:
        raise _unresolved(
            claim, key, f"{key.registry}[{key.item!r}] has no {key.key!r} key"
        )


def resolve_effect_tag(tag: EffectTag, claim: Claim, ctx: ResolverContext) -> None:
    """The tag is a known effect type and the named handler branches on it.

    Both halves are the claim: a tag with no handler is a data label nothing
    reads, which is the state ten of the thirty-eight are in and the reason
    they sit on the frontier naming H4 instead of carrying this member.
    """
    try:
        known = ctx.importer(f"{PACKAGE}.item_effects")._KNOWN_EFFECT_TYPES
    except (ImportError, AttributeError) as missing:
        raise _unresolved(
            claim, tag, "item_effects._KNOWN_EFFECT_TYPES does not resolve"
        ) from missing
    if tag.tag not in known:
        raise _unresolved(
            claim, tag, f"{tag.tag!r} is not an item_effects._KNOWN_EFFECT_TYPES member"
        )
    try:
        module, _ = import_symbol(tag.handler, ctx)
    except LookupError as missing:
        raise _unresolved(claim, tag, str(missing)) from missing
    try:
        text = ctx.read_source(module_path_of(module))
    except OSError as missing:
        raise _unresolved(
            claim, tag, f"{module_path_of(module)} is not readable"
        ) from missing
    if tag.tag not in tag_dispatch_branches(text, tag.handler):
        raise _unresolved(
            claim,
            tag,
            f"{tag.handler} does not branch on {tag.tag!r}; the tag is declared "
            "and nothing reads it",
        )


def resolve_option_schema(
    option: OptionSchema, claim: Claim, ctx: ResolverContext
) -> None:
    """The control exists and is bounded at both ends.

    ``modeled_state`` says the item's state is supplied rather than assumed,
    and an input with no ceiling is an assumption with a form field in front
    of it.
    """
    try:
        options = ctx.importer(f"{PACKAGE}.item_effects").ITEM_INPUT_OPTIONS
    except (ImportError, AttributeError) as missing:
        raise _unresolved(
            claim, option, "item_effects.ITEM_INPUT_OPTIONS does not resolve"
        ) from missing
    control = options.get(option.item, {}).get("options", {}).get(option.option)
    if control is None:
        raise _unresolved(
            claim,
            option,
            f"ITEM_INPUT_OPTIONS[{option.item!r}] declares no {option.option!r} "
            "control",
        )
    missing_bounds = _OPTION_BOUNDS - set(control)
    if missing_bounds:
        raise _unresolved(
            claim,
            option,
            f"control {option.option!r} is missing {sorted(missing_bounds)}; an "
            "unbounded input is an assumption with a form field in front of it",
        )
    if control["type"] not in _OPTION_TYPES:
        raise _unresolved(
            claim,
            option,
            f"control {option.option!r} declares type {control['type']!r}, which "
            f"is not one of {sorted(_OPTION_TYPES)}",
        )
    if not control["min"] <= control["default"] <= control["max"]:
        raise _unresolved(
            claim,
            option,
            f"control {option.option!r} defaults to {control['default']} outside "
            f"[{control['min']}, {control['max']}]",
        )


def resolve_source_ref(
    source: SourceRef,
    claim: Claim,
    ctx: ResolverContext,
    entries: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    """The citation is an entry of the committed full-entry audit.

    The revision is what makes it reproducible, so url and revision are
    matched together: a url whose revision has moved on is a citation of a
    page that no longer says what the claim says it says.  For an **item**
    claim the entry additionally has to be that item's — a review of some
    other item is not a review of this one.
    """
    found = tuple(entries if entries is not None else audit_entries(ctx))
    if not found:
        raise _unresolved(
            claim, source, f"{FULL_ENTRY_AUDIT} holds no item entries to cite"
        )
    matches = [
        entry
        for entry in found
        if entry.get("source_url") == source.url
        and entry.get("revision_id") == source.revision_id
    ]
    if not matches:
        raise _unresolved(
            claim,
            source,
            f"{source.url} at revision {source.revision_id} is not an entry of "
            f"{FULL_ENTRY_AUDIT}",
        )
    if claim.subject_kind == "item" and all(
        entry.get("name") != claim.subject for entry in matches
    ):
        raise _unresolved(
            claim,
            source,
            f"{source.url} is the audit entry for "
            f"{sorted({str(entry.get('name')) for entry in matches})}, not for "
            f"{claim.subject!r}",
        )


def resolve_absence(absence: Absence, claim: Claim, ctx: ResolverContext) -> None:
    """A refusal's issue refs are the ones the tracker actually publishes.

    ``review_issue_refs`` is what the public payload hands a caller for a
    withheld item, so a claim that refuses to model something has to name the
    same issues the API does — otherwise the receipt in the declaration and
    the receipt on the wire disagree and neither is wrong on its own.
    """
    try:
        coverage = ctx.importer(f"{PACKAGE}.item_coverage")
    except ImportError as missing:
        raise _unresolved(claim, absence, "item_coverage does not import") from missing
    if claim.subject_kind == "item":
        published = tuple(coverage.review_issue_refs(claim.subject))
        if tuple(absence.issue_refs) != published:
            raise _unresolved(
                claim,
                absence,
                f"names issues {list(absence.issue_refs)} where the public "
                f"payload publishes {list(published)}",
            )
        return
    tracked = {40}
    for refs in getattr(coverage, "_REVIEW_ISSUE_REFS", {}).values():
        tracked |= set(refs)
    stray = sorted(set(absence.issue_refs) - tracked)
    if stray:
        raise _unresolved(
            claim, absence, f"names issues {stray}, which no item's refs track"
        )


# ── one dispatch over the nine kinds ──────────────────────────────────────

# The dispatch table, keyed by the evidence type itself.  It is a mapping
# rather than an if/elif ladder for one reason: totality is then a set
# comparison against ``EVIDENCE_TYPES`` that a test can run, and a tenth
# evidence kind that nobody wired up fails on the commit that adds it instead
# of silently resolving to nothing.
_RESOLVERS: Mapping[type, Callable[..., None]] = {
    Symbol: resolve_symbol,
    PacketSource: resolve_packet_source,
    PairedSides: resolve_paired_sides,
    EffectKey: resolve_effect_key,
    EffectTag: resolve_effect_tag,
    OptionSchema: resolve_option_schema,
    SourceRef: resolve_source_ref,
    Absence: resolve_absence,
}


def resolve(
    ev: object,
    claim: Claim,
    ctx: ResolverContext,
    *,
    full_session: bool = False,
    entries: Sequence[Mapping[str, Any]] | None = None,
) -> None:
    """Single dispatch over the nine kinds; raises EvidenceUnresolved naming both.

    It takes the whole :class:`Claim` rather than its name because three of
    the nine kinds are judged *against* the claim: a ``TestRef`` has to be
    about it (rule 5), a ``PacketSource`` is proved against the builder the
    same claim names, and a ``SourceRef`` on an item claim has to cite that
    item's audit entry.  ``entries`` is the parsed audit, passed down by
    :func:`resolve_table` so one table costs one read of a three-megabyte
    receipt; ``None`` means "read it yourself".
    """
    if isinstance(ev, TestRef):
        resolve_test_ref(ev, claim, ctx, full_session=full_session)
        return
    if isinstance(ev, SourceRef):
        resolve_source_ref(ev, claim, ctx, entries)
        return
    resolver = _RESOLVERS.get(type(ev))
    if resolver is None:
        raise _unresolved(
            claim, ev, "is not one of the nine evidence kinds this tier resolves"
        )
    resolver(ev, claim, ctx)


def resolve_table(
    claims: Mapping[tuple[str, str, str], Claim],
    ctx: ResolverContext,
    *,
    full_session: bool = False,
) -> list[EvidenceUnresolved]:
    """Collect-all, report-all — one run names every broken member, not the first.

    The first broken member of a two-hundred-claim table is a fact about
    alphabetical order, not about the tree; a table that names all of them is
    what makes a refactor's blast radius readable in one run.
    """
    entries = audit_entries(ctx)
    failures: list[EvidenceUnresolved] = []
    for claim in claims.values():
        for member in claim.evidence:
            try:
                resolve(member, claim, ctx, full_session=full_session, entries=entries)
            except EvidenceUnresolved as unresolved:
                failures.append(unresolved)
    return failures


# ── the classifier chain, walked ──────────────────────────────────────────


# ── front doors ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class MissingFrontDoor:
    """A production module that no test module imports.

    Attributes:
        module: the package-relative dotted name, ``survival.score_state``.
        path: the repository-relative posix path of that module.
    """

    module: str
    path: str


def imported_package_modules(module_text: str) -> frozenset[str]:
    """Every package-relative module name one file's imports name.

    The two rules :func:`front_door_report` is judged on are applied here:
    only ``Import`` and ``ImportFrom`` nodes contribute, and a package import
    contributes the package plus each name it binds — never the package's
    other submodules.  A bound name that is a symbol rather than a submodule
    is contributed too and is harmless, because the only names ever looked up
    in this set are modules the tree actually holds.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(module_text)):
        if isinstance(node, ast.Import):
            found.update(
                alias.name[len(PACKAGE) + 1 :]
                for alias in node.names
                if alias.name.startswith(f"{PACKAGE}.")
            )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level or (
                module != PACKAGE and not module.startswith(f"{PACKAGE}.")
            ):
                continue
            if module == PACKAGE:
                found.update(alias.name for alias in node.names)
                continue
            submodule = module[len(PACKAGE) + 1 :]
            found.add(submodule)
            found.update(f"{submodule}.{alias.name}" for alias in node.names)
    return frozenset(found)


def front_door_report(src_root: Path, test_root: Path) -> tuple[MissingFrontDoor, ...]:
    """Modules outside ``champions/`` that no test module imports (D-95).

    A front door is *a test module importing the production module's dotted
    path*.  Two rules decide the answer, and they live here rather than in a
    document because an earlier reading of this same frontier produced a
    different set with them unstated — a pin taken from that reading would
    have been wrong on its first run.

    **Import, not mention.**  Only an ``Import`` or ``ImportFrom`` node
    counts.  A module named in a string, a comment, a docstring or an
    ``importlib.import_module`` call is a mention: it tells a maintainer
    nothing about where the module's tests are, which is the whole content of
    the claim a front door makes.

    **Package, not submodule.**  ``from src.calculator.survival import X``
    imports the **package** ``survival`` and binds ``X`` out of it; it is a
    front door for ``survival.X`` only when ``X`` is that package's submodule,
    and never for ``survival``'s other submodules.  ``survival/__init__.py``
    is not in the denominator at all, so a package-only import backs nothing.

    The denominator is every ``*.py`` under *src_root* except ``__init__.py``.
    ``champions/`` is excluded by declaration: its front door is the
    per-champion module convention plus ``champions/module_contract``
    validation, and one test module per champion is a different contract from
    this one.

    The roots are parameters rather than seams: this is a survey of two trees,
    not the resolution of an evidence member, and a temporary directory is the
    injection a survey needs.
    """
    imported: set[str] = set()
    for path in sorted(test_root.rglob("*.py")):
        imported |= imported_package_modules(path.read_text(encoding="utf-8"))
    missing: list[MissingFrontDoor] = []
    for path in sorted(src_root.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        module = ".".join(path.relative_to(src_root).with_suffix("").parts)
        if module.startswith("champions.") or module in imported:
            continue
        missing.append(MissingFrontDoor(module=module, path=module_path_of(module)))
    return tuple(missing)
