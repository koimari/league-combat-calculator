"""The oracle pass over S6/S7's diffs raised four dissents; three escalate.

The pass returned 78 ``new_value_correct``, 2 ``old_value_correct`` and 2
``both_wrong``.  One dissent was a real defect — Bloodsong's Expose Weakness
armed twice inside its own window and multiplied a packet by 1.08 squared —
and is corrected in its own commit.  The other three are not absorbable and
not fixable from an implementation lane: one silent-failure the correction
narrows but does not remove, and two gaps in the oracle protocol itself.

Each entry is joined to a **reproducer** — a live property of the tree that
is true while the defect stands and false once it is fixed — and this file
goes red when one of them stops reproducing.  That is how an entry is closed
deliberately rather than quietly, and it is why the escalation is an artifact
rather than a sentence in a commit body: a commit body is absorbed by the
next baseline re-capture.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import golden_snapshot as gs  # noqa: E402  (path is set above)

from src.calculator.ability_spec import AttackClass, DamageClass  # noqa: E402
from src.calculator.survival.actions import SurvivalAction  # noqa: E402
from src.calculator.survival.transitions import (  # noqa: E402
    _apply_cross_participant_modifiers,
    _apply_damage_modifier,
)

RECEIPTS = ROOT / "docs" / "receipts"
RECEIPT = RECEIPTS / "escalated-defects-S6S7-oracle.json"

REQUIRED = ("id", "dated", "raised_by", "what", "reproducer")
REQUIRED_TO_RETIRE = ("retired_on", "resolved_by", "resolution")

EXPOSE = "Bloodsong — Expose Weakness"
UNMAKE = "Abyssal Mask — Unmake"


def _ledger():
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def _entries():
    return _ledger()["defects"]


def _ids():
    return {entry["id"] for entry in _entries()}


class _Ledger:
    """The one ledger call the two transitions under test make."""

    @staticmethod
    def write(action, **fields):
        """Write onto the packet, exactly as OutcomeLedger.write does."""
        if action.event is not None:
            action.event.update(fields)

    @staticmethod
    def skip(action, reason):  # pylint: disable=unused-argument
        """Record nothing: no test here arms an unavailable modifier."""


class _Ctx:
    """The one context member the two transitions under test read."""

    ledger = _Ledger()


class TestTheLedgerIsWellFormed:
    """A ledger nobody has to fill in is a ledger that says nothing."""

    def test_every_entry_is_complete(self):
        entries = _entries() + _ledger()["retired"]
        assert entries, "the escalation ledger is empty"
        for entry in entries:
            for field in REQUIRED:
                assert entry.get(field), f"{entry.get('id')} omits {field}"
            assert len(entry["dated"]) == 10 and entry["dated"].count("-") == 2

    def test_a_retired_entry_names_the_ruling_that_closed_it(self):
        """Retirement is a recorded ruling, not a deletion."""
        for entry in _ledger()["retired"]:
            for field in REQUIRED_TO_RETIRE:
                assert entry.get(field), f"{entry['id']} retires without {field}"

    def test_the_ledger_names_the_slice_and_this_gate(self):
        body = _ledger()
        assert body["slice"] == "S6S7-oracle"
        assert body["gate"] == "tests/test_escalated_defects_s6s7_oracle.py"


class TestTheReceiptCanStillContradictTheNumber:
    """First entry's reproducer: two modifiers, one published factor."""

    def test_the_defect_is_declared(self):
        assert (
            "support_damage_multiplier_publishes_one_of_several_applied_factors"
            in _ids()
        )

    def test_two_holders_apply_two_factors_and_the_receipt_names_one(self):
        """The applied product is 1.08 squared; the receipt says 1.08.

        This is the shape that hid the corrected defect: every moved leaf
        carried a truthful-looking multiplier beside a value the multiplier
        does not produce.  The refresh rule folds two arms of one mechanic by
        one holder and deliberately leaves this — two *holders*, which
        ``HolderStacking.PER_HOLDER`` exists to keep — standing.
        """
        state = {"active_damage_modifiers": []}
        for holder in (0, 1):
            _apply_damage_modifier(
                _Ctx(),
                SurvivalAction(
                    source=EXPOSE,
                    time=1.0,
                    duration=4.0,
                    attacker=holder,
                    multiplier=1.08,
                    amount=0.08,
                    damage_classes=frozenset(DamageClass),
                    attack_classes=frozenset(AttackClass),
                    event={},
                ),
                state,
            )
        packet = SurvivalAction(
            time=2.0,
            attacker=2,
            damage_type="physical",
            basic_attack=True,
            event={},
        )
        amount = _apply_cross_participant_modifiers(_Ctx(), packet, state, 100.0)
        published = packet.event["support_damage_multiplier"]["multiplier"]
        assert amount == pytest.approx(100.0 * 1.08 * 1.08)
        assert published == pytest.approx(1.08)
        assert amount != pytest.approx(100.0 * published)

    def test_two_mechanics_on_one_packet_publish_one_of_them(self):
        """The same shape without a second holder — two different curses."""
        state = {"active_damage_modifiers": []}
        for source, multiplier in ((EXPOSE, 1.08), (UNMAKE, 1.12)):
            _apply_damage_modifier(
                _Ctx(),
                SurvivalAction(
                    source=source,
                    time=0.0,
                    duration=4.0,
                    attacker=0,
                    multiplier=multiplier,
                    amount=multiplier - 1.0,
                    damage_classes=frozenset(DamageClass),
                    attack_classes=frozenset(AttackClass),
                    event={},
                ),
                state,
            )
        packet = SurvivalAction(
            time=1.0,
            attacker=2,
            damage_type="magic",
            basic_attack=True,
            event={},
        )
        amount = _apply_cross_participant_modifiers(_Ctx(), packet, state, 100.0)
        published = packet.event["support_damage_multiplier"]["multiplier"]
        assert amount == pytest.approx(100.0 * 1.08 * 1.12)
        assert amount != pytest.approx(100.0 * published)


