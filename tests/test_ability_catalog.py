from pathlib import Path

from scripts.build_ability_catalog import ABILITY_SLOTS, build_catalog

ROOT = Path(__file__).resolve().parents[1]


def test_cached_catalog_contains_all_five_slots_for_all_champions():
    catalog = build_catalog(ROOT / "data" / "champions.json", "26.15")

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


def test_checked_in_catalog_matches_source_shape():
    import json

    checked_in = json.loads((ROOT / "static" / "ability-catalog.json").read_text())
    fresh = build_catalog(ROOT / "data" / "champions.json", "26.15")
    assert checked_in["champion_count"] == 173
    assert len(checked_in["champions"]) == 173
    assert all(len(champion["abilities"]) == 5 for champion in checked_in["champions"])
    assert all(champion["complete"] for champion in checked_in["champions"])
    assert checked_in["source"]["sha256"] == fresh["source"]["sha256"]
