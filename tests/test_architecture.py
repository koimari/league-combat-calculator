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

# The fight engine: the orchestrator and every step of the `fight/` package.
# Both rules below are about the engine rather than about one file, so they
# read the whole package.
FIGHT_ENGINE_PATHS = (
    SRC_ROOT / "damage.py",
    *sorted((SRC_ROOT / "fight").rglob("*.py")),
)

#: The nodes a docstring may be the first statement of.
DOCSTRING_SCOPES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


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

FIGHT_STEPS_WITHOUT_A_FRONT_DOOR = (
    "fight.after.amp_chain",
    "fight.after.empowered_swings",
    "fight.after.execute_display",
    "fight.after.fight_notes",
    "fight.after.lethality_windows",
    "fight.after.shield_outcome",
    "fight.after.stored_damage",
    "fight.autos.copied_on_hit",
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
    "fight.setup.stat_buff_ultimates",
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
}


def test_damage_engine_does_not_read_item_registry() -> None:
    """Registry dictionaries belong to item_effects, never the fight engine."""
    for path in FIGHT_ENGINE_PATHS:
        assert "ITEM_EFFECTS" not in path.read_text(encoding="utf-8"), path


def test_damage_engine_does_not_dispatch_on_item_names() -> None:
    """Item identity compiles into typed effects before engine execution."""
    item_names = frozenset(_REFERENCE_ITEM_EFFECTS)
    offenders: list[tuple[str, int, str]] = []

    for path in FIGHT_ENGINE_PATHS:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Compare):
                continue
            compared = [node.left, *node.comparators]
            offenders.extend(
                (path.name, node.lineno, value.value)
                for value in compared
                if isinstance(value, ast.Constant) and value.value in item_names
            )

    assert offenders == []


# The steps that still spell a cached item name in code, and what each is
# waiting on.  Set equality, so a step that stops spelling one leaves in the
# same commit and a step that starts spelling one cannot arrive quietly.  A
# name inside a docstring is prose about the mechanic and is not a dispatch,
# so the scan skips docstrings and reads every other literal.
ITEM_NAME_LITERAL_FRONTIER: Mapping[str, tuple[str, frozenset[str]]] = {
    "damage.py": (
        "the published source label on each resource-restore event; it moves "
        "with the restore rule the resource walk names below",
        frozenset({"Catalyst of Aeons"}),
    ),
    "fight/items/eclipse_stack_gate.py": (
        "the row title of the one windowed cooldown proc; it moves when the "
        "cast-proc family reads its display name off the declaration",
        frozenset({"Eclipse"}),
    ),
    "fight/ledger/pool_walk.py": (
        "the one burn row the pool walk consumes by key; it moves with the "
        "periodic family's row keys",
        frozenset({"Liandry's Torment"}),
    ),
    "fight/rotation/mana_declarations.py": (
        "the restore rule the resource walk names its refusals by; it moves "
        "with the resource-ledger declarations",
        frozenset({"Lost Chapter"}),
    ),
    "fight/rotation/mana_walk.py": (
        "the same two restore rules, plus their receipt labels; one slice "
        "with the module above",
        frozenset({"Catalyst of Aeons", "Essence Reaver", "Lost Chapter"}),
    ),
}


def _literal_item_names(path: Path, names: frozenset[str]) -> set[str]:
    """Every cached item name this module spells outside a docstring."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, DOCSTRING_SCOPES)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        for name in names
        if name in node.value
    }


def test_the_fight_steps_spell_no_item_name_outside_the_frontier() -> None:
    """One item, one home: a step reads its row's words off the declaration."""
    names = frozenset(_REFERENCE_ITEM_EFFECTS)
    spelling = {
        path.relative_to(SRC_ROOT).as_posix(): _literal_item_names(path, names)
        for path in FIGHT_ENGINE_PATHS
        if _literal_item_names(path, names)
    }
    assert spelling == {
        module: set(spelled)
        for module, (_, spelled) in ITEM_NAME_LITERAL_FRONTIER.items()
    }


