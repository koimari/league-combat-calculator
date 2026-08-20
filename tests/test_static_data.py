"""static/data.json is generated, and holds only what app.js reads from it."""

import json
from pathlib import Path

import pytest

from scripts.build_static_data import build_snapshot, reviewed_abilities
from scripts.source_receipt import cache_patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "champions.json"
SNAPSHOT = ROOT / "static" / "data.json"
APP_JS = ROOT / "static" / "js" / "app.js"
REBUILD = "rebuild with: python scripts/build_static_data.py"

CHAMPION_KEYS = {"name", "key", "title", "tags", "resource", "abilities"}
ABILITY_KEYS = {"slot", "name", "icon", "maxRank", "maxHits", "variants"}


@pytest.fixture(name="committed")
def _committed():
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_committed_snapshot_is_what_the_generator_writes(committed):
    """The tracked file must equal a fresh build, so identity cannot go stale.

    The generator carries the hand-maintained ability block forward from this
    same file, so what this pins is the derived half — roster, key, title,
    tags, resource — plus the shape of the hand half.
    """
    assert committed == build_snapshot(SOURCE, SNAPSHOT), f"snapshot stale — {REBUILD}"


def test_snapshot_holds_only_the_keys_app_js_reads(committed):
    assert set(committed) == {"champions"}
    for champion in committed["champions"]:
        assert set(champion) == CHAMPION_KEYS, champion["name"]
        for ability in champion["abilities"]:
            assert set(ability) <= ABILITY_KEYS, champion["name"]
            assert {"slot", "name", "icon", "maxRank", "variants"} <= set(ability)
            for variant in ability["variants"]:
                assert set(variant) == {"name"}


def test_snapshot_publishes_the_whole_cached_roster(committed):
    cached = {
        record["name"]
        for record in json.loads(SOURCE.read_text(encoding="utf-8")).values()
    }
    assert {champion["name"] for champion in committed["champions"]} == cached


def test_snapshot_carries_no_number_the_api_owns(committed):
    """Stats, prices and damage ratios come from the API, never from here."""
    body = SNAPSHOT.read_text(encoding="utf-8")
    for banned in ("hpPerLevel", "attackSpeedRatio", '"price"', '"items"', '"patch"'):
        assert banned not in body
    numbers = {
        key
        for champion in committed["champions"]
        for ability in champion["abilities"]
        for key in ability
        if isinstance(ability[key], (int, float))
    }
    assert numbers <= {"maxRank", "maxHits"}


def test_the_page_takes_every_item_from_the_served_catalogue():
    """No snapshot item can outrank /api/items or /api/boots: there are none."""
    source = APP_JS.read_text(encoding="utf-8")
    assert "DATA = { champions: data.champions || [], items: [] };" in source
    assert (
        "buildItemCatalog([...(itemCoverage || []), ...(bootCatalog || [])]);" in source
    )
    assert "mergeItemCoverage" not in source
    assert "backendAvailable" not in source


def test_published_catalogues_stamp_the_patch_the_cache_pins():
    """A builder rerun must not stamp last patch's number on this patch's asset."""
    for name in ("ability-catalog.json", "effect-catalog.json", "bis-profiles.json"):
        catalog = json.loads((ROOT / "static" / name).read_text(encoding="utf-8"))
        assert catalog["patch"] == cache_patch(), name
    for builder in (
        "build_ability_catalog.py",
        "build_effect_catalog.py",
        "build_bis_profiles.py",
    ):
        body = (ROOT / "scripts" / builder).read_text(encoding="utf-8")
        assert '"--patch", default="' not in body, builder
        assert "cache_patch()" in body, builder


def test_patch_day_rebuilds_the_snapshot():
    body = (ROOT / "scripts" / "patch_update.py").read_text(encoding="utf-8")
    assert '"build_static_data.py",' in body


def test_a_reviewed_ability_without_a_variant_fails_closed(tmp_path):
    snapshot = tmp_path / "data.json"
    snapshot.write_text(
        json.dumps(
            {
                "champions": [
                    {
                        "name": "Aatrox",
                        "abilities": [
                            {
                                "slot": "Q",
                                "name": "The Darkin Blade",
                                "icon": "AatroxQ.png",
                                "variants": [],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Aatrox Q"):
        reviewed_abilities(snapshot)


def test_a_reviewed_ability_without_an_icon_fails_closed(tmp_path):
    snapshot = tmp_path / "data.json"
    snapshot.write_text(
        json.dumps(
            {
                "champions": [
                    {
                        "name": "Aatrox",
                        "abilities": [
                            {
                                "slot": "W",
                                "name": "Infernal Chains",
                                "variants": [{"name": "Listed hit"}],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Aatrox W: record has no icon"):
        reviewed_abilities(snapshot)


def test_reviewed_abilities_for_an_uncached_champion_fail_closed(tmp_path):
    snapshot = tmp_path / "data.json"
    snapshot.write_text(
        json.dumps(
            {
                "champions": [
                    {
                        "name": "Nonesuch",
                        "abilities": [
                            {
                                "slot": "Q",
                                "name": "Nothing",
                                "icon": "NonesuchQ.png",
                                "variants": [{"name": "Listed hit"}],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Nonesuch"):
        build_snapshot(SOURCE, snapshot)
