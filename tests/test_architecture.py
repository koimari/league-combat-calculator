"""Static guards for high-value module boundaries."""

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from src.calculator.item_effects import _REFERENCE_ITEM_EFFECTS
from tests.coverage_resolver import front_door_report

ROOT = Path(__file__).parents[1]
SRC_ROOT = ROOT / "src" / "calculator"
TEST_ROOT = ROOT / "tests"

DAMAGE_PATH = ROOT / "src" / "calculator" / "damage.py"


@dataclass(frozen=True, slots=True)
class FrontierEntry:
    """Why a module has no importing test module, and who owes it one."""

    owning_phase: str
    reason: str


# The modules `front_door_report` finds today, each with the reason it has no
# importing test module and the phase that owes it one.  The frontier lives
# here, in the consumer, and never inside the tool that measures it — a
# frontier the measuring tool owns can be driven to zero by editing the tool.
#
# It is pinned by **set equality**, so it shrinks by edit and never silently
# grows: a module that gains a front door leaves in the same commit, and one
# that loses a front door is entered here with a reason and an owner.
FRONT_DOOR_FRONTIER: Mapping[str, FrontierEntry] = {
    "application_errors": FrontierEntry(
        owning_phase="none — pre-campaign debt",
        reason=(
            "the exception vocabulary src/app.py and optimizer.py raise; every "
            "assertion about it runs through an app response instead"
        ),
    ),
    # `comparison` left this frontier by ceasing to exist: `compare_payload`
    # is thirty lines that call `calculate_payload` twice, and it moved into
    # `calculate.py` beside the comparison curves that module already owns.
    # A module whose one symbol has one caller was never a boundary of its
    # own, and the frontier row it needed is the receipt for that.
    "practice_dummy": FrontierEntry(
        owning_phase="none — pre-campaign debt",
        reason=(
            "the practice-target preset, reached only through scenario.py, "
            "whose suite exercises it through a parsed scenario"
        ),
    ),
    # `request_parsing` left this frontier when the optional-integer sibling
    # arrived: `tests/test_request_parsing.py` imports the module to pin the
    # sentinel set (`None` and `""`, never 0) that three optimize fields had
    # each been spelling inline, and a sentinel policy exercised only through
    # an endpoint is a policy nobody has watched decide.
    # `survival.receipt_state` left this frontier at Phase 4 S4, which is what
    # a member closing looks like: the stage that gave `ReceiptLedger` its
    # injected `compile_event` also gave the module an importing test module
    # (`tests/test_program_structure.py`, the one-direction assertions), so the
    # derivation stopped reporting it and the row had to go in the same commit.
    # It is recorded here as a comment rather than silently deleted because the
    # set is the receipt: a member that leaves without a sentence saying why is
    # indistinguishable from a member somebody deleted to make a gate pass.
    # `healing_legacy` left this frontier at the heal-anchor slice, when the
    # self-heal rules gained a declared anchor: `tests/test_healing.py` imports `HealAnchor` and
    # `_payments` to pin what each rule pays on -- a cast, a hit that dealt
    # damage, or a tick schedule of its own -- so the module that had been
    # covered by behaviour without being named is named.
    # `survival.score_state` left this frontier at Phase 4 S10, the last of
    # the six `survival/` members the phase closes (criterion 18).  Its front
    # door is `tests/test_score_state.py`, and writing one was the work: the
    # score ledger's contract is almost entirely refusals -- it records one
    # thing, annotates nothing, and raises rather than scheduling a
    # walk-authored heal -- and a refusal exercised only through a coupled
    # request is a refusal nobody has watched fire.  Recorded here as a
    # comment rather than silently deleted, for the reason the receipt_state
    # note above gives: the set is the receipt, and a member that leaves
    # without a sentence saying why is indistinguishable from a member
    # somebody deleted to make a gate pass.
}


