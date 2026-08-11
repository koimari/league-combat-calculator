"""The resolution and full-session tiers — the resolver, judged.

``coverage_evidence`` refuses a claim whose shape cannot be backed; this
suite is about the tier that asks whether the thing a claim names actually
exists here, and about the tier boundary itself.

Two properties of the boundary are what these tests exist for.  First, the
resolution tier runs on **every** ``pytest`` invocation, filtered or not, so
a dangling ``TestRef`` fails under ``-k`` exactly as it fails under a full
run — proved here by running the same refs through both tiers.  Second, a
filtered session does not *skip* the full-session checks.  ``pytest.skip``
prints green, and a tier that reports skipped reports nothing; the marked
checks are deselected, and a subprocess run is what proves it rather than a
sentence.

Almost every case is fabricated: a source text and a node set handed to the
resolver through its three seams.  That is the point of the seams — the
mutation harness needs to describe trees this repository does not have — and
the handful of live-tree cases at the end are what keep the fabrications
honest about the shape of a real one.
"""

import ast
import fnmatch
import subprocess
import sys
from pathlib import Path

import pytest

from src.calculator.coverage_evidence import (
    Claim,
    EffectKey,
    PacketSource,
    Symbol,
    TestRef,
    validate_claim,
)

# The resolver is imported as a module, never by name: ``test_ref_verdict``
# is a helper, and a ``test_``-prefixed name bound in a collected module is
# a test as far as pytest is concerned.
from tests import coverage_resolver
from tests.coverage_resolver import (
    FULL_SESSION_MARKER,
    CollectedNode,
    EvidenceUnresolved,
    ResolverContext,
    live_context,
    relevance_tokens,
    resolve_test_ref,
    split_node_id,
)

ROOT = Path(__file__).resolve().parents[1]
RESOLVER_PATH = ROOT / "tests" / "coverage_resolver.py"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "tests.yml"

FULL_SESSION_NODE = (
    "tests/test_coverage_claims.py::test_the_full_session_tier_sees_its_own_node"
)

# ── the fabricated tree ───────────────────────────────────────────────────

MANDATE_MODULE_PATH = "fake/test_mandate.py"
MANDATE_NODE = f"{MANDATE_MODULE_PATH}::test_command_prices_the_amp"

CLEAN_MODULE = '''"""Prices Imperial Mandate — Command."""

import pytest


@pytest.fixture
def priced_amp():
    return 0.07


def test_command_prices_the_amp(priced_amp):
    assert priced_amp > 0
'''

UNRELATED_MODULE = '''"""Nothing to do with any coverage claim."""


def test_command_prices_the_amp():
    assert True
'''


def _source(**overrides: str) -> dict[str, str]:
    """The fabricated tree, one path to one module text."""
    tree = {MANDATE_MODULE_PATH: CLEAN_MODULE}
    tree.update(overrides)
    return tree


def _context(
    sources: dict[str, str] | None = None,
    nodes: dict[str, CollectedNode] | None = None,
) -> ResolverContext:
    """A context over a fabricated tree; the importer is never expected to run."""
    tree = _source() if sources is None else sources

    def read_source(path: str) -> str:
        try:
            return tree[path]
        except KeyError as missing:
            raise FileNotFoundError(path) from missing

    def importer(name: str) -> object:
        raise AssertionError(f"the resolver imported {name!r} unasked")

    return ResolverContext(
        importer=importer, read_source=read_source, nodes=nodes or {}
    )


def _node(node_id: str = MANDATE_NODE, **facts) -> dict[str, CollectedNode]:
    """A one-entry collected node set."""
    return {node_id: CollectedNode.from_node_id(node_id, **facts)}


MANDATE_CLAIM = Claim(
    subject_kind="item",
    subject="Imperial Mandate",
    lane="support_packet",
    status="modeled_effect",
    evidence=(
        Symbol(
            path="item_support_effects.derive_item_support_effects",
            role="walk_packet_builder",
        ),
        PacketSource(source="Imperial Mandate — Command"),
        TestRef(node_id=MANDATE_NODE),
    ),
    dimensions=("damage_amplification",),
    issue_refs=(),
    unreachable_reason="",
)
MANDATE_REF = TestRef(node_id=MANDATE_NODE)