class TestOrdinalAddressingSubstitutesEvents:
    """Second entry's reproducer: a leaf path is an ordinal, not an identity."""

    def test_the_defect_is_declared(self):
        assert (
            "ordinal_addressed_leaf_paths_hand_an_oracle_two_different_events" in _ids()
        )

    def test_one_inserted_member_reports_every_later_member_as_a_change(self):
        """The oracle is handed two values that describe two different events.

        ``leaf_report`` pairs ``events[n]`` with ``events[n]``, so removing or
        inserting an earlier member re-labels every later one.  S6/S7 removed
        two events from one scenario, and two of this pass's four dissents are
        readings of that substitution rather than of a wrong number.
        """
        old = {
            "combat": {
                "events": [{"damage_type": "physical"}, {"damage_type": "magic"}]
            }
        }
        new = {
            "combat": {
                "events": [
                    {"damage_type": "true"},
                    {"damage_type": "physical"},
                    {"damage_type": "magic"},
                ]
            }
        }
        diffs = {diff.path: (diff.old, diff.new) for diff in gs.leaf_report(old, new)}
        assert diffs["/combat/events[0]/damage_type"] == ("physical", "true")
        assert diffs["/combat/events[1]/damage_type"] == ("magic", "physical")


class TestTheVerdictSetCannotSayNoEvidence:
    """Third entry's reproducer: a 'cannot certify' has to be spelled as a dissent."""

    def test_the_defect_is_declared(self):
        assert (
            "the_verdict_enum_has_no_member_for_a_leaf_the_evidence_tree_cannot_decide"
            in _ids()
        )

    @pytest.mark.parametrize(
        "receipt,verdict",
        [
            ("oracle-S6S7-leaf24.json", "old_value_correct"),
            ("oracle-S6S7-leaf30.json", "both_wrong"),
        ],
    )
    def test_a_dissent_still_carries_its_own_statement_of_no_evidence(
        self, receipt, verdict
    ):
        """Both receipts say, in their own words, that nothing could decide.

        The verdict they had to return says the opposite, because R-19's set
        has no member for it.  While both halves are true of the committed
        receipt the escalation stands.
        """
        body = json.loads((RECEIPTS / receipt).read_text(encoding="utf-8"))
        assert body["verdict"] == verdict
        prose = json.dumps(body).lower()
        assert "not" in prose
        assert any(
            marker in prose
            for marker in (
                "cannot",
                "could not",
                "no such computation",
                "not excludable",
            )
        )
