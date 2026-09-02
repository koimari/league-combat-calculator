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
import hashlib
import importlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import capture_coverage_classification
from src.calculator import item_behavior_catalog, item_coverage, item_outcomes
from src.calculator.coverage_evidence import (
    EVIDENCE_TYPES,
    UTILITY_DIMENSIONS,
    Absence,
    Claim,
    CoverageClaimError,
    EffectKey,
    EffectTag,
    OptionSchema,
    PacketSource,
    PairedSides,
    SourceRef,
    Symbol,
    TestRef,
    claim_name,
    validate_claim,
)
from src.calculator.data_fetcher import fetch_item_data
from src.calculator.item_coverage import (
    COVERAGE_EVIDENCE,
    FRONTIER,
    target_item_model_coverage,
)
from src.calculator.item_effects import (
    _KNOWN_EFFECT_TYPES,
    ITEM_EFFECTS,
    ITEM_INPUT_OPTIONS,
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


# The two doors that touch a real file, and why each is not a seam.
# ``read_repo_file`` *is* the seam's live implementation.  ``front_door_report``
# surveys two trees rather than resolving an evidence member, and it takes both
# roots as parameters — a temporary directory is the injection a survey needs,
# and a survey routed through ``read_source`` would still have to list the
# files, which is the half a seam cannot supply.
_TREE_READERS: frozenset[str] = frozenset({"read_repo_file", "front_door_report"})


def test_every_filesystem_read_lives_behind_the_read_source_seam() -> None:
    """Only the two declared tree readers touch a real file; the rest ask the seam."""
    tree = ast.parse(RESOLVER_PATH.read_text(encoding="utf-8"))
    filesystem = {"read_text", "open", "is_file", "exists", "iterdir", "glob", "rglob"}
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name in _TREE_READERS:
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
    assert claim_name(MANDATE_CLAIM)


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
        subject_kind="item",
        subject="Imperial Mandate",
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
    # Options that take a value: their value is not a positional path.
    # ``-n auto`` (pytest-xdist) is the workflow's parallel-worker count.
    value_options = {"-n", "--numprocesses", "-p", "--dist", "--cov"}
    for invocation in invocations:
        arguments = invocation[invocation.index("pytest") + 1 :]
        assert "-k" not in arguments
        assert "--keyword" not in arguments
        assert "-m" not in arguments
        positional = []
        skip_next = False
        for argument in arguments:
            if skip_next:
                skip_next = False
                continue
            if argument in value_options:
                skip_next = True
            elif not argument.startswith("-"):
                positional.append(argument)
        assert positional == [], invocation


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


def test_every_walk_packet_literal_is_quoted_by_a_claim_or_withheld() -> None:
    """Criterion 17: the corpus is total over the literals the builder emits.

    ``PacketSource`` resolution runs claim → builder.  This is the return
    edge: a packet the builder emits that no claim quotes and no frontier
    entry withholds owes no evidence to anybody, so a second packet on an
    already-claimed item would enter the walk unremarked — the shape this
    phase exists to kill, one level inside its own evidence union.
    """
    text = coverage_resolver.read_repo_file("src/calculator/item_support_effects.py")
    assert (
        coverage_resolver.unquoted_packet_sources(COVERAGE_EVIDENCE, FRONTIER, text)
        == ()
    )


def test_a_packet_added_to_an_already_claimed_item_is_reported() -> None:
    """The red the totality check ships with (R-05), through its own seam.

    Dream Maker is the case that motivated the check: it is a claimed item
    whose claim quotes one of its two packets, so a holder-level frontier key
    could never have covered the other one and a third growing it would not
    be noticed by the item lane at all.
    """
    text = coverage_resolver.read_repo_file("src/calculator/item_support_effects.py")
    grown = f'{text}\n_ = _packet(source="Dream Maker — Green Dream Bubble")\n'
    assert coverage_resolver.unquoted_packet_sources(
        COVERAGE_EVIDENCE, FRONTIER, grown
    ) == ("Dream Maker — Green Dream Bubble",)
    named = {
        **FRONTIER,
        "packet:Dream Maker — Green Dream Bubble": "synthetic, tracked by #0",
    }
    assert (
        coverage_resolver.unquoted_packet_sources(COVERAGE_EVIDENCE, named, grown) == ()
    )


def test_a_withheld_holder_covers_its_own_packets_and_no_others() -> None:
    """The holder-key route is a derivation, and it is not a blanket.

    An item on the frontier has no claim to quote its packets with, so its
    key stands for them — by the ``"<Holder> — <Effect>"`` spelling every
    ``_packet`` source is built with, never by a second hand list.  Dropping
    the key reports exactly that holder's packet and nothing else, which is
    what says the exemption is doing work rather than passing everything.
    """
    text = coverage_resolver.read_repo_file("src/calculator/item_support_effects.py")
    without = {
        key: reason
        for key, reason in FRONTIER.items()
        if key != "item:Diadem of Songs@support_packet"
    }
    assert coverage_resolver.unquoted_packet_sources(
        COVERAGE_EVIDENCE, without, text
    ) == ("Diadem of Songs — Consonance",)


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
            "names no second engine",
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
    """A tag with a handler; the ten without one are the frontier's.

    Two lanes of handler, because SD9 moved where a tag's behaviour lives: the
    ladder in ``item_effects`` still dispatches the two tags that author an
    assumption note, and a tag it retired is dispatched by the catalog
    compiler that builds the declaration.  The evidence names whichever one
    reads the tag, so a retirement re-points a claim rather than voiding it.

    Only a handler that branches on the *tag* can carry this member, which is
    why the crit family is absent: ``_compile_crit_profile`` dispatches on the
    entry's value keys, so nothing in it reads ``crit_modifier`` as a string
    and this evidence type has nothing to check there.
    """
    for tag, handler in (
        ("ult_empowered_autos", "item_effects._resolve_damage_effects_uncached"),
        ("execute", "item_behavior_catalog._compile_damage_routing"),
        ("magic_damage_amp", "item_behavior_catalog._compile_delta_amp"),
    ):
        _resolve_live(EffectTag(tag=tag, handler=handler))


@pytest.mark.parametrize(
    ("tag", "message"),
    [
        (
            EffectTag(
                tag="target_state",
                handler="item_effects._resolve_damage_effects_uncached",
            ),
            "does not branch on",
        ),
        (
            EffectTag(
                tag="not_a_tag",
                handler="item_effects._resolve_damage_effects_uncached",
            ),
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
    )
    failures = coverage_resolver.resolve_table(
        {("item", "Imperial Mandate", "attacker"): broken}, _live()
    )
    assert [failure.evidence for failure in failures] == list(broken.evidence)
    assert all(
        failure.claim == "item:Imperial Mandate@attacker" for failure in failures
    )


# ── the front-door survey ─────────────────────────────────────────────────

_FRONT_DOOR_TREE: dict[str, str] = {
    "src/calculator/named.py": "",
    "src/calculator/bound.py": "",
    "src/calculator/mentioned.py": "",
    "src/calculator/survival/__init__.py": "",
    "src/calculator/survival/sibling.py": "",
    "src/calculator/champions/gnar.py": "",
    "tests/test_tree.py": (
        "import src.calculator.named\n"
        "from src.calculator import bound\n"
        "from src.calculator.survival import Combatant\n"
        'MENTION = "src.calculator.mentioned"\n'
    ),
}


def _write_tree(root: Path, tree: dict[str, str]) -> None:
    """One fabricated repository on disk — the survey's injection point."""
    for path, text in tree.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def test_the_front_door_survey_reads_imports_and_not_mentions(tmp_path: Path) -> None:
    """Both rules in ``front_door_report``'s docstring, on a tree built for them.

    ``named`` is imported by dotted path and ``bound`` is bound out of the
    package: both are front doors.  ``mentioned`` appears only inside a string
    — the shape an ``importlib.import_module`` call or a comment takes — and
    ``survival.sibling`` is the package-versus-submodule rule: importing a
    name out of ``survival`` is a front door for the package, whose
    ``__init__`` is not in the denominator, and for no submodule of it.
    ``champions/`` is excluded by declaration and never appears.
    """
    _write_tree(tmp_path, _FRONT_DOOR_TREE)
    report = coverage_resolver.front_door_report(
        tmp_path / "src" / "calculator", tmp_path / "tests"
    )
    assert {missing.module for missing in report} == {"mentioned", "survival.sibling"}
    assert {missing.path for missing in report} == {
        "src/calculator/mentioned.py",
        "src/calculator/survival/sibling.py",
    }


def test_the_live_survey_reports_only_real_and_unimported_modules() -> None:
    """The property the frontier rests on, over the two real trees.

    Every module the report names is a file this repository has, and none of
    them is named by an import anywhere in ``tests/`` — the second half
    recomputed here from :func:`imported_package_modules` rather than trusted
    from the report, so a survey that quietly stopped reading a tree would
    show up as a module reported despite being imported.
    """
    report = coverage_resolver.front_door_report(
        ROOT / "src" / "calculator", ROOT / "tests"
    )
    imported: set[str] = set()
    for path in sorted((ROOT / "tests").rglob("*.py")):
        imported |= coverage_resolver.imported_package_modules(
            path.read_text(encoding="utf-8")
        )
    for missing in report:
        assert (ROOT / missing.path).is_file()
        assert missing.module not in imported


# ── the ladder, over the cache ───────────────────────────────────────────────────

CLASSIFICATION_RECEIPT = (
    ROOT / "docs" / "receipts" / "item-coverage-classification.json"
)
# Every slice's allowlist, not one slice's: R-36 makes the file per slice, so
# the gate reads the union of the live permission blocks.  Found by glob and
# never listed, so a slice that adds a receipt without touching this file is
# still gated, and a re-capture that empties a block tightens the gate on the
# commit that lands it.
EXPECTED_COVERAGE_DIFFS = sorted(
    (ROOT / "docs" / "receipts").glob("expected-coverage-diff-*.json")
)

# The two statuses that refuse rather than classify, read from the module that
# defines them so the allowlist's eligibility derivation cannot drift from the
# payload's own.
_REFUSAL_STATUSES = item_coverage._REFUSAL_STATUSES


def _attacker(name: str):
    """The attacker-lane answer for one cached item, on the lanes it needs."""
    return item_coverage.item_model_coverage(name, item_coverage.ATTACKER_LANES)


def _attacker_payload(record: dict) -> dict:
    """The attacker-lane public payload, keyed the way the receipt keys it."""
    return _attacker(str(record.get("name", ""))).as_payload()


def cached_items() -> dict[str, dict]:
    """Every cached item record, keyed by the name the classifiers read."""
    return {
        str(record.get("name", "")): record for record in fetch_item_data().values()
    }


def test_every_reviewed_absence_is_the_reason_the_ladder_publishes() -> None:
    """A reviewed-nothing entry an earlier branch decides would be dead prose.

    ``NO_RUNTIME_BEHAVIOR`` is the one hand-maintained container the attacker
    ladder reads, and it reads it below the declaration branches — so an
    entry whose item also compiles a rule would never be published.  Every
    entry's sentence is asserted to be the sentence the ladder publishes,
    which is the property a container of reviewed absences has to keep.
    """
    for name, reason in item_coverage.NO_RUNTIME_BEHAVIOR.items():
        assert _attacker(name).reason == reason, name


# The eight registries the collapse retired.  This is the one place in the tree
# that spells them, so the scan below reports nothing but a real survivor.
RETIRED_REGISTRIES: frozenset[str] = frozenset(
    {
        "_BLOCKED_REASONS",
        "_CALCULATION_ALLOWED_BLOCKED",
        "_PARTIAL_BLOCKED_REASONS",
        "_STATEFUL_MODELED_ITEMS",
        "_UTILITY_DIMENSIONS",
        "_TARGET_MODELED_REASONS",
        "_TARGET_EVENT_CERTIFIED_REASONS",
        "_TARGET_BLOCKED_REASONS",
    }
)


def whole_identifiers(text: str) -> set[str]:
    """Every maximal word run in a text — an identifier, never a substring.

    ``_BLOCKED_REASONS`` is a suffix of ``_TARGET_BLOCKED_REASONS``, so a
    substring scan would call the first one retired while the second still
    stood.  Splitting the text into whole runs and intersecting is what keeps
    the two answerable separately, and it is a *function* rather than an
    expression buried in an assertion so that the property has its own test.
    """
    return set(re.findall(r"\w+", text))


def source_occurrences(names: frozenset[str]) -> dict[str, frozenset[str]]:
    """Which of ``names`` each file under ``src/`` spells, as whole identifiers.

    Prose counts.  A retired registry named in a comment is not a live
    reference, but it is a name the tree still carries, and the cheapest way
    for a scan like this to stop being able to fail is for its subject to live
    on in prose "as documentation".
    """
    seen: dict[str, frozenset[str]] = {}
    for path in sorted((ROOT / "src").rglob("*.py")):
        hits = names & whole_identifiers(path.read_text(encoding="utf-8"))
        if hits:
            seen[path.relative_to(ROOT).as_posix()] = frozenset(hits)
    return seen


def test_the_eight_retired_registries_have_no_occurrences_left() -> None:
    """Ten registries collapsed to two, and gone is asserted rather than assumed.

    Three of the eight were empty and were asserted empty on the commit before
    their deletion; this is the other half for all eight — a source scan
    proving no reference survived anywhere in ``src/``, so the collapse cannot
    be true of the ladder and false of the imports.  The two that survive are
    named in the assertion below rather than left implicit, because "two" is
    the whole claim: ``NO_RUNTIME_BEHAVIOR``, which carries an absence no
    declaration can, and ``_REVIEW_ISSUE_REFS``, which carries a tracker id.

    The two tests after this one are not decoration.  This assertion measures a
    deletion that has already happened, which is the one shape that passes just
    as loudly when the instrument is broken: its first spelling put two literal
    U+0008 bytes where the word-boundary escape was intended, matched nothing
    in any file in the repository, and made its own ``== []`` a tautology for
    two commits — the campaign's failure shape inside the campaign's own gate.
    So the matcher and the reader each carry a red they can reproduce.
    """
    assert len(RETIRED_REGISTRIES) == 8
    assert hasattr(item_coverage, "NO_RUNTIME_BEHAVIOR")
    assert hasattr(item_coverage, "_REVIEW_ISSUE_REFS")

    assert source_occurrences(RETIRED_REGISTRIES) == {}


def test_the_retired_registry_matcher_reports_a_name_it_is_handed() -> None:
    """R-05's red for the matcher, permanent and reproducible on demand.

    A text fixture rather than a tree edit, for the reason the M1-M9 negatives
    already give: a gate whose red was demonstrated once during development is
    the unverifiable claim about the past this campaign outlaws.
    """
    assert RETIRED_REGISTRIES & whole_identifiers("x = _BLOCKED_REASONS[name]") == {
        "_BLOCKED_REASONS"
    }
    # Prose is an occurrence too.
    assert RETIRED_REGISTRIES & whole_identifiers(
        "# _UTILITY_DIMENSIONS stood here"
    ) == {"_UTILITY_DIMENSIONS"}
    # Whole identifiers, both directions: the shorter name does not match
    # inside the longer one, and a longer name containing it is not a hit.
    assert RETIRED_REGISTRIES & whole_identifiers("_TARGET_BLOCKED_REASONS = {}") == {
        "_TARGET_BLOCKED_REASONS"
    }
    assert (
        RETIRED_REGISTRIES & whole_identifiers("MY_BLOCKED_REASONS_TABLE = {}") == set()
    )


def test_the_retired_registry_scan_reads_the_package_it_claims_to_read() -> None:
    """R-05's red for the reader — the half a matcher fixture cannot cover.

    A scan over zero files reports zero occurrences exactly as convincingly as
    a clean tree does.  The control is a name that **is** in ``src/`` and is
    meant to stay — the surviving reviewed registry — found through the same
    glob, the same read and the same tokenizer the assertion above runs.  A
    moved package, a glob that stopped matching, or a read returning ``""``
    fails here instead of passing quietly there.
    """
    survivors = source_occurrences(frozenset({"NO_RUNTIME_BEHAVIOR"}))

    assert survivors["src/calculator/item_coverage.py"] == {"NO_RUNTIME_BEHAVIOR"}


# ── the numeric gate ──────────────────────────────────────────────────────
#
# Golden is near-vacuous for coverage: ``pipeline.py`` does not import
# ``item_coverage``, so per D-93 this phase has to name a non-golden numeric
# gate, and the committed classification receipt is it.  These two tests are
# that gate's live half — the receipt's shape, and a fresh capture against
# it — which is what turns "evidence added, nothing moved" from a sentence in
# a commit body into something a run either reproduces or does not.


def test_the_classification_receipt_holds_one_record_per_item_and_lane() -> None:
    """Criterion 1: the record count is read from the receipt's own metadata.

    ``item_count`` x ``len(lanes)``, out of **this** receipt.
    ``golden_baseline.json`` carries a field of the same name with the same
    value today, and reading it there would tie a coverage figure to the pair
    engine's data pull; the count has one home and this is the assertion that
    keeps it there.  It is a coverage-record count and not a golden leaf or
    entry count, so umbrella criterion 4 does not reach it.
    """
    receipt = json.loads(CLASSIFICATION_RECEIPT.read_text(encoding="utf-8"))
    metadata = receipt["metadata"]
    assert sorted(receipt["records"]) == metadata["lanes"]
    assert sum(len(lane) for lane in receipt["records"].values()) == (
        capture_coverage_classification.record_count(receipt)
    )
    for lane in receipt["records"].values():
        assert set(lane) == set(CACHE)


def test_a_fresh_classification_capture_on_the_tip_diffs_to_zero() -> None:
    """Criterion 1's other half: the phase moved no coverage record.

    The capture runs both classifiers over every cached item exactly as the
    instrument does, so a reason string, an eligibility flag, a dimension or
    an issue ref that moved anywhere in the corpus lands here as a named leaf.
    Provenance is excluded through the instrument's own constant — ``git_head``
    moves every commit and the fetch stamp moves on every data pull — and
    ``item_count`` is deliberately not in that set, because it is the gate.
    """
    baseline = json.loads(CLASSIFICATION_RECEIPT.read_text(encoding="utf-8"))
    fresh = capture_coverage_classification.capture()
    excluded = capture_coverage_classification.COMPARE_EXCLUDED_PROVENANCE
    assert "item_count" not in excluded
    for snapshot in (baseline, fresh):
        for key in excluded:
            snapshot["metadata"].pop(key, None)
    moved = capture_coverage_classification.differing_leaves(baseline, fresh)

    # 3.8's coverage flip moves records against the committed receipt, and
    # lands against it plus an allowlist rather than re-capturing inside a
    # semantic commit (R-32, R-36, D-97).  Every moved leaf must be in the
    # allowlist and the allowlist must hold no leaf that did not move: an
    # entry for a key that stopped moving is a stale permission, so the
    # spent ones are retired and the set is legitimately empty between
    # slices — which makes the assertion below an equality, not a subset.
    allowlists = [
        json.loads(path.read_text(encoding="utf-8")) for path in EXPECTED_COVERAGE_DIFFS
    ]
    permitted: set[str] = set()
    for lane_status, block in (
        item for allowlist in allowlists for item in allowlist["status_moves"].items()
    ):
        lane, move = lane_status.split(":")
        before, after = move.split("->")
        # Eligibility and the issue refs beside it are *functions* of the
        # status, so a move that crosses the refusal line drags them with it.
        # They are derived from the two status names rather than listed, which
        # is what keeps the permission exact: an eligibility flag that moved
        # under a status move that did not cross the line is still unlisted.
        dragged = ("status",)
        if (before in _REFUSAL_STATUSES) != (after in _REFUSAL_STATUSES):
            dragged += ("calculation_eligible", "review_issue_refs")
        permitted |= {
            f"records.{lane}.{name}.{leaf}"
            for name in block["items"]
            for leaf in dragged
        }
    permitted |= {
        f"records.{lane}.{name}.reason"
        for allowlist in allowlists
        for lane in ("attacker", "target")
        for name in allowlist["reason_moves"]["items"]
    }
    moved_paths = {leaf for leaf, _, _ in moved}

    # A subset and not an equality, deliberately: the allowlist stands while
    # the slice's commits are un-re-captured and empties the moment the
    # receipt is re-captured, exactly as the coupled-golden allowlist does.
    # Equality here would make the re-capture commit red by construction.
    assert moved_paths - permitted == set(), "a coverage record moved unlisted"
    assert len(moved) <= sum(allowlist["total_leaves"] for allowlist in allowlists)
    assert all(allowlist["unclassified"] == [] for allowlist in allowlists)


def test_the_capture_gate_names_the_record_that_moved() -> None:
    """The red this gate can reproduce on demand (R-05), as a permanent test.

    A comparison's negative is a comparison, so the fixture is the committed
    receipt with one published reason perturbed in memory — nothing is
    written and the receipt on disk is not touched.  A gate whose red was
    demonstrated once during development is the unverifiable claim about the
    past this campaign outlaws.
    """
    text = CLASSIFICATION_RECEIPT.read_text(encoding="utf-8")
    baseline = json.loads(text)
    perturbed = json.loads(text)
    item = sorted(perturbed["records"]["attacker"])[0]
    perturbed["records"]["attacker"][item]["reason"] = "a reason nobody published"
    assert capture_coverage_classification.differing_leaves(baseline, perturbed) == (
        (
            f"records.attacker.{item}.reason",
            baseline["records"]["attacker"][item]["reason"],
            "a reason nobody published",
        ),
    )


# ── the corpus, item by item ──────────────────────────────────────────────

CACHE = cached_items()

# The effect tags a live handler branches on, read off the dispatch sites
# rather than listed.  Their complement is what the frontier has to name.
# There are now two homes: ``item_effects``' effect-type ladder, and Phase 3's
# behaviour catalog for every tag whose behaviour has become a declaration.
# Reading only the ladder would report a migrated tag as undispatched on the
# commit that gave it a real home.
DISPATCHED_TAGS: frozenset[str] = (
    frozenset(
        tag
        for handler in ("item_effects._resolve_damage_effects_uncached",)
        for tag in coverage_resolver.tag_dispatch_branches(
            coverage_resolver.read_repo_file("src/calculator/item_effects.py"), handler
        )
    )
    | item_behavior_catalog.declared_tags()
) & _KNOWN_EFFECT_TYPES

FRONTIER_TAGS: frozenset[str] = frozenset(
    key.removeprefix("tag:") for key in FRONTIER if key.startswith("tag:")
)


def _static_context() -> ResolverContext:
    """The two seams that answer without a collected node set.

    Parametrization happens at import, before any session exists, and the
    populations below are parametrized over — so the walk that enumerates them
    reads the package and the tree and nothing pytest knows.  Node ids are the
    full-session tier's, and it uses ``live_context`` like everything else.
    """
    return ResolverContext(
        importer=importlib.import_module,
        read_source=coverage_resolver.read_repo_file,
        nodes={},
    )


def _audit_entry(item: str) -> dict:
    """One item's committed full-entry audit record."""
    return next(
        entry
        for entry in coverage_resolver.audit_entries(_static_context())
        if entry.get("name") == item
    )


def _cached_with_no_described_effect() -> tuple[str, ...]:
    """Every cached item whose Wiki record describes no passive or active."""
    return tuple(
        sorted(
            name
            for name, record in CACHE.items()
            if not item_coverage._has_described_effect(record)
        )
    )


def _cached_with_a_described_effect_nothing_declares() -> tuple[str, ...]:
    """Every cached item whose Wiki record describes an effect no family declares."""
    return tuple(
        sorted(
            name
            for name, record in CACHE.items()
            if item_coverage._has_described_effect(record)
            and not item_coverage._declared_families(name)
        )
    )


# ── one parametrized node per hand-listed entry ───────────────────────────


@pytest.mark.parametrize("item", sorted(item_coverage._ATTACKER_STATE_HOMES))
def test_a_stateful_item_supplies_its_state_from_a_named_home(item: str) -> None:
    """The state a ``modeled_state`` claim asserts is supplied has a home.

    Three routes, and the claim names which: a bounded scenario control, a
    packet the participant ledger schedules, or a sourced registry value.  An
    item that reached ``modeled_state`` with no home would be state the model
    *assumed*, which is the disposition this campaign refuses to let look like
    a computed one.
    """
    CACHE[item]
    assert _attacker(item).optimizer_eligible
    path, home = item_coverage._ATTACKER_STATE_HOMES[item]
    kind, _, value = home.partition(":")
    if kind == "option":
        control = ITEM_INPUT_OPTIONS[item]["options"][value]
        assert control["min"] <= control["default"] <= control["max"]
    elif kind == "packet":
        assert value in {
            capability.packet_source for capability in CAPABILITIES.values()
        }
    else:
        assert value in ITEM_EFFECTS[item]
    assert path


@pytest.mark.parametrize("item", sorted(item_coverage.NO_RUNTIME_BEHAVIOR))
def test_a_reviewed_stats_only_item_adds_no_outgoing_damage(item: str) -> None:
    """The review concluded the item is safe to score, and it still is.

    ``stats_only`` is a claim about a *review*, so what is checked is that the
    review's conclusion survives: the item is a ready full-entry audit record,
    and the optimiser may score it rather than withholding it.  A regression
    that starts blocking one of these fails here with the item's name.
    """
    CACHE[item]
    coverage = _attacker(item)
    assert coverage.optimizer_eligible
    assert coverage.calculation_eligible
    entry = _audit_entry(item)
    assert entry["status"] == "ready"


@pytest.mark.parametrize("item", sorted(ITEM_EFFECTS))
def test_an_item_effects_member_names_a_dispatched_or_frontiered_tag(item: str) -> None:
    """Every registry member's effect tag has a named disposition.

    This is the population backing for the ``ITEM_EFFECTS`` membership
    rule-claim — 123 members, one node each — and the property it pins is the
    one criterion 11 is about: a tag either reaches a live handler branch or
    sits on the frontier naming H4.  A new item carrying a tag that is neither
    fails here on the commit that adds it.
    """
    effect_type = ITEM_EFFECTS[item].get("type")
    assert effect_type in _KNOWN_EFFECT_TYPES
    assert effect_type in DISPATCHED_TAGS | FRONTIER_TAGS
    assert item in CACHE


@pytest.mark.parametrize("item", sorted(ITEM_INPUT_OPTIONS))
def test_an_item_input_options_member_declares_bounded_controls(item: str) -> None:
    """Every scenario control is bounded at both ends, or it is an assumption.

    The population backing for the ``ITEM_INPUT_OPTIONS`` membership
    rule-claim.  Two members declare no control at all — their state is an
    authored event rather than an input — and that is asserted rather than
    skipped over.
    """
    controls = ITEM_INPUT_OPTIONS[item].get("options", {})
    for name, control in controls.items():
        assert set(control) >= {"type", "default", "min", "max"}, name
        assert control["min"] <= control["default"] <= control["max"], name
    assert item in CACHE


@pytest.mark.parametrize("item", _cached_with_no_described_effect())
def test_an_item_with_no_described_effect_is_priced_only_by_what_it_declares(
    item: str,
) -> None:
    """The cached entry describes no passive or active, so there is none to model.

    A few such items still compile a rule from a registry entry — Vampiric
    Scepter's vampirism is a sustain declaration, not a Wiki passive — and
    those publish as modelled.  Every other one is ``stats_only`` for exactly
    the reason that nothing is described: an item that grew a passive and
    stayed here would be a mechanic nothing prices, reported as a reviewed
    absence.
    """
    record = CACHE[item]
    assert not item_coverage._has_described_effect(record)
    coverage = _attacker(item)
    if item_coverage._declared_families(item):
        assert coverage.status in {"modeled_effect", "modeled_state"}
    else:
        assert coverage.status == "stats_only"
        assert "no separate passive or active" in coverage.reason


@pytest.mark.parametrize("item", _cached_with_a_described_effect_nothing_declares())
def test_an_unreviewed_cached_record_is_blocked_with_issue_refs(item: str) -> None:
    """A cached record with an unreviewed effect is withheld, not scored as zero.

    The population is selected by the premise — a described passive or active
    that no rule and no registry entry declares — never by the ladder's answer,
    so the property runs forward: the campaign's own invariant at item scale is
    that such a record gets a named refusal carrying the issue that tracks it,
    never a number.  The two reviewed registries that may still admit one are
    each asserted by their own membership: a bounded scenario control prices as
    ``modeled_state`` and a reviewed absence as ``stats_only``.
    """
    record = CACHE[item]
    coverage = _attacker(item)
    assert record.get("id") is not None or record.get("icon")
    if item in ITEM_INPUT_OPTIONS:
        assert coverage.status == "modeled_state"
    elif item in item_coverage.NO_RUNTIME_BEHAVIOR:
        assert coverage.status == "stats_only"
    else:
        assert coverage.status == "withheld"
        assert not coverage.optimizer_eligible
        assert coverage.review_issue_refs


@pytest.mark.parametrize("item", sorted(item_coverage._TARGET_MODELED_IMPLS))
def test_a_target_modeled_item_is_admitted_by_the_target_model(item: str) -> None:
    """The passive-target model prices this item rather than withholding it."""
    record = CACHE[item]
    assert item_coverage.target_item_model_coverage(record)["status"] == "modeled"
    assert item_coverage.target_build_coverage([record])["complete"]


@pytest.mark.parametrize("item", sorted(item_coverage._TARGET_CERTIFIED_IMPLS))
def test_a_target_event_certified_item_needs_a_certified_timeline(item: str) -> None:
    """The conditional defense withholds rather than mis-timing its trigger.

    This is the mechanism the claim's ``certification_guard`` Symbol names,
    exercised per item: an uncertified timeline is refused by name, and a
    certified one is admitted.
    """
    record = CACHE[item]
    assert (
        item_coverage.target_item_model_coverage(record)["status"]
        == "modeled_event_certified"
    )
    with pytest.raises(ValueError, match=re.escape(item)):
        item_coverage.require_certified_target_timeline(
            [record], {"complete": False, "coarse_sources": ["authored rotation"]}
        )
    item_coverage.require_certified_target_timeline([record], {"complete": True})


def test_a_target_blocked_item_stops_the_run() -> None:
    """A withheld target record refuses the calculation by name.

    The population is not a table of one: since 3.8's flip the target lane
    passes the attacker ladder's refusal through, so every cached record
    whose described passive nothing declares stops a target build rather than
    being called irrelevant.  Guardian's Horn left the population when
    Undaunted got its declaration, so the whole population is checked as a
    set and nothing is named by hand.
    """
    refused = [
        name
        for name, record in CACHE.items()
        if item_coverage.target_item_model_coverage(record)["status"] == "withheld"
    ]
    assert "Guardian's Horn" not in refused
    for item in refused:
        record = CACHE[item]
        assert not item_coverage.target_item_model_coverage(record)[
            "calculation_eligible"
        ]
        with pytest.raises(ValueError, match=re.escape(item)):
            item_coverage.require_target_item_coverage([record])


@pytest.mark.parametrize("item", sorted(item_outcomes.UTILITY_OUTCOMES))
def test_a_utility_item_publishes_its_declared_dimensions(item: str) -> None:
    """The product-facing dimensions reach both public payloads, unchanged."""
    record = CACHE[item]
    declared = [dimension.value for dimension in item_outcomes.UTILITY_OUTCOMES[item]]
    assert _attacker(item).as_payload()["outcome_dimensions"] == declared
    assert (
        item_coverage.target_item_model_coverage(record)["outcome_dimensions"]
        == declared
    )
    assert set(declared) <= UTILITY_DIMENSIONS


@pytest.mark.parametrize("item", sorted(item_coverage._REVIEW_ISSUE_REFS))
def test_an_item_with_review_issues_publishes_them(item: str) -> None:
    """The tracker the declaration names is the tracker the payload publishes."""
    declared = list(item_coverage._REVIEW_ISSUE_REFS[item])
    assert item_coverage.review_issue_refs(item) == declared
    assert all(isinstance(ref, int) and ref > 0 for ref in declared)


# ── the corpus as a whole ─────────────────────────────────────────────────


def test_resolve_table_over_the_live_context_returns_no_failures() -> None:
    """Criterion 3: every evidence member of every claim resolves against this tree.

    This is the tier that makes the drift window one commit wide.  It runs on
    every ``pytest`` invocation, filtered or not, and it is the check that
    would have caught the incident: a claim describing two engine halves while
    one of them exists resolves to a failure here, by name.
    """
    assert coverage_resolver.resolve_table(COVERAGE_EVIDENCE, live_context()) == []


@pytest.mark.full_session
def test_resolve_table_passes_the_full_session_tier_too() -> None:
    """The same table with exact node ids, marker facts and duplicate detection."""
    failures = coverage_resolver.resolve_table(
        COVERAGE_EVIDENCE, live_context(), full_session=True
    )
    assert [str(failure) for failure in failures] == []


@pytest.mark.full_session
def test_every_cached_item_is_backed_by_a_claim_a_node_or_the_frontier() -> None:
    """Criterion 3's second half: no item is covered by a sentence alone.

    The ladder's populations are recomputed from ``data/`` on every call and
    cannot be enumerated at authoring time, so each cached item has to resolve
    to its own claim, to a collected parametrized node naming it, or to a
    frontier entry — the "one sentence covers everything" shape this phase
    exists to kill, checked over the whole shop.
    """
    nodes = coverage_resolver.collected_nodes()
    parametrized = [node for node in nodes if "[" in node]
    unbacked = [
        name
        for name in sorted(CACHE)
        if not any(key[1] == name for key in COVERAGE_EVIDENCE)
        and not any(key.startswith(f"item:{name}@") for key in FRONTIER)
        and not any(name in node[node.index("[") :] for node in parametrized)
    ]
    assert unbacked == []


def test_every_status_the_ladder_can_yield_is_reached_by_a_cached_item() -> None:
    """Emptiness is a pinned fact, not an absence nobody looked at (D-26).

    ``review_pending`` is reserved for a record the shop does not hold, so no
    cached item reaches it on either lane; every other status is reached.
    """
    attacker = {_attacker(name).status for name in CACHE}
    target = {target_item_model_coverage(record)["status"] for record in CACHE.values()}
    assert attacker == {"modeled_effect", "modeled_state", "stats_only", "withheld"}
    assert target == {
        "modeled",
        "modeled_event_certified",
        "not_target_relevant",
        "withheld",
    }


def test_every_hand_listed_entry_carries_exactly_one_claim_on_its_lane() -> None:
    """Criterion 4: unclaimed hand entries number zero, in six containers.

    The sixth container is ``_REVIEW_ISSUE_REFS``, whose entries are covered
    by the ``issue_refs`` of exactly one claim about that item rather than by a
    claim of their own — the refs have one home per item, which is the same
    rule the load gate applies to a negative claim's ``Absence``.
    """
    lanes = (
        ("_ATTACKER_STATE_HOMES", item_coverage._ATTACKER_STATE_HOMES, "attacker"),
        ("NO_RUNTIME_BEHAVIOR", item_coverage.NO_RUNTIME_BEHAVIOR, "attacker"),
        ("_TARGET_MODELED_IMPLS", item_coverage._TARGET_MODELED_IMPLS, "target"),
        ("_TARGET_CERTIFIED_IMPLS", item_coverage._TARGET_CERTIFIED_IMPLS, "target"),
        ("UTILITY_OUTCOMES", item_coverage.UTILITY_OUTCOMES, "utility"),
    )
    unclaimed: list[str] = []
    for container_name, container, lane in lanes:
        unclaimed.extend(
            f"{container_name}:{item}"
            for item in container
            if ("item", item, lane) not in COVERAGE_EVIDENCE
        )
    for item, refs in item_coverage._REVIEW_ISSUE_REFS.items():
        carriers = [
            key
            for key, claim in COVERAGE_EVIDENCE.items()
            if key[1] == item and claim.issue_refs == tuple(refs)
        ]
        if len(carriers) != 1:
            unclaimed.append(f"_REVIEW_ISSUE_REFS:{item} carried by {carriers}")
    assert unclaimed == []
    assert len(COVERAGE_EVIDENCE) == len(
        {
            (claim.subject_kind, claim.subject, claim.lane)
            for claim in COVERAGE_EVIDENCE.values()
        }
    )


def test_the_issue_ref_carrier_is_derived_from_the_item_s_own_claim_lanes() -> None:
    """Which claim carries a review's issues is assembly, not evidence.

    The hand table that answered this per item is gone: the lanes are ranked
    once and the item's own lanes are read off the containers ``_corpus``
    builds from.  This asserts the derivation against the corpus that came out
    of it — every tracked item's refs sit on the first ranked lane it has a
    claim on, and on no other.
    """
    misrouted: list[str] = []
    for item, refs in item_coverage._REVIEW_ISSUE_REFS.items():
        lanes = {
            key[2] for key in COVERAGE_EVIDENCE if key[0] == "item" and key[1] == item
        }
        expected = next(
            lane for lane, _ in item_coverage._CLAIM_LANE_SOURCES if lane in lanes
        )
        carrying = sorted(
            key[2]
            for key, claim in COVERAGE_EVIDENCE.items()
            if key[1] == item and claim.issue_refs == tuple(refs)
        )
        if carrying != [expected]:
            misrouted.append(f"{item}: {carrying} carry refs, expected [{expected}]")
    assert misrouted == []


def test_a_tracked_review_on_no_claim_lane_stops_the_corpus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R-05's red for the routing check, reproducible on demand.

    A ref routed nowhere would be published by ``review_issue_refs`` and
    carried by no claim — a tracked gap with no receipt.  The load tier
    refuses it rather than letting the corpus assemble around it.
    """
    monkeypatch.setattr(
        item_coverage,
        "_REVIEW_ISSUE_REFS",
        {**item_coverage._REVIEW_ISSUE_REFS, "Elixir of Iron": (40,)},
    )
    with pytest.raises(CoverageClaimError, match="Elixir of Iron"):
        item_coverage._validate_issue_ref_routing()


def test_claim_status_is_a_pinned_expectation_the_classifier_agrees_with() -> None:
    """The classifier stays the only authority; the claim is checked against it."""
    classifier = {
        "attacker": _attacker_payload,
        "target": item_coverage.target_item_model_coverage,
    }
    disagreements: list[str] = []
    for (kind, subject, lane), claim in COVERAGE_EVIDENCE.items():
        if kind != "item" or lane not in classifier:
            continue
        if classifier[lane](CACHE[subject])["status"] != claim.status:
            disagreements.append(f"{subject}@{lane}")
    assert disagreements == []


def test_no_src_module_reads_the_corpus_or_a_claims_status() -> None:
    """The load gate is the only reader; nothing in ``src`` consumes a claim.

    ``Claim.status`` is a pinned expectation and never an authority, and the
    way that is kept true is that no production code can see it: the corpus is
    read by its own import-time ``validate_claim_table`` guard and by nothing
    else in ``src``.
    """
    guarded = {
        node.args[0].lineno
        for path in sorted((ROOT / "src").rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "validate_claim_table"
        and node.args
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "COVERAGE_EVIDENCE"
    }
    readers = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "COVERAGE_EVIDENCE" not in text:
            continue
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Name) or node.id != "COVERAGE_EVIDENCE":
                continue
            if isinstance(node.ctx, ast.Store) or node.lineno in guarded:
                continue
            readers.append(f"{path.name}:{node.lineno}")
    assert readers == []


def test_every_split_mechanic_is_claimed_with_both_sides() -> None:
    """Criterion 9: dual-sided evidence resolves against Phase 2, not a name list.

    The pairing-exception set is asserted **empty** (D-92): the next divergence
    has to be a typed entry pointing at a receipt, never a silent omission.
    """
    split_owners = {
        capability.owner.name
        for capability in CAPABILITIES.values()
        if capability.authority.name == "SPLIT" and capability.pair_of
    }
    assert split_owners
    for item in sorted(split_owners):
        claim = COVERAGE_EVIDENCE[("item", item, "support_packet")]
        assert any(isinstance(member, PairedSides) for member in claim.evidence), item
    assert [
        capability.mechanic
        for capability in CAPABILITIES.values()
        if capability.pairing.name == "UNPAIRED_KNOWN_DEFECT"
    ] == []


def test_the_effect_tag_union_is_total() -> None:
    """Criterion 11: every declared tag has a handler branch or names H4."""
    assert DISPATCHED_TAGS | FRONTIER_TAGS == _KNOWN_EFFECT_TYPES
    assert not DISPATCHED_TAGS & FRONTIER_TAGS
    assert all("H4" in FRONTIER[f"tag:{tag}"] for tag in FRONTIER_TAGS)


def test_every_declared_dimension_is_a_member_of_the_closed_set() -> None:
    """Criterion 12: set equality, and every claim's dimensions inside it."""
    measured = {
        dimension.value
        for dimensions in item_outcomes.UTILITY_OUTCOMES.values()
        for dimension in dimensions
    }
    assert measured == UTILITY_DIMENSIONS
    for claim in COVERAGE_EVIDENCE.values():
        assert set(claim.dimensions) <= UTILITY_DIMENSIONS
    for item, dimensions in item_outcomes.UTILITY_OUTCOMES.items():
        claim = COVERAGE_EVIDENCE[("item", item, "utility")]
        assert claim.dimensions == tuple(dimension.value for dimension in dimensions)


def test_the_frontier_holds_no_damage_or_durability_lane_and_every_entry_is_tracked() -> (
    None
):
    """Criterion 14: the escape hatch cannot absorb an attacker or target claim.

    "No such lane at all" is the version of that rule a test can check without
    deciding what "prices damage" means, and it is strictly stronger than the
    criterion asks for.  Every reason carries the issue that tracks it.
    """
    for key, reason in FRONTIER.items():
        assert not key.endswith("@attacker"), key
        assert not key.endswith("@target"), key
        assert re.search(r"#\d+", reason), key
    assert not set(FRONTIER) & {
        f"{kind}:{subject}@{lane}" for kind, subject, lane in COVERAGE_EVIDENCE
    }


# ── M1–M9: nine mutations, none of which is an edit ───────────────────────
#
# Every one of the nine describes a tree this repository does not have and
# hands it to the resolver through a seam, so the suite that proves a broken
# claim is noticed never writes a byte.  Each case runs twice over: the
# member resolves against the **live** tree first, which is what makes the
# real mutation — renaming the accessor in ``src/`` — turn this suite red,
# and then against the mutated one, which is what proves the tier is the
# thing that noticed.  A case asserting only the failure would pass just as
# happily if the member had never resolved at all.

MANDATE_SPLIT_CLAIM = COVERAGE_EVIDENCE[("item", "Imperial Mandate", "support_packet")]
COMMAND_PACKET = "Imperial Mandate — Command"
# The accessor Command's numbers now arrive through.  Phase 3's amp slice
# deleted the bespoke ``item_effects.command_amp_effect`` compiler: the rule
# is declared once for both engines and its ``ValueRef``s read the same
# ``ALLY_ITEM_EFFECTS`` record through this accessor.  M1's question is
# unchanged — rename the thing the pair-engine half reads its number through
# and every sentence about Command stays true while the number goes.
COMMAND_ACCESSOR = "item_effects.ally_item_effect_value"
SUPPORT_MODULE = "src/calculator/item_support_effects.py"
EFFECTS_MODULE = "src/calculator/item_effects.py"
CATALOG_MODULE = "src/calculator/item_behavior_catalog.py"

# The files the nine mutations describe.  They are hashed either side of the
# suite, because "driven through the seams" is a claim about these bytes.
MUTATED_FILES: tuple[str, ...] = (
    EFFECTS_MODULE,
    CATALOG_MODULE,
    "src/calculator/damage.py",
    SUPPORT_MODULE,
    "src/calculator/trigger_stream.py",
    "tests/test_f0_frontend.py",
)


def _plus(claim: Claim, member) -> Claim:
    """The live claim, plus the one member a mutation is about."""
    return dataclasses.replace(claim, evidence=(*claim.evidence, member))


def _only(claim: Claim, kind: type):
    """The claim's single member of one evidence kind."""
    return next(member for member in claim.evidence if isinstance(member, kind))


def _importer_without(module: str, attribute: str):
    """An importer for which *module* does not define *attribute*.

    A rename is indistinguishable from a deletion as far as a claim naming
    the old name is concerned, so one shim serves M1 and M2 both.
    """
    real = importlib.import_module(f"{coverage_resolver.PACKAGE}.{module}")

    class _Renamed:
        """The module as it would be after the rename."""

        def __getattr__(self, name: str) -> object:
            if name == attribute:
                raise AttributeError(name)
            return getattr(real, name)

    shim = _Renamed()

    def importer(name: str) -> object:
        if name == f"{coverage_resolver.PACKAGE}.{module}":
            return shim
        return importlib.import_module(name)

    return importer


def _read_source_with(path: str, text: str):
    """The live tree with one module's text replaced by *text*."""

    def read_source(wanted: str) -> str:
        return text if wanted == path else coverage_resolver.read_repo_file(wanted)

    return read_source


def _packet_call_without_owner(text: str, source: str) -> str:
    """One packet's ``owner=`` keyword deleted, and nobody else's.

    Line-precise rather than a textual sweep: five packets declare ``owner=``
    and the claim under test is about one of them, so a global replace would
    prove the tier notices *some* missing owner rather than this one's.
    """
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.Call):
            continue
        keywords = {keyword.arg: keyword for keyword in node.keywords if keyword.arg}
        if "source" not in keywords:
            continue
        if coverage_resolver.render_source_argument(keywords["source"].value) != source:
            continue
        owner = keywords["owner"]
        lines = text.splitlines(keepends=True)
        del lines[owner.lineno - 1 : owner.end_lineno]
        return "".join(lines)
    raise AssertionError(f"no packet call carries source={source!r}")


def test_M1_renaming_the_pair_engine_effect_accessor_is_noticed() -> None:
    """M1: the accessor Command's pair-engine half reads its number through.

    The incident's first layer.  ``damage._apply_command_amp`` prices the
    holder's own amp from the ``imperial_mandate.command`` declaration, whose
    ``ValueRef``s read the sourced fraction through
    ``item_effects.ally_item_effect_value``, and a rename there leaves every
    sentence about Command looking true and the number gone.
    """
    accessor = Symbol(path=COMMAND_ACCESSOR, role="value_accessor")
    claim = _plus(MANDATE_SPLIT_CLAIM, accessor)
    coverage_resolver.resolve(accessor, claim, _live())

    renamed = dataclasses.replace(
        _live(), importer=_importer_without("item_effects", "ally_item_effect_value")
    )
    with pytest.raises(EvidenceUnresolved, match="names no 'ally_item_effect_value'"):
        coverage_resolver.resolve(accessor, claim, renamed)


def test_M2_deleting_the_pair_side_pricer_is_noticed() -> None:
    """M2: the pair half's ``impl`` is gone and the walk half is intact.

    Nothing on the claim spells ``damage._apply_command_amp``; the capability
    registry does, and ``PairedSides`` resolves both halves through it.  That
    is the point — a hand list agreeing with the surviving half is what the
    incident shipped.
    """
    sides = _only(MANDATE_SPLIT_CLAIM, PairedSides)
    coverage_resolver.resolve(sides, MANDATE_SPLIT_CLAIM, _live())

    deleted = dataclasses.replace(
        _live(), importer=_importer_without("damage", "_apply_command_amp")
    )
    with pytest.raises(
        EvidenceUnresolved,
        match=re.escape("imperial_mandate.command_preview implements"),
    ):
        coverage_resolver.resolve(sides, MANDATE_SPLIT_CLAIM, deleted)


def test_M3_removing_the_command_packet_literal_is_noticed() -> None:
    """M3: the walk half stops emitting the receipt the claim quotes."""
    packet = _only(MANDATE_SPLIT_CLAIM, PacketSource)
    assert packet.source == COMMAND_PACKET
    coverage_resolver.resolve(packet, MANDATE_SPLIT_CLAIM, _live())

    text = coverage_resolver.read_repo_file(SUPPORT_MODULE)
    without = text.replace(f'source="{COMMAND_PACKET}"', 'source="Imperial Mandate"')
    assert without != text
    removed = dataclasses.replace(
        _live(), read_source=_read_source_with(SUPPORT_MODULE, without)
    )
    with pytest.raises(EvidenceUnresolved, match="is not a source= argument"):
        coverage_resolver.resolve(packet, MANDATE_SPLIT_CLAIM, removed)


def test_M4_dropping_owner_from_a_dual_sided_packet_is_noticed() -> None:
    """M4: the packet still exists and the handshake it declared is gone.

    ``owner=`` is the whole of the walk's promise to skip the holder because
    the holder's own engine prices that half.  Dropping it makes two engines
    price one participant with nothing in the payload changed — which is why
    the claim declares the policy and the tier reads the call site.
    """
    sides = _only(MANDATE_SPLIT_CLAIM, PairedSides)
    assert sides.owner_policy == "owner_skips_holder"

    text = coverage_resolver.read_repo_file(SUPPORT_MODULE)
    unowned = _packet_call_without_owner(text, COMMAND_PACKET)
    assert unowned != text
    dropped = dataclasses.replace(
        _live(), read_source=_read_source_with(SUPPORT_MODULE, unowned)
    )
    with pytest.raises(EvidenceUnresolved, match=re.escape("to declare owner=")):
        coverage_resolver.resolve(sides, MANDATE_SPLIT_CLAIM, dropped)


def test_M5_clearing_a_pair_of_leaves_the_dual_sided_claim_unresolved() -> None:
    """M5: a registry with one half's link to the other cleared.

    ``pair_of`` is the only field that says the two engines are pricing one
    mechanic.  Clearing it is exactly the incident — a coverage claim naming
    both sides while only one exists — and it has to fail without any source
    file being touched.
    """
    sides = _only(MANDATE_SPLIT_CLAIM, PairedSides)
    live = _live()
    real = live.importer(f"{coverage_resolver.PACKAGE}.trigger_stream")
    unpaired = dict(CAPABILITIES)
    unpaired["imperial_mandate.command"] = dataclasses.replace(
        CAPABILITIES["imperial_mandate.command"], pair_of=None
    )

    class _Registry:
        """``trigger_stream`` with one capability's pair link cleared."""

        CAPABILITIES = unpaired

    def importer(name: str) -> object:
        return _Registry if name.endswith("trigger_stream") else real

    cleared = dataclasses.replace(live, importer=importer)
    with pytest.raises(EvidenceUnresolved, match="declares no pair_of"):
        coverage_resolver.resolve(sides, MANDATE_SPLIT_CLAIM, cleared)


def test_M6_renaming_an_effect_tag_is_noticed() -> None:
    """M6: the tag survives in the data and the handler stops branching on it.

    A renamed tag reclassifies every item carrying it with no other signal —
    the registry still declares the name, so only the dispatch says whether
    anything reads it.

    The dispatch is the catalog compiler since SD9 retired the ladder's
    ``execute`` branch, and mutating that file is what makes the premise
    exact: the tag's own registry entry lives in ``item_effects`` and is
    untouched here, so the data really does keep the name the handler stopped
    reading.
    """
    tag = EffectTag(
        tag="execute", handler="item_behavior_catalog._compile_damage_routing"
    )
    coverage_resolver.resolve(tag, MANDATE_SPLIT_CLAIM, _live())

    text = coverage_resolver.read_repo_file(CATALOG_MODULE)
    renamed = text.replace('if tag == "execute"', 'if tag == "execute_bonus"')
    assert renamed != text
    assert '"execute"' in coverage_resolver.read_repo_file(EFFECTS_MODULE)
    mutated = dataclasses.replace(
        _live(), read_source=_read_source_with(CATALOG_MODULE, renamed)
    )
    with pytest.raises(EvidenceUnresolved, match="does not branch on 'execute'"):
        coverage_resolver.resolve(tag, MANDATE_SPLIT_CLAIM, mutated)


def test_M7_a_dangling_test_ref_is_noticed_in_both_tiers() -> None:
    """M7: the node the claim names is not in this tree at all.

    Both tiers answer, and they answer differently on purpose: the full
    session knows what was collected, and a filtered one falls back to the
    source, which a ``-k`` expression cannot change.
    """
    ref = _only(MANDATE_SPLIT_CLAIM, TestRef)
    ctx = live_context()
    resolve_test_ref(
        ref, MANDATE_SPLIT_CLAIM, ctx, full_session=coverage_resolver.full_session()
    )

    dangling = TestRef(node_id=f"{ref.node_id}_no_such_node")
    with pytest.raises(EvidenceUnresolved, match="names no collected node"):
        resolve_test_ref(dangling, MANDATE_SPLIT_CLAIM, ctx, full_session=True)
    with pytest.raises(EvidenceUnresolved, match="does not define"):
        resolve_test_ref(dangling, MANDATE_SPLIT_CLAIM, ctx, full_session=False)


def test_M8_a_skip_guarded_test_ref_is_noticed() -> None:
    """M8: the node exists, carries no skip marker, and skips itself.

    ``pytest.skip`` inside the body is the shape rule 4 exists for: the node
    reports green on a machine where its assertions never ran.
    """
    guarded = TestRef(
        node_id="tests/test_f0_frontend.py::test_node_check_passes_for_app_js"
    )
    with pytest.raises(EvidenceUnresolved, match=re.escape("its body calls")):
        resolve_test_ref(
            guarded,
            MANDATE_SPLIT_CLAIM,
            live_context(),
            full_session=coverage_resolver.full_session(),
        )


def test_M9_an_irrelevant_test_ref_is_noticed() -> None:
    """M9: a node that resolves, cannot be skipped, and is about nothing.

    Rule 5, and the reason it exists: without it one collected, unskipped
    node backs every claim in the table.
    """
    unrelated = TestRef(
        node_id="tests/test_resistance.py::TestApplyResistance::test_zero_resistance"
    )
    with pytest.raises(
        EvidenceUnresolved, match="mentions none of the claim's strings"
    ):
        resolve_test_ref(
            unrelated,
            MANDATE_SPLIT_CLAIM,
            live_context(),
            full_session=coverage_resolver.full_session(),
        )


M_SUITE = (
    test_M1_renaming_the_pair_engine_effect_accessor_is_noticed,
    test_M2_deleting_the_pair_side_pricer_is_noticed,
    test_M3_removing_the_command_packet_literal_is_noticed,
    test_M4_dropping_owner_from_a_dual_sided_packet_is_noticed,
    test_M5_clearing_a_pair_of_leaves_the_dual_sided_claim_unresolved,
    test_M6_renaming_an_effect_tag_is_noticed,
    test_M7_a_dangling_test_ref_is_noticed_in_both_tiers,
    test_M8_a_skip_guarded_test_ref_is_noticed,
    test_M9_an_irrelevant_test_ref_is_noticed,
)


def test_the_mutation_suite_is_nine_mutations_that_write_nothing() -> None:
    """Criterion 10: nine of them, and the tree they describe is untouched.

    The digests are the whole assertion.  "Driven through the seams" is a
    claim about bytes on disk, and a suite that edited a file and put it back
    would satisfy every other test in this module.
    """
    assert [case.__name__.split("_")[1] for case in M_SUITE] == [
        f"M{index}" for index in range(1, 10)
    ]
    before = {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in MUTATED_FILES
    }
    for case in M_SUITE:
        case()
    assert {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in MUTATED_FILES
    } == before


def test_the_receipt_names_a_producer_a_reader_can_look_up() -> None:
    """The receipt's provenance is derived from the functions, not typed.

    A hand-written ``metadata.classifiers`` map — the shape the attacker
    lane's lambda invites — survives the rename of the thing it names: the
    receipt would go on citing a symbol nothing defines, and every gate over
    it would stay green.  The names come off the wrapped functions, and this
    asserts what that buys — each one resolves to a callable on the module
    the receipt says it is on.
    """
    receipt = json.loads(CLASSIFICATION_RECEIPT.read_text(encoding="utf-8"))
    recorded = receipt["metadata"]["classifiers"]

    assert set(recorded) == set(capture_coverage_classification.CLASSIFIERS)
    assert set(capture_coverage_classification.CLASSIFIER_NAMES) == set(recorded)
    for lane, dotted in recorded.items():
        module, _, symbol = dotted.rpartition(".")
        assert module == "src.calculator.item_coverage", lane
        resolved = getattr(item_coverage, symbol)  # sightline-ok: 24 - receipt symbol
        assert callable(resolved), dotted
        assert symbol == capture_coverage_classification.CLASSIFIER_NAMES[lane]
