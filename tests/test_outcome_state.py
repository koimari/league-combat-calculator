"""The outcome ledger: write-once, and one named way to change its mind.

D-64.  Two properties carry this module and both are tested as refusals
rather than as capabilities: a second answer to a question already answered
raises, and the only revision that does not raise is one carrying a member of
a one-member reason enum.  A ledger that merely *documents* write-once is the
prose-outruns-code shape the campaign exists to kill.
"""

from __future__ import annotations

import pytest

from src.calculator import ability_spec, trigger_stream
from tests import ability_math
from src.calculator.ability_spec import Disposition
from src.calculator.survival import outcome_state
from src.calculator.survival.actions import NO_SLOT, ActionKind, SurvivalAction


def action(slot: int, *, event_slot: int = NO_SLOT, trigger_slot: int = NO_SLOT):
    """One typed action addressed at ledger slot *slot*."""
    return SurvivalAction(
        kind=ActionKind.DAMAGE,
        aidx=slot,
        event_slot=event_slot,
        trigger_slot=trigger_slot,
    )


def test_a_written_outcome_projects_the_four_numbers() -> None:
    """The ledger's whole read surface: one slot in, one Outcome out."""
    ledger = outcome_state.OutcomeLedger()
    ledger.write(action(0), damage=120.5)
    ledger.write(action(0), shield_absorbed=20.5, _applied_to_health=100.0)
    ledger.write(action(0), overkill=0.0)
    outcome = ledger.get(0)
    assert (outcome.applied, outcome.absorbed) == (120.5, 20.5)
    assert (outcome.to_health, outcome.overkill) == (100.0, 0.0)
    assert outcome.skipped_reason is None
    assert outcome.was_skipped is False


def test_a_slot_no_transition_wrote_projects_zeros_with_no_refusal() -> None:
    """An unreached slot has no number and no reason, and says both."""
    outcome = outcome_state.OutcomeLedger().get(7)
    assert (outcome.applied, outcome.absorbed) == (0.0, 0.0)
    assert outcome.skipped_reason is None
    assert outcome.adjustments == ()


def test_a_second_write_of_one_field_raises_naming_both_values() -> None:
    """Write-once, and the report is actionable rather than a bare complaint."""
    ledger = outcome_state.OutcomeLedger()
    ledger.write(action(3), damage=90.0)
    with pytest.raises(outcome_state.OutcomeRewritten) as excinfo:
        ledger.write(action(3), damage=10.0)
    assert (excinfo.value.slot, excinfo.value.field) == (3, "applied")
    assert (excinfo.value.old, excinfo.value.new) == (90.0, 10.0)


def test_rewriting_the_same_value_is_still_a_rewrite() -> None:
    """Two rules answering one question agree today; that is not the test."""
    ledger = outcome_state.OutcomeLedger()
    ledger.write(action(1), damage=42.0)
    with pytest.raises(outcome_state.OutcomeRewritten):
        ledger.write(action(1), damage=42.0)


def test_two_kernel_kwargs_naming_one_outcome_field_collide() -> None:
    """``damage`` and ``applied_amount`` are one field, so they cannot both win."""
    ledger = outcome_state.OutcomeLedger()
    ledger.write(action(2), damage=5.0)
    with pytest.raises(outcome_state.OutcomeRewritten):
        ledger.write(action(2), applied_amount=5.0)


def test_a_kwarg_the_ledger_does_not_map_is_dropped_not_invented() -> None:
    """The kernel writes receipt fields too; they are not fifth outcomes."""
    ledger = outcome_state.OutcomeLedger()
    ledger.write(action(4), expires_at=3.0, pair_damage=17.0)
    assert ledger.get(4) == outcome_state.Outcome()


def test_a_slotless_action_records_nothing() -> None:
    """``NO_SLOT`` is "this action has no ledger row", not "row -1"."""
    ledger = outcome_state.OutcomeLedger()
    ledger.write(action(NO_SLOT), damage=1.0)
    assert list(ledger.slots()) == []


def test_a_refusal_is_recorded_as_a_reason_and_not_as_a_zero() -> None:
    """The campaign's invariant at ledger granularity."""
    ledger = outcome_state.OutcomeLedger()
    ledger.skip(action(5), "target_dead")
    outcome = ledger.get(5)
    assert outcome.skipped_reason == "target_dead"
    assert outcome.was_skipped is True
    assert outcome.applied == 0.0


