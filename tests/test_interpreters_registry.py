"""The front door for ``interpreters`` — the map, the fold, and both directions.

Three claims live here.  The lane table says which engines owe each family an
answer, so "every family is interpreted" cannot be true of an empty registry.
The ``compilability_for`` fold gives a per-item question a per-item answer,
which is what lets it replace a per-item legacy set.  And reachability is
checked in **both** directions (D-51), because both failures are real: a
declaration no interpreter serves, and an interpreter branch no declaration
reaches.
"""

import ast
import dataclasses
from pathlib import Path

import pytest

from src.calculator.ability_spec import Authority
from src.calculator import bis
from src.calculator import data_fetcher
from src.calculator import interpreters
from src.calculator import item_coverage
from src.calculator import item_effects
from src.calculator import item_behavior_catalog as catalog
from src.calculator.interpreters import damage_routing
from src.calculator.item_behavior import (
    Compilable,
    DefenseField,
    DefenseSubject,
    EngineLane,
    ReceiptOnly,
    ReceiptScope,
    RuleFamily,
    SUBJECT_AUTHORITY,
    Subject,
)
from src.calculator.item_behavior_catalog import registry_owners

SRC_ROOT = Path(__file__).parents[1] / "src" / "calculator"


class _StubInterpreter:
    """A registered interpreter, so the registry's own gates have a subject."""

    def __init__(self, family: RuleFamily, lanes: frozenset[EngineLane]) -> None:
        self.FAMILY = family  # pylint: disable=invalid-name
        self.LANES = lanes  # pylint: disable=invalid-name

    def compile(self, rule, ctx):  # pragma: no cover - never called here
        """Emit nothing; these tests are about registration, not compilation."""
        del rule, ctx
        return ()


def test_every_family_declares_the_lanes_that_owe_it_an_answer() -> None:
    """Declared, not inferred — otherwise an empty registry reports full cover."""
    for family in RuleFamily:
        assert interpreters.lanes_for(family)
    # 53 until 2026-08-16, when umbrella Amendment O, Ruling 1 reclassified
    # crit_profile PAIR_ONLY on a measured emptiness and its receipt-walk lane
    # left the table; then 49 the same day, when umbrella Amendment Q corrected
    # the declaration of the three families the defence resolver feeds --
    # combat_state, opening_defense and threshold_defense -- whose walk-side
    # need is served through the lane they declare and which therefore never
    # owed a receipt-walk interpreter lane at all.  The literal moves only when
    # a ruling moves it, which is what makes an unruled edit here a red rather
    # than a re-typed number.
    assert len(interpreters.declared_pairs()) == 49


def test_counter_four_is_the_gap_between_the_table_and_the_registry() -> None:
    """Every declared pair with no interpreter is counted, never assumed away."""
    gap = frozenset(interpreters.uninterpreted_pairs())
    assert gap == interpreters.declared_pairs() - frozenset(interpreters.INTERPRETERS)
    assert (
        RuleFamily.DELTA_AMP,
        EngineLane.PAIR_ENGINE,
    ) in interpreters.INTERPRETERS


def test_the_compiled_score_walk_gap_is_a_dated_route_and_not_a_zero() -> None:
    """An amp's compiled lane is excused by a named route since H5's stage.

    H5 was SCOPED and its stage landed: the kernel stages a timed, typed
    damage modifier, so every ``delta_amp`` rule is ``Compilable`` and the
    per-rule receipt that used to excuse this lane is gone.  The lane still
    has no interpreter of its own — the walk never reads an amp declaration —
    so what stands between it and an unreceipted zero is the dated row naming
    the two routes the number actually arrives by.  A gap excused by neither
    cannot import (D-101's successor state, not its relaxation).
    """
    pair = (RuleFamily.DELTA_AMP, EngineLane.COMPILED_SCORE_WALK)
    assert pair in interpreters.uninterpreted_pairs()
    assert pair in interpreters.UNSERVED_LANE_RECEIPTS
    assert interpreters.UNSERVED_LANE_RECEIPTS[pair].via == (EngineLane.PAIR_ENGINE,)
    for scope in ReceiptScope:
        assert isinstance(
            interpreters.compilability_for("Horizon Focus", scope), Compilable
        ), scope


