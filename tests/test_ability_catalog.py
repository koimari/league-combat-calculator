import hashlib
import json
from pathlib import Path

from scripts.build_ability_catalog import ABILITY_SLOTS, build_catalog

ROOT = Path(__file__).resolve().parents[1]
PATCH = "26.15"
REBUILD = "rebuild with: python scripts/build_ability_catalog.py"


def test_cached_catalog_contains_all_five_slots_for_all_champions():
    catalog = build_catalog(ROOT / "data" / "champions.json", PATCH)

    assert catalog["champion_count"] == 173
    assert len(catalog["champions"]) == 173
    assert all(
        [ability["slot"] for ability in champion["abilities"]] == list(ABILITY_SLOTS)
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

    assert checked_in["champion_count"] == fresh["champion_count"] == 173
    assert len(checked_in["champions"]) == 173
    assert all(len(champion["abilities"]) == 5 for champion in checked_in["champions"])
    assert all(champion["complete"] for champion in checked_in["champions"])
    assert checked_in["champions"] == fresh["champions"], f"catalogue stale — {REBUILD}"


def test_checked_in_catalog_records_the_data_it_was_built_from():
    """Keep the provenance receipt honest — a wrong hash is worse than none.

    Patch day rebuilds this artifact (scripts/patch_update.py), so the receipt
    is expected to stay current rather than drift until someone notices.
    """
    checked_in = json.loads(
        (ROOT / "static" / "ability-catalog.json").read_text(encoding="utf-8")
    )
    source = ROOT / "data" / "champions.json"

    assert checked_in["source"]["path"] == "data/champions.json"
    assert (
        checked_in["source"]["sha256"]
        == hashlib.sha256(source.read_bytes()).hexdigest()
    ), f"provenance hash does not match data/champions.json — {REBUILD}"
