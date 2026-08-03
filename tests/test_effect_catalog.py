import hashlib
import json
from pathlib import Path

from scripts.build_effect_catalog import build_catalog

ROOT = Path(__file__).resolve().parents[1]
PATCH = "26.15"
REBUILD = "rebuild with: python scripts/build_effect_catalog.py"


def test_effect_catalog_preserves_wiki_order_signals():
    catalog = build_catalog(ROOT / "data" / "items.json", PATCH)
    assert catalog["item_count"] >= 300
    assert "healing_reduction" in catalog["items"]["3165"]["tags"]
    assert "damage_over_time" in catalog["items"]["6653"]["tags"]
    assert catalog["items"]["6653"]["eventOrder"]
    assert (
        "apply healing reduction after the triggering damage"
        in catalog["items"]["3165"]["eventOrder"]
    )


def test_checked_in_effect_catalog_is_not_stale():
    """The served effect catalogue must match a rebuild from current item data.

    Compares the derived items rather than `source.sha256`, which covers every
    byte of data/items.json and so reported staleness for any patch that
    touched an unrelated item field. app.js fetches this file at runtime.
    """
    checked_in = json.loads(
        (ROOT / "static" / "effect-catalog.json").read_text(encoding="utf-8")
    )
    fresh = build_catalog(ROOT / "data" / "items.json", PATCH)

    assert checked_in["item_count"] == fresh["item_count"]
    assert checked_in["items"] == fresh["items"], f"catalogue stale — {REBUILD}"


def test_checked_in_effect_catalog_records_the_data_it_was_built_from():
    """Keep the provenance receipt honest; patch day rebuilds this artifact."""
    checked_in = json.loads(
        (ROOT / "static" / "effect-catalog.json").read_text(encoding="utf-8")
    )
    source = ROOT / "data" / "items.json"

    assert checked_in["source"]["path"] == "data/items.json"
    assert (
        checked_in["source"]["sha256"]
        == hashlib.sha256(source.read_bytes()).hexdigest()
    ), f"provenance hash does not match data/items.json — {REBUILD}"
