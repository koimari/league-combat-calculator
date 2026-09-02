"""A refused row publishes a declared zero, and a priced one publishes MEASURED.

The four-disposition wire shape, read off live coupled runs rather than off a
unit fixture: a refused transition's outcome fields carry ``STRUCTURAL_ZERO``
with the walk's own refusal beside them, so a reader can tell a number no rule
computed from a computed zero without reading a sibling string and knowing
what it implies.  Red here means a production path stopped naming its
refusals.
"""

from __future__ import annotations

import ast
import collections
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SRC = ROOT / "src" / "calculator"


def _golden_snapshot():
    """The capture instrument, imported by path exactly as its own tests do."""
    spec = importlib.util.spec_from_file_location(
        "golden_snapshot", ROOT / "scripts" / "golden_snapshot.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("golden_snapshot", module)
    spec.loader.exec_module(module)
    return module


#: The row keys a refusal zeroes, per panel.  ``ReceiptLedger.skip`` writes
#: exactly these, which is why they are the fields whose zero belongs to the
#: refusal rather than to a rule that ran.
_REFUSAL_ZEROED = {
    "events": ("damage", "overkill"),
    "healing_events": ("applied_amount",),
    "support_events": ("applied_amount",),
}


def _combat(scenario: str) -> dict:
    """One committed coupled scenario's combat receipt, from a live run."""
    snapshot = _golden_snapshot()
    definition = next(
        item for item in snapshot.COUPLED_SCENARIOS if item.name == scenario
    )
    return snapshot.coupled_entry(definition)["combat"]


@pytest.mark.parametrize(
    "scenario", ["mandate_abyssal_curse_roster", "cleaver_bloodsong_roster"]
)
def test_a_refused_row_publishes_a_declared_zero(scenario: str) -> None:
    """The reproducer, inverted, against a live run.

    It used to read "the disposition set is exactly ``{MEASURED}``, including
    on the rows whose ``skipped_reason`` says the walk refused them".  Now
    the refusal is what the entry says: a refused row's outcome fields carry
    ``STRUCTURAL_ZERO`` and the reason beside them is the walk's own, so a
    reader of the map can tell a number no rule computed from a computed
    zero without reading a sibling string and knowing what it implies.

    Both scenarios run, and one of them has no refusal at all — which is the
    other half of the property: a priced row is still ``MEASURED``, so this
    is a distinction being drawn rather than a relabelling of everything.
    """
    combat = _combat(scenario)
    entries = combat["dispositions"]
    assert entries, "a vacuous map proves nothing either way"
    for panel, fields in _REFUSAL_ZEROED.items():
        for index, row in enumerate(combat.get(panel, ())):
            for field in fields:
                if field not in row:
                    continue
                entry = entries[f"{panel}[{index}].{field}"]
                if row.get("skipped_reason") and not row[field]:
                    assert entry["disposition"] == "STRUCTURAL_ZERO"
                    assert entry["reason"] == row["skipped_reason"]
                else:
                    assert entry["disposition"] == "MEASURED"
                    assert "reason" not in entry


def test_the_declared_zero_reaches_a_payload_at_all() -> None:
    """The entry's own ``reproducer_after_closure``, asserted as a number.

    The test above is total over the panels and would pass vacuously on a
    roster where nothing is ever refused.  This is the non-vacuity: a
    committed scenario emits a non-``MEASURED`` disposition, so the campaign's
    claim that three of the four spellings are reachable on a served payload
    is a fact about a run rather than about a unit fixture.
    """
    combat = _combat("cleaver_bloodsong_roster")
    spellings = {entry["disposition"] for entry in combat["dispositions"].values()}
    assert "STRUCTURAL_ZERO" in spellings
    declared = [
        entry
        for entry in combat["dispositions"].values()
        if entry["disposition"] == "STRUCTURAL_ZERO"
    ]
    # 39, pinned by its composition rather than as a bare figure, so a shift
    # in *which* refusal reaches the payload is a failure and not a silent
    # re-count.  ``attacker_state_blocked`` is the merged castability gate:
    # a leaf refused because its caster was disabled when the cast was due.
    # Last re-measured when this roster's Aatrox stopped landing his Q and W
    # as one event each: three strikes a second apart and two chain hits 1.5
    # seconds apart give a disabled window and the fight's end far more
    # leaves to refuse, and spread the same damage out so that fewer
    # attackers and targets die inside the window at all.
    assert collections.Counter(entry["reason"] for entry in declared) == {
        "attacker_state_blocked": 16,
        "trigger_event_skipped": 11,
        "outside_window": 8,
        "attacker_dead": 2,
        "target_dead": 2,
    }
    assert all(entry["reason"] for entry in declared)


def _outcome_ledger_sites() -> dict[str, int]:
    """Every ``OutcomeLedger(...)`` construction expression under ``src/``."""
    sites = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        count = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "OutcomeLedger"
        )
        if count:
            sites[path.relative_to(SRC).as_posix()] = count
    return sites


def test_the_outcome_ledger_is_the_receipt_walks_companion() -> None:
    """The other half, inverted: this reproducer no longer reproduces.

    It read "no walk runs on it, so ``StructuralZero`` and ``Starved`` reach
    no payload".  Both clauses are now false — the receipt adapter builds one
    and drives it from every write, annotation and refusal, so the write-once
    rule and D-62's uniqueness range over real fights; and the verdict that
    record applies to a refused slot is the verdict the receipt view now
    publishes.  Pinned to one site rather than merely to a non-zero count: a
    second construction site would be a second ledger, and two ledgers
    observing one walk is the shape D-64 exists to refuse.
    """
    assert _outcome_ledger_sites() == {"survival/receipt_state.py": 1}


def test_a_live_walk_fills_the_ledger_the_site_builds() -> None:
    """A construction site nothing drives would be the same gap, relocated."""
    from src.calculator.survival.receipt_state import ReceiptLedger

    snapshot = _golden_snapshot()
    definition = next(
        item
        for item in snapshot.COUPLED_SCENARIOS
        if item.name == "cleaver_bloodsong_roster"
    )
    built: list[ReceiptLedger] = []

    class Capturing(ReceiptLedger):
        """The production ledger, keeping the ones a real walk builds."""

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            built.append(self)

    from src.calculator import participant_timeline

    original = participant_timeline.ReceiptLedger
    participant_timeline.ReceiptLedger = Capturing
    try:
        snapshot.coupled_entry(definition)
    finally:
        participant_timeline.ReceiptLedger = original
    assert built, "the coupled walk built no receipt ledger"
    assert any(
        ledger.outcomes.get(slot).skipped_reason is not None
        for ledger in built
        for slot in ledger.outcomes.slots()
    )


def test_the_serializer_can_nevertheless_express_all_four() -> None:
    """The gap is reach, not shape — and the receipt says so.

    Without this the entry would read as "the wire shape is broken", which
    is a different and false claim.
    """
    from src.calculator.ability_spec import Disposition, StructuralZero, Withheld
    from src.calculator.program.views import ViewTag, serialize_leaf

    withheld = serialize_leaf(
        "x", Withheld(receipts=("coverage refused",)), ViewTag.APPLIED
    )
    assert withheld.present is False
    assert withheld.entry["disposition"] == Disposition.WITHHELD.value
    zero = serialize_leaf("y", StructuralZero(reason="declared"), ViewTag.APPLIED)
    assert (zero.value, zero.entry["disposition"]) == (
        0.0,
        Disposition.STRUCTURAL_ZERO.value,
    )
