"""Issue #163 — build_receipts.py consumes the unified Atomizer item domain.

The item-atoms/ tree was retired by the unified Atomizer migration, but
``scripts/build_receipts.py`` still pointed at it: ``data/item-atoms/items.json``
did not exist, so every item receipt reported zero atoms and ``main()`` raised
``KeyError: 'effects'`` on the summary write.  These tests pin the repaired
contract: one item receipt schema, fail-closed validation of the unified
``data/atoms/items.json`` payload, atomic publish (no partial tree), a manifest
cross-check, and the real-data regression.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.build_receipts as br

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _atom(atom_id: str, **extra) -> dict:
    row = {
        "atom_id": atom_id,
        "behavior": atom_id.split(".", 1)[0],
        "source": f"Fixture.{atom_id}",
        "name": atom_id,
        "values": [1.0],
        "units": ["flat"],
        "evidence": [atom_id],
        "hash": "abc123",
    }
    row.update(extra)
    return row


def _items_payload(objects: dict, domain: str = "items") -> dict:
    return {"domain": domain, "generated_at": 0, "source_ref": None, "objects": objects}


@pytest.fixture
def tmp_tree(tmp_path: Path):
    """A small data tree: one champion, three items, unified item atoms."""
    champs = {"Aatrox": {"name": "Aatrox", "abilities": {}}}
    items = {
        "1001": {"name": "Boots"},
        "1004": {"name": "Faerie Charm"},
        "1006": {"name": "Rejuvenation Bead"},
    }
    atoms = {
        "1001": [
            _atom("economy.total"),
            _atom("stat.movespeed"),
        ],
        "1004": [_atom("stat.mana_regen")],
        # 1006 deliberately absent -> zero-atom receipt
    }
    audit = {"Aatrox": {"verdict": "ok", "gap_summary": ""}}
    (tmp_path / "data" / "atoms").mkdir(parents=True)
    (tmp_path / "data" / "champion-audit").mkdir(parents=True)
    (tmp_path / "data").joinpath("champions.json").write_text(json.dumps(champs))
    (tmp_path / "data").joinpath("items.json").write_text(json.dumps(items))
    (tmp_path / "data" / "atoms").joinpath("items.json").write_text(
        json.dumps(_items_payload(atoms))
    )
    (tmp_path / "data" / "atoms").joinpath("aatrox.atoms.json").write_text(
        json.dumps([{"atom_id": "damage.basic-attack", "family": "damage"}])
    )
    (tmp_path / "data" / "champion-audit").joinpath("batch-0.json").write_text(
        json.dumps(audit)
    )
    (tmp_path / "data" / "atoms").joinpath("manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "domains": {
                    "items": {
                        "domain": "items",
                        "object_count": 3,
                        "atom_count": 3,
                        "sha256": "x",
                    }
                },
            }
        )
    )
    return tmp_path


@pytest.fixture
def patched(tmp_tree: Path, monkeypatch):
    monkeypatch.setattr(br, "CHAMPS_JSON", tmp_tree / "data" / "champions.json")
    monkeypatch.setattr(br, "ITEMS_JSON", tmp_tree / "data" / "items.json")
    monkeypatch.setattr(br, "ATOMS_DIR", tmp_tree / "data" / "atoms")
    monkeypatch.setattr(
        br, "ITEM_ATOMS_FILE", tmp_tree / "data" / "atoms" / "items.json"
    )
    monkeypatch.setattr(
        br, "MANIFEST_FILE", tmp_tree / "data" / "atoms" / "manifest.json"
    )
    monkeypatch.setattr(br, "AUDIT_DIR", tmp_tree / "data" / "champion-audit")
    monkeypatch.setattr(br, "OUT", tmp_tree / "docs" / "receipts")
    return tmp_tree


# ---------------------------------------------------------------------------
# Unified source loading and validation (fail closed)
# ---------------------------------------------------------------------------


def test_load_item_atoms_reads_the_unified_domain(patched):
    objects = br.load_item_atoms()
    assert set(objects) == {"1001", "1004"}
    assert objects["1001"][0]["atom_id"] == "economy.total"


def test_load_item_atoms_fails_closed_on_missing_file(tmp_path):
    with pytest.raises(br.ItemAtomError, match="not found"):
        br.load_item_atoms(tmp_path / "nope.json")


def test_load_item_atoms_validates_domain(tmp_path):
    path = tmp_path / "items.json"
    path.write_text(json.dumps(_items_payload({}, domain="champions")))
    with pytest.raises(br.ItemAtomError, match="expected 'items'"):
        br.load_item_atoms(path)


def test_load_item_atoms_validates_objects_mapping(tmp_path):
    path = tmp_path / "items.json"
    path.write_text(json.dumps({"domain": "items", "objects": []}))
    with pytest.raises(br.ItemAtomError, match="must be a mapping"):
        br.load_item_atoms(path)


def test_load_item_atoms_validates_atom_row_shape(tmp_path):
    path = tmp_path / "items.json"
    path.write_text(
        json.dumps(_items_payload({"1001": [{"behavior": "stat", "source": "x"}]}))
    )
    with pytest.raises(br.ItemAtomError, match="string atom_id"):
        br.load_item_atoms(path)


# ---------------------------------------------------------------------------
# Item receipt schema
# ---------------------------------------------------------------------------


def test_item_receipt_reads_current_unified_atoms():
    """Regression fixture (issue #163): item 1001 reads its live unified atoms."""
    objects = br.load_item_atoms()
    assert "1001" in objects, "unified item atoms must cover item 1001"
    receipt = br.item_receipt("1001", {"name": "Boots"})
    assert receipt["atoms"]["count"] == len(objects["1001"])
    assert receipt["atoms"]["ids"] == [a["atom_id"] for a in objects["1001"]]
    assert "stat.movespeed" in receipt["atoms"]["ids"]
    # families are the atom_id namespaces; stats are not effects
    assert receipt["atoms"]["families"] == sorted(
        {a["atom_id"].split(".", 1)[0] for a in objects["1001"]}
    )
    assert all(f != "stat" for f in receipt["atoms"]["families"]) or receipt["atoms"][
        "effects"
    ] == [a for a in receipt["atoms"]["ids"] if not a.startswith("stat.")]


def test_item_receipt_zero_atoms_for_absent_id():
    receipt = br.item_receipt("999999", {"name": "No Such Item"}, atoms=[])
    assert receipt["atoms"] == {"count": 0, "ids": [], "families": [], "effects": []}
    assert receipt["name"] == "No Such Item"


def test_item_receipt_effects_exclude_stats():
    atoms = [
        _atom("stat.attack_damage"),
        _atom("damage.physical"),
        _atom("economy.total"),
    ]
    receipt = br.item_receipt("42", {"name": "Fixture"}, atoms=atoms)
    assert receipt["atoms"]["effects"] == ["damage.physical", "economy.total"]


# ---------------------------------------------------------------------------
# Atomic build + publish
# ---------------------------------------------------------------------------


def test_main_builds_the_receipt_trees(patched):
    summary = br.build()
    out = patched / "docs" / "receipts"
    assert summary["champions"]["Aatrox"]["atoms"] == 1
    assert summary["items"]["Boots"]["atoms"] == 2
    assert summary["items"]["Boots"]["effects"] == 1
    assert summary["items"]["Faerie Charm"]["atoms"] == 1
    assert summary["items"]["Rejuvenation Bead"]["atoms"] == 0
    # published tree
    assert (
        json.loads((out / "champions" / "aatrox.json").read_text())["atoms"]["count"]
        == 1
    )
    assert json.loads((out / "items" / "1001.json").read_text())["atoms"]["count"] == 2
    # The summary is the run's printed report, not a tracked artefact: its
    # champion atom counts come from the gitignored corpus.
    assert not (out / "summary.json").exists()


def test_main_fails_closed_on_manifest_mismatch(patched):
    manifest = patched / "data" / "atoms" / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "domains": {
                    "items": {
                        "object_count": 99,
                        "atom_count": 3,
                    }
                }
            }
        )
    )
    with pytest.raises(br.ItemAtomError, match="object_count"):
        br.build()


