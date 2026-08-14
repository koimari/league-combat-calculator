"""The ledger join's raise set, asserted rather than described.

`69e7323` joined the write-once ``OutcomeLedger`` to the receipt walk, so a
record that raises is now built and driven on every ``/api/calculate``,
``/api/bis`` and ``/api/optimize`` request.  That is the design working — a
second answer to one question is refused — and it is also an operational
change no commit body stated: a condition that used to resolve silently, the
event dict taking the last write, is now an unhandled exception on a user
request.

This file is the escalation's gate, and it has done the job the last
paragraph of this docstring used to describe.  It asserted three facts: the
ledger is constructed on the serving path, the three raises are real, and the
request boundary does not name them.  The third inverted on 2026-08-14, when
the umbrella's Amendment G ruled that D-25's "exactly one catch" names a
place rather than an exception type and that a contested outcome is
``STARVED``.  So the assertions below now state the resolved property: the
raises are still raises, nothing absorbs them, and the boundary converts them
into a 500 carrying the field, the producer and the reason.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.app as app_module
from src.calculator.survival.actions import SurvivalAction
from src.calculator.survival.outcome_state import (
    DuplicateApplied,
    OutcomeLedger,
    OutcomeRewritten,
)
from src.calculator.survival.receipt_state import ReceiptLedger

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "docs" / "receipts" / "escalated-defects-ledger-join.json"
ENTRY_ID = (
    "the_write_once_ledger_raises_on_three_serving_paths_and_no_boundary_names_it"
)


def _entry():
    """The entry, read from the list it is actually in.

    It retired rather than being deleted, so this reads ``retired`` and
    asserts ``defects`` is empty: an entry quietly reopening under a new id
    would otherwise be invisible to the file that gates it.
    """
    block = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert block["defects"] == []
    for defect in block["retired"]:
        if defect["id"] == ENTRY_ID:
            return defect
    raise AssertionError(f"{ENTRY_ID} is not a retired entry of {RECEIPT.name}")


def _action(*, aidx: int, event_slot: int = 3, subject: int = 1) -> SurvivalAction:
    return SurvivalAction(aidx=aidx, subject=subject, event_slot=event_slot)


def test_the_entry_is_dated_and_records_how_it_closed() -> None:
    entry = _entry()
    assert entry["dated"] == "2026-08-14"
    assert entry["reproducer"].strip() and entry["for_the_owner"].strip()
    closed = entry["what_closed_and_when"]
    assert closed["the_ruling"].strip() and closed["gate_inversion"].strip()
    # The half that keeps a closure honest: nothing was absorbed.  An
    # absorbed OutcomeRewritten is the last-write-wins the join replaced,
    # which this receipt's own `how_an_entry_closes` refuses as a closure.
    assert closed["what_was_not_done"].strip()


def test_the_receipt_walk_builds_the_raising_ledger() -> None:
    """The join itself: every receipt walk carries one."""
    ledger = ReceiptLedger(
        compile_event=lambda *args, **kwargs: None,
        actions=[],
        index_of={},
        expanded_healing={},
        healing={},
    )
    assert isinstance(ledger.outcomes, OutcomeLedger)


def test_a_second_write_to_one_outcome_field_raises() -> None:
    ledger = OutcomeLedger()
    action = _action(aidx=0)
    ledger.write(action, damage=10.0)
    with pytest.raises(OutcomeRewritten):
        ledger.write(action, applied_amount=11.0)


def test_a_second_applied_claim_for_one_key_raises() -> None:
    ledger = OutcomeLedger()
    ledger.write(_action(aidx=0), damage=10.0)
    with pytest.raises(DuplicateApplied):
        ledger.write(_action(aidx=1), damage=10.0)


def test_a_second_unpreserved_skip_raises() -> None:
    ledger = OutcomeLedger()
    action = _action(aidx=0)
    ledger.skip(action, "holder_health_gate")
    ledger.skip(action, "trigger_event_skipped", preserve_reason=True)
    with pytest.raises(OutcomeRewritten):
        ledger.skip(action, "trigger_event_skipped")


@pytest.mark.parametrize(
    "raised",
    [
        OutcomeRewritten(0, "applied", 1.0, 2.0),
        DuplicateApplied(("Imperial Mandate - Command", 1, 3), 0, 1),
    ],
    ids=["OutcomeRewritten", "DuplicateApplied"],
)
def test_the_request_boundary_names_these_raises(raised) -> None:
    """The recorded consequence, inverted, as a fact rather than a sentence.

    It read: these propagate, so a request that trips one returns a bare 500
    with no disposition and no receipt.  Since Amendment G the one boundary
    converts the class, so the same request gets the ``STARVED`` receipt —
    the field whose answer is contested, the producer that contested it, and
    why there is no number to publish.  Red here means the boundary stopped
    naming a refusal, which is the regression the whole campaign is about.
    """

    def _view():
        raise raised

    guarded = app_module._within_starvation_boundary(_view)  # noqa: SLF001
    with app_module.app.test_request_context("/api/calculate", method="POST"):
        response, status = guarded()
    body = response.get_json()
    assert status == 500
    assert body["disposition"] == "STARVED"
    assert body["starved"]["field"] == raised.field
    assert body["starved"]["producer"] == raised.producer
    assert body["starved"]["reason"] == raised.reason


def test_nothing_absorbs_a_contested_outcome() -> None:
    """The other half of the closure: the raise is still a raise.

    Converting at the boundary and absorbing at the write are different
    things, and only the first is what Amendment G ruled.  The ledger still
    refuses the second answer where it is written, so the discipline the join
    landed for is exactly as strict as it was.
    """
    ledger = OutcomeLedger()
    action = _action(aidx=0)
    ledger.write(action, damage=10.0)
    with pytest.raises(OutcomeRewritten):
        ledger.write(action, applied_amount=11.0)


def test_the_entry_names_every_raise_site_that_exists() -> None:
    """The measured block is read back against the module, not trusted."""
    source = (ROOT / "src" / "calculator" / "survival" / "outcome_state.py").read_text(
        encoding="utf-8"
    )
    lines = source.splitlines()
    raising = {
        index
        for index, line in enumerate(lines, start=1)
        if "raise OutcomeRewritten(" in line or "raise DuplicateApplied(" in line
    }
    recorded = {
        int(site.split(".py:", 1)[1].split(" ", 1)[0])
        for site in _entry()["measured"]["raise_sites"]
    }
    assert recorded == raising
