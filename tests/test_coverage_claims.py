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
import dataclasses
import fnmatch
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from src.calculator.coverage_evidence import (
    EVIDENCE_TYPES,
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
    validate_claim,
)
from src.calculator.trigger_stream import CAPABILITIES

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


# ── the other eight evidence kinds ────────────────────────────────────────

MANDATE_SUPPORT_CLAIM = Claim(
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
        PairedSides(
            mechanic="imperial_mandate.command", owner_policy="owner_skips_holder"
        ),
        TestRef(node_id=MANDATE_NODE),
    ),
    dimensions=("damage_amplification",),
    issue_refs=(),
    unreachable_reason="",
)


def _live() -> ResolverContext:
    """The live seams with an empty node set — every kind but ``TestRef``."""
    return ResolverContext(
        importer=importlib.import_module,
        read_source=coverage_resolver.read_repo_file,
        nodes={},
    )


def _resolve_live(member, claim: Claim = MANDATE_SUPPORT_CLAIM) -> None:
    """One member against the real tree."""
    coverage_resolver.resolve(member, claim, _live())


def test_the_dispatch_covers_every_evidence_kind() -> None:
    """Totality, as a set comparison rather than a ladder anyone can outgrow.

    ``TestRef`` and ``SourceRef`` are dispatched by name because they take a
    parameter the others do not — the tier flag and the parsed audit — so the
    table plus those two is the union, and a tenth kind fails here on the
    commit that adds it.
    """
    assert set(coverage_resolver._RESOLVERS) | {TestRef, SourceRef} == set(
        EVIDENCE_TYPES
    )


def test_an_unknown_evidence_kind_is_unresolved_rather_than_ignored() -> None:
    """A member the tier cannot dispatch is a failure, never a silent pass."""
    with pytest.raises(EvidenceUnresolved, match="nine evidence kinds"):
        _resolve_live(object())


# ── Symbol ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "damage._apply_command_amp",
        "survival.transitions.trigger_defy",
        "item_effects.ITEM_INPUT_OPTIONS",
        "item_coverage._has_described_effect",
    ],
    ids=["one-segment module", "two-segment module", "registry", "private predicate"],
)
def test_a_live_symbol_resolves_to_its_module_and_object(path: str) -> None:
    """The split between module and attribute is found, not declared.

    ``survival.transitions.trigger_defy`` is a two-segment module and one
    attribute and ``damage._apply_command_amp`` is one of each; the longest
    importable prefix is what tells them apart.
    """
    module, found = coverage_resolver.import_symbol(path, _live())
    assert path.startswith(module)
    assert found is not None


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("damage._apply_command_amp_renamed", "names no '_apply_command_amp_renamed'"),
        ("nowhere.at_all", "names no importable module"),
    ],
    ids=["M1: the accessor is renamed", "M2: the module is gone"],
)
def test_a_symbol_naming_nothing_is_unresolved(path: str, message: str) -> None:
    """The mutation shape M1 and M2 both take: the prose outlives the code."""
    with pytest.raises(EvidenceUnresolved, match=message):
        _resolve_live(Symbol(path=path, role="pair_engine"))


# ── PacketSource ──────────────────────────────────────────────────────────


def test_packet_sites_read_every_source_argument_with_its_keywords() -> None:
    """The measurement is the contract, and ``owner=`` is what it is for.

    The count is read off the module rather than pinned, and the distinct
    source set is what Phase 3 derives its producer count from.  What is
    asserted here is the property the campaign turns on: exactly the packets
    whose mechanic Phase 2 declares ``SPLIT`` carry ``owner=``.
    """
    text = coverage_resolver.read_repo_file("src/calculator/item_support_effects.py")
    sites = coverage_resolver.packet_sites(text)
    assert len(sites) >= len({site.source for site in sites}) >= 1
    owning = {site.source for site in sites if "owner" in site.keywords}
    split = {
        capability.packet_source
        for capability in CAPABILITIES.values()
        if capability.authority.name == "SPLIT" and capability.packet_source
    }
    assert owning == split