def test_damage_engine_does_not_read_item_registry() -> None:
    """Registry dictionaries belong to item_effects, never damage.py."""
    source = DAMAGE_PATH.read_text(encoding="utf-8")
    assert "ITEM_EFFECTS" not in source


def test_damage_engine_does_not_dispatch_on_item_names() -> None:
    """Item identity compiles into typed effects before engine execution."""
    tree = ast.parse(DAMAGE_PATH.read_text(encoding="utf-8"))
    item_names = frozenset(_REFERENCE_ITEM_EFFECTS)
    offenders: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        compared = [node.left, *node.comparators]
        for value in compared:
            if isinstance(value, ast.Constant) and value.value in item_names:
                offenders.append((node.lineno, value.value))

    assert offenders == []


def test_every_module_outside_champions_has_a_front_door_or_a_frontier_entry() -> None:
    """D-95: the front-door registry is derived, and this is what it says.

    Set equality in both directions.  A module that gains a front door has to
    leave the frontier in the same commit, and a module that loses one has to
    be entered with a reason and an owner — the point of a derived registry is
    that neither move can be silent.
    """
    report = front_door_report(SRC_ROOT, TEST_ROOT)
    assert {missing.module for missing in report} == set(FRONT_DOOR_FRONTIER)
    for missing in report:
        assert (ROOT / missing.path).is_file(), missing.path


def test_every_frontier_entry_carries_a_reason_and_an_owner() -> None:
    """A frontier entry is a receipt, not a suppression."""
    for module, entry in FRONT_DOOR_FRONTIER.items():
        assert entry.reason.strip(), module
        assert entry.owning_phase.strip(), module


def test_the_survey_covers_more_than_the_filename_convention_it_replaced() -> None:
    """The other half of D-95: a front door is an import, not a filename.

    The registry this replaced was a tuple of eleven module names checked
    against `tests/test_<module>.py` existing.  A file whose name matches
    proves nothing about what it imports, and eleven hand-chosen names prove
    nothing about the rest of the package — so the property asserted now is
    the one the tuple could not state: every module outside `champions/` is
    either imported by a test module or carries a frontier entry, with the
    denominator read off the tree rather than typed.
    """
    surveyed = {
        ".".join(path.relative_to(SRC_ROOT).with_suffix("").parts)
        for path in SRC_ROOT.rglob("*.py")
        if path.name != "__init__.py"
        and path.relative_to(SRC_ROOT).parts[0] != "champions"
    }
    reported = {missing.module for missing in front_door_report(SRC_ROOT, TEST_ROOT)}
    assert set(FRONT_DOOR_FRONTIER) <= surveyed
    assert reported <= surveyed
    assert surveyed - reported


# SC9: the pre-combat stat surface had three recipes -- a roster card
# resolved without `external_stat_bonuses`, the coupled capture without
# `rune_page`, the request path with both -- and every omission read as a
# default rather than as a decision.  The recipe now has one home and the
# read off a request has one home; these two names are what the guards below
# hold the tree to.
PRE_COMBAT_RECIPE_HOME = "calculator.stats.resolve_pre_combat_stats"
PRE_COMBAT_PARAMS_READ = "calculator.pipeline.FightParams.pre_combat_stats"

# The inputs that make a stat block a *build's* rather than a champion's.  A
# call passing none of them is the level-and-items block three harnesses ask
# for and is not this surface.
BUILD_CONTEXT_KEYWORDS = frozenset(
    {
        "item_options",
        "role",
        "role_quest_complete",
        "external_stat_bonuses",
        "rune_page",
    }
)

# Every surface that composes a participant's stats as combat begins, and the
# helper it reaches the recipe through: the module function directly when it
# holds no request, the FightParams read when it does.
PRE_COMBAT_SURFACES: Mapping[str, str] = {
    "calculator.scenario.ChampionLoadout.resolve": "resolve_pre_combat_stats",
    "calculator.calculate._combat_receipt": "pre_combat_stats",
    "calculator.optimizer._evaluate_build_uncached": "pre_combat_stats",
    "calculator.pipeline.run_fight": "pre_combat_stats",
    "golden_snapshot._coupled_receipt": "pre_combat_stats",
}