def test_an_owner_whose_behaviour_is_still_engine_code_is_not_compilable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fold fails closed: an absence never becomes a compiled-lane promise.

    Counter 3 reached zero at 3.7-r2, so no real owner takes this branch any
    more and the frontier can no longer supply a subject.  The branch is
    still live and still load-bearing — the next registry tag anybody adds
    lands in it before its declaration does — so it is driven synthetically
    (D-26): an owner the registries know, with its rule set emptied.  A test
    that retired itself the moment the population emptied would leave the
    fail-closed branch unproven exactly when nothing else covers it.
    """
    owner = "Actualizer"
    assert catalog.registry_entries(owner), "the subject must have a registry entry"
    assert catalog.behavior_rules(owner), "the subject must be a declared owner"
    monkeypatch.setattr(interpreters, "behavior_rules", lambda name: ())
    for scope in ReceiptScope:
        verdict = interpreters.compilability_for(owner, scope)
        assert isinstance(verdict, ReceiptOnly)
        assert owner in verdict.reason
        assert verdict.scope is scope
    assert not catalog.undeclared_owners(), (
        "counter 3 is back above zero; the live population, not this "
        "synthetic subject, is what that regression should be read from"
    )


def test_an_owner_with_no_registry_entry_has_nothing_to_represent() -> None:
    """Stats-only items are compilable because there is no behaviour to compile."""
    for scope in ReceiptScope:
        assert isinstance(interpreters.compilability_for("Boots", scope), Compilable)


def test_the_fold_concatenates_receipt_only_reasons_in_declaration_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-43's fold, stated here rather than left to each caller."""

    class _Rule:  # pylint: disable=too-few-public-methods
        def __init__(self, compilability) -> None:
            self.compilability = compilability

    monkeypatch.setattr(
        interpreters,
        "behavior_rules",
        lambda owner: (
            _Rule(Compilable()),
            _Rule(ReceiptOnly("first", ReceiptScope.SURVIVAL_LEDGER_TRANSITION)),
            _Rule(ReceiptOnly("second", ReceiptScope.SURVIVAL_LEDGER_TRANSITION)),
            _Rule(ReceiptOnly("other scope", ReceiptScope.SUPPORT_TEMPLATE_SHAPE)),
        ),
    )
    verdict = interpreters.compilability_for(
        "Anything", ReceiptScope.SURVIVAL_LEDGER_TRANSITION
    )
    assert isinstance(verdict, ReceiptOnly)
    assert verdict.reason == "first; second"
    # The fourth rule refuses too, and in a scope nobody asked about; folding
    # it in is precisely the conflation the scope axis exists to end.
    assert "other scope" not in verdict.reason


def test_all_compilable_folds_to_compilable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half of the fold."""

    class _Rule:  # pylint: disable=too-few-public-methods
        def __init__(self, compilability) -> None:
            self.compilability = compilability

    monkeypatch.setattr(
        interpreters, "behavior_rules", lambda owner: (_Rule(Compilable()),)
    )
    assert isinstance(
        interpreters.compilability_for(
            "Anything", ReceiptScope.SURVIVAL_LEDGER_TRANSITION
        ),
        Compilable,
    )


def test_no_registered_interpreter_is_an_orphan_branch() -> None:
    """D-51's interpreter->author direction, over the live registry."""
    assert interpreters.reachability_report(registry_owners()).orphan_branches == ()


def test_a_declaration_no_lane_serves_is_reported_rather_than_silent() -> None:
    """The other direction: the compiled lane owes Hypershot an answer it has not got."""
    report = interpreters.reachability_report(registry_owners())
    assert any(
        "horizon_focus.hypershot" in entry and "compiled_score_walk" in entry
        for entry in report.unreached_declarations
    )
    assert all("pair_engine" not in entry for entry in report.unreached_declarations)


