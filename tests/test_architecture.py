"""Static guards for high-value module boundaries."""

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from src.calculator.item_effects import _OFFLINE_ITEM_EFFECTS
from tests.coverage_resolver import front_door_report

ROOT = Path(__file__).parents[1]
SRC_ROOT = ROOT / "src" / "calculator"
TEST_ROOT = ROOT / "tests"

# These modules are large enough to need a named entry point.  The older
# campaign suites remain in place because their issue history is useful when
# a regression is investigated.
SUBSTANTIAL_MODULE_FRONT_DOORS = (
    "passive_parser",
    "healing",
    "rotation_resolver",
    "capabilities",
    "bis",
    "public_response",
    "atomizer_domains",
    "loadout_rules",
    "auto_attack_policy",
    "data_registry",
    "economics_data",
)
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
# grows.  It has shrunk once already: the same derivation reports ten members
# against the pre-campaign tree and six against this one, because Phase 0's
# and Phase 2's new suites import `survival/{accumulate, actions, compile,
# transitions}` directly.  That is the frontier working, and it is why the
# ten is not written down anywhere as a target.
FRONT_DOOR_FRONTIER: Mapping[str, FrontierEntry] = {
    "application_errors": FrontierEntry(
        owning_phase="none — pre-campaign debt",
        reason=(
            "the exception vocabulary src/app.py and optimizer.py raise; every "
            "assertion about it runs through an app response instead"
        ),
    ),
    "healing_legacy": FrontierEntry(
        owning_phase="none — pre-campaign debt",
        reason=(
            "the pre-ledger healing path, reached only through healing.py and "
            "champions/healing_rules.py; tests/test_healing.py covers it by "
            "behaviour without naming it"
        ),
    ),
    "practice_dummy": FrontierEntry(
        owning_phase="none — pre-campaign debt",
        reason=(
            "the practice-target preset, reached only through scenario.py, "
            "whose suite exercises it through a parsed scenario"
        ),
    ),
    "request_parsing": FrontierEntry(
        owning_phase="none — pre-campaign debt",
        reason=(
            "request coercion, exercised through the endpoints in "
            "tests/test_app.py rather than through its own module"
        ),
    ),
    "survival.receipt_state": FrontierEntry(
        owning_phase="Phase 4",
        reason=(
            "re-exported by survival/__init__ and reached through it; Phase 4 "
            "rebuilds it as a program view and owns its front door"
        ),
    ),
    "survival.score_state": FrontierEntry(
        owning_phase="Phase 4",
        reason=(
            "re-exported by survival/__init__ and reached through it; Phase 4 "
            "rebuilds it as a program view and owns its front door"
        ),
    ),
}


def test_damage_engine_does_not_read_item_registry() -> None:
    """Registry dictionaries belong to item_effects, never damage.py."""
    source = DAMAGE_PATH.read_text(encoding="utf-8")
    assert "ITEM_EFFECTS" not in source


def test_damage_engine_does_not_dispatch_on_item_names() -> None:
    """Item identity compiles into typed effects before engine execution."""
    tree = ast.parse(DAMAGE_PATH.read_text(encoding="utf-8"))
    item_names = frozenset(_OFFLINE_ITEM_EFFECTS)
    offenders: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        compared = [node.left, *node.comparators]
        for value in compared:
            if isinstance(value, ast.Constant) and value.value in item_names:
                offenders.append((node.lineno, value.value))

    assert offenders == []


def test_substantial_calculator_modules_have_named_test_front_doors() -> None:
    """Production module names must lead maintainers to a test suite."""
    missing = [
        module
        for module in SUBSTANTIAL_MODULE_FRONT_DOORS
        if not (ROOT / "tests" / f"test_{module}.py").is_file()
    ]
    assert missing == []


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


def test_the_derivation_subsumes_the_hand_tuple_it_replaces() -> None:
    """D-98's delta, asserted before the flip that deletes the tuple.

    The hand tuple asserts a filename convention over eleven chosen modules;
    the derivation asserts a real import over every module outside
    `champions/`.  Two facts make the flip a deletion rather than a loss of
    coverage: no tuple member is on the frontier, so the derivation agrees
    with everything the tuple claimed, and the derivation's denominator is
    strictly larger than the tuple's — the modules it covers that the tuple
    never named are the delta the tuple could never have seen.
    """
    surveyed = {
        ".".join(path.relative_to(SRC_ROOT).with_suffix("").parts)
        for path in SRC_ROOT.rglob("*.py")
        if path.name != "__init__.py"
        and not path.relative_to(SRC_ROOT).parts[0] == "champions"
    }
    assert set(SUBSTANTIAL_MODULE_FRONT_DOORS) <= surveyed
    assert not set(SUBSTANTIAL_MODULE_FRONT_DOORS) & set(FRONT_DOOR_FRONTIER)
    assert surveyed - set(SUBSTANTIAL_MODULE_FRONT_DOORS)