BOTH_TIERS = pytest.mark.parametrize("full_session", [False, True], ids=["-k", "full"])


def _verdict(ref: TestRef, ctx: ResolverContext, *, full_session: bool):
    """One ref through whichever tier the case is exercising."""
    return coverage_resolver.test_ref_verdict(ref, ctx, full_session=full_session)


# ── resolver topology ─────────────────────────────────────────────────────


def test_the_resolver_is_not_a_collectable_module(pytestconfig) -> None:
    """It matches none of pytest's ``python_files`` patterns, so it is a helper.

    The ruling is that the resolver is uncollected: a ``-k`` expression aimed
    at something else must not be able to remove the machinery the resolution
    tier runs on.
    """
    patterns = pytestconfig.getini("python_files")
    assert patterns, "pytest reported no python_files patterns to check against"
    assert not any(fnmatch.fnmatch(RESOLVER_PATH.name, pattern) for pattern in patterns)


def test_the_resolver_imports_only_coverage_evidence_from_the_package() -> None:
    """One production import, at module scope or anywhere else.

    Every other read is a seam.  A second package import would be a branch
    the mutation harness cannot replace, and it would resolve at import time
    — before any test could describe a different tree.
    """
    tree = ast.parse(RESOLVER_PATH.read_text(encoding="utf-8"))
    package_imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            package_imports.update(
                alias.name
                for alias in node.names
                if alias.name.startswith("src.calculator")
            )
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "the resolver declares no relative import"
            if (node.module or "").startswith("src.calculator"):
                package_imports.add(node.module or "")
    assert package_imports == {"src.calculator.coverage_evidence"}


def test_the_resolver_memoizes_nothing() -> None:
    """No cache decorator, and one rebindable module-level name.

    A memo would answer the second mutation with the first mutation's tree,
    which turns the whole mutation suite green by construction.  The one
    module-level name that is rebound is the session handle; the node set
    itself lives in ``config.stash``.
    """
    text = RESOLVER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(text)
    decorators = {
        ast.unparse(decorator)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
    }
    assert not any(
        "cache" in decorator or "memo" in decorator for decorator in decorators
    ), sorted(decorators)

    rebound = {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Global)
        for name in node.names
    }
    assert rebound == {"_SESSION_CONFIG"}
    assert "_SESSION_CONFIG: pytest.Config | None = None" in text


def test_every_filesystem_read_lives_behind_the_read_source_seam() -> None:
    """Only ``read_repo_file`` touches a real file; everything else asks the seam."""
    tree = ast.parse(RESOLVER_PATH.read_text(encoding="utf-8"))
    filesystem = {"read_text", "open", "is_file", "exists", "iterdir", "glob", "rglob"}
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name == "read_repo_file":
            continue
        used = {
            inner.attr for inner in ast.walk(node) if isinstance(inner, ast.Attribute)
        } | {inner.id for inner in ast.walk(node) if isinstance(inner, ast.Name)}
        offenders.extend(f"{node.name}: {call}" for call in sorted(used & filesystem))
    assert offenders == []


def test_live_context_is_built_fresh_from_the_stashed_node_set(pytestconfig) -> None:
    """The only zero-argument constructor, and it caches nothing between calls."""
    first = live_context()
    second = live_context()
    assert first is not second
    assert first.nodes is coverage_resolver.collected_nodes()
    assert first.nodes is pytestconfig.stash[coverage_resolver.COLLECTED_NODES]
    assert coverage_resolver.full_session() == (
        pytestconfig.stash[coverage_resolver.FULL_SESSION]
    )


def test_the_context_is_frozen_and_carries_exactly_three_seams() -> None:
    """Three seams, and no way to swap one after the fact."""
    ctx = _context()
    assert ResolverContext.__dataclass_fields__.keys() == {
        "importer",
        "read_source",
        "nodes",
    }
    with pytest.raises(AttributeError):
        ctx.nodes = {}  # type: ignore[misc]