def test_an_interpreter_no_declaration_reaches_is_an_orphan_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-51's interpreter->author direction, with a red it can reproduce.

    The pair is read off the frontier rather than named: every migration
    slice registers another one, and a hard-coded family would make this
    test quietly stop testing the direction it exists for.
    """
    family, lane = interpreters.uninterpreted_pairs()[0]
    stub = _StubInterpreter(family, frozenset({lane}))
    monkeypatch.setattr(
        interpreters,
        "INTERPRETERS",
        dict(interpreters.INTERPRETERS) | {(family, lane): stub},
    )
    report = interpreters.reachability_report(frozenset())
    assert (
        f"{family.value}/{lane.value} is registered and no declaration reaches it"
        in report.orphan_branches
    )
    # And the gate raises on it: the owner set is narrowed to the holders
    # that declare nothing of this family, which is what "no declaration
    # reaches this branch" means once the family itself has declarations.
    monkeypatch.setattr(
        interpreters,
        "rule_owners",
        lambda: frozenset(
            owner
            for owner in catalog.rule_owners()
            if all(rule.family is not family for rule in catalog.behavior_rules(owner))
        ),
    )
    with pytest.raises(interpreters.InterpreterRegistryError, match="orphan|reaches"):
        interpreters.validate_registrations()


def test_a_registration_that_contradicts_its_own_interpreter_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The key and the interpreter's own declaration are one fact, checked."""
    stub = _StubInterpreter(RuleFamily.SUSTAIN, frozenset({EngineLane.PAIR_ENGINE}))
    monkeypatch.setattr(
        interpreters,
        "INTERPRETERS",
        {(RuleFamily.DELTA_AMP, EngineLane.PAIR_ENGINE): stub},
    )
    with pytest.raises(interpreters.InterpreterRegistryError, match="does not claim"):
        interpreters.validate_registrations()


def test_a_registration_on_a_lane_the_family_never_declared_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interpreter on an undeclared lane can never be reached."""
    stub = _StubInterpreter(RuleFamily.ALLY_PACKET, frozenset({EngineLane.PAIR_ENGINE}))
    monkeypatch.setattr(
        interpreters,
        "INTERPRETERS",
        {(RuleFamily.ALLY_PACKET, EngineLane.PAIR_ENGINE): stub},
    )
    with pytest.raises(interpreters.InterpreterRegistryError, match="declares no"):
        interpreters.validate_registrations()


def test_validate_registrations_runs_at_import() -> None:
    """The registry's gates are import-time, so a bad map fails collection."""
    module = SRC_ROOT / "interpreters" / "__init__.py"
    tree = ast.parse(module.read_text(encoding="utf-8"))
    called = {
        node.value.func.id
        for node in tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
    }
    assert "validate_registrations" in called


def test_nothing_under_survival_imports_the_interpreter_package() -> None:
    """The one-way dependency the build-time contract rests on."""
    offenders = []
    for path in sorted((SRC_ROOT / "survival").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.ImportFrom) and node.module:
                if "interpreters" in node.module or "item_behavior_catalog" in (
                    node.module
                ):
                    offenders.append(f"{path.name}: {node.module}")
            elif isinstance(node, ast.Import):
                offenders.extend(
                    f"{path.name}: {alias.name}"
                    for alias in node.names
                    if "interpreters" in alias.name
                    or "item_behavior_catalog" in alias.name
                )
    assert offenders == []


def _owners_declaring(family: RuleFamily) -> tuple[str, ...]:
    """Every owner whose declarations include *family*, in a stated order."""
    return tuple(
        owner
        for owner in sorted(catalog.rule_owners())
        if any(rule.family is family for rule in catalog.behavior_rules(owner))
    )


