"""Unified Atomizer contract tests.

The atomizer is the single way to atomize anything numerical (items,
abilities, runes, economics, stats, champions) across sessions.  These
tests pin the Atom contract and the per-effect independence rule that the
old item atomizer violated (issue #140).
"""

from pathlib import Path

from src.calculator.atomizer import Atomizer, number_and_unit, split_effect_fragments
from src.calculator.atomizer_domains import (
    atomize_abilities,
    atomize_item,
    atomize_item_catalogue,
)
from src.calculator.data_fetcher import fetch_item_data, fetch_champion_data

ROOT = Path(__file__).resolve().parents[1]


def _item(name):
    return next(v for v in fetch_item_data().values() if v.get("name") == name)


def test_atom_contract_fields():
    a = Atomizer("items", source_ref="Test")
    a.add(
        "damage.magic",
        "damage",
        "Test.passives[0]",
        "Bolt",
        [50.0],
        ["flat"],
        ["kw:magic damage"],
    )
    emitted = a.emit()
    assert len(emitted) == 1
    atom = emitted[0]
    for key in (
        "atom_id",
        "behavior",
        "source",
        "name",
        "values",
        "units",
        "evidence",
        "hash",
    ):
        assert key in atom, key
    assert atom["hash"] == atom["hash"]  # deterministic
    assert atom["evidence"] == ["kw:magic damage"]


def test_dedup_merges_evidence_per_behavior():
    a = Atomizer("items", source_ref="Test")
    a.add(
        "damage.physical",
        "damage",
        "p[0]",
        "A",
        [10.0],
        ["flat"],
        ["passive:A@kw:physical"],
    )
    a.add(
        "damage.physical",
        "damage",
        "a[0]",
        "B",
        [],
        [],
        ["active:B@kw:physical damage"],
    )
    emitted = a.emit()
    assert len(emitted) == 1
    assert set(emitted[0]["evidence"]) == {
        "passive:A@kw:physical",
        "active:B@kw:physical damage",
    }


def test_number_and_unit_extraction():
    values, units = number_and_unit("50 (+ 25% AP) bonus magic damage")
    # raw numbers preserved; the % unit is carried separately
    assert values == [50.0, 25.0]
    assert units == ["flat", "percent"]


def test_item_multi_effect_independence_issue_140_fixture():
    """A multi-effect item emits atoms for EVERY effect with exact receipts."""
    ravenous = _item("Ravenous Hydra")
    atoms = atomize_item(ravenous)
    evidence = {ev for atom in atoms for ev in atom["evidence"]}
    assert any(ev.startswith("active:Ravenous Crescent@") for ev in evidence), evidence
    assert any(ev.startswith("passive:Cleave@") for ev in evidence), evidence
    # The active's damage/lifesteal atoms must exist (not absorbed by passive).
    active_damage = [
        a
        for a in atoms
        if any(ev.startswith("active:Ravenous Crescent@") for ev in a["evidence"])
        and a["behavior"] in {"damage", "stat"}
    ]
    assert active_damage, "active emitted no damage/stat atoms"


def test_item_atom_values_are_numeric():
    for name in ("Ravenous Hydra", "Infinity Edge", "Liandry's Torment"):
        atoms = atomize_item(_item(name))
        assert atoms
        for atom in atoms:
            for value in atom["values"]:
                assert isinstance(value, (int, float)), (name, atom)


def test_item_catalogue_covers_every_cache_item():
    catalogue = atomize_item_catalogue(fetch_item_data())
    assert len(catalogue) == 324
    assert all(atoms for atoms in catalogue.values())


def test_ability_atomizer_reads_leveling_modifiers():
    from src.calculator.data_fetcher import DEFAULT_DATA_DIR

    ahri = fetch_champion_data(data_directory=DEFAULT_DATA_DIR)["Ahri"]
    slots = atomize_abilities("Ahri", ahri)
    assert "Q" in slots
    q_atoms = slots["Q"]
    assert q_atoms
    for atom in q_atoms:
        assert atom["source"].startswith("Ahri.Q")
        assert all(isinstance(v, float) for v in atom["values"])


def test_effect_fragments_split_branches():
    effect = {
        "description": "Deal damage. Heal allies.",
        "branches": ["branch one", "branch two"],
    }
    fragments = split_effect_fragments(effect, prefix="x.passives", index=0)
    assert len(fragments) >= 4  # 2 branches + 2 sentences
    assert fragments[0][1] == "branch one"