def test_node_ids_split_into_the_parts_the_rules_read() -> None:
    """A parametrized method id is a path, a class chain, a name and an id."""
    assert split_node_id("tests/test_x.py::TestThing::test_case[Rylai's-3]") == (
        "tests/test_x.py",
        ("TestThing",),
        "test_case",
        "[Rylai's-3]",
    )
    assert split_node_id("tests/test_x.py::test_case") == (
        "tests/test_x.py",
        (),
        "test_case",
        "",
    )


# ── rule 1: the id resolves to exactly one collected node ─────────────────


def test_the_fabricated_claim_is_itself_well_formed() -> None:
    """The load tier accepts the claim these cases resolve, so a failure is the tier's."""
    validate_claim(MANDATE_CLAIM)


@BOTH_TIERS
def test_a_dangling_test_ref_fails_in_both_tiers(full_session: bool) -> None:
    """A node id naming no file fails filtered exactly as it fails whole.

    This is the criterion the whole tier boundary rests on: under ``-k`` the
    resolution tier still refuses a ``TestRef`` that names nothing.
    """
    ref = TestRef(node_id="fake/test_absent.py::test_gone")
    verdict = _verdict(ref, _context(nodes=_node()), full_session=full_session)
    assert not verdict.resolved
    assert verdict.tier == ("full_session" if full_session else "resolution")


def test_a_ref_naming_a_function_the_module_lacks_fails() -> None:
    """The file resolves and the function does not — named separately on purpose."""
    ref = TestRef(node_id=f"{MANDATE_MODULE_PATH}::test_renamed_away")
    verdict = _verdict(ref, _context(), full_session=False)
    assert not verdict.resolved
    assert "does not define" in verdict.failures[0]


def test_a_duplicated_node_id_fails_the_full_session_tier() -> None:
    """Rule 1 at full strength: one id, two collected nodes, no evidence."""
    nodes = _node(occurrences=2)
    verdict = _verdict(MANDATE_REF, _context(nodes=nodes), full_session=True)
    assert not verdict.resolved
    assert "2 collected nodes" in verdict.failures[0]


def test_the_full_session_tier_refuses_an_uncollected_node() -> None:
    """A ref nothing collected has no evidence, whatever its source says."""
    verdict = _verdict(MANDATE_REF, _context(nodes={}), full_session=True)
    assert verdict.failures == ("names no collected node",)


# ── rules 2 and 3: no skip marker, no xfail in any form ───────────────────


@pytest.mark.parametrize("marker", ["skip", "skipif"])
def test_a_skip_marker_on_the_function_fails(marker: str) -> None:
    """A skipped node backs no claim; the decorator is read out of the source."""
    module = CLEAN_MODULE.replace(
        "def test_command_prices_the_amp",
        f"@pytest.mark.{marker}(reason='x')\ndef test_command_prices_the_amp",
    )
    verdict = _verdict(
        MANDATE_REF,
        _context(_source(**{MANDATE_MODULE_PATH: module})),
        full_session=False,
    )
    assert not verdict.resolved
    assert marker in verdict.failures[0]


@pytest.mark.parametrize("strict", ["", "(strict=True)"])
def test_an_xfail_marker_fails_strict_or_not(strict: str) -> None:
    """A node expected to fail is not evidence that something works, either way."""
    module = CLEAN_MODULE.replace(
        "def test_command_prices_the_amp",
        f"@pytest.mark.xfail{strict}\ndef test_command_prices_the_amp",
    )
    verdict = _verdict(
        MANDATE_REF,
        _context(_source(**{MANDATE_MODULE_PATH: module})),
        full_session=False,
    )
    assert not verdict.resolved
    assert "xfail" in verdict.failures[0]