@pytest.mark.parametrize(
    "family", sorted(RuleFamily, key=lambda member: member.value), ids=lambda f: f.value
)
def test_deleting_a_families_interpreter_withholds_it_rather_than_pricing_zero(
    family: RuleFamily, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Criterion 11, one case per family: the interpreter *is* the coverage.

    The registry is not a lookup table beside the answer, it is the reason
    there is an answer at all — so removing one registration has to turn every
    item declaring that family into a named refusal on that lane, and never
    into a zero somebody could sum.  Three things are asserted per lane, and
    the first is what stops the other two passing vacuously: the item is
    *eligible* before the deletion, refused after it, and the refusal names the
    exact ``family/lane`` that went missing.

    A family with no declarations yet cannot be tested this way and is not
    quietly skipped: it must be the one the catalog dates as unmigrated, so
    this parametrization goes red the day that family is declared without its
    interpreter, and the day an undeclared family stops being named.
    """
    owners = _owners_declaring(family)
    if not owners:
        assert family in catalog.UNMIGRATED_FAMILIES, (
            f"{family.value} declares no rule and no slice is on record to "
            "migrate it, so nothing states why its interpreter has no subject"
        )
        return
    for lane in sorted(interpreters.lanes_for(family), key=lambda member: member.value):
        reduced = {
            key: value
            for key, value in interpreters.INTERPRETERS.items()
            if key != (family, lane)
        }
        registered = (family, lane) in interpreters.INTERPRETERS
        needed = frozenset({lane})
        for owner in owners:
            before = item_coverage.item_model_coverage(owner, needed)
            monkeypatch.setattr(item_coverage, "INTERPRETERS", reduced)
            after = item_coverage.item_model_coverage(owner, needed)
            monkeypatch.setattr(
                item_coverage, "INTERPRETERS", interpreters.INTERPRETERS
            )
            pair = f"{family.value}/{lane.value}"
            if registered:
                assert pair not in before.reason, (
                    f"{owner} already refuses {pair} with the interpreter "
                    "present, so its deletion proves nothing here"
                )
            assert after.status == "withheld"
            assert pair in after.reason
            assert "withheld rather than priced as zero" in after.reason
            assert not after.optimizer_eligible
            assert not after.calculation_eligible


class _StubRule:  # pylint: disable=too-few-public-methods
    """A declaration with just the fields the registration gates read."""

    def __init__(self, family: RuleFamily, compilability) -> None:
        self.family = family
        self.compilability = compilability
        self.mechanic_id = f"stub.{family.value}"
        self.owner = "Stub"
        self.payload = None


def _only_rule(monkeypatch: pytest.MonkeyPatch, rule) -> None:
    """Make the whole tree consist of one declaration."""
    monkeypatch.setattr(interpreters, "rule_owners", lambda: frozenset({"Stub"}))
    monkeypatch.setattr(interpreters, "behavior_rules", lambda owner: (rule,))


def test_an_unserved_lane_with_no_receipt_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Criterion 12's first clause: a declared family with no interpreter.

    Deleting a registration does not merely change a counter — it makes every
    declaration of that family unpriced on that lane, and the gate refuses to
    import a tree in that state unless something *names* the gap.  Without
    this, counter 4 is the only witness a missing interpreter has, and a
    counter is a number nobody has to read.
    """
    monkeypatch.setattr(
        interpreters,
        "INTERPRETERS",
        {
            key: value
            for key, value in interpreters.INTERPRETERS.items()
            if key != (RuleFamily.ON_HIT_STRIKE, EngineLane.PAIR_ENGINE)
        },
    )
    with pytest.raises(
        interpreters.InterpreterRegistryError, match="unreceipted zero"
    ) as raised:
        interpreters.validate_registrations()
    assert "on_hit_strike" in str(raised.value)
    assert "pair_engine" in str(raised.value)


def test_a_dated_gap_receipt_no_declaration_reaches_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reverse direction: a receipt for a lane that is served (D-92).

    A gap table nobody prunes is the hand-maintained exception list this
    campaign deletes everywhere else, so a row for a pair some interpreter
    already serves is a failure rather than a harmless leftover.

    The planted row is otherwise impeccable — ``sustain`` really is served on
    both the lane the row names and the lane it routes to — so the only thing
    wrong with it is that nobody needs it, which is what the gate must see.
    """
    monkeypatch.setattr(
        interpreters,
        "UNSERVED_LANE_RECEIPTS",
        dict(interpreters.UNSERVED_LANE_RECEIPTS)
        | {
            (
                RuleFamily.SUSTAIN,
                EngineLane.DEFENSE_RESOLVER,
            ): interpreters.UnservedLane(
                reason="a lane that is in fact served",
                via=(EngineLane.PAIR_ENGINE,),
            )
        },
    )
    with pytest.raises(
        interpreters.InterpreterRegistryError, match="receipt for nothing"
    ) as raised:
        interpreters.validate_registrations()
    assert "routes to" not in str(raised.value), (
        "the planted row's route is sound, so the only complaint must be that "
        "the row itself is unnecessary"
    )


def test_a_compiled_gap_is_excused_by_the_rules_own_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The per-rule form, which is the one every amp carries (D-101).

    Both halves are asserted on one stub: the same family and lane passes with
    a ``ReceiptOnly`` compilability and raises with a ``Compilable`` one, so
    what is being tested is the receipt and not the pair.

    Since H5's stage the live tree carries ``delta_amp``'s compiled lane in
    the dated table — the flip made those rules compilable, so the per-rule
    receipt that used to excuse the lane is gone and a route had to be named
    for it instead.  That makes the narrowing below load-bearing rather than
    incidental: the stub's tables serve every lane but the compiled one, so
    it reaches the per-rule branch this test exists for, which no live
    declaration reaches any more.

    The narrowing serves the receipt walk from the live registration rather
    than excusing it from the dated table, because Amendment M, Ruling 1
    retired that row: the family's walk interpreter landed, and a fixture
    excusing a lane the tree serves would be testing a tree nobody has.
    """
    assert (
        RuleFamily.DELTA_AMP,
        EngineLane.COMPILED_SCORE_WALK,
    ) in interpreters.UNSERVED_LANE_RECEIPTS

    _only_rule(
        monkeypatch,
        _StubRule(
            RuleFamily.DELTA_AMP,
            ReceiptOnly(
                "the kernel cannot amp", ReceiptScope.SCORE_KERNEL_DAMAGE_MODIFIER
            ),
        ),
    )
    # The registry is narrowed with the declaration set: every other
    # registration would otherwise be an orphan branch of this one-rule tree,
    # which is a true report about a fixture and not the thing under test.
    monkeypatch.setattr(
        interpreters,
        "INTERPRETERS",
        {
            (RuleFamily.DELTA_AMP, lane): interpreters.INTERPRETERS[
                (RuleFamily.DELTA_AMP, lane)
            ]
            for lane in (EngineLane.PAIR_ENGINE, EngineLane.RECEIPT_WALK)
        },
    )
    # Empty rather than narrowed: with both served lanes registered, every
    # dated row would be one no declaration in this one-rule tree reaches,
    # which the reverse direction of the check reports as stale.
    monkeypatch.setattr(interpreters, "UNSERVED_LANE_RECEIPTS", {})
    interpreters.validate_registrations()

    _only_rule(monkeypatch, _StubRule(RuleFamily.DELTA_AMP, Compilable()))
    with pytest.raises(interpreters.InterpreterRegistryError, match="unreceipted zero"):
        interpreters.validate_registrations()


def test_a_subject_its_authority_cannot_see_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Criterion 12's third clause, and the incident's own shape.

    A rule acting on any roster attacker under a ``PAIR_ONLY`` authority is a
    mechanic whose owning engine cannot see the input its rule reads — which
    is failure mode C of the incident, stated as a declaration.  The subject
    is read off a live rule rather than invented, so the case dies if the
    roster-scoped subjects ever stop existing.
    """
    roster_scoped = [
        rule
        for owner in sorted(catalog.rule_owners())
        for rule in catalog.behavior_rules(owner)
        if getattr(rule.payload, "subject", None) is not None
        and Authority.PAIR_ONLY
        not in SUBJECT_AUTHORITY[rule.payload.subject]  # type: ignore[index]
    ]
    assert roster_scoped, "no declaration acts on a roster-scoped subject"
    rule = roster_scoped[0]
    capability = interpreters.CAPABILITIES[rule.mechanic_id]
    monkeypatch.setattr(
        interpreters,
        "CAPABILITIES",
        dict(interpreters.CAPABILITIES)
        | {
            rule.mechanic_id: dataclasses.replace(
                capability, authority=Authority.PAIR_ONLY
            )
        },
    )
    with pytest.raises(
        interpreters.InterpreterRegistryError, match="which cannot see it"
    ):
        interpreters.validate_registrations()


def test_every_gap_row_says_why_the_lane_is_unserved() -> None:
    """A gap with no reason is the silence the table exists to replace.

    What the row does *not* carry is when it retires: that is campaign
    bookkeeping with one home in ``docs/receipts/campaign-stages.json``, and
    ``tests/test_behavior_frontier`` asserts no stage name reaches ``src/``.
    """
    for (family, lane), row in interpreters.UNSERVED_LANE_RECEIPTS.items():
        assert row.reason.strip(), f"{family.value}/{lane.value} has no reason"
        assert row.via, f"{family.value}/{lane.value} names no route"
        assert (family, lane) not in interpreters.INTERPRETERS


def test_every_dated_gap_row_routes_to_a_lane_the_registry_serves() -> None:
    """Criterion 4's other half: the fallback receipt is *tested*, not stated.

    A row's whole excuse is that the number arrives by another of its
    family's lanes.  Stated in prose, that excuse reads identically whether
    the lane it names is served or empty — the pair-engine half of Command
    was documented and absent, and nothing noticed.  ``via`` is the claim as
    data and this is the check: every route lane is one the family declares
    and one an interpreter serves, and no row routes to itself.
    """
    for (family, lane), row in interpreters.UNSERVED_LANE_RECEIPTS.items():
        pair = f"{family.value}/{lane.value}"
        assert row.via, f"{pair} names no route"
        for route in row.via:
            assert route is not lane, f"{pair} routes to itself"
            assert route in interpreters.lanes_for(family), f"{pair} -> {route.value}"
            assert (
                family,
                route,
            ) in interpreters.INTERPRETERS, f"{pair} routes through an unserved lane"


@pytest.mark.parametrize(
    ("via", "complaint"),
    [
        ((), "names no route"),
        ((EngineLane.RECEIPT_WALK,), "which no interpreter serves"),
        ((EngineLane.STAT_RESOLVER,), "does not declare"),
        ((EngineLane.COMPILED_SCORE_WALK,), "routes the lane to itself"),
    ],
    ids=("empty", "unserved", "undeclared", "circular"),
)
def test_a_route_the_registry_does_not_serve_is_refused(
    via, complaint: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R-05's red for the route clause, one shape per way a route can lie.

    ``on_hit_strike``'s compiled lane is the subject because its real route —
    the pair engine — is the one every packet-fed row stands on, so each
    substitution below is that row with its one true sentence replaced by a
    plausible false one.
    """
    pair = (RuleFamily.ON_HIT_STRIKE, EngineLane.COMPILED_SCORE_WALK)
    monkeypatch.setattr(
        interpreters,
        "UNSERVED_LANE_RECEIPTS",
        dict(interpreters.UNSERVED_LANE_RECEIPTS)
        | {
            pair: interpreters.UnservedLane(
                reason=interpreters.UNSERVED_LANE_RECEIPTS[pair].reason,
                via=via,
            )
        },
    )
    with pytest.raises(interpreters.InterpreterRegistryError, match=complaint):
        interpreters.validate_registrations()


def test_no_gap_row_stands_on_a_counter_this_phase_has_retired() -> None:
    """Every surviving row waits on an interpreter, not on a name site.

    Two rows used to stand on the walk reading a sustain key by item name in
    ``survival/receipt_state.py``, and were dated at counter 1's residue for
    it.  That read is gone: the below-half bonus is a declaration the walk
    lane's own interpreter compiles.  A row outliving its stated cause is the
    prose-outruns-code failure inside the table that exists to prevent it, so
    the reason is asserted rather than trusted.  The date it carried moved to
    the stage records with every other date, so what is left to assert here is
    the half that was ever a fact about this tree.
    """
    for (family, lane), row in interpreters.UNSERVED_LANE_RECEIPTS.items():
        assert "counter 1" not in row.reason, f"{family.value}/{lane.value}"


def test_the_walk_lane_serves_the_family_that_authors_its_own_recoveries() -> None:
    """``sustain``'s receipt-walk half is served, not dated.

    The walk pays out two sustain shapes itself — a regeneration window's
    ticks and the below-half healing bonus — so its lane owes an interpreter
    rather than a route to somebody else's number.
    """
    assert (
        RuleFamily.SUSTAIN,
        EngineLane.RECEIPT_WALK,
    ) in interpreters.INTERPRETERS
    assert (
        RuleFamily.SUSTAIN,
        EngineLane.RECEIPT_WALK,
    ) not in interpreters.UNSERVED_LANE_RECEIPTS


def test_the_hand_certification_is_gone_and_the_fold_is_what_bis_publishes() -> None:
    """The other half of D-98: the retired table has zero occurrences in ``src/``.

    Not as a binding and not as a sentence about one — a name surviving in
    prose is how a reader learns to look for something that is not there.  The
    published receipt is asserted against the fold in both directions, so a
    payload wired to something else entirely could not pass this by certifying
    nothing.
    """
    retired = "BIS_CERTIFIED_" + "DEFENSIVE_EFFECTS"
    holders = [
        path.relative_to(SRC_ROOT).as_posix()
        for path in sorted(SRC_ROOT.rglob("*.py"))
        if retired in path.read_text(encoding="utf-8")
    ]
    assert holders == []

    derived = interpreters.survival_ledger_certifications()
    assert set(derived) == {"Eclipse", "Death's Dance", "Sundered Sky"}
    assert all(note.strip() for note in derived.values())
    for owner, note in derived.items():
        receipt = bis.bis_defensive_effect_receipt(owner, {})
        assert receipt["status"] == "certified"
        assert receipt["note"] == note
    uncertified = sorted(set(catalog.rule_owners()) - set(derived))
    assert uncertified
    for owner in uncertified:
        assert (
            bis.bis_defensive_effect_receipt(owner, {})["status"]
            == "no_special_defensive_effect"
        )


def test_each_certification_names_the_declaration_it_was_read_from() -> None:
    """A derived note cites its mechanic, so the receipt points at the rule."""
    for owner, note in interpreters.survival_ledger_certifications().items():
        entries = interpreters.survival_ledger_entries(owner)
        assert entries
        for entry in entries:
            assert entry.mechanic_id in note
            assert entry.owner == owner


def test_a_declaration_that_drops_its_ledger_component_stops_certifying() -> None:
    """The sensitivity that a name-keyed table structurally cannot have.

    Eclipse is certified because its proc declares a ``self_shield``.  Take the
    shield out of the declaration and the classifier says so — which is what
    makes the published certification an observation rather than a claim.
    """
    (rule,) = [
        candidate
        for candidate in catalog.behavior_rules("Eclipse")
        if interpreters.survival_ledger_contribution(candidate) is not None
    ]
    assert (
        interpreters.survival_ledger_contribution(rule)
        is interpreters.SurvivalLedgerContribution.SELF_SHIELD
    )
    shieldless = dataclasses.replace(
        rule, payload=dataclasses.replace(rule.payload, self_shield=None)
    )
    assert interpreters.survival_ledger_contribution(shieldless) is None


def test_a_forced_strike_that_heals_somebody_else_is_not_a_holder_ledger_entry() -> (
    None
):
    """The subject clause: this fold answers about the *holder's* ledger."""
    (rule,) = [
        candidate
        for candidate in catalog.behavior_rules("Sundered Sky")
        if interpreters.survival_ledger_contribution(candidate) is not None
    ]
    elsewhere = dataclasses.replace(
        rule, payload=dataclasses.replace(rule.payload, subject=Subject.TARGET)
    )
    assert interpreters.survival_ledger_contribution(elsewhere) is None


# ── damage_routing's per-owner equivalence fixtures ───────────────────────
#
# Umbrella Amendment P requires a fixture PER OWNER for this family, and the
# plural is the point: three owners deliver through three different kernel
# mechanisms, and the one committed coupled scenario that covers the family
# holds only Death's Dance, so a green baseline proves nothing about the two
# that can still fail.  Each fixture below asserts the retirement was a
# re-spelling -- the walk interpreter's number against the producer the walk
# read before it -- rather than a re-pricing.


@pytest.mark.parametrize("holder_is_melee", [True, False])
def test_the_walk_venom_equals_the_registry_accessor_it_replaced(
    holder_is_melee: bool,
) -> None:
    """Serpent's Fang: the barrier-state adjustment, on both range classes.

    ``item_effects.serpents_fang_venom`` is what the walk read before this
    family retired, and it returns the SURVIVING share.  So does the
    interpreter, and that is the whole hazard the fixture guards: the
    declaration carries the cut, the ledger multiplies by its complement, and
    a subtraction on the wrong side is off by the entire effect.
    """
    item = data_fetcher.get_item_by_name("Serpent's Fang")
    before = item_effects.serpents_fang_venom([item], is_melee=holder_is_melee)
    after = damage_routing.walk_venom(
        ["Serpent's Fang"],
        level=13,
        fight_duration_seconds=8.0,
        target_bonus_health=0.0,
        holder_is_melee=holder_is_melee,
    )
    assert before is not None and after is not None
    assert (after.keep, after.duration) == before
    assert after.owner == "Serpent's Fang"


def test_the_walk_execution_equals_the_pair_engines_stamp() -> None:
    """The Collector: the Execute rider, against the ratio the pair engine stamps.

    ``damage.py`` stamps ``execute_threshold_ratio`` from
    ``item_effects``'s own ``ExecuteEffect``; the walk now reads the
    declaration.  Equal numbers, one producer.
    """
    effects = item_effects.resolve_damage_effects(
        [data_fetcher.get_item_by_name("The Collector")]
    )
    rider = damage_routing.walk_execution(
        ["The Collector"],
        level=13,
        fight_duration_seconds=8.0,
        target_bonus_health=0.0,
        holder_is_melee=True,
    )
    assert effects.execute is not None and rider is not None
    assert rider.threshold == effects.execute.threshold
    assert rider.owner == effects.execute.item_name


@pytest.mark.parametrize("holder_is_melee", [True, False])
def test_the_walk_deferral_equals_the_resolved_defensive_state(
    holder_is_melee: bool,
) -> None:
    """Death's Dance: the Defer rider, against the resolver's own schedule.

    The resolver still builds this family's schedule and still publishes it
    as the holder's opening defensive state; what the walk now stages is the
    rider.  Two consumers of one declaration is only honest while they agree,
    so the fixture is what makes that a checked fact -- including the
    melee/ranged share, which is resolved against the holder paying it.
    """
    (rule,) = [
        candidate
        for candidate in catalog.behavior_rules("Death's Dance")
        if candidate.family is RuleFamily.DAMAGE_ROUTING
    ]
    subject = DefenseSubject(
        level=13, stats={"is_melee": float(holder_is_melee)}, options={}
    )
    outcome = interpreters.resolve_defense(rule, subject)
    resolved = {grant.name: grant.value for grant in outcome.fields}
    rider = damage_routing.walk_deferral(
        ["Death's Dance"],
        level=13,
        fight_duration_seconds=8.0,
        target_bonus_health=0.0,
        holder_is_melee=holder_is_melee,
    )
    assert rider is not None
    assert rider.fraction == resolved[DefenseField.DAMAGE_DEFERRAL_FRACTION.value]
    assert rider.duration == resolved[DefenseField.DAMAGE_DEFERRAL_DURATION.value]
    assert rider.ticks == resolved[DefenseField.DAMAGE_DEFERRAL_TICKS.value]


def test_no_routing_declaration_is_left_without_a_walk_branch() -> None:
    """Amendment P's stop clause, as a test rather than as a reading.

    Every declaration of the family compiles on the walk lane.  A fourth
    mechanic whose payload the interpreter has no branch for raises here
    instead of reaching a payload as a silently unstaged rider.
    """
    rules = damage_routing.walk_rules(sorted(catalog.rule_owners()))
    assert {rule.mechanic_id for rule in rules} == {
        "deaths_dance.ignore_pain",
        "serpents_fang.shield_bypass",
        "the_collector.execute",
    }
    for rule in rules:
        fields = damage_routing.WALK_INTERPRETER.compile(
            rule,
            catalog.build_context(
                rule.owner,
                13,
                fight_duration_seconds=8.0,
                target_bonus_health=0.0,
                holder_is_melee=True,
            ),
        )
        assert fields
        assert all(field.lane is EngineLane.RECEIPT_WALK for field in fields)
