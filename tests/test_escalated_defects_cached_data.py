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

import ast
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


def test_every_open_defect_names_a_scheduled_home() -> None:
    """A gap with a blocker and no home is where filed work goes to rot.

    Both entries were correctly outside the campaign's scope, which is what
    left them unowned: gated, reproducible, and waiting for nobody.  Each now
    names the route that can actually close it, and the route is one that
    exists rather than a promise — the check below is the other half.
    """
    for defect in receipt()["defects"]:
        home = defect["scheduled_home"]
        assert (ROOT / home["route"]).exists(), defect["id"]
        assert home["as_a_command"].strip()
        assert home["what_fires_it"].strip()
        assert home["how_it_closes_from_there"].strip()
    assert receipt()["how_an_entry_is_scheduled"].strip()


def test_the_named_route_really_reads_this_artifact() -> None:
    """A home nothing consumes is a declaration, which is what this campaign
    spent its length removing.  So the route is asserted to read the receipt
    and to emit a line per open entry, rather than to have been mentioned."""
    routes = {defect["scheduled_home"]["route"] for defect in receipt()["defects"]}
    assert routes == {"scripts/patch_update.py"}
    sys.path.insert(0, str(ROOT / "scripts"))
    import patch_update  # noqa: PLC0415  pylint: disable=import-outside-toplevel

    assert patch_update.ESCALATED_CACHED_DATA == RECEIPT
    printed = "\n".join(patch_update.escalated_cached_data_lines())
    for defect in receipt()["defects"]:
        assert defect["id"] in printed
        assert defect["scheduled_home"]["what_fires_it"] in printed


def test_the_scheduled_home_check_has_a_red_it_can_reproduce() -> None:
    """R-05, through the section builder's own seam.

    A receipt whose entry names no home prints the absence instead of
    printing nothing, so a home that quietly disappears is visible on the one
    day somebody is reading the audit.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import patch_update  # noqa: PLC0415  pylint: disable=import-outside-toplevel

    homeless = json.loads(RECEIPT.read_text(encoding="utf-8"))
    for defect in homeless["defects"]:
        defect.pop("scheduled_home", None)
    scratch = ROOT / "docs" / "receipts" / ".homeless-for-the-red.json"
    scratch.write_text(json.dumps(homeless), encoding="utf-8")
    try:
        printed = "\n".join(patch_update.escalated_cached_data_lines(scratch))
    finally:
        scratch.unlink()
    assert "(no home named)" in printed


def _executable_strings(path: Path) -> list[str]:
    """Every string literal in one module that is not a docstring.

    A comment cannot open a file and neither can a docstring, so the two are
    excluded: what makes the entry's clause true or false is whether a runtime
    module *names the artifact in code*.  Comments never reach the AST at all;
    docstrings are subtracted explicitly.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_no_runtime_module_reads_the_item_atoms() -> None:
    """The second entry's same clause: the overstatement is available, not taken.

    Scope note (merge of origin/main): main added modules that *cite* the atom
    corpus as sourced evidence — ``ability_atoms``, ``cleanse_eligibility`` and
    six champion modules name ``data/atoms/...`` in comments and docstrings, and
    ``cleanse_eligibility`` transcribes individual atom records (with hashes
    independently recomputed) to publish as ``source_atoms`` receipts.  None of
    that is a read: ``ability_atoms.required_ability_atom`` atomizes the cached
    *champion* rows in memory through ``atomizer.atomize_abilities`` and opens no
    file under ``data/atoms/``.  The entry's clause is about the ITEM atoms being
    summed by a serving path, so this pins the clause it actually makes — no src
    module names the artifact in executable code — instead of the prose scan it
    used to, which a provenance comment was enough to break.
    """
    hits = sorted(
        {
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "src").rglob("*.py")
            if any("data/atoms" in text for text in _executable_strings(path))
        }
    )
    assert hits == []
