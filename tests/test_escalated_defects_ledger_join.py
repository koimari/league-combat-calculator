"""The ledger join's raise set, asserted rather than described.

`69e7323` joined the write-once ``OutcomeLedger`` to the receipt walk, so a
record that raises is now built and driven on every ``/api/calculate``,
``/api/bis`` and ``/api/optimize`` request.  That is the design working — a
second answer to one question is refused — and it is also an operational
change no commit body stated: a condition that used to resolve silently, the
event dict taking the last write, is now an unhandled exception on a user
request.

This file is the escalation's gate.  It asserts the three facts the entry
claims, so the entry cannot rot into prose: the ledger is constructed on the
serving path, the three raises are real, and the request boundary does not
name them.  The last assertion is the point of the file.  If a future slice
teaches the boundary to convert these into a receipted 500, or proves the
raises unreachable, this file's own inversion is what records it — the entry
does not close by being deleted.
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
    block = json.loads(RECEIPT.read_text(encoding="utf-8"))
    for defect in block["defects"]:
        if defect["id"] == ENTRY_ID:
            return defect
    raise AssertionError(f"{ENTRY_ID} is not an open entry of {RECEIPT.name}")


def _action(*, aidx: int, event_slot: int = 3, subject: int = 1) -> SurvivalAction:
    return SurvivalAction(aidx=aidx, subject=subject, event_slot=event_slot)


def test_the_entry_is_open_and_dated() -> None:
    entry = _entry()
    assert entry["dated"] == "2026-08-14"
    assert entry["reproducer"].strip() and entry["for_the_owner"].strip()


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
def test_the_request_boundary_does_not_name_these_raises(raised) -> None:
    """The recorded consequence, as a fact rather than a sentence.

    D-25's single catch names ``ProjectionStarvation``; these are
    ``RuntimeError`` subclasses and propagate, so a request that trips one
    returns a bare 500 with no disposition and no receipt.  Asserting the
    propagation is what makes the escalation's claim checkable — and what
    turns red on the commit that changes it, in either direction.
    """

    def _view():
        raise raised

    guarded = app_module._within_starvation_boundary(_view)  # noqa: SLF001
    with pytest.raises(type(raised)):
        guarded()


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