def test_every_item_name_frontier_entry_carries_a_reason() -> None:
    """A frontier entry is a receipt, not a suppression."""
    for module, (reason, spelled) in ITEM_NAME_LITERAL_FRONTIER.items():
        assert reason.strip(), module
        assert spelled, module


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

# The inputs that make a stat block a *build's* rather than a champion's.
BUILD_CONTEXT_KEYWORDS = frozenset(
    {
        "item_options",
        "role",
        "role_quest_complete",
        "external_stat_bonuses",
        "rune_page",
    }
)

# Every `calculate_total_stats` site that is deliberately NOT a participant's
# pre-combat surface, with the reason it is narrower.  Declared, because the
# first version of this guard counted a site only if it passed one of the five
# keywords -- under which a caller that omitted all five was definitionally
# invisible, and omitting inputs is precisely SC9's failure.  The guard below
# is keyed on the callee instead and is total: every site is the one recipe or
# is entered here.
#
# What these five share is that no request stands behind them.  Each is a
# reference parse over a fixed matrix or over champion data alone -- cached or
# captured on `(champion, data version)` with the level and build written into
# the harness -- so an input added to the participant recipe must NOT reach
# them: it would invalidate a cache key that never mentions a request, and
# move the golden's champion-baseline section on a change about neither.
NARROWER_STAT_SURFACES: Mapping[str, str] = {
    "calculator.rotation_resolver._matrix_dps_rows": (
        "the reference DPS matrix, cached on (champion, data version) and "
        "explicitly independent of the request's level and build"
    ),
    "calculator.rotation_resolver._canonical_kit_parse": (
        "the canonical full-kit parse the derived cast order is read off: "
        "level 11, no items, by construction"
    ),
    "cast_dependency_audit._parse": (
        "one cell of the audit's fixed MATRIX_LEVELS x MATRIX_BUILDS sweep"
    ),
    "golden_snapshot._parse_abilities_fresh": (
        "the ability parse of the golden's champion-baseline section, whose "
        "level and items are the section's own constants"
    ),
    "golden_snapshot.snapshot_champion_baselines": (
        "the golden's champion-baseline stats at levels 1/11/18 with no items"
    ),
}

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


def _stat_sites() -> dict[str, list[frozenset[str]]]:
    """Every `calculate_total_stats` site, by enclosing def, with its keywords.

    Keyed on the callee and nothing else, so a caller that supplies no
    keyword at all is counted rather than defined away.
    """
    sites: dict[str, list[frozenset[str]]] = {}
    for scope, call in _scanned_scopes():
        if _called_name(call) != "calculate_total_stats":
            continue
        supplied = frozenset(k.arg for k in call.keywords if k.arg)
        sites.setdefault(scope, []).append(supplied)
    return sites


def test_the_pre_combat_stat_recipe_is_written_in_exactly_one_place() -> None:
    """SC9: one composition, so no surface can drop an input by omission.

    Set equality against the declared narrower surfaces, in both directions:
    a new stat composition fails until somebody rules it a participant's (and
    routes it) or enters it below with a reason.
    """
    sites = _stat_sites()
    assert sites[PRE_COMBAT_RECIPE_HOME] == [BUILD_CONTEXT_KEYWORDS]
    assert set(sites) - {PRE_COMBAT_RECIPE_HOME} == set(NARROWER_STAT_SURFACES)


def test_each_narrower_stat_surface_is_narrow_and_says_why() -> None:
    """A declaration is a receipt, and the tree has to agree with it.

    Narrow means it composes a champion's stat block and not a build's: a
    site that starts passing one of the five has stopped being a reference
    parse and owes the participant recipe a call, so the entry stops covering
    it here rather than quietly widening.
    """
    sites = _stat_sites()
    for scope, reason in NARROWER_STAT_SURFACES.items():
        assert reason.strip(), scope
        for supplied in sites[scope]:
            assert not supplied & BUILD_CONTEXT_KEYWORDS, scope


def test_the_request_read_answers_every_input_of_the_recipe() -> None:
    """The other half, so the guards above cannot pass vacuously.

    The recipe naming all five is asserted with the site count; a
    `FightParams` read answering only some of them would put the same
    silence one call deeper.
    """
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
