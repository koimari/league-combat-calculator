import json
from pathlib import Path

from scripts.build_effect_catalog import build_catalog

ROOT = Path(__file__).resolve().parents[1]


def test_effect_catalog_preserves_wiki_order_signals():
    catalog = build_catalog(ROOT / "data" / "items.json", "26.15")
    assert catalog["item_count"] >= 300
    assert "healing_reduction" in catalog["items"]["3165"]["tags"]
    assert "damage_over_time" in catalog["items"]["6653"]["tags"]
    assert catalog["items"]["6653"]["eventOrder"]
    assert (
        "apply healing reduction after the triggering damage"
        in catalog["items"]["3165"]["eventOrder"]
    )


def test_checked_in_effect_catalog_matches_wiki_source():
    checked_in = json.loads((ROOT / "static" / "effect-catalog.json").read_text())
    fresh = build_catalog(ROOT / "data" / "items.json", "26.15")
    assert checked_in["item_count"] == fresh["item_count"]
    assert checked_in["source"]["sha256"] == fresh["source"]["sha256"]
