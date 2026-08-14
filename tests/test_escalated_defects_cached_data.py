"""Two cached-data defects, gated so they cannot be forgotten quietly.

Both were flagged as asides inside an oracle receipt about something else,
and an aside inside a receipt nobody re-reads is prose with a filename.  Each
reproducer runs here.  Red means the defect closed -- retire the entry and
invert the assertion; it does not mean a regression.

Neither defect moves a damage number: rule 5 keeps every runtime item value in
``item_effects.py``, and both consumers are evidence assets rather than
serving paths.  That is stated in the entries and asserted below, so "this is
filed" cannot quietly become "this is fine".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calculator.item_source import effect_text  # noqa: E402

RECEIPT = ROOT / "docs" / "receipts" / "escalated-defects-cached-data.json"
ITEMS = ROOT / "data" / "items.json"
ITEM_ATOMS = ROOT / "data" / "atoms" / "items.json"
MANDATE = "4005"


def receipt() -> dict:
    """The committed artifact this file is the gate for."""
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def mandate() -> dict:
    """Imperial Mandate, as the cache holds it."""
    return json.loads(ITEMS.read_text(encoding="utf-8"))[MANDATE]


def test_the_receipt_declares_what_it_is_and_what_gates_it() -> None:
    block = receipt()
    assert block["artifact"] == "escalated_defects"
    assert block["gate"] == "tests/test_escalated_defects_cached_data.py"
    assert [defect["id"] for defect in block["defects"]] == [
        "imperial_mandate_simple_description_describes_a_different_item",
        "one_ability_haste_phrase_is_atomized_three_ways",
    ]


def test_every_open_defect_carries_a_reproducer_and_a_date() -> None:
    """An entry without a reproducer is an opinion with a filename."""
    for defect in receipt()["defects"]:
        assert defect["dated"] and defect["reproducer"]
        assert defect["reproducer_after_closure"]
        assert defect["why_this_lane_may_not_fix_it"]
        assert defect["why_it_does_not_move_a_number"]


def test_the_simple_description_still_describes_a_different_item() -> None:
    """Entry 1's reproducer, over the cache and over the passives beside it."""
    item = mandate()
    assert item["name"] == "Imperial Mandate"
    assert item["simpleDescription"] == "Defer damage until later."
    spoken = " ".join(effect_text(effect) for effect in item["passives"]).lower()
    assert "defer" not in spoken and "delay" not in spoken


def test_no_runtime_module_reads_the_field() -> None:
    """The entry's "does not move a number" clause, asserted rather than said."""
    hits = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src").rglob("*.py")
        if "simpleDescription" in path.read_text(encoding="utf-8")
    ]
    assert hits == []


def test_one_phrase_is_still_three_atoms() -> None:
    """Entry 2's reproducer: one branch, one fact, three atoms valued 20."""
    atoms = json.loads(ITEM_ATOMS.read_text(encoding="utf-8"))["objects"][MANDATE]
    branch = "Imperial Mandate.passives[0].branches[0]"
    from_one_branch = {
        atom["atom_id"]: tuple(atom["values"])
        for atom in atoms
        if atom["source"] == branch
    }
    assert from_one_branch == {
        "control.immobilize": (20.0,),
        "stat.haste": (20.0,),
        "timing.cooldown": (20.0,),
    }


def test_the_item_s_real_flat_haste_is_not_that_number() -> None:
    """Why the fan-out is a defect and not a duplication: the stat disagrees."""
    flat = mandate()["stats"]["abilityHaste"]["flat"]
    atoms = json.loads(ITEM_ATOMS.read_text(encoding="utf-8"))["objects"][MANDATE]
    declared = next(atom for atom in atoms if atom["atom_id"] == "stat.ability_haste")
    assert flat == 15.0
    assert declared["values"] == [flat]


def test_no_runtime_module_reads_the_item_atoms() -> None:
    """The second entry's same clause: the overstatement is available, not taken."""
    hits = [
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src").rglob("*.py")
        if "data/atoms" in path.read_text(encoding="utf-8")
    ]
    assert hits == []