def test_a_second_refusal_raises_unless_the_first_is_preserved() -> None:
    """The one legitimate double skip is the holder-health gate's, declared."""
    ledger = outcome_state.OutcomeLedger()
    ledger.skip(action(6), "holder_health_gate")
    ledger.skip(action(6), "redirect_gate", preserve_reason=True)
    assert ledger.get(6).skipped_reason == "holder_health_gate"
    with pytest.raises(outcome_state.OutcomeRewritten):
        ledger.skip(action(6), "redirect_gate")


def test_the_only_adjustment_reason_is_the_holder_health_gate() -> None:
    """D-64: exactly one named way a later transition revises an earlier one."""
    assert [member.name for member in outcome_state.AdjustmentReason] == [
        "HOLDER_HEALTH_GATE"
    ]


def test_an_adjustment_revises_the_value_and_survives_beside_it() -> None:
    """A revision is a record, so the rule that changed its mind is readable."""
    ledger = outcome_state.OutcomeLedger()
    ledger.write(action(8), damage=0.0)
    ledger.adjust(
        outcome_state.Adjustment(
            slot=8,
            field="applied",
            value=310.0,
            reason=outcome_state.AdjustmentReason.HOLDER_HEALTH_GATE,
        )
    )
    outcome = ledger.get(8)
    assert outcome.applied == 310.0
    assert [adjustment.reason for adjustment in outcome.adjustments] == [
        outcome_state.AdjustmentReason.HOLDER_HEALTH_GATE
    ]
    assert ledger.adjustments() == outcome.adjustments


def test_an_adjustment_cannot_invent_an_answer_nobody_computed() -> None:
    """Revising an unwritten field would be a write wearing a reason."""
    ledger = outcome_state.OutcomeLedger()
    with pytest.raises(outcome_state.UnwrittenAdjustment):
        ledger.adjust(
            outcome_state.Adjustment(
                slot=9,
                field="applied",
                value=1.0,
                reason=outcome_state.AdjustmentReason.HOLDER_HEALTH_GATE,
            )
        )


def test_an_adjustment_names_a_real_field_and_a_declared_reason() -> None:
    """Both invariants live on the record, so a bad one cannot be constructed."""
    with pytest.raises(ValueError):
        outcome_state.Adjustment(
            slot=0,
            field="not_an_outcome",
            value=1.0,
            reason=outcome_state.AdjustmentReason.HOLDER_HEALTH_GATE,
        )
    with pytest.raises(ValueError):
        outcome_state.Adjustment(
            slot=0, field="applied", value=1.0, reason="holder_health_gate"
        )


def test_trigger_linkage_matches_the_two_ledgers_it_sits_beside() -> None:
    """No trigger passes; an applied trigger passes; a blocked one does not."""
    ledger = outcome_state.OutcomeLedger()
    assert ledger.trigger_applied(action(0)) is True
    ledger.mark_applied(action(1, event_slot=11))
    assert ledger.trigger_applied(action(2, trigger_slot=11)) is True
    ledger.mark_blocked(action(3, event_slot=12))
    assert ledger.trigger_applied(action(4, trigger_slot=12)) is False


def test_scheduling_a_walk_authored_heal_fails_closed() -> None:
    """A walk-authored packet is an action; this ledger holds outcomes."""
    ledger = outcome_state.OutcomeLedger()
    with pytest.raises(AssertionError) as excinfo:
        ledger.schedule_heal({"source_key": "maw_omnivamp"}, "main")
    assert "maw_omnivamp" in str(excinfo.value)


def test_annotations_are_dropped_unless_the_ledger_is_annotating() -> None:
    """Verbosity is a flag on one ledger, not a second ledger (S3's ruling)."""
    quiet = outcome_state.OutcomeLedger()
    quiet.annotate(action(0), overkill=5.0)
    assert quiet.get(0).overkill == 0.0
    assert quiet.records_annotations is False

    loud = outcome_state.OutcomeLedger(annotating=True)
    loud.annotate(action(0), overkill=5.0)
    assert loud.get(0).overkill == 5.0
    assert loud.records_annotations is True


def test_the_ledger_answers_the_whole_kernel_adapter_protocol() -> None:
    """Drop-in third adapter: the same surface the other two implement."""
    protocol = (
        "write",
        "annotate",
        "skip",
        "trigger_applied",
        "mark_applied",
        "mark_blocked",
        "schedule_heal",
        "records_annotations",
        "records_event_fields",
    )
    ledger = outcome_state.OutcomeLedger()
    for name in protocol:
        assert hasattr(ledger, name), name


# ---------------------------------------------------------------------------
# Where a leaf is born: ledger reads wrapped as Quantity (D-72)
# ---------------------------------------------------------------------------


