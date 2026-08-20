import json
from pathlib import Path

import pytest

from scripts.build_ability_catalog import build_catalog
from src.calculator.cast_dependency import BASE_CAST_SLOTS
from src.calculator.champions import registered_champion_names
from scripts.source_receipt import source_sha256

ROOT = Path(__file__).resolve().parents[1]
PATCH = "26.15"
REBUILD = "rebuild with: python scripts/build_ability_catalog.py"


def test_cached_catalog_contains_all_five_slots_for_all_champions():
    catalog = build_catalog(ROOT / "data" / "champions.json", PATCH)

    assert catalog["champion_count"] == len(catalog["champions"])
    assert all(
        [ability["slot"] for ability in champion["abilities"]] == list(BASE_CAST_SLOTS)
        and all(
            ability["ingestion_status"] == "metadata_ingested"
            for ability in champion["abilities"]
        )
        for champion in catalog["champions"]
    )


def test_checked_in_catalog_is_not_stale():
    """The served catalogue must match what the builder produces from current data.

    Compares the *derived* catalogue rather than `source.sha256`. That hash
    covers every byte of data/champions.json, so it moved on any patch that
    touched unrelated champion fields and reported staleness where the
    catalogue was in fact identical. app.js fetches this file at runtime, so
    the content it serves is what matters.
    """
    checked_in = json.loads(
        (ROOT / "static" / "ability-catalog.json").read_text(encoding="utf-8")
    )
    fresh = build_catalog(ROOT / "data" / "champions.json", PATCH)

    assert checked_in["champion_count"] == fresh["champion_count"]
    assert len(checked_in["champions"]) == checked_in["champion_count"]
    assert all(len(champion["abilities"]) == 5 for champion in checked_in["champions"])
    assert all(champion["complete"] for champion in checked_in["champions"])
    assert checked_in["champions"] == fresh["champions"], f"catalogue stale — {REBUILD}"


def test_checked_in_catalog_records_the_data_it_was_built_from():
    """Keep the provenance receipt honest — a wrong hash is worse than none.

    Uses source_sha256 rather than a raw digest so this passes on Windows and
    macOS/Linux alike: git rewrites line endings on checkout, so the same
    tracked file has two different raw digests depending on the platform.
    """
    checked_in = json.loads(
        (ROOT / "static" / "ability-catalog.json").read_text(encoding="utf-8")
    )
    source = ROOT / "data" / "champions.json"

    assert checked_in["source"]["path"] == "data/champions.json"
    assert checked_in["source"]["sha256"] == source_sha256(
        source
    ), f"provenance hash does not match data/champions.json — {REBUILD}"


def test_the_published_roster_is_the_engine_registry():
    """The picker may only offer champions the engine will accept as attackers."""
    checked_in = json.loads(
        (ROOT / "static" / "ability-catalog.json").read_text(encoding="utf-8")
    )
    names = [champion["name"] for champion in checked_in["champions"]]

    assert names == sorted(registered_champion_names())
    assert checked_in["ability_slots"] == list(BASE_CAST_SLOTS)


def test_a_cached_champion_with_no_module_stops_the_build(tmp_path):
    """Fail closed: an unregistered cache row is never published to the UI."""
    raw = json.loads((ROOT / "data" / "champions.json").read_text(encoding="utf-8"))
    raw["Nobody"] = {"name": "Nobody", "key": "Nobody", "id": -1, "abilities": {}}
    source = tmp_path / "champions.json"
    source.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="no validated module: Nobody"):
        build_catalog(source, PATCH)


def test_a_registered_module_with_no_cache_row_stops_the_build(tmp_path):
    raw = json.loads((ROOT / "data" / "champions.json").read_text(encoding="utf-8"))
    dropped = next(key for key, value in raw.items() if value.get("name") == "Aatrox")
    del raw[dropped]
    source = tmp_path / "champions.json"
    source.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="no cached row: Aatrox"):
        build_catalog(source, PATCH)