def test_a_module_level_pytestmark_skip_fails() -> None:
    """The marker rule reads every level, which is where a skip hides best."""
    module = CLEAN_MODULE.replace(
        "import pytest\n", "import pytest\n\npytestmark = pytest.mark.skip\n"
    )
    verdict = _verdict(
        MANDATE_REF,
        _context(_source(**{MANDATE_MODULE_PATH: module})),
        full_session=False,
    )
    assert not verdict.resolved
    assert "skip" in verdict.failures[0]


def test_a_class_level_pytestmark_xfail_fails() -> None:
    """A class ``pytestmark`` reaches its methods, so the scan walks the chain."""
    module = (
        '"""Prices Imperial Mandate — Command."""\n\n'
        "import pytest\n\n\n"
        "class TestCommand:\n"
        "    pytestmark = [pytest.mark.xfail]\n\n"
        "    def test_command_prices_the_amp(self):\n"
        "        assert True\n"
    )
    ref = TestRef(
        node_id=f"{MANDATE_MODULE_PATH}::TestCommand::test_command_prices_the_amp"
    )
    verdict = _verdict(
        ref, _context(_source(**{MANDATE_MODULE_PATH: module})), full_session=False
    )
    assert not verdict.resolved
    assert "xfail" in verdict.failures[0]


def test_a_marker_the_collected_node_carries_fails_the_full_session_tier() -> None:
    """The full-session tier reads pytest's resolved markers, not the source."""
    nodes = _node(markers=("skip",))
    verdict = _verdict(MANDATE_REF, _context(nodes=nodes), full_session=True)
    assert not verdict.resolved
    assert "skip" in verdict.failures[0]


# ── rule 4: no skip call in the body or the fixture closure ───────────────


@pytest.mark.parametrize("call", ["pytest.skip('no node')", "pytest.importorskip('x')"])
@BOTH_TIERS
def test_a_skip_call_in_the_body_fails(call: str, full_session: bool) -> None:
    """A test that can green out from inside its own body proves nothing."""
    module = CLEAN_MODULE.replace("    assert priced_amp > 0", f"    {call}")
    verdict = _verdict(
        MANDATE_REF,
        _context(_source(**{MANDATE_MODULE_PATH: module}), nodes=_node()),
        full_session=full_session,
    )
    assert not verdict.resolved
    assert "its body calls" in verdict.failures[0]


@BOTH_TIERS
def test_a_skip_call_in_a_fixture_in_the_closure_fails(full_session: bool) -> None:
    """The closure counts: the four live skips of this shape are why the rule exists."""
    module = CLEAN_MODULE.replace(
        "    return 0.07", "    pytest.skip('the amp is not wired up')"
    )
    nodes = _node(fixtures=("priced_amp",))
    verdict = _verdict(
        MANDATE_REF,
        _context(_source(**{MANDATE_MODULE_PATH: module}), nodes=nodes),
        full_session=full_session,
    )
    assert not verdict.resolved
    assert "priced_amp" in verdict.failures[0]


def test_a_fixture_the_tier_cannot_read_is_named_not_failed() -> None:
    """An unreadable definition is not evidence of a skip — but it is not silence."""
    nodes = _node(fixtures=("factory_built", "tmp_path"))
    verdict = _verdict(MANDATE_REF, _context(nodes=nodes), full_session=True)
    assert verdict.resolved
    assert verdict.unscanned_fixtures == frozenset({"factory_built"})


@BOTH_TIERS
def test_a_clean_ref_passes_every_rule_this_tier_can_check(full_session: bool) -> None:
    """The positive case, so the negatives above are not all a broken harness."""
    verdict = _verdict(
        MANDATE_REF,
        _context(nodes=_node(fixtures=("priced_amp",))),
        full_session=full_session,
    )
    assert verdict.resolved, verdict.failures
    assert verdict.unscanned_fixtures == frozenset()


# ── rule 5: the node is about the claim ───────────────────────────────────