def test_a_written_field_reads_as_measured_wrapping_the_same_float() -> None:
    """S3's purity claim, at the boundary: ``Measured`` wraps, it transforms not."""
    ledger = outcome_state.OutcomeLedger()
    ledger.write(action(0), damage=123.456789)
    quantity = ledger.quantity(0, "applied")
    assert quantity.disposition is Disposition.MEASURED
    assert quantity.read() == ledger.get(0).applied == 123.456789


def test_a_refused_transition_reads_as_a_structural_zero_carrying_its_reason() -> None:
    """The walk said the mechanic does not apply; the reason is the receipt."""
    ledger = outcome_state.OutcomeLedger()
    ledger.skip(action(1), "target_dead")
    quantity = ledger.quantity(1, "applied")
    assert quantity.disposition is Disposition.STRUCTURAL_ZERO
    assert quantity.reason == "target_dead"
    assert quantity.read() == 0.0


def test_a_field_with_no_write_and_no_refusal_reads_as_starved() -> None:
    """The campaign's invariant where the leaf is born.

    The ledger holds neither a number nor a refusal for this slot, so it
    cannot say whether the rule ran -- and answering 0.0 would be exactly the
    uncomputed number that looks computed.
    """
    ledger = outcome_state.OutcomeLedger()
    quantity = ledger.quantity(2, "applied")
    assert quantity.disposition is Disposition.STARVED
    assert quantity.field == "applied"
    with pytest.raises(trigger_stream.ProjectionStarvation):
        quantity.read()


def test_the_starved_read_is_lazy() -> None:
    """Holding one costs nothing; reading one is the error (D-25)."""
    ledger = outcome_state.OutcomeLedger()
    held = [ledger.quantity(slot, "overkill") for slot in range(5)]
    assert all(item.disposition is Disposition.STARVED for item in held)


def test_quantities_answers_every_numeric_field_and_no_receipt_field() -> None:
    """``skipped_reason`` is a receipt, not a number, so it has no quantity."""
    ledger = outcome_state.OutcomeLedger()
    ledger.write(action(3), damage=10.0, shield_absorbed=2.0)
    quantities = ledger.quantities(3)
    assert set(quantities) == {"applied", "absorbed", "to_health", "overkill"}
    assert quantities["applied"].disposition is Disposition.MEASURED
    assert quantities["to_health"].disposition is Disposition.STARVED
    with pytest.raises(ValueError):
        ledger.quantity(3, "skipped_reason")


def test_an_unknown_field_cannot_be_asked_for() -> None:
    """A typo must never become a fifth outcome that reads as starved."""
    with pytest.raises(ValueError):
        outcome_state.OutcomeLedger().quantity(0, "aplied")


def test_a_total_over_a_refused_and_a_measured_member_is_measured() -> None:
    """A structural zero contributes 0.0, which is the propagation row."""
    ledger = outcome_state.OutcomeLedger()
    ledger.write(action(0), damage=40.0)
    ledger.skip(action(1), "spell_shield_blocked")
    total = ability_math.quantity_sum(
        (ledger.quantity(0, "applied"), ledger.quantity(1, "applied"))
    )
    assert total == ability_spec.Measured(amount=40.0)


def test_a_total_over_a_starved_member_raises_rather_than_counting_it_as_zero() -> None:
    """The incident at the aggregate, refused by the algebra rather than by review."""
    ledger = outcome_state.OutcomeLedger()
    ledger.write(action(0), damage=40.0)
    with pytest.raises(trigger_stream.ProjectionStarvation):
        ability_math.quantity_sum(
            (ledger.quantity(0, "applied"), ledger.quantity(9, "applied"))
        )