def test_render_source_argument_collapses_an_f_string_to_slots() -> None:
    """``{}`` is the only brace a ``PacketSource`` may carry, and this is why."""
    rendered = coverage_resolver.render_source_argument(
        ast.parse('f"{item} — Reap"', mode="eval").body
    )
    assert rendered == "{} — Reap"
    assert (
        coverage_resolver.render_source_argument(
            ast.parse('"Cull — Reap"', mode="eval").body
        )
        == "Cull — Reap"
    )
    assert (
        coverage_resolver.render_source_argument(ast.parse("name", mode="eval").body)
        is None
    )


def test_a_live_packet_source_resolves_against_its_declared_builder() -> None:
    """The claim names the builder; the builder emits the source."""
    _resolve_live(PacketSource(source="Imperial Mandate — Command"))


def test_a_packet_source_with_no_builder_symbol_is_unresolved() -> None:
    """M3's shape: the literal is removed and nothing else changes.

    A repository-wide scan would still find the string in a comment or a
    test, so the member is proved against the module the claim itself names.
    """
    claim = Claim(
        subject_kind="item",
        subject="Imperial Mandate",
        lane="attacker",
        status="modeled_effect",
        evidence=(
            Symbol(path="damage._apply_command_amp", role="pair_engine"),
            TestRef(node_id=MANDATE_NODE),
        ),
        dimensions=(),
        issue_refs=(),
        unreachable_reason="",
    )
    with pytest.raises(EvidenceUnresolved, match="names no builder"):
        coverage_resolver.resolve(
            PacketSource(source="Imperial Mandate — Command"), claim, _live()
        )


def test_a_packet_source_the_builder_never_emits_is_unresolved() -> None:
    """The other half of M3: the builder resolves and the receipt is gone."""
    with pytest.raises(EvidenceUnresolved, match="is not a source= argument"):
        _resolve_live(PacketSource(source="Imperial Mandate — Commandeer"))


# ── PairedSides ───────────────────────────────────────────────────────────


def test_every_split_capability_resolves_as_a_paired_mechanic() -> None:
    """The registry is the authority, and it closes in both directions.

    Five mechanics declare ``SPLIT`` on the walk side today.  Each is
    resolved through the same door a claim uses, so a half deleted, a
    ``pair_of`` cleared or an owner changed fails here rather than in review.
    """
    walk_halves = [
        capability
        for capability in CAPABILITIES.values()
        if capability.authority.name == "SPLIT" and capability.pair_of
    ]
    assert walk_halves
    for capability in walk_halves:
        _resolve_live(
            PairedSides(mechanic=capability.mechanic, owner_policy="owner_skips_holder")
        )


@pytest.mark.parametrize(
    ("sides", "message"),
    [
        (
            PairedSides(
                mechanic="imperial_mandate.made_up", owner_policy="owner_skips_holder"
            ),
            "not a declared capability",
        ),
        (
            PairedSides(mechanic="cull.reap", owner_policy="owner_skips_holder"),
            "not SPLIT",
        ),
        (
            PairedSides(
                mechanic="imperial_mandate.command",
                owner_policy="holder_is_not_a_source",
            ),
            "expects the .* packet not to declare owner=",
        ),
    ],
    ids=["undeclared", "not split", "wrong owner policy"],
)
def test_a_paired_sides_member_that_does_not_hold_is_unresolved(
    sides: PairedSides, message: str
) -> None:
    """Each half of the handshake fails on its own, named separately."""
    with pytest.raises(EvidenceUnresolved, match=message):
        _resolve_live(sides)