def _called_name(node: ast.Call) -> str:
    """What one call expression spells, bare name or dotted attribute alike."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _calls_by_scope(path: Path, module: str) -> list[tuple[str, ast.Call]]:
    """Every call expression in one module, tagged with the def enclosing it."""
    found: list[tuple[str, ast.Call]] = []

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(child, f"{scope}.{child.name}")
                continue
            if isinstance(child, ast.Call):
                found.append((scope, child))
            visit(child, scope)

    visit(ast.parse(path.read_text(encoding="utf-8")), module)
    return found


def _scanned_scopes() -> list[tuple[str, ast.Call]]:
    """Calls in `src/calculator` and in the capture harnesses beside it.

    `scripts/` is scanned because the drift this guards against happened
    there: `golden_snapshot._coupled_receipt` calls itself a mirror of the
    request path's composition, and a src-only scan is exactly the reading
    under which it stayed one for a campaign while missing an input.
    """
    scoped: list[tuple[str, ast.Call]] = []
    for path in sorted(SRC_ROOT.rglob("*.py"), key=lambda item: item.as_posix()):
        module = ".".join(path.relative_to(SRC_ROOT.parent).with_suffix("").parts)
        scoped.extend(_calls_by_scope(path, module))
    for path in sorted((ROOT / "scripts").glob("*.py"), key=lambda item: item.name):
        scoped.extend(_calls_by_scope(path, path.stem))
    return scoped


def _recipe_sites() -> dict[str, int]:
    """Where a build-context `calculate_total_stats` call is written."""
    sites: dict[str, int] = {}
    for scope, call in _scanned_scopes():
        if _called_name(call) != "calculate_total_stats":
            continue
        supplied = {keyword.arg for keyword in call.keywords if keyword.arg}
        if BUILD_CONTEXT_KEYWORDS & supplied:
            sites[scope] = sites.get(scope, 0) + 1

    return sites


def test_the_pre_combat_stat_recipe_is_written_in_exactly_one_place() -> None:
    """SC9: one composition, so no surface can drop an input by omission."""
    assert _recipe_sites() == {PRE_COMBAT_RECIPE_HOME: 1}


def test_the_one_recipe_states_every_input_and_the_request_read_answers_all_of_them():
    """Both halves, so neither guard above can pass vacuously.

    A helper that named three of the five inputs would satisfy the site count
    while leaving the other two to a default -- which is the failure, not the
    fix -- and a `FightParams` read that answered only some of them would put
    the same silence one call deeper.
    """
    (recipe,) = [
        call
        for scope, call in _scanned_scopes()
        if scope == PRE_COMBAT_RECIPE_HOME
        and _called_name(call) == "calculate_total_stats"
    ]
    assert {keyword.arg for keyword in recipe.keywords} == BUILD_CONTEXT_KEYWORDS
    (request_read,) = [
        call
        for scope, call in _scanned_scopes()
        if scope == PRE_COMBAT_PARAMS_READ
        and _called_name(call) == "resolve_pre_combat_stats"
    ]
    assert {keyword.arg for keyword in request_read.keywords} == BUILD_CONTEXT_KEYWORDS


def test_every_pre_combat_surface_routes_through_the_one_helper() -> None:
    """The three recipes SC9 named, plus the two that shared one of them."""
    routed: dict[str, set[str]] = {scope: set() for scope in PRE_COMBAT_SURFACES}
    for scope, call in _scanned_scopes():
        if scope in routed:
            routed[scope].add(_called_name(call))
    for scope, helper in PRE_COMBAT_SURFACES.items():
        assert helper in routed[scope], scope