class TestAtMostOneAppliedContribution:
    """D-62's other half, and the half a write-once field does not cover.

    Write-once is keyed by ``(slot, field)``: it stops one transition
    answering the same question twice and says nothing about a *second
    producer*.  Two engines each delivering an applied number for one
    mechanic on one subject at one event are two different slots, both
    legitimate write-once writes, and one mechanic counted twice -- which is
    the arrangement keeping a legacy amp alive beside a new coupled pricer
    would create.
    """

    @staticmethod
    def contribution(slot: int, *, source: str, subject: int, event: int):
        """One applied delivery, addressed by the criterion's own key."""
        return SurvivalAction(
            kind=ActionKind.DAMAGE,
            aidx=slot,
            subject=subject,
            source_key=source,
            event_slot=event,
        )

    def test_one_contribution_per_key_is_recorded(self) -> None:
        ledger = outcome_state.OutcomeLedger()
        ledger.write(
            self.contribution(0, source="mandate", subject=1, event=7), damage=40.0
        )
        assert ledger.applied_contributions() == {("mandate", 1, 7): 0}

    def test_a_second_producer_of_the_same_contribution_raises(self) -> None:
        """Two slots, one (mechanic, subject, event_id): a double count."""
        ledger = outcome_state.OutcomeLedger()
        ledger.write(
            self.contribution(0, source="mandate", subject=1, event=7), damage=40.0
        )
        with pytest.raises(outcome_state.DuplicateApplied) as raised:
            ledger.write(
                self.contribution(3, source="mandate", subject=1, event=7),
                applied_amount=40.0,
            )
        assert raised.value.key == ("mandate", 1, 7)
        assert (raised.value.first, raised.value.second) == (0, 3)

    def test_the_same_mechanic_on_a_second_subject_is_not_a_duplicate(self) -> None:
        """Imperial Mandate arms two allies; that is two contributions."""
        ledger = outcome_state.OutcomeLedger()
        ledger.write(
            self.contribution(0, source="mandate", subject=1, event=7), damage=40.0
        )
        ledger.write(
            self.contribution(1, source="mandate", subject=2, event=7), damage=40.0
        )
        assert len(ledger.applied_contributions()) == 2

    def test_the_same_subject_on_a_second_event_is_not_a_duplicate(self) -> None:
        ledger = outcome_state.OutcomeLedger()
        ledger.write(
            self.contribution(0, source="mandate", subject=1, event=7), damage=40.0
        )
        ledger.write(
            self.contribution(1, source="mandate", subject=1, event=8), damage=40.0
        )
        assert len(ledger.applied_contributions()) == 2

    def test_a_second_mechanic_on_one_event_is_not_a_duplicate(self) -> None:
        ledger = outcome_state.OutcomeLedger()
        ledger.write(
            self.contribution(0, source="mandate", subject=1, event=7), damage=40.0
        )
        ledger.write(
            self.contribution(1, source="abyssal", subject=1, event=7), damage=40.0
        )
        assert len(ledger.applied_contributions()) == 2

    def test_one_slot_writing_two_applied_aliases_is_a_rewrite_not_a_duplicate(
        self,
    ) -> None:
        """The write-once rule still owns the one-slot case, by its own name."""
        ledger = outcome_state.OutcomeLedger()
        packet = self.contribution(0, source="mandate", subject=1, event=7)
        ledger.write(packet, damage=40.0)
        with pytest.raises(outcome_state.OutcomeRewritten):
            ledger.write(packet, applied_amount=40.0)

    def test_a_refusal_claims_no_contribution(self) -> None:
        """A skipped transition delivered nothing, so it claims no key."""
        ledger = outcome_state.OutcomeLedger()
        ledger.skip(self.contribution(0, source="mandate", subject=1, event=7), "gated")
        assert ledger.applied_contributions() == {}


class TestTheDiagnosticAnnotationsAreNotOutcomes:
    """``pair_damage`` and ``live_damage`` are one annotation's two halves.

    Both are the packet's value *before* absorption; the applied outcome is
    what consumed shield and health.  Mapping either onto ``applied`` makes
    one question answerable twice, with two numbers that agree only while
    nothing overkills.
    """

    @staticmethod
    def packet():
        """One damage action addressed at a real ledger slot."""
        return SurvivalAction(
            kind=ActionKind.DAMAGE, aidx=0, event_slot=3, source_key="q", subject=1
        )

    def test_neither_half_of_the_pair_maps_onto_an_outcome_field(self) -> None:
        aliases = outcome_state.OutcomeLedger._WRITE_ALIASES
        assert "live_damage" not in aliases
        assert "pair_damage" not in aliases

    def test_the_annotation_and_the_applied_write_do_not_collide(self) -> None:
        """The live sequence: annotate the diagnostics, then write the outcome."""
        ledger = outcome_state.OutcomeLedger(annotating=True)
        packet = self.packet()
        ledger.annotate(packet, pair_damage=300.0, live_damage=240.0)
        ledger.write(packet, damage=180.0, _applied_to_health=150.0)
        assert ledger.get(0).applied == 180.0

    def test_the_applied_outcome_is_the_absorbed_one_not_the_live_one(self) -> None:
        """Overkill is where the two numbers part, so it is where this is read."""
        ledger = outcome_state.OutcomeLedger(annotating=True)
        packet = self.packet()
        ledger.annotate(packet, live_damage=1000.0)
        ledger.write(packet, damage=250.0)
        ledger.annotate(packet, overkill=750.0)
        outcome = ledger.get(0)
        assert (outcome.applied, outcome.overkill) == (250.0, 750.0)