def test_relevance_tokens_are_the_claims_own_strings() -> None:
    """Subject, symbol path and its tail, packet fragments, and effect keys."""
    claim = Claim(
        subject_kind="item",
        subject="Imperial Mandate",
        lane="attacker",
        status="modeled_effect",
        evidence=(
            Symbol(path="damage._apply_command_amp", role="pair_engine"),
            EffectKey(
                registry="ITEM_EFFECTS",
                item="Imperial Mandate",
                key="command_amp_percent",
            ),
            TestRef(node_id=MANDATE_NODE),
        ),
        dimensions=(),
        issue_refs=(),
        unreachable_reason="",
    )
    tokens = relevance_tokens(claim)
    assert "Imperial Mandate" in tokens
    assert "damage._apply_command_amp" in tokens
    assert "_apply_command_amp" in tokens
    assert "command_amp_percent" in tokens


def test_an_irrelevant_test_ref_is_unresolved() -> None:
    """M9's shape: it resolves, it is unskipped, and it is about nothing.

    Without this rule one smoke test that imports the package discharges
    every claim in the table.
    """
    ctx = _context(_source(**{MANDATE_MODULE_PATH: UNRELATED_MODULE}), nodes=_node())
    with pytest.raises(EvidenceUnresolved) as raised:
        resolve_test_ref(MANDATE_REF, MANDATE_CLAIM, ctx, full_session=True)
    assert "mentions none of the claim's strings" in str(raised.value)
    assert raised.value.claim == "item:Imperial Mandate@support_packet"


def test_a_relevant_test_ref_resolves() -> None:
    """The module text names the claim's subject, so the node is about it."""
    resolve_test_ref(
        MANDATE_REF,
        MANDATE_CLAIM,
        _context(nodes=_node(fixtures=("priced_amp",))),
        full_session=True,
    )


def test_a_parametrization_id_can_carry_the_relevance() -> None:
    """One parametrized node per item is the shape a rule-claim's population uses."""
    node_id = f"{MANDATE_MODULE_PATH}::test_command_prices_the_amp[Imperial Mandate]"
    ctx = _context(
        _source(**{MANDATE_MODULE_PATH: UNRELATED_MODULE}),
        nodes=_node(node_id),
    )
    resolve_test_ref(TestRef(node_id=node_id), MANDATE_CLAIM, ctx, full_session=True)


def test_resolve_names_the_claim_and_the_member_it_broke() -> None:
    """One run has to say which claim and which member, not merely that one failed."""
    ctx = _context(nodes={})
    with pytest.raises(EvidenceUnresolved) as raised:
        resolve_test_ref(MANDATE_REF, MANDATE_CLAIM, ctx, full_session=True)
    assert raised.value.evidence == MANDATE_REF
    assert "TestRef" in str(raised.value)


# ── the live tree ─────────────────────────────────────────────────────────


def test_a_live_test_ref_resolves_through_the_live_seams() -> None:
    """A real node, a real claim, whichever tier this invocation is running."""
    node_id = (
        "tests/test_coverage_evidence.py::test_the_evidence_union_is_the_closed_nine"
    )
    claim = Claim(
        subject_kind="rule",
        subject="coverage_evidence.validate_claim_table",
        lane="attacker",
        status="modeled_effect",
        evidence=(
            Symbol(
                path="coverage_evidence.validate_claim_table", role="value_accessor"
            ),
            TestRef(node_id=node_id),
        ),
        dimensions=(),
        issue_refs=(),
        unreachable_reason="",
    )
    validate_claim(claim)
    resolve_test_ref(
        TestRef(node_id=node_id),
        claim,
        live_context(),
        full_session=coverage_resolver.full_session(),
    )


def test_the_live_skip_guarded_nodes_are_refused() -> None:
    """The repository's four ``pytest.skip('node is not installed')`` tests.

    They are the exact shape rule 4 exists for, and they are real: a claim
    backed by one of them would be a claim that passes on a machine where
    the assertion never ran.
    """
    ref = TestRef(
        node_id="tests/test_f0_frontend.py::test_node_check_passes_for_app_js"
    )
    verdict = _verdict(
        ref, live_context(), full_session=coverage_resolver.full_session()
    )
    assert not verdict.resolved
    assert "its body calls" in verdict.failures[0]