def test_M5_clearing_a_pair_of_leaves_the_dual_sided_claim_unresolved() -> None:
    """The mutation is a context, not an edit: a registry with one half gone.

    ``pair_of`` is the only field that says the two engines are pricing one
    mechanic.  Clearing it is exactly the incident — a coverage claim naming
    both sides while only one exists — and it has to fail without any source
    file being touched.
    """
    live = _live()
    real = live.importer("src.calculator.trigger_stream")
    unpaired = dict(CAPABILITIES)
    unpaired["imperial_mandate.command"] = dataclasses.replace(
        CAPABILITIES["imperial_mandate.command"], pair_of=None
    )

    class _Registry:
        """``trigger_stream`` with one capability's pair link cleared."""

        CAPABILITIES = unpaired

    def importer(name: str) -> object:
        return _Registry if name.endswith("trigger_stream") else real

    ctx = ResolverContext(
        importer=importer, read_source=live.read_source, nodes=live.nodes
    )
    with pytest.raises(EvidenceUnresolved, match="declares no pair_of"):
        coverage_resolver.resolve(
            PairedSides(
                mechanic="imperial_mandate.command", owner_policy="owner_skips_holder"
            ),
            MANDATE_SUPPORT_CLAIM,
            ctx,
        )


# ── EffectKey, EffectTag, OptionSchema ────────────────────────────────────


def test_a_live_effect_key_resolves_to_its_registry_entry() -> None:
    """The key, never its number — the resolution is exactly membership."""
    _resolve_live(
        EffectKey(registry="ITEM_EFFECTS", item="Thornmail", key="bonus_armor_ratio")
    )


@pytest.mark.parametrize(
    ("key", "message"),
    [
        (
            EffectKey(registry="ITEM_EFFECTS", item="Thornmail", key="thorn_percent"),
            "has no 'thorn_percent' key",
        ),
        (
            EffectKey(registry="ITEM_EFFECTS", item="Thornmail Plus", key="base"),
            "has no 'Thornmail Plus' entry",
        ),
    ],
    ids=["key", "holder"],
)
def test_an_effect_key_the_registry_lacks_is_unresolved(key, message: str) -> None:
    """Rule 5's discipline: the declaration names where the number lives."""
    with pytest.raises(EvidenceUnresolved, match=message):
        _resolve_live(key)


def test_a_live_effect_tag_resolves_to_a_handler_that_branches_on_it() -> None:
    """A tag with a handler; the ten without one are the frontier's."""
    _resolve_live(EffectTag(tag="thorns", handler="item_effects.thorns_effects"))


@pytest.mark.parametrize(
    ("tag", "message"),
    [
        (
            EffectTag(tag="target_state", handler="item_effects.thorns_effects"),
            "does not branch on",
        ),
        (
            EffectTag(tag="not_a_tag", handler="item_effects.thorns_effects"),
            "not an item_effects._KNOWN_EFFECT_TYPES member",
        ),
    ],
    ids=["M6: the tag is renamed", "unknown tag"],
)
def test_an_effect_tag_with_no_live_branch_is_unresolved(tag, message: str) -> None:
    """M6's shape: renaming a tag reclassifies items with no other signal."""
    with pytest.raises(EvidenceUnresolved, match=message):
        _resolve_live(tag)


def test_a_live_option_schema_resolves_to_a_bounded_control() -> None:
    """Bounded is the whole claim: type, default, and both ends."""
    _resolve_live(OptionSchema(item="Heartsteel", option="bonus_health"))


def test_an_option_the_registry_does_not_declare_is_unresolved() -> None:
    """An item whose state is claimed supplied has to name the control."""
    with pytest.raises(EvidenceUnresolved, match="declares no 'unbounded' control"):
        _resolve_live(OptionSchema(item="Heartsteel", option="unbounded"))