class TestTheReceiptWalkRunsIt:
    """The join, over real fights rather than over fixtures.

    Both properties above are refusals, and a refusal that never ranges over
    a real fight is indistinguishable from one that cannot fire.  So this
    class asserts the ledger is the receipt adapter's companion, that a live
    coupled walk actually fills it, and that D-62's uniqueness is enforced on
    the production object rather than on a ledger a test built.
    """

    @staticmethod
    def capturing_ledger(monkeypatch):
        """Drive the real coupled walk, keeping every ledger it builds."""
        import importlib.util
        import sys
        from pathlib import Path

        from src.calculator import participant_timeline
        from src.calculator.survival import receipt_state

        built: list[receipt_state.ReceiptLedger] = []

        class Capturing(receipt_state.ReceiptLedger):
            """The production ledger, with a list of the ones a walk made."""

            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                built.append(self)

        monkeypatch.setattr(participant_timeline, "ReceiptLedger", Capturing)
        root = Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location(
            "golden_snapshot", root / "scripts" / "golden_snapshot.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("golden_snapshot", module)
        spec.loader.exec_module(module)
        definition = next(
            item
            for item in module.COUPLED_SCENARIOS
            if item.name == "cleaver_bloodsong_roster"
        )
        module.coupled_entry(definition)
        return built

    def test_the_receipt_adapter_carries_one(self) -> None:
        """The construction site the escalation's reproducer looked for."""
        from src.calculator.survival import receipt_state

        ledger = receipt_state.ReceiptLedger(
            actions=[], index_of={}, compile_event=lambda *a, **k: None
        )
        assert isinstance(ledger.outcomes, outcome_state.OutcomeLedger)

    def test_a_live_fight_fills_it(self, monkeypatch) -> None:
        """A real coupled walk writes outcomes, so the rules have a domain."""
        built = self.capturing_ledger(monkeypatch)
        assert built, "the coupled walk built no receipt ledger"
        assert any(list(ledger.outcomes.slots()) for ledger in built)

    def test_a_live_fight_claims_applied_contributions(self, monkeypatch) -> None:
        """D-62's uniqueness ranges over real keys, not over fixture keys."""
        built = self.capturing_ledger(monkeypatch)
        claimed = {
            key: slot
            for ledger in built
            for key, slot in ledger.outcomes.applied_contributions().items()
        }
        assert claimed, "no applied contribution was claimed over a real fight"

    def test_a_live_fight_records_the_walks_refusals(self, monkeypatch) -> None:
        """A refusal reaches the ledger, which is where a declared zero is born."""
        built = self.capturing_ledger(monkeypatch)
        refused = [
            ledger.outcomes.get(slot).skipped_reason
            for ledger in built
            for slot in ledger.outcomes.slots()
            if ledger.outcomes.get(slot).was_skipped
        ]
        assert refused, "the coupled corpus refused no transition"
        assert all(reason for reason in refused)

    def test_the_production_ledger_refuses_a_double_count(self) -> None:
        """R-05's seam: the live path's uniqueness fails on demand."""
        from src.calculator.survival import receipt_state

        ledger = receipt_state.ReceiptLedger(
            actions=[], index_of={}, compile_event=lambda *a, **k: None
        )
        first = SurvivalAction(
            kind=ActionKind.DAMAGE,
            aidx=0,
            event_slot=7,
            source_key="mandate",
            subject=1,
            event={},
        )
        second = SurvivalAction(
            kind=ActionKind.DAMAGE,
            aidx=1,
            event_slot=7,
            source_key="mandate",
            subject=1,
            event={},
        )
        ledger.write(first, damage=40.0)
        with pytest.raises(outcome_state.DuplicateApplied):
            ledger.write(second, damage=40.0)

    def test_the_production_ledger_refuses_a_second_answer(self) -> None:
        """The write-once half, on the object the walk actually drives."""
        from src.calculator.survival import receipt_state

        ledger = receipt_state.ReceiptLedger(
            actions=[], index_of={}, compile_event=lambda *a, **k: None
        )
        packet = SurvivalAction(kind=ActionKind.DAMAGE, aidx=0, event={})
        ledger.write(packet, overkill=1.0)
        with pytest.raises(outcome_state.OutcomeRewritten):
            ledger.write(packet, overkill=2.0)
