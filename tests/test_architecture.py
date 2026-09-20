"""Static guards for high-value module boundaries.

The front-door frontier is here, one entry per module with the reason it has
no importing test module, beside the guard that holds the set to equality.
The two tree scans live in `scripts/item_name_boundary.py` and
`scripts/pre_combat_stat_sites.py`, each with its own declared frontier.
"""

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import item_name_boundary
import pre_combat_stat_sites

from tests.coverage_resolver import front_door_report

ROOT = Path(__file__).parents[1]
SRC_ROOT = ROOT / "src" / "calculator"
TEST_ROOT = ROOT / "tests"


@dataclass(frozen=True, slots=True)
class FrontierEntry:
    """Why a module has no importing test module, and who owes it one."""

    owning_phase: str
    reason: str


# The steps of the `fight/` package whose whole contract is the numbers
# `calculate_fight_damage` publishes.  A sibling step that also states
# something no total can show -- a schedule, a vocabulary, a refusal -- has an
# importing suite and is not here; these have nothing to assert except through
# the fight, so an import written into a suite to satisfy this rule would be a
# front door that backs nothing.  That is a property of the package rather
# than a deferral, so no phase owes them one.  They are listed one by one, so
# the set still cannot grow by accident.
FIGHT_STEP = FrontierEntry(
    owning_phase="none — a property of the fight package, not a deferral",
    reason=(
        "a step of the fight engine whose whole contract is the numbers "
        "damage.calculate_fight_damage publishes, asserted there by every "
        "suite that exercises it"
    ),
)

#: The leaves a module split lifted out, and the module whose suite drives
#: each one.  Listed one by one, for the reason the fight steps are: the set
#: may not grow by accident.
SPLIT_LEAVES = {
    "atom_spelling": "atomizer_domains",
    "capability_fields": "capabilities",
    "ability_ranks": "scenario",
    "champion_opening_defenses": "defensive_effects",
    "fight_receipts": "pipeline",
    "interaction_atoms": "interaction_effects",
    "program.views.survival_blocks": "program.views.survival",
    "rune_sustain_events": "pipeline",
    "support_bailout": "support_effects",
    "support_champion_packets": "support_effects",
    "survival.defense_contracts": "survival.receipt_state",
}


def _split_leaf(source: str) -> FrontierEntry:
    """A leaf whose readers are its siblings, still asserted through *source*."""
    return FrontierEntry(
        owning_phase="sightline #27, the split that gave the leaf its own file",
        reason=(
            f"a leaf of {source}, whose suite drives every line of it; it "
            "gains a front door when a suite asserts its contract directly"
        ),
    )


FIGHT_STEPS_WITHOUT_A_FRONT_DOOR = (
    "fight.after.amp_chain",
    "fight.after.empowered_swings",
    "fight.after.execute_display",
    "fight.after.fight_notes",
    "fight.after.lethality_windows",
    "fight.after.shield_outcome",
    "fight.autos.copied_on_hit",
    "fight.autos.double_shot",
    "fight.autos.first_auto_strikes",
    "fight.autos.on_hit_healing",
    "fight.autos.on_hit_layering",
    "fight.autos.simulation",
    "fight.autos.stacking_strikes",
    "fight.declarations",
    "fight.items.cast_procs",
    "fight.items.energized_packets",
    "fight.items.proc_triggers",
    "fight.items.ultimate_procs",
    "fight.ledger.breakdown",
    "fight.ledger.execute_stamps",
    "fight.rotation.ability_rotation",
    "fight.rotation.burst_autos",
    "fight.rotation.cast_plan",
    "fight.rotation.energy_walk",
    "fight.rotation.mana_walk",
    "fight.rotation.precomputed_procs",
    "fight.rotation.stack_timeline",
    "fight.runes.amplifiers",
    "fight.runes.keystone_attacks",
    "fight.runes.keystone_casts",
    "fight.runes.keystone_ledger_walk",
    "fight.runes.keystone_stacks",
    "fight.runes.page_damage",
    "fight.runes.streams",
    "fight.setup.combat_state",
    "fight.setup.shield_reaver",
    "fight.stacks.account",
    "fight.stacks.ashe",
    "fight.stacks.aurelion_sol",
    "fight.stacks.bard",
    "fight.stacks.heimerdinger",
    "fight.stacks.ksante",
    "fight.stacks.rengar",
    "fight.stacks.senna",
    "fight.state",
)


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
    **dict.fromkeys(FIGHT_STEPS_WITHOUT_A_FRONT_DOOR, FIGHT_STEP),
    **{name: _split_leaf(source) for name, source in SPLIT_LEAVES.items()},
}


def test_item_identity_stops_at_the_fight_engines_door() -> None:
    """The three rules `scripts/item_name_boundary.py` owns.

    Registry dictionaries belong to `item_effects`, item identity compiles
    into typed effects before the engine runs, and a step reads its row's
    words off the declaration rather than spelling the name.
    """
    assert item_name_boundary.registry_readers() == []
    assert item_name_boundary.name_comparisons() == []
    assert item_name_boundary.frontier_drift() == []


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


def test_the_pre_combat_stat_surface_has_one_recipe() -> None:
    """The four rules `scripts/pre_combat_stat_sites.py` owns.

    Every composition is the recipe or a declared narrower surface, a
    declared surface stays narrow, the `FightParams` read answers every
    input, and the five surfaces SC9 named all route through the helper.
    """
    assert pre_combat_stat_sites.recipe_drift() == []
    assert pre_combat_stat_sites.widened_surfaces() == []
    assert pre_combat_stat_sites.unrouted_surfaces() == []
    assert (
        pre_combat_stat_sites.request_read_inputs()
        == pre_combat_stat_sites.BUILD_CONTEXT_KEYWORDS
    )
