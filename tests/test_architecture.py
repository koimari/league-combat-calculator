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
    # `comparison` joined this frontier with the one-request compare
    # boundary: the module is new, and the two complete results it returns
    # are asserted through `/api/compare` in `tests/test_app.py`, so it has
    # behaviour coverage and no front door.  Recorded as an arrival for the
    # reason the departures below are recorded: the set is the receipt.
    "comparison": FrontierEntry(
        owning_phase="none - arrived with the compare boundary",
        reason=(
            "the one-request build-comparison boundary, exercised only "
            "through /api/compare in tests/test_app.py rather than through "
            "its own module"
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
