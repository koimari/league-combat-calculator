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
from src.calculator import interpreters
from src.calculator import item_coverage
from src.calculator import item_behavior_catalog as catalog
from src.calculator.item_behavior import (
    Compilable,
    EngineLane,
    ReceiptOnly,
    ReceiptScope,
    RuleFamily,
    SUBJECT_AUTHORITY,
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
    assert len(interpreters.declared_pairs()) == 53


def test_counter_four_is_the_gap_between_the_table_and_the_registry() -> None:
    """Every declared pair with no interpreter is counted, never assumed away."""
    gap = frozenset(interpreters.uninterpreted_pairs())
    assert gap == interpreters.declared_pairs() - frozenset(interpreters.INTERPRETERS)
    assert (
        RuleFamily.DELTA_AMP,
        EngineLane.PAIR_ENGINE,
    ) in interpreters.INTERPRETERS


def test_the_compiled_score_walk_gap_is_a_receipt_and_not_a_zero() -> None:
    """An amp's compiled lane is a named refusal until H5's stage flips it.

    H5 is SCOPED, and the extension it scopes is a stage of its own after
    Phase 4's S7; before that stage's flip the kernel still raises, so the
    lane is a receipt rather than a zero (D-101).
    """
    assert (
        RuleFamily.DELTA_AMP,
        EngineLane.COMPILED_SCORE_WALK,
    ) in interpreters.uninterpreted_pairs()
    verdict = interpreters.compilability_for(
        "Horizon Focus", ReceiptScope.SCORE_KERNEL_DAMAGE_MODIFIER
    )
    assert isinstance(verdict, ReceiptOnly)
    assert "compiled score kernel" in verdict.reason
    # ...and the amp refusal answers only its own scope: asking the
    # build-level gate's question about an amp holder must not fall a build
    # back for a refusal that gate does not own.
    assert isinstance(
        interpreters.compilability_for(
            "Horizon Focus", ReceiptScope.SURVIVAL_LEDGER_TRANSITION
        ),
        Compilable,
    )


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
    """
    monkeypatch.setattr(
        interpreters,
        "UNSERVED_LANE_RECEIPTS",
        dict(interpreters.UNSERVED_LANE_RECEIPTS)
        | {
            (
                RuleFamily.ON_HIT_STRIKE,
                EngineLane.PAIR_ENGINE,
            ): interpreters.UnservedLane(
                reason="a lane that is in fact served", retires_at="never"
            )
        },
    )
    with pytest.raises(
        interpreters.InterpreterRegistryError, match="receipt for nothing"
    ):
        interpreters.validate_registrations()


def test_a_compiled_gap_is_excused_by_the_rules_own_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The per-rule form, which is the one every amp carries (D-101).

    Both halves are asserted on one stub: the same family and lane passes with
    a ``ReceiptOnly`` compilability and raises with a ``Compilable`` one, so
    what is being tested is the receipt and not the pair.  ``delta_amp``'s
    compiled lane is deliberately absent from the dated table for exactly this
    reason, and that absence is asserted here rather than left to be noticed.
    """
    assert (
        RuleFamily.DELTA_AMP,
        EngineLane.COMPILED_SCORE_WALK,
    ) not in interpreters.UNSERVED_LANE_RECEIPTS

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
            (RuleFamily.DELTA_AMP, EngineLane.PAIR_ENGINE): interpreters.INTERPRETERS[
                (RuleFamily.DELTA_AMP, EngineLane.PAIR_ENGINE)
            ]
        },
    )
    monkeypatch.setattr(
        interpreters,
        "UNSERVED_LANE_RECEIPTS",
        {
            (RuleFamily.DELTA_AMP, EngineLane.RECEIPT_WALK): (
                interpreters.UNSERVED_LANE_RECEIPTS[
                    (RuleFamily.DELTA_AMP, EngineLane.RECEIPT_WALK)
                ]
            )
        },
    )
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


def test_every_dated_gap_row_says_what_retires_it() -> None:
    """A gap with no date is the silence the table exists to replace."""
    for (family, lane), row in interpreters.UNSERVED_LANE_RECEIPTS.items():
        assert row.reason.strip(), f"{family.value}/{lane.value} has no reason"
        assert row.retires_at.strip(), f"{family.value}/{lane.value} has no date"
        assert (family, lane) not in interpreters.INTERPRETERS
