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
import importlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest

from src.calculator.coverage_evidence import (
    Claim,
    EffectKey,
    PacketSource,
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
    try:
        haystacks.append(ctx.read_source(module_path).lower())
    except OSError:
        pass
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