# ── the tier gate ─────────────────────────────────────────────────────────


class _Options:
    """The three fields ``_is_full_session`` reads off a parsed command line."""

    def __init__(self, keyword: str = "", markexpr: str = "", file_or_dir=()) -> None:
        self.keyword = keyword
        self.markexpr = markexpr
        self.file_or_dir = list(file_or_dir)


class _Config:
    """Enough of a pytest ``Config`` for the session predicate."""

    def __init__(self, option: _Options) -> None:
        self.option = option


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        (_Options(), True),
        (_Options(keyword="mandate"), False),
        (_Options(markexpr="not slow"), False),
        (_Options(file_or_dir=["tests/test_coverage_claims.py"]), False),
    ],
    ids=["whole", "-k", "-m", "path"],
)
def test_the_full_session_predicate_reads_all_three_filters(
    options: _Options, expected: bool
) -> None:
    """Any of ``-k``, ``-m`` or a path narrows collection, so any of them downgrades."""
    from tests.conftest import _is_full_session  # local: it is a hook helper

    assert _is_full_session(_Config(options)) is expected


def test_a_filtered_session_deselects_the_full_session_tier_and_skips_nothing() -> None:
    """Deselected, never skipped — proved by running one, not by saying so.

    ``pytest.skip`` reports green for work it did not do, which is this
    campaign's own failure shape.  A path argument is a filter, so this run
    must not collect the marked node at all.
    """
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_coverage_claims.py",
            "--collect-only",
            "-q",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert FULL_SESSION_NODE not in completed.stdout
    assert "deselected" in completed.stdout
    assert "skipped" not in completed.stdout


@pytest.mark.full_session
def test_the_full_session_tier_sees_its_own_node() -> None:
    """The other half: an unfiltered run collects the marked tier and this node.

    It proves itself — the check that the gate lets the tier through is the
    tier finding itself in the stashed node set.
    """
    nodes = coverage_resolver.collected_nodes()
    assert coverage_resolver.full_session() is True
    assert FULL_SESSION_NODE in nodes
    assert nodes[FULL_SESSION_NODE].markers >= {FULL_SESSION_MARKER}


@pytest.mark.full_session
def test_the_resolver_contributes_no_collected_node() -> None:
    """The uncollected ruling, checked against what a whole session collected."""
    collected = coverage_resolver.collected_nodes()
    assert not [
        node for node in collected if node.startswith("tests/coverage_resolver")
    ]


def _shell_commands(workflow: str) -> list[list[str]]:
    """Every ``run:`` command in a workflow, tokenized, block scalars included."""
    commands: list[list[str]] = []
    lines = workflow.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        index += 1
        if not stripped.startswith("run:"):
            continue
        body = stripped[len("run:") :].strip()
        if body not in ("|", ">", "|-", ">-"):
            commands.append(body.split())
            continue
        indent = len(line) - len(line.lstrip())
        while index < len(lines):
            following = lines[index]
            if following.strip() and len(following) - len(following.lstrip()) <= indent:
                break
            commands.append(following.strip().split())
            index += 1
    return commands


def test_ci_runs_pytest_with_no_keyword_marker_or_path_filter() -> None:
    """Otherwise the full-session tier is decorative: never collected anywhere.

    The workflow is read as shell commands rather than as YAML — the repo
    carries no YAML parser — and every command whose first word is ``pytest``
    has to carry no ``-k``, no ``-m`` and no positional path.
    """
    commands = _shell_commands(WORKFLOW_PATH.read_text(encoding="utf-8"))
    invocations = [
        command
        for command in commands
        if command[:1] == ["pytest"] or command[:3] == ["python", "-m", "pytest"]
    ]
    assert invocations, "the workflow runs no pytest step"
    for invocation in invocations:
        arguments = invocation[invocation.index("pytest") + 1 :]
        assert "-k" not in arguments and "--keyword" not in arguments
        assert "-m" not in arguments
        assert [
            argument for argument in arguments if not argument.startswith("-")
        ] == [], invocation