def test_failure_publishes_no_partial_tree(patched):
    """A malformed atom row aborts before anything is written or published."""
    atoms = patched / "data" / "atoms" / "items.json"
    payload = json.loads(atoms.read_text())
    payload["objects"]["1004"] = [{"behavior": "stat"}]  # missing atom_id
    atoms.write_text(json.dumps(payload))
    out = patched / "docs" / "receipts"
    out.mkdir(parents=True)
    marker = out / "existing.txt"
    marker.write_text("keep")
    with pytest.raises(br.ItemAtomError):
        br.build()
    assert marker.read_text() == "keep"
    assert not (out / "summary.json").exists()
    assert not (out / "champions").exists()
    assert not (out / "items").exists()


# ---------------------------------------------------------------------------
# Real-data regression (issue #163)
# ---------------------------------------------------------------------------


def test_main_completes_on_real_data_and_matches_manifest(tmp_path, monkeypatch):
    """main() must no longer raise on 'effects'; totals match the manifest."""
    # Publish to a scratch OUT so the tracked docs/receipts tree is untouched.
    monkeypatch.setattr(br, "OUT", tmp_path / "receipts")
    objects = br.load_item_atoms()
    manifest_items = br._manifest_items()
    assert manifest_items is not None, "data/atoms/manifest.json must carry items"
    summary = br.build()
    assert len(summary["items"]) == manifest_items["object_count"]
    total = sum(v["atoms"] for v in summary["items"].values())
    assert total == manifest_items["atom_count"]
    assert len(summary["champions"]) == 173
    # item 1001 regression fixture
    receipt = br.item_receipt("1001", {"name": "Boots"})
    assert receipt["atoms"]["count"] == len(objects["1001"]) > 0
    assert receipt["atoms"]["effects"], "Boots should carry non-stat atoms"


def test_script_entrypoint_bootstraps_repo_import_path(tmp_path):
    """Direct execution from outside the repo can import the calculator package."""
    probe = """
import runpy
import sys
from pathlib import Path

script = Path(sys.argv[1]).resolve()
sys.path = [str(script.parent)] + [
    entry for entry in sys.path if entry not in ("", str(script.parent.parent))
]
namespace = runpy.run_path(str(script), run_name="receipt_probe")
receipt = namespace["champion_receipt"]("Aatrox", {"abilities": {}}, {})
assert receipt["champion"] == "Aatrox"
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            probe,
            str(Path(br.__file__).resolve()),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