def test_an_unbounded_control_is_unresolved() -> None:
    """A control missing an end is an assumption with a form field in front."""
    live = _live()
    real = live.importer("src.calculator.item_effects")

    class _Registry:
        """``item_effects`` with one control's ceiling removed."""

        ITEM_INPUT_OPTIONS = {
            "Heartsteel": {
                "options": {"bonus_health": {"type": "int", "default": 0, "min": 0}}
            }
        }

    def importer(name: str) -> object:
        return _Registry if name.endswith("item_effects") else real

    ctx = ResolverContext(
        importer=importer, read_source=live.read_source, nodes=live.nodes
    )
    with pytest.raises(EvidenceUnresolved, match=r"is missing \['max'\]"):
        coverage_resolver.resolve(
            OptionSchema(item="Heartsteel", option="bonus_health"),
            MANDATE_SUPPORT_CLAIM,
            ctx,
        )


# ── SourceRef and Absence ─────────────────────────────────────────────────


def test_a_live_source_ref_resolves_to_that_items_audit_entry() -> None:
    """A citation is a url *and* a revision, and it is the subject's own."""
    entries = coverage_resolver.audit_entries(_live())
    entry = next(item for item in entries if item["name"] == "Banshee's Veil")
    claim = Claim(
        subject_kind="item",
        subject="Banshee's Veil",
        lane="attacker",
        status="stats_only",
        evidence=(
            SourceRef(url=entry["source_url"], revision_id=entry["revision_id"]),
        ),
        dimensions=(),
        issue_refs=(),
        unreachable_reason="",
    )
    coverage_resolver.resolve(claim.evidence[0], claim, _live())

    stale = SourceRef(url=entry["source_url"], revision_id=entry["revision_id"] - 1)
    with pytest.raises(EvidenceUnresolved, match="is not an entry of"):
        coverage_resolver.resolve(stale, claim, _live())


def test_a_source_ref_citing_another_items_entry_is_unresolved() -> None:
    """A review of some other item is not a review of this one."""
    entries = coverage_resolver.audit_entries(_live())
    entry = next(item for item in entries if item["name"] == "Abyssal Mask")
    claim = Claim(
        subject_kind="item",
        subject="Banshee's Veil",
        lane="attacker",
        status="stats_only",
        evidence=(
            SourceRef(url=entry["source_url"], revision_id=entry["revision_id"]),
        ),
        dimensions=(),
        issue_refs=(),
        unreachable_reason="",
    )
    with pytest.raises(EvidenceUnresolved, match='not for "Banshee\'s Veil"'):
        coverage_resolver.resolve(claim.evidence[0], claim, _live())


def test_an_absence_names_the_issues_the_public_payload_publishes() -> None:
    """The declaration's receipt and the receipt on the wire are one list."""
    claim = Claim(
        subject_kind="item",
        subject="Guardian's Horn",
        lane="target",
        status="blocked",
        evidence=(
            Absence(reason="Legendary's reduction is not modelled.", issue_refs=(40,)),
        ),
        dimensions=(),
        issue_refs=(),
        unreachable_reason="",
    )
    coverage_resolver.resolve(claim.evidence[0], claim, _live())

    wrong = Absence(reason="Same reason, different tracker.", issue_refs=(43,))
    with pytest.raises(EvidenceUnresolved, match="the public payload publishes"):
        coverage_resolver.resolve(wrong, claim, _live())


# ── the table ─────────────────────────────────────────────────────────────


def test_resolve_table_reports_every_broken_member_not_the_first() -> None:
    """One run names all of them; the first is a fact about alphabetical order."""
    broken = Claim(
        subject_kind="item",
        subject="Imperial Mandate",
        lane="attacker",
        status="modeled_effect",
        evidence=(
            Symbol(path="damage._gone", role="pair_engine"),
            Symbol(path="item_effects._also_gone", role="value_accessor"),
        ),
        dimensions=(),
        issue_refs=(),
        unreachable_reason="",
    )
    failures = coverage_resolver.resolve_table(
        {("item", "Imperial Mandate", "attacker"): broken}, _live()
    )
    assert [failure.evidence for failure in failures] == list(broken.evidence)
    assert all(
        failure.claim == "item:Imperial Mandate@attacker" for failure in failures
    )
